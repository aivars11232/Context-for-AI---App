"""Unit coverage for direct, bounded, request-scoped Ollama HTTP transport."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time

import pytest

from context_for_ai.infrastructure.configuration.ollama_model import (
    normalize_ollama_endpoint,
)
from context_for_ai.infrastructure.ollama.transport import (
    OllamaHttpRequest,
    OllamaTransportCancelled,
    OllamaTransportFailure,
    OllamaTransportTimeout,
    StandardLibraryOllamaTransport,
)


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


class _CancelsAfterChecks:
    def __init__(self, count: int) -> None:
        self._count = count
        self.checks = 0

    def is_cancelled(self) -> bool:
        self.checks += 1
        return self.checks >= self._count


class _CancelsWhen:
    def __init__(self, predicate) -> None:
        self._predicate = predicate

    def is_cancelled(self) -> bool:
        return bool(self._predicate())


class _FakeSocket:
    def __init__(self, events: list[str], peer: object) -> None:
        self._events = events
        self._peer = peer
        self.on_close = lambda: None

    def getpeername(self) -> object:
        self._events.append("peer")
        return self._peer

    def shutdown(self, _how: int) -> None:
        self._events.append("socket_shutdown")
        self.on_close()

    def close(self) -> None:
        self._events.append("socket_close")
        self.on_close()


class _FakeResponse:
    def __init__(
        self,
        events: list[str],
        *,
        status: int = 200,
        media_type: str | None = "application/json",
        body: bytes = b'{"ok":true}',
        read_error: Exception | None = None,
        held: bool = False,
    ) -> None:
        self._events = events
        self.status = status
        self._media_type = media_type
        self._body = body
        self._read_error = read_error
        self._held = held
        self._release = threading.Event()
        self.read_called = False
        self.closed = False

    def getheader(self, name: str) -> str | None:
        self._events.append(f"header:{name}")
        return self._media_type

    def read(self) -> bytes:
        self._events.append("read")
        self.read_called = True
        if self._held:
            self._release.wait(timeout=2)
        if self._read_error is not None:
            raise self._read_error
        return self._body

    def close(self) -> None:
        self._events.append("response_close")
        self.closed = True
        self._release.set()


class _FakeConnection:
    def __init__(
        self,
        events: list[str],
        response: _FakeResponse,
        *,
        peer: object = ("127.0.0.1", 11434),
        connect_error: Exception | None = None,
        response_error: Exception | None = None,
        held_connect: bool = False,
    ) -> None:
        self._events = events
        self._response = response
        self._connect_error = connect_error
        self._response_error = response_error
        self._held_connect = held_connect
        self._connect_release = threading.Event()
        self.sock = _FakeSocket(events, peer)
        self.sock.on_close = self._release_blocking_work
        self.request_observation: tuple[
            str, str, bytes | None, dict[str, str]
        ] | None = None
        self.closed = False

    def connect(self) -> None:
        self._events.append("connect")
        if self._held_connect:
            self._connect_release.wait(timeout=2)
        if self._connect_error is not None:
            raise self._connect_error

    def _release_blocking_work(self) -> None:
        self._connect_release.set()
        self._response.close()

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] = {},
    ) -> None:
        self._events.append("request")
        self.request_observation = (method, url, body, dict(headers))

    def getresponse(self) -> _FakeResponse:
        self._events.append("getresponse")
        if self._response_error is not None:
            raise self._response_error
        return self._response

    def close(self) -> None:
        self._events.append("connection_close")
        self.closed = True


@dataclass
class _Harness:
    transport: StandardLibraryOllamaTransport
    connection: _FakeConnection
    response: _FakeResponse
    events: list[str]
    construction: list[tuple[str, int, float]]


def _harness(
    *,
    peer: object = ("127.0.0.1", 11434),
    status: int = 200,
    body: bytes = b'{"ok":true}',
    media_type: str | None = "application/json",
    read_error: Exception | None = None,
    held: bool = False,
    connect_error: Exception | None = None,
    response_error: Exception | None = None,
    held_connect: bool = False,
) -> _Harness:
    events: list[str] = []
    construction: list[tuple[str, int, float]] = []
    response = _FakeResponse(
        events,
        status=status,
        body=body,
        media_type=media_type,
        read_error=read_error,
        held=held,
    )
    connection = _FakeConnection(
        events,
        response,
        peer=peer,
        connect_error=connect_error,
        response_error=response_error,
        held_connect=held_connect,
    )

    def factory(host: str, port: int, timeout: float) -> _FakeConnection:
        construction.append((host, port, timeout))
        return connection

    transport = StandardLibraryOllamaTransport(
        normalize_ollama_endpoint("http://127.0.0.1:11434"),
        poll_interval_seconds=0.001,
        connection_factory=factory,
    )
    return _Harness(transport, connection, response, events, construction)


def _deadline(seconds: float = 1) -> float:
    return time.monotonic() + seconds


def test_transport_connects_and_checks_the_actual_peer_before_sending() -> None:
    harness = _harness(body=b'{"version":"1"}')

    result = harness.transport.exchange(
        OllamaHttpRequest("GET", "/api/version"),
        deadline=_deadline(),
        cancellation_token=_NeverCancelled(),
    )

    assert result.status == 200
    assert result.media_type == "application/json"
    assert result.body == b'{"version":"1"}'
    assert harness.construction[0][:2] == ("127.0.0.1", 11434)
    assert 0 < harness.construction[0][2] <= 1
    assert harness.events.index("peer") < harness.events.index("request")
    assert harness.connection.request_observation == (
        "GET",
        "/api/version",
        None,
        {"Accept": "application/json"},
    )
    assert harness.response.closed
    assert harness.connection.closed


def test_default_stdlib_connection_completes_one_real_loopback_exchange() -> None:
    observation: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            observation["path"] = self.path
            observation["headers"] = dict(self.headers)
            body = b'{"version":"test-daemon"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    worker = threading.Thread(
        target=server.handle_request,
        name="ollama-transport-test-server",
    )
    worker.start()
    try:
        port = server.server_address[1]
        transport = StandardLibraryOllamaTransport(
            normalize_ollama_endpoint(f"http://127.0.0.1:{port}")
        )
        response = transport.exchange(
            OllamaHttpRequest("GET", "/api/version"),
            deadline=_deadline(),
            cancellation_token=_NeverCancelled(),
        )
    finally:
        worker.join(2)
        server.server_close()

    assert not worker.is_alive()
    assert response.status == 200
    assert response.media_type == "application/json; charset=utf-8"
    assert response.body == b'{"version":"test-daemon"}'
    assert observation["path"] == "/api/version"
    observed_headers = {
        key.casefold(): value
        for key, value in observation["headers"].items()  # type: ignore[union-attr]
    }
    assert observed_headers["accept"] == "application/json"
    assert not {
        "authorization",
        "proxy-authorization",
        "cookie",
        "x-api-key",
    } & set(observed_headers)


def test_transport_accepts_an_actual_ipv6_loopback_peer() -> None:
    harness = _harness(peer=("::1", 11434, 0, 0))

    result = harness.transport.exchange(
        OllamaHttpRequest("GET", "/api/status"),
        deadline=_deadline(),
        cancellation_token=_NeverCancelled(),
    )

    assert result.status == 200


@pytest.mark.parametrize(
    "peer",
    (("192.0.2.4", 11434), ("example.test", 11434), None),
)
def test_transport_rejects_a_non_loopback_or_unparseable_actual_peer(
    peer: object,
) -> None:
    harness = _harness(peer=peer)

    with pytest.raises(OllamaTransportFailure):
        harness.transport.exchange(
            OllamaHttpRequest("GET", "/api/version"),
            deadline=_deadline(),
            cancellation_token=_NeverCancelled(),
        )

    assert "request" not in harness.events
    assert harness.connection.closed


@pytest.mark.parametrize("status", (302, 401, 404, 429, 500, 504))
def test_non_200_status_is_returned_without_reading_or_retaining_its_body(
    status: int,
) -> None:
    harness = _harness(status=status, body=b'{"secret":"must-not-read"}')

    result = harness.transport.exchange(
        OllamaHttpRequest("POST", "/api/show", b"{}"),
        deadline=_deadline(),
        cancellation_token=_NeverCancelled(),
    )

    assert result.status == status
    assert result.media_type is None
    assert result.body is None
    assert not harness.response.read_called
    assert harness.response.closed
    assert harness.connection.closed


def test_transport_sends_no_ambient_or_sensitive_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("OLLAMA_API_KEY", "secret")
    monkeypatch.setenv("NETRC", "/secret/netrc")
    harness = _harness()

    harness.transport.exchange(
        OllamaHttpRequest("POST", "/api/generate", b'{"prompt":"exact"}'),
        deadline=_deadline(),
        cancellation_token=_NeverCancelled(),
    )

    assert harness.connection.request_observation == (
        "POST",
        "/api/generate",
        b'{"prompt":"exact"}',
        {"Accept": "application/json", "Content-Type": "application/json"},
    )


@pytest.mark.parametrize(
    "http_request",
    (
        OllamaHttpRequest("GET", "/api/generate"),
        OllamaHttpRequest("POST", "/api/pull", b"{}"),
        OllamaHttpRequest("GET", "/api/version", b"{}"),
        OllamaHttpRequest("POST", "/api/show"),
    ),
)
def test_transport_rejects_every_non_allowlisted_operation_before_connecting(
    http_request: OllamaHttpRequest,
) -> None:
    harness = _harness()

    with pytest.raises(ValueError):
        harness.transport.exchange(
            http_request,
            deadline=_deadline(),
            cancellation_token=_NeverCancelled(),
        )

    assert not harness.construction


def test_a_200_body_read_failure_retains_only_the_usable_status() -> None:
    harness = _harness(read_error=OSError("private provider detail"))

    with pytest.raises(OllamaTransportFailure) as captured:
        harness.transport.exchange(
            OllamaHttpRequest("POST", "/api/generate", b"{}"),
            deadline=_deadline(),
            cancellation_token=_NeverCancelled(),
        )

    assert captured.value.response_status == 200
    assert str(captured.value) == ""
    assert harness.response.closed
    assert harness.connection.closed


def test_a_failure_before_response_status_retains_no_exception_detail() -> None:
    harness = _harness(response_error=OSError("private connection detail"))

    with pytest.raises(OllamaTransportFailure) as captured:
        harness.transport.exchange(
            OllamaHttpRequest("GET", "/api/version"),
            deadline=_deadline(),
            cancellation_token=_NeverCancelled(),
        )

    assert captured.value.response_status is None
    assert str(captured.value) == ""
    assert harness.connection.closed


def test_socket_timeout_is_classified_and_all_transport_work_is_joined() -> None:
    harness = _harness(connect_error=TimeoutError("private timeout detail"))

    with pytest.raises(OllamaTransportTimeout):
        harness.transport.exchange(
            OllamaHttpRequest("GET", "/api/version"),
            deadline=_deadline(),
            cancellation_token=_NeverCancelled(),
        )

    assert harness.connection.closed
    assert not any(
        thread.name == "ollama-http-exchange" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_cancellation_aborts_a_held_body_and_joins_the_helper() -> None:
    harness = _harness(held=True, body=b'{"response":"must-discard"}')
    token = _CancelsWhen(lambda: harness.response.read_called)

    with pytest.raises(OllamaTransportCancelled):
        harness.transport.exchange(
            OllamaHttpRequest("POST", "/api/generate", b"{}"),
            deadline=_deadline(),
            cancellation_token=token,
        )

    assert harness.response.closed
    assert harness.connection.closed
    assert not any(
        thread.name == "ollama-http-exchange" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_cancellation_aborts_a_held_connect_before_any_request_is_sent() -> None:
    harness = _harness(held_connect=True)
    token = _CancelsWhen(lambda: "connect" in harness.events)

    with pytest.raises(OllamaTransportCancelled):
        harness.transport.exchange(
            OllamaHttpRequest("GET", "/api/version"),
            deadline=_deadline(),
            cancellation_token=token,
        )

    assert "request" not in harness.events
    assert "socket_shutdown" in harness.events
    assert harness.connection.closed
    assert not any(
        thread.name == "ollama-http-exchange" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_deadline_aborts_a_held_body_and_joins_the_helper() -> None:
    harness = _harness(held=True, body=b'{"response":"must-discard"}')

    with pytest.raises(OllamaTransportTimeout):
        harness.transport.exchange(
            OllamaHttpRequest("POST", "/api/generate", b"{}"),
            deadline=_deadline(0.01),
            cancellation_token=_NeverCancelled(),
        )

    assert harness.response.closed
    assert harness.connection.closed
    assert not any(
        thread.name == "ollama-http-exchange" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_entry_cancellation_and_expired_deadline_start_no_transport_work() -> None:
    cancelled = _harness()
    with pytest.raises(OllamaTransportCancelled):
        cancelled.transport.exchange(
            OllamaHttpRequest("GET", "/api/version"),
            deadline=time.monotonic() - 1,
            cancellation_token=_CancelsAfterChecks(1),
        )
    assert not cancelled.construction

    expired = _harness()
    with pytest.raises(OllamaTransportTimeout):
        expired.transport.exchange(
            OllamaHttpRequest("GET", "/api/version"),
            deadline=time.monotonic() - 1,
            cancellation_token=_NeverCancelled(),
        )
    assert not expired.construction
