"""Inward contracts for deterministic context components used by application code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from context_for_ai.domain.decisions import (
    Constraint,
    ConstraintDecision,
    ConstraintSourceEvidence,
    ContextPacket,
    InterpretationDecision,
    ReferenceDecision,
    ReferenceMention,
    ReferenceOutcome,
    RetrievalExclusion,
    RetrievalResult,
    require_retrieval_evidence,
)
from context_for_ai.domain.entities import ConversationState, Entity, Memory, Message
from context_for_ai.domain.enums import ClarificationReason, MessageRole, ReferenceStatus
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ClarificationRequest, ValidationResult
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    ensure_utc,
)


@dataclass(frozen=True, slots=True)
class InterpretationRequest:
    """Exact immutable inputs for one deterministic interpretation."""

    processing_run_id: DomainId
    message: Message
    state: ConversationState
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if self.message.conversation_id != self.state.conversation_id:
            raise LifecycleInvariantError(
                "Interpretation message and state must share a conversation."
            )
        object.__setattr__(self, "evaluated_at", ensure_utc(self.evaluated_at))


def _validate_current_user_message(message: Message, state: ConversationState) -> None:
    if message.role is not MessageRole.USER:
        raise LifecycleInvariantError("Reference requests require a current USER message.")
    if message.conversation_id != state.conversation_id:
        raise LifecycleInvariantError(
            "Reference message and state must share a conversation."
        )


def _validate_mentions(
    message: Message,
    mentions: tuple[ReferenceMention, ...],
) -> tuple[ReferenceMention, ...]:
    frozen = tuple(mentions)
    if [mention.mention_ordinal for mention in frozen] != list(range(len(frozen))):
        raise LifecycleInvariantError(
            "Reference mentions require contiguous zero-based ordinals."
        )
    previous_end = 0
    for mention in frozen:
        if mention.end_offset > len(message.original_text):
            raise LifecycleInvariantError("Reference mention exceeds its source message.")
        if message.original_text[mention.start_offset : mention.end_offset] != mention.surface_text:
            raise LifecycleInvariantError(
                "Reference mention surface must equal its exact source slice."
            )
        if mention.start_offset < previous_end:
            raise LifecycleInvariantError(
                "Reference mentions must be source ordered and non-overlapping."
            )
        previous_end = mention.end_offset
    return frozen


def _validate_scoped_entities(entities: tuple[Entity, ...]) -> tuple[Entity, ...]:
    frozen = tuple(entities)
    if len({entity.id for entity in frozen}) != len(frozen):
        raise LifecycleInvariantError("Scoped reference entities require distinct IDs.")
    identities = {(entity.entity_type, entity.native_id) for entity in frozen}
    if len(identities) != len(frozen):
        raise LifecycleInvariantError(
            "Scoped reference entities require distinct canonical identities."
        )
    return frozen


@dataclass(frozen=True, slots=True)
class ReferenceMentionExtractionRequest:
    """Exact immutable inputs for final TASK-0008 mention extraction."""

    message: Message
    seed_mentions: tuple[ReferenceMention, ...]
    scoped_entities: tuple[Entity, ...]

    def __post_init__(self) -> None:
        if self.message.role is not MessageRole.USER:
            raise LifecycleInvariantError(
                "Reference extraction requires a current USER message."
            )
        object.__setattr__(
            self,
            "seed_mentions",
            _validate_mentions(self.message, self.seed_mentions),
        )
        object.__setattr__(
            self,
            "scoped_entities",
            _validate_scoped_entities(self.scoped_entities),
        )


@dataclass(frozen=True, slots=True)
class ReferenceResolutionRequest:
    """All deterministic inputs needed for one pure reference decision."""

    processing_run_id: DomainId
    message: Message
    prior_messages: tuple[Message, ...]
    state: ConversationState
    mentions: tuple[ReferenceMention, ...]
    scoped_entities: tuple[Entity, ...]
    prior_resolved_outcomes: tuple[ReferenceOutcome, ...]
    evaluated_at: datetime

    def __post_init__(self) -> None:
        _validate_current_user_message(self.message, self.state)
        mentions = _validate_mentions(self.message, self.mentions)
        entities = _validate_scoped_entities(self.scoped_entities)
        prior_messages = tuple(self.prior_messages)
        if len({message.id for message in prior_messages}) != len(prior_messages):
            raise LifecycleInvariantError("Prior reference messages require distinct IDs.")
        if any(
            message.conversation_id != self.message.conversation_id
            for message in prior_messages
        ):
            raise LifecycleInvariantError(
                "Prior reference messages must belong to the current conversation."
            )
        sequences = [message.sequence_number for message in prior_messages]
        if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
            raise LifecycleInvariantError(
                "Prior reference messages require strictly ascending sequence order."
            )
        if any(sequence >= self.message.sequence_number for sequence in sequences):
            raise LifecycleInvariantError(
                "Prior reference messages must precede the current message."
            )

        outcomes = tuple(self.prior_resolved_outcomes)
        prior_by_id = {message.id: message for message in prior_messages}
        entity_ids = {entity.id for entity in entities}
        outcome_keys = [
            (outcome.message_id, outcome.mention_ordinal) for outcome in outcomes
        ]
        if len(set(outcome_keys)) != len(outcome_keys):
            raise LifecycleInvariantError(
                "Prior resolved outcomes require distinct message/mention identities."
            )
        if any(
            outcome.status is not ReferenceStatus.RESOLVED
            or outcome.message_id not in prior_by_id
            or outcome.resolved_entity_id not in entity_ids
            for outcome in outcomes
        ):
            raise LifecycleInvariantError(
                "Prior outcomes must be RESOLVED and link supplied messages to scoped entities."
            )
        expected_order = sorted(
            outcomes,
            key=lambda outcome: (
                prior_by_id[outcome.message_id].sequence_number,
                outcome.mention_ordinal,
                str(outcome.id),
            ),
        )
        if list(outcomes) != expected_order:
            raise LifecycleInvariantError(
                "Prior resolved outcomes require message/mention order."
            )

        object.__setattr__(self, "prior_messages", prior_messages)
        object.__setattr__(self, "mentions", mentions)
        object.__setattr__(self, "scoped_entities", entities)
        object.__setattr__(self, "prior_resolved_outcomes", outcomes)
        object.__setattr__(self, "evaluated_at", ensure_utc(self.evaluated_at))


@dataclass(frozen=True, slots=True)
class ConstraintEvaluationRequest:
    """Exact immutable inputs for one deterministic constraint decision."""

    message: Message
    state: ConversationState
    interpretation: InterpretationDecision
    reference_outcomes: tuple[ReferenceOutcome, ...]
    eligible_constraints: tuple[Constraint, ...]
    eligible_evidence: tuple[ConstraintSourceEvidence, ...]
    active_project_name: str | None
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if self.message.conversation_id != self.state.conversation_id:
            raise LifecycleInvariantError(
                "Constraint message and state must share a conversation."
            )
        if (
            self.interpretation.interpretation.source_message_id
            != self.message.id
        ):
            raise LifecycleInvariantError(
                "Constraint interpretation must belong to the request message."
            )
        references = tuple(self.reference_outcomes)
        constraints = tuple(self.eligible_constraints)
        evidence = tuple(self.eligible_evidence)
        if {item.constraint_id for item in evidence} != {
            constraint.id for constraint in constraints
        }:
            raise LifecycleInvariantError(
                "Eligible constraints require exactly one source-evidence item each."
            )
        if self.active_project_name is not None and not self.active_project_name.strip():
            raise LifecycleInvariantError(
                "Active project name must be non-empty or null."
            )
        object.__setattr__(self, "reference_outcomes", references)
        object.__setattr__(self, "eligible_constraints", constraints)
        object.__setattr__(self, "eligible_evidence", evidence)
        object.__setattr__(self, "evaluated_at", ensure_utc(self.evaluated_at))


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
        candidate_memories = tuple(self.candidate_memories)
        if len({memory.id for memory in candidate_memories}) != len(
            candidate_memories
        ):
            raise LifecycleInvariantError(
                "RetrievalRequest candidate memories require distinct IDs."
            )
        object.__setattr__(self, "candidate_memories", candidate_memories)
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
        selected, excluded = require_retrieval_evidence(
            self.selected,
            self.excluded,
        )
        expected_confidence = selected[0].score if selected else None
        if self.confidence != expected_confidence:
            raise LifecycleInvariantError(
                "RetrievalDecision.confidence must equal the highest selected score or null."
            )
        object.__setattr__(self, "selected", selected)
        object.__setattr__(self, "excluded", excluded)


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


class InterpretationEngine(Protocol):
    """Return one source-preserving deterministic interpretation decision."""

    def interpret(self, request: InterpretationRequest) -> InterpretationDecision: ...


class ReferenceMentionExtractor(Protocol):
    """Return the canonical final source-ordered mention sequence."""

    def extract(
        self,
        request: ReferenceMentionExtractionRequest,
    ) -> tuple[ReferenceMention, ...]: ...


class ReferenceResolver(Protocol):
    """Return one immutable deterministic reference decision."""

    def resolve(self, request: ReferenceResolutionRequest) -> ReferenceDecision: ...


class ConstraintEngine(Protocol):
    """Return one deterministic constraint decision without persistence."""

    def evaluate(self, request: ConstraintEvaluationRequest) -> ConstraintDecision: ...


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
