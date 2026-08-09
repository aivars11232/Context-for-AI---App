"""Inward system-service ports with no desktop or infrastructure dependency."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from context_for_ai.domain.enums import FailureCode, PipelineStage
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.configuration import LogLevel
from context_for_ai.domain.value_objects import DomainId, ensure_utc


def _optional_non_negative_integer(field_name: str, value: int | None) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise LifecycleInvariantError(f"{field_name} must be non-negative or null.")


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One redacted structured event with additive correlation identifiers."""

    timestamp: datetime
    level: LogLevel
    event_name: str
    stage: PipelineStage
    configuration_fingerprint: str
    conversation_id: DomainId | None = None
    user_message_id: DomainId | None = None
    processing_run_id: DomainId | None = None
    context_packet_id: DomainId | None = None
    model_request_id: DomainId | None = None
    model_response_id: DomainId | None = None
    validation_result_id: DomainId | None = None
    clarification_request_id: DomainId | None = None
    memory_id: DomainId | None = None
    memory_revision_id: DomainId | None = None
    correction_attempt_number: int | None = None
    error_type: FailureCode | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))
        if not isinstance(self.event_name, str) or not self.event_name.strip():
            raise LifecycleInvariantError("TraceEvent.event_name must be non-empty.")
        if (
            not isinstance(self.configuration_fingerprint, str)
            or not self.configuration_fingerprint.strip()
        ):
            raise LifecycleInvariantError(
                "TraceEvent.configuration_fingerprint must be non-empty."
            )
        _optional_non_negative_integer(
            "TraceEvent.correction_attempt_number",
            self.correction_attempt_number,
        )
        if self.error_type is not None and not isinstance(self.error_type, FailureCode):
            raise LifecycleInvariantError(
                "TraceEvent.error_type must be a canonical failure code or null."
            )


class Clock(Protocol):
    """Return the current timezone-aware UTC instant."""

    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    """Create one canonical domain identifier on demand."""

    def new_id(self) -> DomainId: ...


class TraceLogger(Protocol):
    """Emit a pre-redacted structured trace event."""

    def emit(self, event: TraceEvent) -> None: ...


class TransactionBoundary(Protocol):
    """Open one short atomic boundary without exposing a concrete connection."""

    def transaction(self) -> AbstractContextManager[None]: ...
