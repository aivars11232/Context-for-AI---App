"""Immutable records produced by deterministic context decisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from context_for_ai.domain.enums import (
    ConditionEvaluation,
    ConditionKind,
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
class QualifierMatch:
    kind: QualifierKind
    rule_id: str
    matched_text: str

    def __post_init__(self) -> None:
        _required_text("QualifierMatch.rule_id", self.rule_id)
        _required_text("QualifierMatch.matched_text", self.matched_text)


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
