"""Immutable records produced by deterministic context decisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from context_for_ai.domain.enums import (
    ConditionEvaluation,
    ConditionKind,
    ClarificationReason,
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    IntentType,
    OutputType,
    QualifierKind,
    ReferenceStatus,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    ensure_utc,
)


CONDITION_GRAMMAR_VERSION = "mvp-condition-v1"
CONTEXT_PACKET_SCHEMA_VERSION = "mvp-context-packet-v1"

_HARD_CONSTRAINT_TYPES = frozenset(
    {ConstraintType.REQUIRED, ConstraintType.FORBIDDEN, ConstraintType.PRESERVE}
)


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _normalize_time(instance: object, field_name: str) -> None:
    object.__setattr__(instance, field_name, ensure_utc(getattr(instance, field_name)))


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
class MatchedRuleEvidence:
    """One source-preserving deterministic rule match."""

    rule_id: str
    matched_text: str
    normalized_phrase: str
    start_offset: int
    end_offset: int
    priority: int

    def __post_init__(self) -> None:
        _required_text("MatchedRuleEvidence.rule_id", self.rule_id)
        _required_text("MatchedRuleEvidence.matched_text", self.matched_text)
        _required_text("MatchedRuleEvidence.normalized_phrase", self.normalized_phrase)
        _non_negative_integer("MatchedRuleEvidence.start_offset", self.start_offset)
        _non_negative_integer("MatchedRuleEvidence.end_offset", self.end_offset)
        if self.end_offset <= self.start_offset:
            raise LifecycleInvariantError(
                "MatchedRuleEvidence.end_offset must follow start_offset."
            )
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise LifecycleInvariantError(
                "MatchedRuleEvidence.priority must be an integer."
            )


@dataclass(frozen=True, slots=True)
class IntentCandidate:
    """One ranked supported-intent candidate and its evidence."""

    intent: IntentType
    output_type: OutputType
    evidence: MatchedRuleEvidence


@dataclass(frozen=True, slots=True)
class QualifierMatch:
    kind: QualifierKind
    rule_id: str
    matched_text: str
    normalized_phrase: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    captures: FrozenJsonObject = field(default_factory=lambda: FrozenJsonObject({}))

    def __post_init__(self) -> None:
        _required_text("QualifierMatch.rule_id", self.rule_id)
        _required_text("QualifierMatch.matched_text", self.matched_text)
        normalized_phrase = self.normalized_phrase
        if normalized_phrase is None:
            normalized_phrase = " ".join(self.matched_text.casefold().split())
            object.__setattr__(self, "normalized_phrase", normalized_phrase)
        _required_text("QualifierMatch.normalized_phrase", normalized_phrase)
        start_offset = 0 if self.start_offset is None else self.start_offset
        end_offset = (
            start_offset + len(self.matched_text)
            if self.end_offset is None
            else self.end_offset
        )
        _non_negative_integer("QualifierMatch.start_offset", start_offset)
        _non_negative_integer("QualifierMatch.end_offset", end_offset)
        if end_offset <= start_offset:
            raise LifecycleInvariantError(
                "QualifierMatch.end_offset must follow start_offset."
            )
        object.__setattr__(self, "start_offset", start_offset)
        object.__setattr__(self, "end_offset", end_offset)
        object.__setattr__(self, "captures", _freeze_json_object(self.captures))


@dataclass(frozen=True, slots=True)
class RequestInterpretation:
    processing_run_id: DomainId
    source_message_id: DomainId
    intent: IntentType
    expected_output_type: OutputType
    intent_rule_id: str | None
    qualifiers: tuple[QualifierMatch, ...]
    confidence: UnitScore
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.intent_rule_id is not None:
            _required_text("RequestInterpretation.intent_rule_id", self.intent_rule_id)
        object.__setattr__(self, "qualifiers", tuple(self.qualifiers))
        _required_text("RequestInterpretation.reason", self.reason)
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class ReferenceMention:
    """Unresolved source mention emitted for the later reference stage."""

    mention_ordinal: int
    surface_text: str
    normalized_phrase: str
    qualifier_rule_id: str
    start_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        _non_negative_integer("ReferenceMention.mention_ordinal", self.mention_ordinal)
        _required_text("ReferenceMention.surface_text", self.surface_text)
        _required_text("ReferenceMention.normalized_phrase", self.normalized_phrase)
        _required_text("ReferenceMention.qualifier_rule_id", self.qualifier_rule_id)
        _non_negative_integer("ReferenceMention.start_offset", self.start_offset)
        _non_negative_integer("ReferenceMention.end_offset", self.end_offset)
        if self.end_offset <= self.start_offset:
            raise LifecycleInvariantError(
                "ReferenceMention.end_offset must follow start_offset."
            )


@dataclass(frozen=True, slots=True)
class InterpretationDecision:
    """Complete immutable result of deterministic message interpretation."""

    interpretation: RequestInterpretation
    rule_set_version: str
    intent_candidates: tuple[IntentCandidate, ...]
    proposed_topic_label: str | None
    proposed_task_title: str | None
    reference_mentions: tuple[ReferenceMention, ...]
    clarification_reason: ClarificationReason | None
    clarification_details: FrozenJsonObject | None

    def __post_init__(self) -> None:
        _required_text("InterpretationDecision.rule_set_version", self.rule_set_version)
        object.__setattr__(self, "intent_candidates", tuple(self.intent_candidates))
        object.__setattr__(self, "reference_mentions", tuple(self.reference_mentions))
        if self.proposed_topic_label is not None:
            _required_text(
                "InterpretationDecision.proposed_topic_label",
                self.proposed_topic_label,
            )
        if self.proposed_task_title is not None:
            _required_text(
                "InterpretationDecision.proposed_task_title",
                self.proposed_task_title,
            )
        if (self.clarification_reason is None) != (
            self.clarification_details is None
        ):
            raise LifecycleInvariantError(
                "Interpretation clarification reason and details must be supplied together."
            )
        if self.clarification_details is not None:
            object.__setattr__(
                self,
                "clarification_details",
                _freeze_json_object(self.clarification_details),
            )


@dataclass(frozen=True, slots=True)
class Condition:
    grammar_version: str
    kind: ConditionKind
    expected_value: str
    evaluation: ConditionEvaluation

    def __post_init__(self) -> None:
        if self.grammar_version != CONDITION_GRAMMAR_VERSION:
            raise LifecycleInvariantError(
                f"Condition.grammar_version must be {CONDITION_GRAMMAR_VERSION!r}."
            )
        _required_text("Condition.expected_value", self.expected_value)


@dataclass(frozen=True, slots=True)
class ReferenceOutcome:
    id: DomainId
    processing_run_id: DomainId
    message_id: DomainId
    mention_ordinal: int
    surface_text: str
    status: ReferenceStatus
    resolved_entity_id: DomainId | None
    source_message_id: DomainId | None
    confidence: UnitScore
    candidate_evidence: tuple[FrozenJsonObject, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        _non_negative_integer("ReferenceOutcome.mention_ordinal", self.mention_ordinal)
        _required_text("ReferenceOutcome.surface_text", self.surface_text)
        if self.status is ReferenceStatus.RESOLVED and self.resolved_entity_id is None:
            raise LifecycleInvariantError("Resolved reference requires resolved_entity_id.")
        if self.status is not ReferenceStatus.RESOLVED and self.resolved_entity_id is not None:
            raise LifecycleInvariantError(
                "Only a resolved reference may have resolved_entity_id."
            )
        object.__setattr__(
            self,
            "candidate_evidence",
            _freeze_json_objects(self.candidate_evidence),
        )
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class Constraint:
    id: DomainId
    processing_run_id: DomainId
    message_id: DomainId
    ordinal: int
    constraint_type: ConstraintType
    underlying_constraint_type: ConstraintType | None
    scope: ConstraintScope
    normalized_rule: str
    priority: int
    source_kind: ConstraintSourceKind
    source_text: str
    confidence: UnitScore
    resolution_status: ConstraintResolutionStatus
    conflict_group_id: str | None
    condition: Condition | None
    created_at: datetime

    def __post_init__(self) -> None:
        _non_negative_integer("Constraint.ordinal", self.ordinal)
        _required_text("Constraint.normalized_rule", self.normalized_rule)
        _non_negative_integer("Constraint.priority", self.priority)
        _required_text("Constraint.source_text", self.source_text)
        if self.conflict_group_id is not None:
            _required_text("Constraint.conflict_group_id", self.conflict_group_id)

        is_conditional = self.constraint_type is ConstraintType.CONDITIONAL
        if is_conditional:
            if self.underlying_constraint_type not in _HARD_CONSTRAINT_TYPES:
                raise LifecycleInvariantError(
                    "Conditional constraint requires a hard underlying constraint type."
                )
            if self.condition is None:
                raise LifecycleInvariantError("Conditional constraint requires condition.")
        elif self.underlying_constraint_type is not None or self.condition is not None:
            raise LifecycleInvariantError(
                "Only a conditional constraint may have underlying type or condition."
            )
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class ConstraintSourceEvidence:
    """Observable provenance and comparison inputs for one constraint."""

    constraint_id: DomainId
    target_key: str
    contributing_rule_ids: tuple[str, ...]
    source_texts: tuple[str, ...]
    source_message_sequence: int | None
    source_created_at: datetime
    comparison_tuple: tuple[str, ...]

    def __post_init__(self) -> None:
        _required_text("ConstraintSourceEvidence.target_key", self.target_key)
        rule_ids = tuple(self.contributing_rule_ids)
        source_texts = tuple(self.source_texts)
        comparison_tuple = tuple(self.comparison_tuple)
        if not rule_ids or not source_texts or not comparison_tuple:
            raise LifecycleInvariantError(
                "Constraint source evidence collections cannot be empty."
            )
        for rule_id in rule_ids:
            _required_text("ConstraintSourceEvidence.rule_id", rule_id)
        for source_text in source_texts:
            _required_text("ConstraintSourceEvidence.source_text", source_text)
        for value in comparison_tuple:
            _required_text("ConstraintSourceEvidence.comparison_value", value)
        if self.source_message_sequence is not None:
            _non_negative_integer(
                "ConstraintSourceEvidence.source_message_sequence",
                self.source_message_sequence,
            )
        object.__setattr__(self, "contributing_rule_ids", rule_ids)
        object.__setattr__(self, "source_texts", source_texts)
        object.__setattr__(self, "comparison_tuple", comparison_tuple)
        _normalize_time(self, "source_created_at")


@dataclass(frozen=True, slots=True)
class ConstraintConflictGroup:
    """One deterministic group of equally authoritative hard opposition."""

    id: str
    target_key: str
    constraint_ids: tuple[DomainId, ...]

    def __post_init__(self) -> None:
        _required_text("ConstraintConflictGroup.id", self.id)
        _required_text("ConstraintConflictGroup.target_key", self.target_key)
        constraint_ids = tuple(self.constraint_ids)
        if len(constraint_ids) < 2:
            raise LifecycleInvariantError(
                "ConstraintConflictGroup requires at least two constraint IDs."
            )
        object.__setattr__(self, "constraint_ids", constraint_ids)


@dataclass(frozen=True, slots=True)
class ResponsePolicy:
    """Fixed text-only/no-actions policy for one interpreted result."""

    expected_output_type: OutputType
    rule_set_version: str
    text_only: bool = True
    actions_allowed: bool = False

    def __post_init__(self) -> None:
        _required_text("ResponsePolicy.rule_set_version", self.rule_set_version)
        if self.text_only is not True or self.actions_allowed is not False:
            raise LifecycleInvariantError(
                "MVP response policy must be text-only with actions disallowed."
            )


@dataclass(frozen=True, slots=True)
class ConstraintDecision:
    """Complete immutable result of deterministic constraint evaluation."""

    constraints: tuple[Constraint, ...]
    evidence: tuple[ConstraintSourceEvidence, ...]
    conflict_groups: tuple[ConstraintConflictGroup, ...]
    response_policy: ResponsePolicy
    clarification_reason: ClarificationReason | None
    clarification_details: FrozenJsonObject | None

    def __post_init__(self) -> None:
        constraints = tuple(self.constraints)
        evidence = tuple(self.evidence)
        conflict_groups = tuple(self.conflict_groups)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "conflict_groups", conflict_groups)
        constraint_ids = {constraint.id for constraint in constraints}
        if {item.constraint_id for item in evidence} != constraint_ids:
            raise LifecycleInvariantError(
                "ConstraintDecision requires exactly one evidence item per constraint."
            )
        if any(
            constraint_id not in constraint_ids
            for group in conflict_groups
            for constraint_id in group.constraint_ids
        ):
            raise LifecycleInvariantError(
                "Conflict groups must reference decision constraints."
            )
        if (self.clarification_reason is None) != (
            self.clarification_details is None
        ):
            raise LifecycleInvariantError(
                "Constraint clarification reason and details must be supplied together."
            )
        if self.clarification_details is not None:
            object.__setattr__(
                self,
                "clarification_details",
                _freeze_json_object(self.clarification_details),
            )


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    id: DomainId
    context_packet_id: DomainId
    memory_id: DomainId
    rank: int
    score: UnitScore
    reasons: tuple[str, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        _non_negative_integer("RetrievalResult.rank", self.rank)
        if isinstance(self.reasons, str):
            raise LifecycleInvariantError("RetrievalResult.reasons must be a collection.")
        reasons = tuple(self.reasons)
        if not reasons:
            raise LifecycleInvariantError("RetrievalResult.reasons cannot be empty.")
        for reason in reasons:
            _required_text("RetrievalResult.reason", reason)
        object.__setattr__(self, "reasons", reasons)
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class RetrievalExclusion:
    id: DomainId
    context_packet_id: DomainId
    memory_id: DomainId
    exclusion_reason: RetrievalExclusionReason
    computed_score: UnitScore | None
    details: FrozenJsonObject
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze_json_object(self.details))
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class ContextPacket:
    id: DomainId
    processing_run_id: DomainId
    message_id: DomainId
    packet: FrozenJsonObject
    schema_version: str
    prompt_policy_version: str
    configuration_fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != CONTEXT_PACKET_SCHEMA_VERSION:
            raise LifecycleInvariantError(
                f"ContextPacket.schema_version must be {CONTEXT_PACKET_SCHEMA_VERSION!r}."
            )
        _required_text("ContextPacket.prompt_policy_version", self.prompt_policy_version)
        _required_text(
            "ContextPacket.configuration_fingerprint",
            self.configuration_fingerprint,
        )
        object.__setattr__(self, "packet", _freeze_json_object(self.packet))
        _normalize_time(self, "created_at")
