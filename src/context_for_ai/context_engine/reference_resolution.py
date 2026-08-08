"""Pure deterministic TASK-0008 reference resolution."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from context_for_ai.context_engine.normalization import (
    find_phrase_matches,
    normalize_text,
)
from context_for_ai.context_engine.reference_extraction import (
    parse_named_item_declaration,
)
from context_for_ai.domain.decisions import (
    ReferenceCandidateEvidence,
    ReferenceDecision,
    ReferenceMention,
    ReferenceOutcome,
    reference_evidence_order_key,
)
from context_for_ai.domain.entities import ConversationState, Entity, Message
from context_for_ai.domain.enums import (
    ClarificationReason,
    EntityType,
    ReferenceRankReason,
    ReferenceStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import ReferenceResolutionRequest
from context_for_ai.domain.ports.system import IdGenerator
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


_ALL_ENTITY_TYPES = frozenset(EntityType)
_FIXED_COMPATIBILITY: dict[str, tuple[str, frozenset[EntityType]]] = {
    "it": ("it", _ALL_ENTITY_TYPES),
    "this": ("this", _ALL_ENTITY_TYPES),
    "that": ("that", _ALL_ENTITY_TYPES),
    "the app": ("app", frozenset({EntityType.PROJECT, EntityType.NAMED_ITEM})),
    "this app": ("app", frozenset({EntityType.PROJECT, EntityType.NAMED_ITEM})),
    "that app": ("app", frozenset({EntityType.PROJECT, EntityType.NAMED_ITEM})),
    "the project": ("project", frozenset({EntityType.PROJECT})),
    "this project": ("project", frozenset({EntityType.PROJECT})),
    "that project": ("project", frozenset({EntityType.PROJECT})),
    "the topic": ("topic", frozenset({EntityType.TOPIC})),
    "this topic": ("topic", frozenset({EntityType.TOPIC})),
    "that topic": ("topic", frozenset({EntityType.TOPIC})),
    "the task": ("task", frozenset({EntityType.TASK})),
    "this task": ("task", frozenset({EntityType.TASK})),
    "that task": ("task", frozenset({EntityType.TASK})),
}
_PRIOR_FORM = "same as before"
_FILE_FORMS = frozenset({"the file", "this file", "that file"})


@dataclass(frozen=True, slots=True)
class _MentionSemantics:
    lookup_key: str | None
    compatible_types: frozenset[EntityType]
    explicit_name: bool = False
    prior_reference: bool = False
    file_reference: bool = False
    declaration_target: bool = False


def _declaration_target(message: Message, mention: ReferenceMention) -> bool:
    declaration = parse_named_item_declaration(message.original_text)
    return bool(
        declaration is not None
        and declaration.command == "call this"
        and declaration.target_start_offset == mention.start_offset
        and declaration.target_end_offset == mention.end_offset
        and mention.normalized_phrase == "this"
    )


def _mention_semantics(
    message: Message,
    mention: ReferenceMention,
) -> _MentionSemantics:
    if _declaration_target(message, mention):
        return _MentionSemantics(None, frozenset(), declaration_target=True)
    if mention.qualifier_rule_id.startswith("reference-name:"):
        return _MentionSemantics(
            mention.normalized_phrase,
            _ALL_ENTITY_TYPES,
            explicit_name=True,
        )
    if mention.normalized_phrase == _PRIOR_FORM:
        return _MentionSemantics(
            None,
            _ALL_ENTITY_TYPES,
            prior_reference=True,
        )
    if mention.normalized_phrase in _FILE_FORMS:
        return _MentionSemantics(None, frozenset(), file_reference=True)
    try:
        lookup_key, entity_types = _FIXED_COMPATIBILITY[mention.normalized_phrase]
    except KeyError as error:
        raise LifecycleInvariantError(
            "Resolver received an unsupported final reference mention."
        ) from error
    return _MentionSemantics(lookup_key, entity_types)


def _is_active_state(entity: Entity, state: ConversationState) -> bool:
    if entity.entity_type is EntityType.PROJECT:
        return True
    if entity.entity_type is EntityType.TOPIC:
        return entity.native_id == state.active_topic_id
    if entity.entity_type is EntityType.TASK:
        return entity.native_id == state.active_task_id
    return False


def _placeholder(reason: ReferenceRankReason) -> tuple[ReferenceCandidateEvidence, ...]:
    return (
        ReferenceCandidateEvidence(
            1,
            None,
            None,
            None,
            None,
            UnitScore("0.00"),
            reason,
            None,
            None,
            None,
            None,
            None,
        ),
    )


def _entity_evidence(
    entity: Entity,
    *,
    score: UnitScore,
    reason: ReferenceRankReason,
    evidence_message_id: DomainId | None = None,
    evidence_message_sequence: int | None = None,
    prior_mention_ordinal: int | None = None,
) -> ReferenceCandidateEvidence:
    return ReferenceCandidateEvidence(
        1,
        entity.id,
        entity.entity_type,
        entity.display_name,
        entity.normalized_name,
        score,
        reason,
        entity.source_message_id,
        evidence_message_id,
        evidence_message_sequence,
        prior_mention_ordinal,
        entity.is_active,
    )


def _tracked_recency(
    entity: Entity,
    request: ReferenceResolutionRequest,
    prior_by_id: dict[DomainId, Message],
) -> tuple[int, int, DomainId] | None:
    matches = [
        (
            prior_by_id[outcome.message_id].sequence_number,
            outcome.mention_ordinal,
            outcome.message_id,
        )
        for outcome in request.prior_resolved_outcomes
        if outcome.resolved_entity_id == entity.id
    ]
    return max(matches) if matches else None


def _source_recency(
    entity: Entity,
    prior_messages: tuple[Message, ...],
) -> tuple[int, DomainId] | None:
    matches = [
        (message.sequence_number, message.id)
        for message in prior_messages
        if find_phrase_matches(normalize_text(message.original_text), entity.normalized_name)
    ]
    return max(matches) if matches else None


def _ranked_evidence(
    request: ReferenceResolutionRequest,
    semantics: _MentionSemantics,
) -> tuple[ReferenceCandidateEvidence, ...]:
    candidates = tuple(
        entity
        for entity in request.scoped_entities
        if entity.entity_type in semantics.compatible_types
        and (
            not semantics.explicit_name
            or entity.normalized_name == semantics.lookup_key
        )
    )
    if not candidates:
        return _placeholder(ReferenceRankReason.NO_CANDIDATE)

    prior_by_id = {message.id: message for message in request.prior_messages}
    selected: dict[DomainId, ReferenceCandidateEvidence] = {}
    unmatched: list[Entity] = []
    for entity in candidates:
        if not entity.is_active:
            selected[entity.id] = _entity_evidence(
                entity,
                score=UnitScore("0.00"),
                reason=ReferenceRankReason.STALE_ENTITY,
            )
        elif (
            not semantics.prior_reference
            and semantics.lookup_key == entity.normalized_name
        ):
            selected[entity.id] = _entity_evidence(
                entity,
                score=UnitScore("1.00"),
                reason=ReferenceRankReason.EXACT_NAME,
                evidence_message_id=request.message.id,
                evidence_message_sequence=request.message.sequence_number,
            )
        elif not semantics.prior_reference and _is_active_state(entity, request.state):
            selected[entity.id] = _entity_evidence(
                entity,
                score=UnitScore("0.90"),
                reason=ReferenceRankReason.ACTIVE_STATE,
            )
        else:
            unmatched.append(entity)

    tracked = {
        entity.id: recency
        for entity in unmatched
        if (recency := _tracked_recency(entity, request, prior_by_id)) is not None
    }
    greatest_tracked = max(tracked.values()) if tracked else None
    source_candidates: list[Entity] = []
    for entity in unmatched:
        recency = tracked.get(entity.id)
        if recency is None:
            source_candidates.append(entity)
            continue
        sequence, ordinal, message_id = recency
        selected[entity.id] = _entity_evidence(
            entity,
            score=UnitScore("0.80") if recency == greatest_tracked else UnitScore("0.00"),
            reason=ReferenceRankReason.RECENT_TRACKED,
            evidence_message_id=message_id,
            evidence_message_sequence=sequence,
            prior_mention_ordinal=ordinal,
        )

    sources = {
        entity.id: recency
        for entity in source_candidates
        if (recency := _source_recency(entity, request.prior_messages)) is not None
    }
    greatest_source = max(sources.values()) if sources else None
    for entity in source_candidates:
        recency = sources.get(entity.id)
        if recency is None:
            continue
        sequence, message_id = recency
        selected[entity.id] = _entity_evidence(
            entity,
            score=UnitScore("0.60") if recency == greatest_source else UnitScore("0.00"),
            reason=ReferenceRankReason.SOURCE_MESSAGE,
            evidence_message_id=message_id,
            evidence_message_sequence=sequence,
        )

    if not selected:
        return _placeholder(ReferenceRankReason.NO_CANDIDATE)
    ordered = sorted(selected.values(), key=reference_evidence_order_key)
    return tuple(replace(item, rank=rank) for rank, item in enumerate(ordered, 1))


def _outcome(
    request: ReferenceResolutionRequest,
    mention: ReferenceMention,
    outcome_id: DomainId,
) -> ReferenceOutcome:
    semantics = _mention_semantics(request.message, mention)
    if semantics.declaration_target:
        return ReferenceOutcome(
            outcome_id,
            request.processing_run_id,
            request.message.id,
            mention.mention_ordinal,
            mention.surface_text,
            ReferenceStatus.NOT_APPLICABLE,
            None,
            request.message.id,
            UnitScore("1.00"),
            _placeholder(ReferenceRankReason.DECLARATION_TARGET),
            request.evaluated_at,
        )
    if semantics.file_reference:
        return ReferenceOutcome(
            outcome_id,
            request.processing_run_id,
            request.message.id,
            mention.mention_ordinal,
            mention.surface_text,
            ReferenceStatus.UNRESOLVED,
            None,
            None,
            UnitScore("0.00"),
            _placeholder(ReferenceRankReason.FILE_CONTEXT_UNSUPPORTED),
            request.evaluated_at,
        )

    evidence = _ranked_evidence(request, semantics)
    positive = tuple(item for item in evidence if item.score > UnitScore(0))
    top_score = positive[0].score if positive else UnitScore(0)
    top = tuple(item for item in positive if item.score == top_score)
    if len(top) >= 2:
        status = ReferenceStatus.AMBIGUOUS
        resolved_entity_id = None
        source_message_id = None
        confidence = top_score
    elif len(top) == 1 and top_score >= UnitScore("0.80"):
        status = ReferenceStatus.RESOLVED
        resolved_entity_id = top[0].entity_id
        source_message_id = (
            top[0].evidence_message_id or top[0].entity_source_message_id
        )
        confidence = top_score
    else:
        status = ReferenceStatus.UNRESOLVED
        resolved_entity_id = None
        source_message_id = (
            None
            if not top
            else top[0].evidence_message_id or top[0].entity_source_message_id
        )
        confidence = top_score
    return ReferenceOutcome(
        outcome_id,
        request.processing_run_id,
        request.message.id,
        mention.mention_ordinal,
        mention.surface_text,
        status,
        resolved_entity_id,
        source_message_id,
        confidence,
        evidence,
        request.evaluated_at,
    )


def _source_message_ids(outcome: ReferenceOutcome) -> tuple[str, ...]:
    values: list[str] = []
    for evidence in outcome.candidate_evidence:
        for source_id in (
            evidence.entity_source_message_id,
            evidence.evidence_message_id,
        ):
            if source_id is not None and str(source_id) not in values:
                values.append(str(source_id))
    if outcome.source_message_id is not None and str(outcome.source_message_id) not in values:
        values.append(str(outcome.source_message_id))
    return tuple(values)


def _blocking_details(outcome: ReferenceOutcome) -> FrozenJsonObject:
    base: dict[str, object] = {
        "mention_ordinal": outcome.mention_ordinal,
        "surface_text": outcome.surface_text,
        "candidate_evidence": tuple(
            item.to_json_object() for item in outcome.candidate_evidence
        ),
        "source_message_ids": _source_message_ids(outcome),
    }
    if outcome.status is ReferenceStatus.AMBIGUOUS:
        highest = outcome.confidence
        top = tuple(
            item for item in outcome.candidate_evidence if item.score == highest
        )
        types = {item.entity_type for item in top}
        names = Counter(item.display_name for item in top)
        annotate = len(types) > 1 or any(count > 1 for count in names.values())
        labels = tuple(
            (
                f"{item.display_name} ({item.entity_type.value.lower()})"
                if annotate
                else item.display_name
            )
            for item in top
            if item.display_name is not None and item.entity_type is not None
        )
        base["entity_type"] = (
            next(iter(types)).value.lower()
            if len(types) == 1 and None not in types
            else "entity"
        )
        base["candidate_labels"] = labels
    return FrozenJsonObject(base)


class DeterministicReferenceResolver:
    """Resolve final mentions without repositories, clocks, providers, or mutation."""

    def __init__(self, id_generator: IdGenerator) -> None:
        self._id_generator = id_generator

    def resolve(self, request: ReferenceResolutionRequest) -> ReferenceDecision:
        outcomes = tuple(
            _outcome(request, mention, self._id_generator.new_id())
            for mention in request.mentions
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
        if blocking is None:
            return ReferenceDecision(outcomes, None, None, False)
        reason = (
            ClarificationReason.AMBIGUOUS_REFERENCE
            if blocking.status is ReferenceStatus.AMBIGUOUS
            else ClarificationReason.UNRESOLVED_REFERENCE
        )
        return ReferenceDecision(
            outcomes,
            reason,
            _blocking_details(blocking),
            True,
        )


__all__ = ["DeterministicReferenceResolver"]
