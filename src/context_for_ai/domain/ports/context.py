"""Inward contracts for deterministic context components used by application code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from context_for_ai.domain.decisions import (
    ContextPacket,
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.entities import Memory
from context_for_ai.domain.enums import ClarificationReason
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ClarificationRequest, ValidationResult
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    ensure_utc,
)


@dataclass(frozen=True, slots=True)
class ClarificationBuildRequest:
    """Canonical reason and template inputs for one deterministic question."""

    clarification_request_id: DomainId
    processing_run_id: DomainId
    reason: ClarificationReason
    details: FrozenJsonObject
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.details, FrozenJsonObject):
            object.__setattr__(self, "details", FrozenJsonObject(self.details))
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """All deterministic inputs needed to rank a bounded memory candidate set."""

    context_packet_id: DomainId
    processing_run_id: DomainId
    source_message_id: DomainId
    conversation_id: DomainId
    project_id: DomainId | None
    active_topic_label: str | None
    request_text: str
    candidate_memories: tuple[Memory, ...]
    minimum_relevance_score: UnitScore
    result_limit: int
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if self.active_topic_label is not None and not isinstance(
            self.active_topic_label, str
        ):
            raise LifecycleInvariantError(
                "RetrievalRequest.active_topic_label must be text or null."
            )
        if not isinstance(self.request_text, str):
            raise LifecycleInvariantError("RetrievalRequest.request_text must be text.")
        object.__setattr__(self, "candidate_memories", tuple(self.candidate_memories))
        if (
            not isinstance(self.result_limit, int)
            or isinstance(self.result_limit, bool)
            or self.result_limit < 0
        ):
            raise LifecycleInvariantError(
                "RetrievalRequest.result_limit must be non-negative."
            )
        object.__setattr__(self, "evaluated_at", ensure_utc(self.evaluated_at))


@dataclass(frozen=True, slots=True)
class RetrievalDecision:
    """Complete selected/excluded retrieval audit returned by the retriever."""

    selected: tuple[RetrievalResult, ...]
    excluded: tuple[RetrievalExclusion, ...]
    confidence: UnitScore | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected", tuple(self.selected))
        object.__setattr__(self, "excluded", tuple(self.excluded))


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    """One immutable packet and one fully buffered candidate for validation."""

    packet: ContextPacket
    model_response_id: DomainId
    validation_result_id: DomainId
    candidate_response: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_response, str):
            raise LifecycleInvariantError(
                "ValidationRequest.candidate_response must be text."
            )
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))


@dataclass(frozen=True, slots=True)
class RevisionEnvelope:
    """Typed violations and unchanged packet lineage for one permitted revision."""

    context_packet_id: DomainId
    failed_model_response_id: DomainId
    attempt_number: int
    violations: tuple[FrozenJsonObject, ...]

    def __post_init__(self) -> None:
        if self.attempt_number not in (1, 2):
            raise LifecycleInvariantError(
                "RevisionEnvelope.attempt_number must be 1 or 2."
            )
        violations = tuple(
            value if isinstance(value, FrozenJsonObject) else FrozenJsonObject(value)
            for value in self.violations
        )
        if not violations:
            raise LifecycleInvariantError(
                "RevisionEnvelope.violations cannot be empty."
            )
        object.__setattr__(self, "violations", violations)


@dataclass(frozen=True, slots=True)
class CorrectionExhausted:
    """Typed bounded result when no configured revision remains."""

    failed_model_response_id: DomainId


type CorrectionDecision = RevisionEnvelope | CorrectionExhausted


class ClarificationBuilder(Protocol):
    """Build one canonical clarification question without a model call."""

    def build(self, request: ClarificationBuildRequest) -> ClarificationRequest: ...


class ContextRetriever(Protocol):
    """Return deterministic retrieval selections and all exclusion evidence."""

    def retrieve(self, request: RetrievalRequest) -> RetrievalDecision: ...


class ResponseValidator(Protocol):
    """Validate one complete candidate against one immutable packet."""

    def validate(self, request: ValidationRequest) -> ValidationResult: ...


class CorrectionController(Protocol):
    """Plan one bounded revision or report deterministic exhaustion."""

    def plan(
        self,
        *,
        context_packet_id: DomainId,
        failed_model_response_id: DomainId,
        validation_result: ValidationResult,
        current_revision_count: int,
        maximum_revisions: int,
    ) -> CorrectionDecision: ...
