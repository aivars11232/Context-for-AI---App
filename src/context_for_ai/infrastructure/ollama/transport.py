"""Direct loopback HTTP transport with bounded, cancellation-aware exchanges."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import http.client
import ipaddress
import math
import socket
import threading
import time
from typing import Protocol, cast

from context_for_ai.domain.ports.model_gateway import CancellationToken
from context_for_ai.infrastructure.configuration.ollama_model import (
    NormalizedOllamaEndpoint,
)


_ALLOWED_OPERATIONS = frozenset(
    {
        ("GET", "/api/version"),
        ("GET", "/api/status"),
        ("POST", "/api/show"),
        ("POST", "/api/generate"),
    }
)


@dataclass(frozen=True, slots=True)
class OllamaHttpRequest:
    """One allowlisted native Ollama request without caller-supplied headers."""

    method: str
    path: str
    body: bytes | None = None


@dataclass(frozen=True, slots=True)
class OllamaHttpResponse:
    """One status plus a body buffered only for nominal HTTP 200 responses."""

    status: int
    media_type: str | None
    body: bytes | None


class OllamaTransportFailure(Exception):
    """Report a provider-safe transport failure without retaining its cause."""

    def __init__(self, *, response_status: int | None = None) -> None:
        super().__init__()
        self.response_status = response_status


class OllamaTransportTimeout(OllamaTransportFailure):
    """Report expiry while an exchange was active."""


class OllamaTransportCancelled(OllamaTransportFailure):
    """Report cooperative cancellation while an exchange was active."""


class OllamaTransport(Protocol):
    """Exchange one allowlisted request within the caller's shared deadline."""

    def exchange(
        self,
        request: OllamaHttpRequest,
        *,
        deadline: float,
        cancellation_token: CancellationToken,
    ) -> OllamaHttpResponse: ...


class _SocketLike(Protocol):
    def getpeername(self) -> object: ...

    def shutdown(self, how: int) -> None: ...

    def close(self) -> None: ...


class _ResponseLike(Protocol):
    status: int

    def getheader(self, name: str) -> str | None: ...

    def read(self) -> bytes: ...

    def close(self) -> None: ...


class _ConnectionLike(Protocol):
    sock: _SocketLike | None

    def connect(self) -> None: ...

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] = {},
    ) -> None: ...

    def getresponse(self) -> _ResponseLike: ...

    def close(self) -> None: ...


type _ConnectionFactory = Callable[[str, int, float], _ConnectionLike]


@dataclass(slots=True)
class _ExchangeState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    finished: threading.Event = field(default_factory=threading.Event)
    connection: _ConnectionLike | None = None
    response: _ResponseLike | None = None
    result: OllamaHttpResponse | None = None
    failure: OllamaTransportFailure | None = None
    timed_out: bool = False
    response_status: int | None = None
    aborted: bool = False


class _DirectHTTPConnection(http.client.HTTPConnection):
    """HTTP connection whose direct numeric socket exists before connect blocks."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        super().__init__(host=host, port=port, timeout=timeout)
        address = ipaddress.ip_address(host)
        family = socket.AF_INET if address.version == 4 else socket.AF_INET6
        connected_socket = socket.socket(family, socket.SOCK_STREAM)
        connected_socket.settimeout(timeout)
        self.sock = connected_socket
        self._direct_peer = (
            (host, port) if address.version == 4 else (host, port, 0, 0)
        )

    def connect(self) -> None:
        connected_socket = self.sock
        if connected_socket is None:
            raise OSError
        connected_socket.connect(self._direct_peer)


class StandardLibraryOllamaTransport:
    """Use one new direct connection and helper thread for each exchange."""

    def __init__(
        self,
        endpoint: NormalizedOllamaEndpoint,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 0.01,
        connection_factory: _ConnectionFactory | None = None,
    ) -> None:
        if (
            not isinstance(endpoint, NormalizedOllamaEndpoint)
            or not isinstance(poll_interval_seconds, (int, float))
            or isinstance(poll_interval_seconds, bool)
            or not math.isfinite(poll_interval_seconds)
            or poll_interval_seconds <= 0
        ):
            raise ValueError
        self._endpoint = endpoint
        self._monotonic = monotonic
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._connection_factory = connection_factory or _stdlib_connection

    def exchange(
        self,
        request: OllamaHttpRequest,
        *,
        deadline: float,
        cancellation_token: CancellationToken,
    ) -> OllamaHttpResponse:
        """Complete, abort, and join one request-scoped transport operation."""

        self._validate_request(request)
        if cancellation_token.is_cancelled():
            raise OllamaTransportCancelled
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise OllamaTransportTimeout

        state = _ExchangeState()
        worker = threading.Thread(
            target=self._run_exchange,
            args=(state, request, remaining),
            name="ollama-http-exchange",
            daemon=False,
        )
        try:
            worker.start()
        except RuntimeError as error:
            raise OllamaTransportFailure from error

        while not state.finished.is_set():
            if cancellation_token.is_cancelled():
                self._abort_and_join(state, worker)
                raise OllamaTransportCancelled
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                self._abort_and_join(state, worker)
                if cancellation_token.is_cancelled():
                    raise OllamaTransportCancelled
                raise OllamaTransportTimeout
            state.finished.wait(min(self._poll_interval_seconds, remaining))

        worker.join()
        if cancellation_token.is_cancelled():
            self._discard(state)
            raise OllamaTransportCancelled
        if self._monotonic() >= deadline or state.timed_out:
            self._discard(state)
            if cancellation_token.is_cancelled():
                raise OllamaTransportCancelled
            raise OllamaTransportTimeout
        if state.failure is not None:
            raise state.failure
        result = state.result
        if result is None:
            raise OllamaTransportFailure(response_status=state.response_status)
        if cancellation_token.is_cancelled():
            self._discard(state)
            raise OllamaTransportCancelled
        if self._monotonic() >= deadline:
            self._discard(state)
            if cancellation_token.is_cancelled():
                raise OllamaTransportCancelled
            raise OllamaTransportTimeout
        return result

    def _run_exchange(
        self,
        state: _ExchangeState,
        request: OllamaHttpRequest,
        socket_timeout: float,
    ) -> None:
        connection: _ConnectionLike | None = None
        response: _ResponseLike | None = None
        response_status: int | None = None
        try:
            connection = self._connection_factory(
                self._endpoint.host,
                self._endpoint.port,
                socket_timeout,
            )
            with state.lock:
                if state.aborted:
                    return
                state.connection = connection
            connection.connect()
            if self._is_aborted(state):
                return
            self._verify_loopback_peer(connection)
            if self._is_aborted(state):
                return

            headers = {"Accept": "application/json"}
            if request.body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(
                request.method,
                request.path,
                body=request.body,
                headers=headers,
            )
            response = connection.getresponse()
            response_status = response.status
            if (
                not isinstance(response_status, int)
                or isinstance(response_status, bool)
                or not 100 <= response_status <= 599
            ):
                raise OllamaTransportFailure
            with state.lock:
                if state.aborted:
                    return
                state.response = response
                state.response_status = response_status

            if response_status == 200:
                media_type = response.getheader("Content-Type")
                body = response.read()
                if not isinstance(body, bytes):
                    raise OllamaTransportFailure(response_status=200)
                result = OllamaHttpResponse(response_status, media_type, body)
            else:
                result = OllamaHttpResponse(response_status, None, None)
            with state.lock:
                if not state.aborted:
                    state.result = result
        except (TimeoutError, socket.timeout):
            with state.lock:
                if not state.aborted:
                    state.timed_out = True
                    state.response_status = response_status
        except Exception:
            with state.lock:
                if not state.aborted:
                    state.failure = OllamaTransportFailure(
                        response_status=response_status
                    )
                    state.response_status = response_status
        finally:
            _close_quietly(response)
            _close_quietly(connection)
            with state.lock:
                state.response = None
                state.connection = None
            state.finished.set()

    @staticmethod
    def _validate_request(request: OllamaHttpRequest) -> None:
        if not isinstance(request, OllamaHttpRequest):
            raise ValueError
        if (request.method, request.path) not in _ALLOWED_OPERATIONS:
            raise ValueError
        if request.method == "GET" and request.body is not None:
            raise ValueError
        if request.method == "POST" and not isinstance(request.body, bytes):
            raise ValueError

    @staticmethod
    def _verify_loopback_peer(connection: _ConnectionLike) -> None:
        connected_socket = connection.sock
        if connected_socket is None:
            raise OllamaTransportFailure
        peer = connected_socket.getpeername()
        host = peer[0] if isinstance(peer, tuple) and peer else peer
        try:
            address = ipaddress.ip_address(host)
        except ValueError as error:
            raise OllamaTransportFailure from error
        if not address.is_loopback:
            raise OllamaTransportFailure

    @staticmethod
    def _is_aborted(state: _ExchangeState) -> bool:
        with state.lock:
            return state.aborted

    @staticmethod
    def _discard(state: _ExchangeState) -> None:
        with state.lock:
            state.result = None

    @staticmethod
    def _abort_and_join(
        state: _ExchangeState,
        worker: threading.Thread,
    ) -> None:
        with state.lock:
            state.aborted = True
            state.result = None
            response = state.response
            connection = state.connection
            connected_socket = connection.sock if connection is not None else None
        if connected_socket is not None:
            try:
                connected_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            _close_quietly(connected_socket)
        _close_quietly(response)
        _close_quietly(connection)
        worker.join()


def _stdlib_connection(host: str, port: int, timeout: float) -> _ConnectionLike:
    return cast(_ConnectionLike, _DirectHTTPConnection(host, port, timeout))


def _close_quietly(value: object | None) -> None:
    if value is None:
        return
    try:
        value.close()  # type: ignore[attr-defined]
    except Exception:
        pass


__all__ = [
    "OllamaHttpRequest",
    "OllamaHttpResponse",
    "OllamaTransport",
    "OllamaTransportCancelled",
    "OllamaTransportFailure",
    "OllamaTransportTimeout",
    "StandardLibraryOllamaTransport",
]
