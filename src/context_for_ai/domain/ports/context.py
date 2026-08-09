"""Inward contracts for deterministic context components used by application code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from context_for_ai.domain.decisions import (
    PROMPT_POLICY_VERSION,
    TOKEN_ESTIMATOR_VERSION,
    Constraint,
    ConstraintDecision,
    ConstraintSourceEvidence,
    ConstraintPacketLineage,
    ContextPacket,
    CorrectionEnvelope,
    InterpretationDecision,
    OmissionRecord,
    ReferenceDecision,
    ReferenceMention,
    ReferenceOutcome,
    RetrievalExclusion,
    RetrievalResult,
    require_retrieval_evidence,
)
from context_for_ai.domain.entities import ConversationState, Entity, Memory, Message, Topic
from context_for_ai.domain.enums import (
    ClarificationReason,
    ContextBudgetPhase,
    FailureCode,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    PromptRenderKind,
    PromptSection,
    ReferenceStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
    ProcessingRun,
    ValidationResult,
)
from context_for_ai.domain.ports.configuration import ValidationConfigurationSnapshot
from context_for_ai.domain.ports.records import ContextPacketRecord
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


def _positive_integer(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LifecycleInvariantError(f"{field_name} must be a positive integer.")


@dataclass(frozen=True, slots=True)
class ContextPacketBuildRequest:
    """All immutable provider-independent inputs for one v2 packet build."""

    context_packet_id: DomainId
    processing_run: ProcessingRun
    message: Message
    state: ConversationState
    active_project_id: DomainId | None
    active_topic: Topic | None
    interpretation: InterpretationDecision
    reference_outcomes: tuple[ReferenceOutcome, ...]
    constraint_decision: ConstraintDecision
    constraint_packet_lineage: tuple[ConstraintPacketLineage, ...]
    retrieval_decision: RetrievalDecision
    selected_memories: tuple[Memory, ...]
    context_window_tokens: int
    maximum_prompt_tokens: int
    reserved_response_tokens: int
    validation_configuration: ValidationConfigurationSnapshot
    created_at: datetime

    def __post_init__(self) -> None:
        run = self.processing_run
        message = self.message
        state = self.state
        if message.role is not MessageRole.USER:
            raise LifecycleInvariantError("Context packet requires the run USER message.")
        if (
            run.user_message_id != message.id
            or run.conversation_id != message.conversation_id
            or state.conversation_id != message.conversation_id
        ):
            raise LifecycleInvariantError(
                "Context packet run, message, and state lineage must agree."
            )
        if self.interpretation.interpretation.processing_run_id != run.id or (
            self.interpretation.interpretation.source_message_id != message.id
        ):
            raise LifecycleInvariantError(
                "Context packet interpretation must belong to the run message."
            )
        if self.interpretation.clarification_reason is not None:
            raise LifecycleInvariantError(
                "A clarification interpretation cannot reach packet construction."
            )
        if self.active_topic is None:
            if state.active_topic_id is not None:
                raise LifecycleInvariantError(
                    "Context packet requires the active topic snapshot."
                )
        elif (
            state.active_topic_id != self.active_topic.id
            or self.active_topic.conversation_id != run.conversation_id
        ):
            raise LifecycleInvariantError(
                "Context packet active topic must match the state and conversation."
            )

        references = tuple(self.reference_outcomes)
        if [value.mention_ordinal for value in references] != list(range(len(references))):
            raise LifecycleInvariantError(
                "Context packet references require contiguous source order."
            )
        if any(
            value.processing_run_id != run.id
            or value.message_id != message.id
            or value.status not in {ReferenceStatus.RESOLVED, ReferenceStatus.NOT_APPLICABLE}
            for value in references
        ):
            raise LifecycleInvariantError(
                "Context packet references must be admissible outcomes for the run message."
            )

        constraints = self.constraint_decision.constraints
        if self.constraint_decision.clarification_reason is not None:
            raise LifecycleInvariantError(
                "A clarifying constraint decision cannot reach packet construction."
            )
        if tuple(sorted(constraints, key=lambda value: (-value.priority, value.ordinal))) != constraints:
            raise LifecycleInvariantError(
                "Context packet constraints require canonical priority/ordinal order."
            )
        if any(
            value.processing_run_id != run.id or value.message_id != message.id
            for value in constraints
        ):
            raise LifecycleInvariantError(
                "Context packet constraints must belong to the run message."
            )
        lineage = tuple(self.constraint_packet_lineage)
        if tuple(value.constraint_id for value in lineage) != tuple(
            value.id for value in constraints
        ):
            raise LifecycleInvariantError(
                "Context packet requires one ordered lineage companion per constraint."
            )

        selected_memories = tuple(self.selected_memories)
        selected_results = self.retrieval_decision.selected
        if any(
            value.context_packet_id != self.context_packet_id
            for value in (*selected_results, *self.retrieval_decision.excluded)
        ):
            raise LifecycleInvariantError(
                "Retrieval evidence must carry the preallocated context packet ID."
            )
        if tuple(value.id for value in selected_memories) != tuple(
            value.memory_id for value in selected_results
        ):
            raise LifecycleInvariantError(
                "Selected memories must bijectively follow retrieval rank order."
            )
        if len({value.id for value in selected_memories}) != len(selected_memories):
            raise LifecycleInvariantError("Selected memory snapshots require distinct IDs.")

        _positive_integer("context_window_tokens", self.context_window_tokens)
        _positive_integer("maximum_prompt_tokens", self.maximum_prompt_tokens)
        _positive_integer("reserved_response_tokens", self.reserved_response_tokens)
        if self.context_window_tokens <= self.reserved_response_tokens:
            raise LifecycleInvariantError(
                "Context window must exceed reserved response tokens."
            )
        if (
            self.validation_configuration.configuration_fingerprint
            != run.configuration_fingerprint
        ):
            raise LifecycleInvariantError(
                "Validation configuration fingerprint must match the processing run."
            )

        object.__setattr__(self, "reference_outcomes", references)
        object.__setattr__(self, "constraint_packet_lineage", lineage)
        object.__setattr__(self, "selected_memories", selected_memories)
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))


@dataclass(frozen=True, slots=True)
class ContextBudgetExceeded:
    context_packet_id: DomainId
    code: FailureCode
    phase: ContextBudgetPhase
    token_estimator: str
    estimated_required_tokens: int
    effective_prompt_budget: int

    def __post_init__(self) -> None:
        if not isinstance(self.context_packet_id, DomainId):
            raise LifecycleInvariantError(
                "Context budget result requires a packet domain ID."
            )
        if self.code is not FailureCode.CONTEXT_BUDGET_EXCEEDED:
            raise LifecycleInvariantError("Context budget result requires the canonical code.")
        if not isinstance(self.phase, ContextBudgetPhase):
            raise LifecycleInvariantError(
                "Context budget result requires a canonical phase."
            )
        if self.token_estimator != TOKEN_ESTIMATOR_VERSION:
            raise LifecycleInvariantError("Context budget result has an unknown estimator.")
        for field_name in ("estimated_required_tokens", "effective_prompt_budget"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise LifecycleInvariantError(
                    f"ContextBudgetExceeded.{field_name} must be non-negative."
                )


@dataclass(frozen=True, slots=True)
class PromptRenderResult:
    context_packet_id: DomainId
    prompt_policy_version: str
    render_kind: PromptRenderKind
    rendered_prompt: str
    estimated_prompt_tokens: int
    effective_prompt_budget: int
    included_sections: tuple[PromptSection, ...]
    omitted_sections: tuple[OmissionRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.context_packet_id, DomainId):
            raise LifecycleInvariantError(
                "Prompt render result requires a packet domain ID."
            )
        if self.prompt_policy_version != PROMPT_POLICY_VERSION:
            raise LifecycleInvariantError("Prompt render result has an unknown policy.")
        if not isinstance(self.render_kind, PromptRenderKind):
            raise LifecycleInvariantError(
                "Prompt render result has an unknown render kind."
            )
        if not isinstance(self.rendered_prompt, str):
            raise LifecycleInvariantError("Prompt render result must contain text.")
        for field_name in ("estimated_prompt_tokens", "effective_prompt_budget"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise LifecycleInvariantError(
                    f"PromptRenderResult.{field_name} must be non-negative."
                )
        if self.estimated_prompt_tokens > self.effective_prompt_budget:
            raise LifecycleInvariantError("A prompt render result must fit its budget.")
        included = tuple(self.included_sections)
        if any(not isinstance(value, PromptSection) for value in included):
            raise LifecycleInvariantError(
                "Prompt render included sections must be canonical."
            )
        canonical = tuple(value for value in PromptSection if value in included)
        if included != canonical:
            raise LifecycleInvariantError(
                "Prompt render included sections require canonical order."
            )
        omitted = tuple(self.omitted_sections)
        if any(not isinstance(value, OmissionRecord) for value in omitted):
            raise LifecycleInvariantError("Prompt render omissions must be typed records.")
        object.__setattr__(self, "included_sections", included)
        object.__setattr__(self, "omitted_sections", omitted)


@dataclass(frozen=True, slots=True)
class ContextPacketBuildSuccess:
    record: ContextPacketRecord
    initial_render: PromptRenderResult

    def __post_init__(self) -> None:
        if not isinstance(self.record, ContextPacketRecord) or not isinstance(
            self.initial_render, PromptRenderResult
        ):
            raise LifecycleInvariantError(
                "Packet build success requires typed packet and render records."
            )
        if self.record.packet.id != self.initial_render.context_packet_id or (
            self.initial_render.render_kind is not PromptRenderKind.INITIAL
        ):
            raise LifecycleInvariantError(
                "Packet build success requires a matching initial render."
            )


type ContextPacketBuildResult = ContextPacketBuildSuccess | ContextBudgetExceeded


@dataclass(frozen=True, slots=True)
class PromptRenderRequest:
    packet: ContextPacket
    correction_envelope: CorrectionEnvelope | None

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ContextPacket):
            raise LifecycleInvariantError(
                "Prompt render request requires a typed context packet."
            )
        if self.correction_envelope is not None and not isinstance(
            self.correction_envelope, CorrectionEnvelope
        ):
            raise LifecycleInvariantError(
                "Prompt render correction envelope must be typed or null."
            )


type PromptRenderOutcome = PromptRenderResult | ContextBudgetExceeded


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    """One immutable packet and one fully buffered candidate for validation."""

    packet: ContextPacket
    model_response_id: DomainId
    validation_result_id: DomainId
    candidate_response: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ContextPacket):
            raise LifecycleInvariantError(
                "ValidationRequest.packet must be a typed context packet."
            )
        if not isinstance(self.model_response_id, DomainId) or not isinstance(
            self.validation_result_id, DomainId
        ):
            raise LifecycleInvariantError(
                "ValidationRequest response and result IDs must be domain IDs."
            )
        if not isinstance(self.candidate_response, str):
            raise LifecycleInvariantError(
                "ValidationRequest.candidate_response must be text."
            )
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))


@dataclass(frozen=True, slots=True)
class FailedCandidateLineage:
    """Explicit persisted facts for the candidate that failed validation."""

    processing_run_id: DomainId
    context_packet_id: DomainId
    model_request_id: DomainId
    model_response_id: DomainId
    attempt_number: int
    request_purpose: ModelRequestPurpose
    request_status: ModelRequestStatus
    assistant_message_id: DomainId | None

    def __post_init__(self) -> None:
        for field_name in (
            "processing_run_id",
            "context_packet_id",
            "model_request_id",
            "model_response_id",
        ):
            if not isinstance(getattr(self, field_name), DomainId):
                raise LifecycleInvariantError(
                    f"FailedCandidateLineage.{field_name} must be a domain ID."
                )
        if (
            not isinstance(self.attempt_number, int)
            or isinstance(self.attempt_number, bool)
            or self.attempt_number not in (0, 1, 2)
        ):
            raise LifecycleInvariantError(
                "FailedCandidateLineage.attempt_number must be 0, 1, or 2."
            )
        if not isinstance(self.request_purpose, ModelRequestPurpose) or not isinstance(
            self.request_status, ModelRequestStatus
        ):
            raise LifecycleInvariantError(
                "FailedCandidateLineage request purpose and status must be canonical."
            )
        if self.assistant_message_id is not None and not isinstance(
            self.assistant_message_id, DomainId
        ):
            raise LifecycleInvariantError(
                "FailedCandidateLineage.assistant_message_id must be a domain ID or null."
            )


@dataclass(frozen=True, slots=True)
class CorrectionPlanRequest:
    """One immutable packet, failed-candidate lineage, and failed report."""

    packet: ContextPacket
    failed_candidate: FailedCandidateLineage
    validation_result: ValidationResult

    def __post_init__(self) -> None:
        if (
            not isinstance(self.packet, ContextPacket)
            or not isinstance(self.failed_candidate, FailedCandidateLineage)
            or not isinstance(self.validation_result, ValidationResult)
        ):
            raise LifecycleInvariantError(
                "CorrectionPlanRequest requires typed packet, lineage, and report."
            )


@dataclass(frozen=True, slots=True)
class CorrectionExhausted:
    """Typed bounded result when no configured revision remains."""

    processing_run_id: DomainId
    context_packet_id: DomainId
    failed_model_request_id: DomainId
    failed_model_response_id: DomainId
    validation_result_id: DomainId
    attempt_number: int
    correction_limit: int

    def __post_init__(self) -> None:
        for field_name in (
            "processing_run_id",
            "context_packet_id",
            "failed_model_request_id",
            "failed_model_response_id",
            "validation_result_id",
        ):
            if not isinstance(getattr(self, field_name), DomainId):
                raise LifecycleInvariantError(
                    f"CorrectionExhausted.{field_name} must be a domain ID."
                )
        for field_name in ("attempt_number", "correction_limit"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value not in (0, 1, 2)
            ):
                raise LifecycleInvariantError(
                    f"CorrectionExhausted.{field_name} must be 0, 1, or 2."
                )
        if self.attempt_number != self.correction_limit:
            raise LifecycleInvariantError(
                "CorrectionExhausted attempt must equal the correction limit."
            )


type CorrectionDecision = CorrectionEnvelope | CorrectionExhausted


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


class ContextPacketBuilder(Protocol):
    """Build one immutable packet aggregate and its initial render."""

    def build(self, request: ContextPacketBuildRequest) -> ContextPacketBuildResult: ...


class PromptRenderer(Protocol):
    """Render one immutable packet under its fixed prompt policy."""

    def render(self, request: PromptRenderRequest) -> PromptRenderOutcome: ...


class ResponseValidator(Protocol):
    """Validate one complete candidate against one immutable packet."""

    def validate(self, request: ValidationRequest) -> ValidationResult: ...


class CorrectionController(Protocol):
    """Plan one bounded revision or report deterministic exhaustion."""

    def plan(self, request: CorrectionPlanRequest) -> CorrectionDecision: ...
