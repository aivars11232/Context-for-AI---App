"""Immutable records produced by deterministic context decisions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from context_for_ai.domain.enums import (
    ConditionEvaluation,
    ConditionKind,
    ClarificationReason,
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    EntityType,
    IntentType,
    MemoryScope,
    MemoryStatus,
    OutputType,
    QualifierKind,
    ReferenceRankReason,
    ReferenceStatus,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import DomainValidationError, LifecycleInvariantError
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    canonical_decimal_string,
    ensure_utc,
    format_utc_timestamp,
    parse_utc_timestamp,
)


CONDITION_GRAMMAR_VERSION = "mvp-condition-v1"
CONTEXT_PACKET_SCHEMA_VERSION = "mvp-context-packet-v1"

_HARD_CONSTRAINT_TYPES = frozenset(
    {ConstraintType.REQUIRED, ConstraintType.FORBIDDEN, ConstraintType.PRESERVE}
)
_ENTITY_REFERENCE_REASONS = frozenset(
    {
        ReferenceRankReason.EXACT_NAME,
        ReferenceRankReason.ACTIVE_STATE,
        ReferenceRankReason.RECENT_TRACKED,
        ReferenceRankReason.SOURCE_MESSAGE,
        ReferenceRankReason.STALE_ENTITY,
    }
)
_PLACEHOLDER_REFERENCE_REASONS = frozenset(
    {
        ReferenceRankReason.NO_CANDIDATE,
        ReferenceRankReason.FILE_CONTEXT_UNSUPPORTED,
        ReferenceRankReason.DECLARATION_TARGET,
    }
)
_REFERENCE_REASON_ORDER = {
    reason: index
    for index, reason in enumerate(
        (
            ReferenceRankReason.EXACT_NAME,
            ReferenceRankReason.ACTIVE_STATE,
            ReferenceRankReason.RECENT_TRACKED,
            ReferenceRankReason.SOURCE_MESSAGE,
            ReferenceRankReason.STALE_ENTITY,
            ReferenceRankReason.NO_CANDIDATE,
            ReferenceRankReason.FILE_CONTEXT_UNSUPPORTED,
            ReferenceRankReason.DECLARATION_TARGET,
        )
    )
}
_REFERENCE_EVIDENCE_KEYS = frozenset(
    {
        "rank",
        "entity_id",
        "entity_type",
        "display_name",
        "normalized_name",
        "score",
        "rank_reason",
        "entity_source_message_id",
        "evidence_message_id",
        "evidence_message_sequence",
        "prior_mention_ordinal",
        "is_active",
    }
)
_RETRIEVAL_REASON_NAMES = (
    "project_match",
    "topic_match",
    "keyword_jaccard",
    "recency",
    "importance",
    "scope_match",
    "correction_match",
)
_RETRIEVAL_EXCLUSION_DETAIL_KEYS = {
    RetrievalExclusionReason.SCOPE_MISMATCH: frozenset(
        {
            "scope",
            "request_conversation_id",
            "request_project_id",
            "memory_conversation_id",
            "memory_project_id",
        }
    ),
    RetrievalExclusionReason.DELETED: frozenset({"stored_status", "deleted_at"}),
    RetrievalExclusionReason.EXPIRED: frozenset(
        {"stored_status", "expires_at", "evaluated_at"}
    ),
    RetrievalExclusionReason.SCORE_BELOW_THRESHOLD: frozenset(
        {"minimum_relevance_score"}
    ),
    RetrievalExclusionReason.DUPLICATE_CONTENT: frozenset({"retained_memory_id"}),
    RetrievalExclusionReason.LIMIT_EXCEEDED: frozenset(
        {"result_limit", "pre_limit_rank"}
    ),
}


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _normalize_time(instance: object, field_name: str) -> None:
    object.__setattr__(instance, field_name, ensure_utc(getattr(instance, field_name)))


def _non_negative_integer(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleInvariantError(f"{field_name} must be a non-negative integer.")


def _canonical_unit_score_text(field_name: str, value: object) -> UnitScore:
    if not isinstance(value, str):
        raise LifecycleInvariantError(f"{field_name} must be a canonical decimal string.")
    try:
        parsed = Decimal(value)
        score = UnitScore(parsed)
        canonical = canonical_decimal_string(parsed)
    except (DomainValidationError, InvalidOperation, ValueError) as error:
        raise LifecycleInvariantError(
            f"{field_name} must be a canonical unit decimal string."
        ) from error
    if canonical != value:
        raise LifecycleInvariantError(
            f"{field_name} must use canonical fixed-point decimal notation."
        )
    return score


def _canonical_detail_id(
    details: FrozenJsonObject,
    key: str,
    *,
    optional: bool = False,
) -> DomainId | None:
    value = details[key]
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise LifecycleInvariantError(
            f"Retrieval exclusion detail {key!r} must be a canonical UUID string"
            f"{' or null' if optional else ''}."
        )
    try:
        identifier = DomainId(value)
    except DomainValidationError as error:
        raise LifecycleInvariantError(
            f"Retrieval exclusion detail {key!r} must be a canonical UUID string."
        ) from error
    if str(identifier) != value:
        raise LifecycleInvariantError(
            f"Retrieval exclusion detail {key!r} must use canonical UUID text."
        )
    return identifier


def _canonical_detail_time(details: FrozenJsonObject, key: str) -> datetime:
    value = details[key]
    if not isinstance(value, str):
        raise LifecycleInvariantError(
            f"Retrieval exclusion detail {key!r} must be a canonical UTC string."
        )
    try:
        timestamp = parse_utc_timestamp(value)
    except DomainValidationError as error:
        raise LifecycleInvariantError(
            f"Retrieval exclusion detail {key!r} must be a canonical UTC string."
        ) from error
    if format_utc_timestamp(timestamp) != value:
        raise LifecycleInvariantError(
            f"Retrieval exclusion detail {key!r} must use canonical UTC text."
        )
    return timestamp


def _detail_non_negative_integer(details: FrozenJsonObject, key: str) -> int:
    value = details[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleInvariantError(
            f"Retrieval exclusion detail {key!r} must be a non-negative integer."
        )
    return value


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
class ReferenceCandidateEvidence:
    """One canonical ranked entity candidate or explicit placeholder."""

    rank: int
    entity_id: DomainId | None
    entity_type: EntityType | None
    display_name: str | None
    normalized_name: str | None
    score: UnitScore
    rank_reason: ReferenceRankReason
    entity_source_message_id: DomainId | None
    evidence_message_id: DomainId | None
    evidence_message_sequence: int | None
    prior_mention_ordinal: int | None
    is_active: bool | None

    def __post_init__(self) -> None:
        if not isinstance(self.rank, int) or isinstance(self.rank, bool) or self.rank < 1:
            raise LifecycleInvariantError(
                "ReferenceCandidateEvidence.rank must be a one-based integer."
            )
        if self.evidence_message_sequence is not None:
            _non_negative_integer(
                "ReferenceCandidateEvidence.evidence_message_sequence",
                self.evidence_message_sequence,
            )
        if self.prior_mention_ordinal is not None:
            _non_negative_integer(
                "ReferenceCandidateEvidence.prior_mention_ordinal",
                self.prior_mention_ordinal,
            )

        if self.rank_reason in _PLACEHOLDER_REFERENCE_REASONS:
            if any(
                value is not None
                for value in (
                    self.entity_id,
                    self.entity_type,
                    self.display_name,
                    self.normalized_name,
                    self.entity_source_message_id,
                    self.evidence_message_id,
                    self.evidence_message_sequence,
                    self.prior_mention_ordinal,
                    self.is_active,
                )
            ) or self.score != UnitScore(0):
                raise LifecycleInvariantError(
                    "Placeholder reference evidence requires null candidate fields and score 0.00."
                )
            return

        if self.rank_reason not in _ENTITY_REFERENCE_REASONS:
            raise LifecycleInvariantError("Unknown reference evidence rank reason.")
        if self.entity_id is None or self.entity_type is None:
            raise LifecycleInvariantError(
                "Entity reference evidence requires entity identity and type."
            )
        if self.display_name is None or self.normalized_name is None:
            raise LifecycleInvariantError(
                "Entity reference evidence requires display and normalized names."
            )
        _required_text("ReferenceCandidateEvidence.display_name", self.display_name)
        _required_text("ReferenceCandidateEvidence.normalized_name", self.normalized_name)
        if not isinstance(self.is_active, bool):
            raise LifecycleInvariantError(
                "Entity reference evidence requires a boolean active state."
            )

        expected_scores: dict[ReferenceRankReason, frozenset[UnitScore]] = {
            ReferenceRankReason.EXACT_NAME: frozenset({UnitScore("1.00")}),
            ReferenceRankReason.ACTIVE_STATE: frozenset({UnitScore("0.90")}),
            ReferenceRankReason.RECENT_TRACKED: frozenset(
                {UnitScore("0.80"), UnitScore("0.00")}
            ),
            ReferenceRankReason.SOURCE_MESSAGE: frozenset(
                {UnitScore("0.60"), UnitScore("0.00")}
            ),
            ReferenceRankReason.STALE_ENTITY: frozenset({UnitScore("0.00")}),
        }
        if self.score not in expected_scores[self.rank_reason]:
            raise LifecycleInvariantError(
                "Reference evidence score does not match its canonical rank reason."
            )

        if self.rank_reason is ReferenceRankReason.STALE_ENTITY:
            if self.is_active:
                raise LifecycleInvariantError("Stale reference evidence must be inactive.")
            if any(
                value is not None
                for value in (
                    self.evidence_message_id,
                    self.evidence_message_sequence,
                    self.prior_mention_ordinal,
                )
            ):
                raise LifecycleInvariantError(
                    "Stale reference evidence cannot carry message-recency evidence."
                )
            return

        if not self.is_active:
            raise LifecycleInvariantError(
                "Non-stale entity reference evidence must be active."
            )
        if self.rank_reason is ReferenceRankReason.EXACT_NAME:
            if (
                self.evidence_message_id is None
                or self.evidence_message_sequence is None
                or self.prior_mention_ordinal is not None
            ):
                raise LifecycleInvariantError(
                    "Exact-name evidence requires the current message and sequence only."
                )
        elif self.rank_reason is ReferenceRankReason.ACTIVE_STATE:
            if any(
                value is not None
                for value in (
                    self.evidence_message_id,
                    self.evidence_message_sequence,
                    self.prior_mention_ordinal,
                )
            ):
                raise LifecycleInvariantError(
                    "Active-state evidence uses entity-source fallback, not message recency."
                )
        elif self.rank_reason is ReferenceRankReason.RECENT_TRACKED:
            if (
                self.evidence_message_id is None
                or self.evidence_message_sequence is None
                or self.prior_mention_ordinal is None
            ):
                raise LifecycleInvariantError(
                    "Tracked evidence requires a prior message sequence and mention ordinal."
                )
        elif self.rank_reason is ReferenceRankReason.SOURCE_MESSAGE and (
            self.evidence_message_id is None
            or self.evidence_message_sequence is None
            or self.prior_mention_ordinal is not None
        ):
            raise LifecycleInvariantError(
                "Source-message evidence requires a prior message sequence only."
            )

    def to_json_object(self) -> FrozenJsonObject:
        """Return the exact durable candidate-evidence object."""

        return FrozenJsonObject(
            {
                "rank": self.rank,
                "entity_id": None if self.entity_id is None else str(self.entity_id),
                "entity_type": (
                    None if self.entity_type is None else self.entity_type.value
                ),
                "display_name": self.display_name,
                "normalized_name": self.normalized_name,
                "score": float(self.score),
                "rank_reason": self.rank_reason.value,
                "entity_source_message_id": (
                    None
                    if self.entity_source_message_id is None
                    else str(self.entity_source_message_id)
                ),
                "evidence_message_id": (
                    None
                    if self.evidence_message_id is None
                    else str(self.evidence_message_id)
                ),
                "evidence_message_sequence": self.evidence_message_sequence,
                "prior_mention_ordinal": self.prior_mention_ordinal,
                "is_active": self.is_active,
            }
        )

    @classmethod
    def from_json_object(
        cls,
        value: FrozenJsonObject | Mapping[str, object],
    ) -> ReferenceCandidateEvidence:
        """Validate and hydrate the exact durable candidate-evidence object."""

        if set(value) != _REFERENCE_EVIDENCE_KEYS:
            raise LifecycleInvariantError(
                "Reference candidate evidence must contain exactly the canonical keys."
            )
        return cls(
            rank=value["rank"],  # type: ignore[arg-type]
            entity_id=(
                None
                if value["entity_id"] is None
                else DomainId(value["entity_id"])  # type: ignore[arg-type]
            ),
            entity_type=(
                None
                if value["entity_type"] is None
                else EntityType(value["entity_type"])  # type: ignore[arg-type]
            ),
            display_name=value["display_name"],  # type: ignore[arg-type]
            normalized_name=value["normalized_name"],  # type: ignore[arg-type]
            score=UnitScore(value["score"]),  # type: ignore[arg-type]
            rank_reason=ReferenceRankReason(value["rank_reason"]),  # type: ignore[arg-type]
            entity_source_message_id=(
                None
                if value["entity_source_message_id"] is None
                else DomainId(value["entity_source_message_id"])  # type: ignore[arg-type]
            ),
            evidence_message_id=(
                None
                if value["evidence_message_id"] is None
                else DomainId(value["evidence_message_id"])  # type: ignore[arg-type]
            ),
            evidence_message_sequence=value["evidence_message_sequence"],  # type: ignore[arg-type]
            prior_mention_ordinal=value["prior_mention_ordinal"],  # type: ignore[arg-type]
            is_active=value["is_active"],  # type: ignore[arg-type]
        )


def reference_evidence_order_key(
    evidence: ReferenceCandidateEvidence,
) -> tuple[object, ...]:
    """Return the canonical presentation key, excluding the stored rank."""

    recency_sequence = (
        evidence.evidence_message_sequence
        if evidence.rank_reason
        in {ReferenceRankReason.RECENT_TRACKED, ReferenceRankReason.SOURCE_MESSAGE}
        else None
    )
    recency_ordinal = (
        evidence.prior_mention_ordinal
        if evidence.rank_reason is ReferenceRankReason.RECENT_TRACKED
        else None
    )
    return (
        -evidence.score.value,
        _REFERENCE_REASON_ORDER[evidence.rank_reason],
        -(recency_sequence if recency_sequence is not None else -1),
        -(recency_ordinal if recency_ordinal is not None else -1),
        evidence.normalized_name or "",
        evidence.entity_type.value if evidence.entity_type is not None else "",
        str(evidence.entity_id) if evidence.entity_id is not None else "",
    )


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
    candidate_evidence: tuple[ReferenceCandidateEvidence, ...]
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

        evidence = tuple(self.candidate_evidence)
        if not evidence or any(
            not isinstance(item, ReferenceCandidateEvidence) for item in evidence
        ):
            raise LifecycleInvariantError(
                "ReferenceOutcome requires non-empty typed candidate evidence."
            )
        if [item.rank for item in evidence] != list(range(1, len(evidence) + 1)):
            raise LifecycleInvariantError(
                "Reference candidate evidence ranks must be one-based and contiguous."
            )
        if tuple(sorted(evidence, key=reference_evidence_order_key)) != evidence:
            raise LifecycleInvariantError(
                "Reference candidate evidence must use canonical presentation order."
            )
        entity_ids = tuple(
            item.entity_id for item in evidence if item.entity_id is not None
        )
        if len(set(entity_ids)) != len(entity_ids):
            raise LifecycleInvariantError(
                "Reference candidate evidence may contain each entity only once."
            )
        placeholders = tuple(
            item
            for item in evidence
            if item.rank_reason in _PLACEHOLDER_REFERENCE_REASONS
        )
        if placeholders and (len(evidence) != 1 or len(placeholders) != 1):
            raise LifecycleInvariantError(
                "Placeholder reference evidence must be the sole evidence item."
            )

        positive = tuple(item for item in evidence if item.score > UnitScore(0))
        highest_score = positive[0].score if positive else UnitScore(0)
        top = tuple(item for item in positive if item.score == highest_score)

        if self.status is ReferenceStatus.RESOLVED:
            if (
                len(top) != 1
                or highest_score < UnitScore("0.80")
                or top[0].entity_id != self.resolved_entity_id
            ):
                raise LifecycleInvariantError(
                    "Resolved reference requires one matching top candidate at or above 0.80."
                )
            expected_source = (
                top[0].evidence_message_id or top[0].entity_source_message_id
            )
            if self.confidence != highest_score or self.source_message_id != expected_source:
                raise LifecycleInvariantError(
                    "Resolved reference confidence/source must match its winning evidence."
                )
        elif self.status is ReferenceStatus.AMBIGUOUS:
            if len(top) < 2 or highest_score == UnitScore(0):
                raise LifecycleInvariantError(
                    "Ambiguous reference requires at least two positive top candidates."
                )
            if self.confidence != highest_score or self.source_message_id is not None:
                raise LifecycleInvariantError(
                    "Ambiguous reference requires shared top confidence and null source."
                )
        elif self.status is ReferenceStatus.UNRESOLVED:
            if placeholders:
                if placeholders[0].rank_reason not in {
                    ReferenceRankReason.NO_CANDIDATE,
                    ReferenceRankReason.FILE_CONTEXT_UNSUPPORTED,
                }:
                    raise LifecycleInvariantError(
                        "Declaration-target evidence requires NOT_APPLICABLE status."
                    )
                expected_confidence = UnitScore(0)
                expected_source = None
            elif not positive:
                expected_confidence = UnitScore(0)
                expected_source = None
            else:
                if len(top) != 1 or highest_score >= UnitScore("0.80"):
                    raise LifecycleInvariantError(
                        "Unresolved positive evidence requires one top candidate below 0.80."
                    )
                expected_confidence = highest_score
                expected_source = (
                    top[0].evidence_message_id or top[0].entity_source_message_id
                )
            if (
                self.confidence != expected_confidence
                or self.source_message_id != expected_source
            ):
                raise LifecycleInvariantError(
                    "Unresolved reference confidence/source must match its evidence."
                )
        else:
            if (
                len(placeholders) != 1
                or placeholders[0].rank_reason
                is not ReferenceRankReason.DECLARATION_TARGET
                or self.confidence != UnitScore(1)
                or self.source_message_id != self.message_id
            ):
                raise LifecycleInvariantError(
                    "NOT_APPLICABLE requires declaration-target evidence and current-message source."
                )

        object.__setattr__(self, "candidate_evidence", evidence)
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class ReferenceDecision:
    """Complete immutable result of deterministic reference resolution."""

    outcomes: tuple[ReferenceOutcome, ...]
    clarification_reason: ClarificationReason | None
    clarification_details: FrozenJsonObject | None
    blocks_generation: bool

    def __post_init__(self) -> None:
        outcomes = tuple(self.outcomes)
        object.__setattr__(self, "outcomes", outcomes)
        if not isinstance(self.blocks_generation, bool):
            raise LifecycleInvariantError(
                "ReferenceDecision.blocks_generation must be boolean."
            )
        if [outcome.mention_ordinal for outcome in outcomes] != list(
            range(len(outcomes))
        ):
            raise LifecycleInvariantError(
                "ReferenceDecision outcomes require contiguous source-order ordinals."
            )
        if len({outcome.id for outcome in outcomes}) != len(outcomes):
            raise LifecycleInvariantError(
                "ReferenceDecision outcome IDs must be distinct."
            )
        if outcomes and (
            len({outcome.processing_run_id for outcome in outcomes}) != 1
            or len({outcome.message_id for outcome in outcomes}) != 1
        ):
            raise LifecycleInvariantError(
                "ReferenceDecision outcomes must share one run and current message."
            )

        blocking = next(
            (
                outcome
                for outcome in outcomes
                if outcome.status
                in {ReferenceStatus.AMBIGUOUS, ReferenceStatus.UNRESOLVED}
            ),
            None,
        )
        expected_reason = (
            None
            if blocking is None
            else (
                ClarificationReason.AMBIGUOUS_REFERENCE
                if blocking.status is ReferenceStatus.AMBIGUOUS
                else ClarificationReason.UNRESOLVED_REFERENCE
            )
        )
        if self.blocks_generation is not (blocking is not None):
            raise LifecycleInvariantError(
                "ReferenceDecision blocking flag must match its material outcomes."
            )
        if (self.clarification_reason is None) != (
            self.clarification_details is None
        ):
            raise LifecycleInvariantError(
                "Reference clarification reason and details must be supplied together."
            )
        if self.clarification_reason is not expected_reason:
            raise LifecycleInvariantError(
                "Reference clarification reason must match the earliest blocking outcome."
            )
        if blocking is None:
            return

        details = _freeze_json_object(self.clarification_details)  # type: ignore[arg-type]
        if (
            details.get("mention_ordinal") != blocking.mention_ordinal
            or details.get("surface_text") != blocking.surface_text
        ):
            raise LifecycleInvariantError(
                "Reference clarification details must identify the earliest blocking mention."
            )
        object.__setattr__(self, "clarification_details", details)


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
        if not isinstance(self.score, UnitScore):
            raise LifecycleInvariantError("RetrievalResult.score must be a UnitScore.")
        if isinstance(self.reasons, str):
            raise LifecycleInvariantError("RetrievalResult.reasons must be a collection.")
        reasons = tuple(self.reasons)
        if len(reasons) != len(_RETRIEVAL_REASON_NAMES):
            raise LifecycleInvariantError(
                "RetrievalResult.reasons must contain exactly seven factor strings."
            )
        for reason, factor_name in zip(
            reasons,
            _RETRIEVAL_REASON_NAMES,
            strict=True,
        ):
            prefix = f"{factor_name}="
            if not isinstance(reason, str) or not reason.startswith(prefix):
                raise LifecycleInvariantError(
                    "RetrievalResult.reasons require the canonical factor order."
                )
            _canonical_unit_score_text(
                f"RetrievalResult reason {factor_name}",
                reason[len(prefix) :],
            )
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
        if not isinstance(self.exclusion_reason, RetrievalExclusionReason):
            raise LifecycleInvariantError(
                "RetrievalExclusion.exclusion_reason must be canonical."
            )
        if self.computed_score is not None and not isinstance(
            self.computed_score,
            UnitScore,
        ):
            raise LifecycleInvariantError(
                "RetrievalExclusion.computed_score must be a UnitScore or null."
            )
        details = _freeze_json_object(self.details)
        object.__setattr__(self, "details", details)

        expected_keys = _RETRIEVAL_EXCLUSION_DETAIL_KEYS[self.exclusion_reason]
        if set(details) != expected_keys:
            raise LifecycleInvariantError(
                "RetrievalExclusion.details must contain exactly the canonical keys "
                f"for {self.exclusion_reason.value}."
            )

        score_required = self.exclusion_reason in {
            RetrievalExclusionReason.SCORE_BELOW_THRESHOLD,
            RetrievalExclusionReason.DUPLICATE_CONTENT,
            RetrievalExclusionReason.LIMIT_EXCEEDED,
        }
        if score_required != (self.computed_score is not None):
            raise LifecycleInvariantError(
                "RetrievalExclusion.computed_score nullability must match its reason."
            )

        if self.exclusion_reason is RetrievalExclusionReason.SCOPE_MISMATCH:
            self._validate_scope_mismatch_details(details)
        elif self.exclusion_reason is RetrievalExclusionReason.DELETED:
            if details["stored_status"] != MemoryStatus.DELETED.value:
                raise LifecycleInvariantError(
                    "DELETED exclusion requires stored_status DELETED."
                )
            _canonical_detail_time(details, "deleted_at")
        elif self.exclusion_reason is RetrievalExclusionReason.EXPIRED:
            if details["stored_status"] != MemoryStatus.ACTIVE.value:
                raise LifecycleInvariantError(
                    "EXPIRED exclusion requires stored_status ACTIVE."
                )
            expires_at = _canonical_detail_time(details, "expires_at")
            evaluated_at = _canonical_detail_time(details, "evaluated_at")
            if expires_at > evaluated_at:
                raise LifecycleInvariantError(
                    "EXPIRED exclusion requires expires_at at or before evaluated_at."
                )
        elif self.exclusion_reason is RetrievalExclusionReason.SCORE_BELOW_THRESHOLD:
            _canonical_unit_score_text(
                "Retrieval exclusion minimum_relevance_score",
                details["minimum_relevance_score"],
            )
        elif self.exclusion_reason is RetrievalExclusionReason.DUPLICATE_CONTENT:
            retained_memory_id = _canonical_detail_id(details, "retained_memory_id")
            if retained_memory_id == self.memory_id:
                raise LifecycleInvariantError(
                    "DUPLICATE_CONTENT must reference a different retained memory."
                )
        else:
            result_limit = _detail_non_negative_integer(details, "result_limit")
            pre_limit_rank = _detail_non_negative_integer(details, "pre_limit_rank")
            if pre_limit_rank < result_limit:
                raise LifecycleInvariantError(
                    "LIMIT_EXCEEDED requires pre_limit_rank at or beyond result_limit."
                )

        _normalize_time(self, "created_at")

    @staticmethod
    def _validate_scope_mismatch_details(details: FrozenJsonObject) -> None:
        scope_value = details["scope"]
        if not isinstance(scope_value, str):
            raise LifecycleInvariantError(
                "SCOPE_MISMATCH detail 'scope' must be canonical text."
            )
        try:
            scope = MemoryScope(scope_value)
        except ValueError as error:
            raise LifecycleInvariantError(
                "SCOPE_MISMATCH detail 'scope' must be a canonical MemoryScope."
            ) from error

        request_conversation_id = _canonical_detail_id(
            details,
            "request_conversation_id",
        )
        request_project_id = _canonical_detail_id(
            details,
            "request_project_id",
            optional=True,
        )
        memory_conversation_id = _canonical_detail_id(
            details,
            "memory_conversation_id",
            optional=True,
        )
        memory_project_id = _canonical_detail_id(
            details,
            "memory_project_id",
            optional=True,
        )

        if scope is MemoryScope.CONVERSATION:
            if (
                memory_conversation_id is None
                or memory_conversation_id == request_conversation_id
            ):
                raise LifecycleInvariantError(
                    "SCOPE_MISMATCH conversation details must describe different owners."
                )
        elif scope is MemoryScope.PROJECT:
            if memory_project_id is None or (
                request_project_id is not None
                and memory_project_id == request_project_id
            ):
                raise LifecycleInvariantError(
                    "SCOPE_MISMATCH project details must describe different owners."
                )
        else:
            raise LifecycleInvariantError(
                "GLOBAL memory cannot have a SCOPE_MISMATCH exclusion."
            )


def require_retrieval_evidence(
    selected: tuple[RetrievalResult, ...],
    excluded: tuple[RetrievalExclusion, ...],
    *,
    context_packet_id: DomainId | None = None,
) -> tuple[tuple[RetrievalResult, ...], tuple[RetrievalExclusion, ...]]:
    """Validate canonical retrieval evidence identity, partition, order, and time."""

    frozen_selected = tuple(selected)
    frozen_excluded = tuple(excluded)
    evidence = (*frozen_selected, *frozen_excluded)

    packet_ids = {item.context_packet_id for item in evidence}
    if context_packet_id is not None and any(
        packet_id != context_packet_id for packet_id in packet_ids
    ):
        raise LifecycleInvariantError(
            "Every retrieval evidence item must belong to the aggregate packet."
        )
    if len(packet_ids) > 1:
        raise LifecycleInvariantError(
            "Retrieval evidence requires one common context packet identity."
        )

    if [result.rank for result in frozen_selected] != list(
        range(len(frozen_selected))
    ):
        raise LifecycleInvariantError(
            "Retrieval results require contiguous zero-based rank order."
        )
    if any(
        earlier.score.value < later.score.value
        for earlier, later in zip(
            frozen_selected,
            frozen_selected[1:],
            strict=False,
        )
    ):
        raise LifecycleInvariantError(
            "Retrieval results require descending score order."
        )

    selected_ids = [result.id for result in frozen_selected]
    excluded_ids = [exclusion.id for exclusion in frozen_excluded]
    if len(set(selected_ids)) != len(selected_ids) or len(set(excluded_ids)) != len(
        excluded_ids
    ):
        raise LifecycleInvariantError("Retrieval evidence requires distinct record IDs.")
    if set(selected_ids) & set(excluded_ids):
        raise LifecycleInvariantError(
            "Selected and excluded retrieval record IDs must be disjoint."
        )

    selected_memory_ids = [result.memory_id for result in frozen_selected]
    excluded_memory_ids = [exclusion.memory_id for exclusion in frozen_excluded]
    if len(set(selected_memory_ids)) != len(selected_memory_ids) or len(
        set(excluded_memory_ids)
    ) != len(excluded_memory_ids):
        raise LifecycleInvariantError(
            "Retrieval evidence requires distinct memory IDs within each partition."
        )
    if set(selected_memory_ids) & set(excluded_memory_ids):
        raise LifecycleInvariantError(
            "Selected and excluded memory IDs must be disjoint."
        )
    if excluded_memory_ids != sorted(excluded_memory_ids, key=str):
        raise LifecycleInvariantError(
            "Retrieval exclusions require canonical memory UUID order."
        )

    retrieval_times = {item.created_at for item in evidence}
    if len(retrieval_times) > 1:
        raise LifecycleInvariantError(
            "Retrieval evidence requires one common retrieval timestamp."
        )

    return frozen_selected, frozen_excluded


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
