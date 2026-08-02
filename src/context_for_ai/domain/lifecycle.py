"""Immutable records for processing, model, validation, and failure lineage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from context_for_ai.domain.enums import (
    ClarificationReason,
    FailureCode,
    ModelRequestPurpose,
    ModelRequestStatus,
    PipelineStage,
    ProcessingRunStatus,
    ProviderKind,
    ValidationStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    ensure_utc,
)


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _optional_text(field_name: str, value: str | None) -> None:
    if value is not None:
        _required_text(field_name, value)


def _normalize_time(instance: object, field_name: str) -> datetime:
    value = ensure_utc(getattr(instance, field_name))
    object.__setattr__(instance, field_name, value)
    return value


def _normalize_optional_time(instance: object, field_name: str) -> datetime | None:
    raw_value = getattr(instance, field_name)
    if raw_value is None:
        return None
    value = ensure_utc(raw_value)
    object.__setattr__(instance, field_name, value)
    return value


def _non_negative_integer(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleInvariantError(f"{field_name} must be a non-negative integer.")


def _freeze_json_object(value: FrozenJsonObject | Mapping[str, object]) -> FrozenJsonObject:
    return value if isinstance(value, FrozenJsonObject) else FrozenJsonObject(value)


def _freeze_json_objects(
    values: tuple[FrozenJsonObject, ...],
) -> tuple[FrozenJsonObject, ...]:
    if isinstance(values, (str, bytes)):
        raise LifecycleInvariantError("JSON evidence must be a collection of objects.")
    return tuple(_freeze_json_object(value) for value in values)


@dataclass(frozen=True, slots=True)
class ProcessingRun:
    id: DomainId
    conversation_id: DomainId
    user_message_id: DomainId
    idempotency_key: str
    status: ProcessingRunStatus
    state_version_at_start: int
    configuration_fingerprint: str
    started_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        _required_text("ProcessingRun.idempotency_key", self.idempotency_key)
        _non_negative_integer(
            "ProcessingRun.state_version_at_start",
            self.state_version_at_start,
        )
        _required_text(
            "ProcessingRun.configuration_fingerprint",
            self.configuration_fingerprint,
        )
        _normalize_time(self, "started_at")
        _normalize_optional_time(self, "completed_at")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    id: DomainId
    processing_run_id: DomainId
    context_packet_id: DomainId
    purpose: ModelRequestPurpose
    attempt_number: int
    provider: ProviderKind
    model_name: str
    status: ModelRequestStatus
    rendered_prompt: str
    request: FrozenJsonObject
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    safe_error_message: str | None

    def __post_init__(self) -> None:
        _non_negative_integer("ModelRequest.attempt_number", self.attempt_number)
        if self.attempt_number > 2:
            raise LifecycleInvariantError("ModelRequest.attempt_number cannot exceed 2.")
        _required_text("ModelRequest.model_name", self.model_name)
        if not isinstance(self.rendered_prompt, str):
            raise LifecycleInvariantError("ModelRequest.rendered_prompt must be text.")
        object.__setattr__(self, "request", _freeze_json_object(self.request))
        _normalize_optional_time(self, "started_at")
        _normalize_optional_time(self, "completed_at")
        _optional_text("ModelRequest.error_code", self.error_code)
        _optional_text("ModelRequest.safe_error_message", self.safe_error_message)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    id: DomainId
    model_request_id: DomainId
    response_text: str
    metadata: FrozenJsonObject
    assistant_message_id: DomainId | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.response_text, str):
            raise LifecycleInvariantError("ModelResponse.response_text must be text.")
        object.__setattr__(self, "metadata", _freeze_json_object(self.metadata))
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    id: DomainId
    model_response_id: DomainId
    status: ValidationStatus
    score: UnitScore
    violations: tuple[FrozenJsonObject, ...]
    evidence: tuple[FrozenJsonObject, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "violations", _freeze_json_objects(self.violations))
        object.__setattr__(self, "evidence", _freeze_json_objects(self.evidence))
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class CorrectionAttempt:
    id: DomainId
    processing_run_id: DomainId
    attempt_number: int
    prior_model_response_id: DomainId
    revised_model_request_id: DomainId
    reasons: tuple[FrozenJsonObject, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if self.attempt_number not in (1, 2):
            raise LifecycleInvariantError(
                "CorrectionAttempt.attempt_number must be 1 or 2."
            )
        reasons = _freeze_json_objects(self.reasons)
        if not reasons:
            raise LifecycleInvariantError("CorrectionAttempt.reasons cannot be empty.")
        object.__setattr__(self, "reasons", reasons)
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class ClarificationRequest:
    id: DomainId
    processing_run_id: DomainId
    reason: ClarificationReason
    question_text: str
    details: FrozenJsonObject
    created_at: datetime

    def __post_init__(self) -> None:
        _required_text("ClarificationRequest.question_text", self.question_text)
        object.__setattr__(self, "details", _freeze_json_object(self.details))
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class SafeFailure:
    id: DomainId
    processing_run_id: DomainId
    stage: PipelineStage
    error_code: FailureCode
    safe_message: str
    details: FrozenJsonObject
    is_terminal: bool
    created_at: datetime

    def __post_init__(self) -> None:
        _required_text("SafeFailure.safe_message", self.safe_message)
        object.__setattr__(self, "details", _freeze_json_object(self.details))
        if not isinstance(self.is_terminal, bool):
            raise LifecycleInvariantError("SafeFailure.is_terminal must be boolean.")
        _normalize_time(self, "created_at")
