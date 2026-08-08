"""Deterministic request-scoped transport for Ollama adapter evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, unique
import json
from threading import Event, Lock

from context_for_ai.domain.ports import CancellationToken, GenerationRequest
from context_for_ai.infrastructure.ollama.transport import (
    OllamaHttpRequest,
    OllamaHttpResponse,
    OllamaTransportCancelled,
    OllamaTransportFailure,
    OllamaTransportTimeout,
)
from context_for_ai.infrastructure.ollama.wire import (
    encode_generate_request,
    encode_show_request,
)


class OllamaTransportFixtureError(AssertionError):
    """Report an invalid, mismatched, or exhausted controlled script."""


class ControlledCancellationToken:
    """Thread-safe, monotonic cancellation token owned by one test call."""

    def __init__(self, *, cancelled: bool = False) -> None:
        self._cancelled = Event()
        if cancelled:
            self._cancelled.set()

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


class ControlledMonotonicClock:
    """Thread-safe manually advanced monotonic clock."""

    def __init__(self, initial: float = 100.0) -> None:
        self._value = float(initial)
        self._lock = Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._value

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise OllamaTransportFixtureError(
                "Controlled clock advances must be non-negative."
            )
        with self._lock:
            self._value += seconds


@unique
class ScriptedEffect(StrEnum):
    RESPONSE = "RESPONSE"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class ScriptedExchange:
    """One exact expected request and its controlled transport observation."""

    expected_request: OllamaHttpRequest
    status: int = 200
    media_type: str | None = "application/json"
    body_fragments: tuple[bytes, ...] = (b"{}",)
    advance_seconds: float = 0.0
    effect: ScriptedEffect = ScriptedEffect.RESPONSE
    failure_status: int | None = None
    hold_after_fragments: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.expected_request, OllamaHttpRequest):
            raise OllamaTransportFixtureError(
                "Scripted exchanges require an exact OllamaHttpRequest."
            )
        if not isinstance(self.effect, ScriptedEffect):
            raise OllamaTransportFixtureError(
                "Scripted exchange effect must be canonical."
            )
        if self.advance_seconds < 0:
            raise OllamaTransportFixtureError(
                "Scripted exchange time advance must be non-negative."
            )
        fragments = tuple(self.body_fragments)
        if any(not isinstance(fragment, bytes) for fragment in fragments):
            raise OllamaTransportFixtureError(
                "Scripted response fragments must be bytes."
            )
        object.__setattr__(self, "body_fragments", fragments)
        if self.hold_after_fragments is not None and not (
            0 <= self.hold_after_fragments <= len(fragments)
        ):
            raise OllamaTransportFixtureError(
                "Held fragment index must identify a response boundary."
            )


@dataclass(frozen=True, slots=True)
class ControlledExchangeRecord:
    """One immutable request observation without a retained cancellation token."""

    ordinal: int
    request: OllamaHttpRequest
    deadline: float


@dataclass(slots=True)
class _HoldPoint:
    reached: Event
    released: Event


class ScriptedOllamaTransport:
    """Execute a finite script while emulating closure and buffered fragments."""

    def __init__(
        self,
        steps: tuple[ScriptedExchange, ...],
        clock: ControlledMonotonicClock,
    ) -> None:
        self._steps = tuple(steps)
        if any(not isinstance(step, ScriptedExchange) for step in self._steps):
            raise OllamaTransportFixtureError(
                "Controlled transport steps must be ScriptedExchange values."
            )
        self._clock = clock
        self._lock = Lock()
        self._next_index = 0
        self._records: list[ControlledExchangeRecord] = []
        self._closed_indices: list[int] = []
        self._aborted_indices: list[int] = []
        self._active_indices: set[int] = set()
        self._holds = {
            index: _HoldPoint(Event(), Event())
            for index, step in enumerate(self._steps)
            if step.hold_after_fragments is not None
        }

    def exchange(
        self,
        request: OllamaHttpRequest,
        *,
        deadline: float,
        cancellation_token: CancellationToken,
    ) -> OllamaHttpResponse:
        with self._lock:
            if self._next_index >= len(self._steps):
                raise OllamaTransportFixtureError(
                    "Controlled Ollama transport script is exhausted."
                )
            index = self._next_index
            step = self._steps[index]
            if request != step.expected_request:
                raise OllamaTransportFixtureError(
                    "Controlled Ollama request did not match the next script step."
                )
            self._next_index += 1
            self._records.append(ControlledExchangeRecord(index, request, deadline))
            self._active_indices.add(index)

        try:
            self._checkpoint(cancellation_token, deadline, index)
            self._clock.advance(step.advance_seconds)
            self._checkpoint(cancellation_token, deadline, index)
            if step.effect is ScriptedEffect.TIMEOUT:
                self._mark_aborted(index)
                raise OllamaTransportTimeout
            if step.effect is ScriptedEffect.FAILURE:
                raise OllamaTransportFailure(
                    response_status=step.failure_status
                )

            if step.status != 200:
                self._hold_if_requested(
                    index,
                    step,
                    completed_fragments=0,
                    cancellation_token=cancellation_token,
                    deadline=deadline,
                )
                self._checkpoint(cancellation_token, deadline, index)
                return OllamaHttpResponse(step.status, None, None)

            buffer = bytearray()
            self._hold_if_requested(
                index,
                step,
                completed_fragments=0,
                cancellation_token=cancellation_token,
                deadline=deadline,
            )
            for fragment_number, fragment in enumerate(step.body_fragments, start=1):
                buffer.extend(fragment)
                self._hold_if_requested(
                    index,
                    step,
                    completed_fragments=fragment_number,
                    cancellation_token=cancellation_token,
                    deadline=deadline,
                )
            self._checkpoint(cancellation_token, deadline, index)
            return OllamaHttpResponse(step.status, step.media_type, bytes(buffer))
        finally:
            with self._lock:
                self._active_indices.discard(index)
                self._closed_indices.append(index)

    @property
    def call_snapshot(self) -> tuple[ControlledExchangeRecord, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def closed_indices(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._closed_indices)

    @property
    def aborted_indices(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._aborted_indices)

    @property
    def active_indices(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(sorted(self._active_indices))

    def wait_until_held(self, index: int, timeout_seconds: float = 2.0) -> None:
        hold = self._hold(index)
        if not hold.reached.wait(timeout_seconds):
            raise OllamaTransportFixtureError(
                "Controlled Ollama exchange did not reach its hold point."
            )

    def release(self, index: int) -> None:
        self._hold(index).released.set()

    def _hold_if_requested(
        self,
        index: int,
        step: ScriptedExchange,
        *,
        completed_fragments: int,
        cancellation_token: CancellationToken,
        deadline: float,
    ) -> None:
        if step.hold_after_fragments != completed_fragments:
            return
        hold = self._hold(index)
        hold.reached.set()
        while not hold.released.wait(0.001):
            self._checkpoint(cancellation_token, deadline, index)
        self._checkpoint(cancellation_token, deadline, index)

    def _checkpoint(
        self,
        cancellation_token: CancellationToken,
        deadline: float,
        index: int,
    ) -> None:
        if cancellation_token.is_cancelled():
            self._mark_aborted(index)
            raise OllamaTransportCancelled
        if self._clock() >= deadline:
            self._mark_aborted(index)
            if cancellation_token.is_cancelled():
                raise OllamaTransportCancelled
            raise OllamaTransportTimeout

    def _mark_aborted(self, index: int) -> None:
        with self._lock:
            if index not in self._aborted_indices:
                self._aborted_indices.append(index)

    def _hold(self, index: int) -> _HoldPoint:
        try:
            return self._holds[index]
        except KeyError as error:
            raise OllamaTransportFixtureError(
                "Controlled exchange does not define a hold point."
            ) from error


def json_body(value: Mapping[str, object]) -> bytes:
    """Encode deterministic fixture JSON without production codec shortcuts."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def successful_script(
    document: Mapping[str, object],
    request: GenerationRequest,
) -> tuple[ScriptedExchange, ...]:
    """Build the canonical four-stage success script from versioned fixture data."""

    model = str(document["model"])
    responses = document["responses"]
    if not isinstance(responses, Mapping):
        raise OllamaTransportFixtureError("Fixture responses must be an object.")
    advances = (0.1, 0.2, 0.3, 0.4)
    requests = (
        OllamaHttpRequest("GET", "/api/version"),
        OllamaHttpRequest("GET", "/api/status"),
        OllamaHttpRequest("POST", "/api/show", encode_show_request(model)),
        OllamaHttpRequest(
            "POST",
            "/api/generate",
            encode_generate_request(request, model),
        ),
    )
    response_names = ("version", "status", "show", "generate")
    steps: list[ScriptedExchange] = []
    for expected_request, response_name, advance in zip(
        requests, response_names, advances, strict=True
    ):
        response = responses[response_name]
        if not isinstance(response, Mapping):
            raise OllamaTransportFixtureError(
                "Each fixture response must be an object."
            )
        body = response["body"]
        if not isinstance(body, Mapping):
            raise OllamaTransportFixtureError(
                "Each fixture response body must be an object."
            )
        steps.append(
            ScriptedExchange(
                expected_request=expected_request,
                status=int(response["status"]),
                media_type=str(response["media_type"]),
                body_fragments=(json_body(body),),
                advance_seconds=advance,
            )
        )
    return tuple(steps)


__all__ = [
    "ControlledCancellationToken",
    "ControlledExchangeRecord",
    "ControlledMonotonicClock",
    "OllamaTransportFixtureError",
    "ScriptedEffect",
    "ScriptedExchange",
    "ScriptedOllamaTransport",
    "json_body",
    "successful_script",
]
