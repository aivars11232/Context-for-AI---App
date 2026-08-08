"""Focused tests for pure deterministic TASK-0008 reference resolution."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from context_for_ai.context_engine.normalization import normalize_phrase
from context_for_ai.context_engine.reference_extraction import (
    DeterministicReferenceMentionExtractor,
)
from context_for_ai.context_engine.reference_resolution import (
    DeterministicReferenceResolver,
)
from context_for_ai.domain.decisions import (
    ReferenceCandidateEvidence,
    ReferenceMention,
    ReferenceOutcome,
)
from context_for_ai.domain.entities import ConversationState, Entity, Message
from context_for_ai.domain.enums import (
    ClarificationReason,
    EntityType,
    MessageRole,
    ReferenceRankReason,
    ReferenceStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import (
    ReferenceMentionExtractionRequest,
    ReferenceResolutionRequest,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
CONVERSATION_ID = DomainId("40000000-0000-4000-8000-000000000001")


def identifier(number: int) -> DomainId:
    return DomainId(f"40000000-0000-4000-8000-{number:012d}")


class SequenceIds:
    def __init__(self, start: int = 900) -> None:
        self.next_number = start
        self.calls = 0

    def new_id(self) -> DomainId:
        value = identifier(self.next_number)
        self.next_number += 1
        self.calls += 1
        return value


def entity(
    number: int,
    entity_type: EntityType,
    display_name: str,
    *,
    active: bool = True,
    source_message_id: DomainId | None = None,
) -> Entity:
    native_id = identifier(100 + number)
    project_id = native_id if entity_type is EntityType.PROJECT else None
    return Entity(
        identifier(number),
        entity_type,
        native_id,
        project_id,
        display_name,
        normalize_phrase(display_name),
        source_message_id,
        active,
        NOW,
        NOW,
    )


def user_message(number: int, text: str, sequence: int) -> Message:
    return Message(
        identifier(number),
        CONVERSATION_ID,
        MessageRole.USER,
        text,
        NOW,
        sequence,
    )


def state(
    *,
    active_topic_id: DomainId | None = None,
    active_task_id: DomainId | None = None,
) -> ConversationState:
    return ConversationState(
        CONVERSATION_ID,
        active_topic_id,
        active_task_id,
        None,
        None,
        (),
        0,
        NOW,
    )


def extracted(message: Message, entities: tuple[Entity, ...]) -> tuple[ReferenceMention, ...]:
    return DeterministicReferenceMentionExtractor().extract(
        ReferenceMentionExtractionRequest(message, (), entities)
    )


def active_evidence(candidate: Entity) -> ReferenceCandidateEvidence:
    return ReferenceCandidateEvidence(
        1,
        candidate.id,
        candidate.entity_type,
        candidate.display_name,
        candidate.normalized_name,
        UnitScore("0.90"),
        ReferenceRankReason.ACTIVE_STATE,
        candidate.source_message_id,
        None,
        None,
        None,
        True,
    )


def prior_resolved(
    number: int,
    message: Message,
    candidate: Entity,
    *,
    ordinal: int = 0,
) -> ReferenceOutcome:
    return ReferenceOutcome(
        identifier(number),
        identifier(700 + number),
        message.id,
        ordinal,
        "the app",
        ReferenceStatus.RESOLVED,
        candidate.id,
        candidate.source_message_id,
        UnitScore("0.90"),
        (active_evidence(candidate),),
        NOW,
    )


def resolve(
    message: Message,
    candidates: tuple[Entity, ...],
    *,
    prior_messages: tuple[Message, ...] = (),
    prior_outcomes: tuple[ReferenceOutcome, ...] = (),
    conversation_state: ConversationState | None = None,
    ids: SequenceIds | None = None,
):
    generator = ids or SequenceIds()
    mentions = extracted(message, candidates)
    request = ReferenceResolutionRequest(
        identifier(800),
        message,
        prior_messages,
        conversation_state or state(),
        mentions,
        candidates,
        prior_outcomes,
        NOW,
    )
    return DeterministicReferenceResolver(generator).resolve(request)


def test_active_project_resolves_the_app_with_creation_source_lineage() -> None:
    source_id = identifier(50)
    project = entity(
        2,
        EntityType.PROJECT,
        "Context for AI",
        source_message_id=source_id,
    )

    decision = resolve(user_message(10, "correct the app structure", 10), (project,))

    outcome = decision.outcomes[0]
    assert outcome.status is ReferenceStatus.RESOLVED
    assert outcome.resolved_entity_id == project.id
    assert outcome.source_message_id == source_id
    assert outcome.confidence == UnitScore("0.90")
    assert outcome.candidate_evidence[0].rank_reason is ReferenceRankReason.ACTIVE_STATE
    assert decision.blocks_generation is False


def test_exact_name_beats_active_state_and_uses_current_message_lineage() -> None:
    project = entity(2, EntityType.PROJECT, "Context for AI")
    named_item = entity(3, EntityType.NAMED_ITEM, "App")
    current = user_message(10, "fix the app", 10)

    outcome = resolve(current, (project, named_item)).outcomes[0]

    assert outcome.status is ReferenceStatus.RESOLVED
    assert outcome.resolved_entity_id == named_item.id
    assert outcome.source_message_id == current.id
    assert tuple(item.score for item in outcome.candidate_evidence) == (
        UnitScore("1.00"),
        UnitScore("0.90"),
    )
    assert tuple(item.rank_reason for item in outcome.candidate_evidence) == (
        ReferenceRankReason.EXACT_NAME,
        ReferenceRankReason.ACTIVE_STATE,
    )


def test_exact_tie_is_ambiguous_with_canonical_labels_and_null_selection() -> None:
    project = entity(2, EntityType.PROJECT, "App")
    named_item = entity(3, EntityType.NAMED_ITEM, "App")

    decision = resolve(user_message(10, "fix the app", 10), (project, named_item))

    outcome = decision.outcomes[0]
    assert outcome.status is ReferenceStatus.AMBIGUOUS
    assert outcome.resolved_entity_id is None
    assert outcome.source_message_id is None
    assert outcome.confidence == UnitScore("1.00")
    assert decision.clarification_reason is ClarificationReason.AMBIGUOUS_REFERENCE
    assert decision.clarification_details is not None
    assert decision.clarification_details["entity_type"] == "entity"
    assert decision.clarification_details["candidate_labels"] == (
        "App (named_item)",
        "App (project)",
    )


def test_same_as_before_uses_latest_tracked_candidate_and_retains_older_evidence() -> None:
    first = entity(2, EntityType.NAMED_ITEM, "First")
    second = entity(3, EntityType.NAMED_ITEM, "Second")
    prior_one = user_message(11, "use first", 1)
    prior_two = user_message(12, "use second", 2)
    current = user_message(10, "same as before", 3)
    outcomes = (
        prior_resolved(20, prior_one, first),
        prior_resolved(21, prior_two, second),
    )

    outcome = resolve(
        current,
        (first, second),
        prior_messages=(prior_one, prior_two),
        prior_outcomes=outcomes,
    ).outcomes[0]

    assert outcome.status is ReferenceStatus.RESOLVED
    assert outcome.resolved_entity_id == second.id
    assert outcome.source_message_id == prior_two.id
    assert tuple(item.rank_reason for item in outcome.candidate_evidence) == (
        ReferenceRankReason.RECENT_TRACKED,
        ReferenceRankReason.RECENT_TRACKED,
    )
    assert tuple(item.score for item in outcome.candidate_evidence) == (
        UnitScore("0.80"),
        UnitScore("0.00"),
    )


def test_source_message_band_is_unresolved_below_threshold_and_keeps_older_match() -> None:
    first = entity(2, EntityType.NAMED_ITEM, "Alpha")
    second = entity(3, EntityType.NAMED_ITEM, "Beta")
    prior_one = user_message(11, "change Alpha", 1)
    prior_two = user_message(12, "then Beta", 2)

    decision = resolve(
        user_message(10, "fix it", 3),
        (first, second),
        prior_messages=(prior_one, prior_two),
    )

    outcome = decision.outcomes[0]
    assert outcome.status is ReferenceStatus.UNRESOLVED
    assert outcome.confidence == UnitScore("0.60")
    assert outcome.source_message_id == prior_two.id
    assert tuple(item.score for item in outcome.candidate_evidence) == (
        UnitScore("0.60"),
        UnitScore("0.00"),
    )
    assert decision.clarification_reason is ClarificationReason.UNRESOLVED_REFERENCE


def test_stale_exact_candidate_is_retained_at_zero_and_cannot_win() -> None:
    stale = entity(2, EntityType.NAMED_ITEM, "Legacy", active=False)

    outcome = resolve(user_message(10, "update Legacy", 3), (stale,)).outcomes[0]

    assert outcome.status is ReferenceStatus.UNRESOLVED
    assert outcome.source_message_id is None
    assert outcome.candidate_evidence[0].rank_reason is ReferenceRankReason.STALE_ENTITY
    assert outcome.candidate_evidence[0].score == UnitScore("0.00")


def test_no_candidate_file_and_declaration_use_exact_placeholders() -> None:
    unrelated = entity(2, EntityType.NAMED_ITEM, "Architecture")

    no_candidate = resolve(user_message(10, "fix it", 3), (unrelated,)).outcomes[0]
    file_outcome = resolve(user_message(11, "open the file", 3), ()).outcomes[0]
    declaration = resolve(user_message(12, 'call this "Architecture"', 3), ()).outcomes[0]

    assert no_candidate.candidate_evidence[0].rank_reason is ReferenceRankReason.NO_CANDIDATE
    assert file_outcome.status is ReferenceStatus.UNRESOLVED
    assert (
        file_outcome.candidate_evidence[0].rank_reason
        is ReferenceRankReason.FILE_CONTEXT_UNSUPPORTED
    )
    assert declaration.status is ReferenceStatus.NOT_APPLICABLE
    assert declaration.source_message_id == identifier(12)
    assert (
        declaration.candidate_evidence[0].rank_reason
        is ReferenceRankReason.DECLARATION_TARGET
    )


def test_earliest_material_failure_supplies_the_single_blocking_details() -> None:
    project = entity(2, EntityType.PROJECT, "Context for AI")
    current = user_message(10, "the project then the file then it", 3)

    decision = resolve(current, (project,))

    assert tuple(item.status for item in decision.outcomes) == (
        ReferenceStatus.RESOLVED,
        ReferenceStatus.UNRESOLVED,
        ReferenceStatus.RESOLVED,
    )
    assert decision.blocks_generation is True
    assert decision.clarification_reason is ClarificationReason.UNRESOLVED_REFERENCE
    assert decision.clarification_details is not None
    assert decision.clarification_details["mention_ordinal"] == 1
    assert decision.clarification_details["surface_text"] == "the file"


def test_empty_mentions_create_no_outcomes_or_ids() -> None:
    ids = SequenceIds()
    decision = resolve(user_message(10, "plain request", 3), (), ids=ids)

    assert decision.outcomes == ()
    assert decision.blocks_generation is False
    assert ids.calls == 0


def test_resolver_rejects_an_unlisted_injected_final_mention() -> None:
    current = user_message(10, "those", 3)
    mention = ReferenceMention(0, "those", "those", "injected", 0, 5)
    request = ReferenceResolutionRequest(
        identifier(800),
        current,
        (),
        state(),
        (mention,),
        (),
        (),
        NOW,
    )

    with pytest.raises(LifecycleInvariantError, match="unsupported final"):
        DeterministicReferenceResolver(SequenceIds()).resolve(request)
