"""Versioned evaluation and acceptance coverage for TASK-0008 references."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import inspect
import json
from pathlib import Path

import pytest
import yaml

from context_for_ai.application import (
    RegisterNamedItemInput,
    RegisterNamedItemService,
    RegisterProjectInput,
    RegisterProjectService,
)
from context_for_ai.context_engine import (
    DeterministicReferenceMentionExtractor,
    DeterministicReferenceResolver,
)
from context_for_ai.context_engine.normalization import normalize_phrase
from context_for_ai.domain.entities import Conversation, ConversationState, Entity, Message
from context_for_ai.domain.enums import (
    ClarificationReason,
    EntityType,
    MessageRole,
    ProcessingRunStatus,
    ReferenceRankReason,
    ReferenceStatus,
)
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.context import (
    ReferenceMentionExtractionRequest,
    ReferenceResolutionRequest,
)
from context_for_ai.domain.state_transitions import initial_conversation_state
from context_for_ai.domain.value_objects import DomainId, UnitScore
from context_for_ai.infrastructure.database import (
    SQLiteConversationRepository,
    SQLiteConversationStateRepository,
    SQLiteEntityRepository,
    SQLiteMessageRepository,
    SQLiteProcessingRunRepository,
    SQLiteProjectRepository,
    SQLiteReferenceResolutionRepository,
    SQLiteTransactionBoundary,
    apply_migrations,
    connect_database,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "deterministic_references"
DOCUMENT = yaml.safe_load((FIXTURE_ROOT / "cases.yaml").read_text(encoding="utf-8"))
VERSION = (FIXTURE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
CASES = tuple(DOCUMENT["cases"])
FIXED = DOCUMENT["fixed"]
NOW = datetime.fromisoformat(FIXED["evaluated_at"].replace("Z", "+00:00"))


def identifier(number: int) -> DomainId:
    return DomainId(f"76000000-0000-4000-8000-{number:012d}")


class SequenceIds:
    def __init__(self, start: int = 900) -> None:
        self.next_number = start
        self.calls = 0

    def new_id(self) -> DomainId:
        result = identifier(self.next_number)
        self.next_number += 1
        self.calls += 1
        return result


class FixedClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW


def _message(text: str, *, number: int = 2, sequence: int = 8) -> Message:
    return Message(
        identifier(number),
        DomainId(FIXED["conversation_id"]),
        MessageRole.USER,
        text,
        NOW,
        sequence,
    )


def _state() -> ConversationState:
    return ConversationState(
        DomainId(FIXED["conversation_id"]),
        None,
        None,
        None,
        None,
        (),
        0,
        NOW,
    )


def _entities(case: dict[str, object]) -> tuple[Entity, ...]:
    records: list[Entity] = []
    for index, raw in enumerate(case["entities"]):  # type: ignore[index]
        definition = dict(raw)
        entity_type = EntityType(str(definition["type"]))
        native_id = identifier(100 + index)
        records.append(
            Entity(
                identifier(200 + index),
                entity_type,
                native_id,
                native_id if entity_type is EntityType.PROJECT else None,
                str(definition["name"]),
                normalize_phrase(str(definition["name"])),
                identifier(300 + index),
                bool(definition["active"]),
                NOW,
                NOW,
            )
        )
    return tuple(records)


def _evaluate(case: dict[str, object]):
    message = _message(str(case["message"]))
    entities = _entities(case)
    mentions = DeterministicReferenceMentionExtractor().extract(
        ReferenceMentionExtractionRequest(message, (), entities)
    )
    ids = SequenceIds()
    decision = DeterministicReferenceResolver(ids).resolve(
        ReferenceResolutionRequest(
            DomainId(FIXED["processing_run_id"]),
            message,
            (),
            _state(),
            mentions,
            entities,
            (),
            NOW,
        )
    )
    return message, entities, mentions, decision, ids


def test_fixture_is_versioned_unique_and_covers_required_reference_categories() -> None:
    assert DOCUMENT["fixture_version"] == VERSION == "task-0008-deterministic-v1"
    case_ids = [case["id"] for case in CASES]
    assert len(case_ids) == len(set(case_ids))
    assert {case["category"] for case in CASES} == {
        "exact",
        "stale",
        "tied",
        "missing",
        "declaration",
        "file",
        "unsupported",
    }


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_versioned_deterministic_reference_cases(case: dict[str, object]) -> None:
    _, _, mentions, decision, ids = _evaluate(case)

    assert len(mentions) == int(case["mentions"])
    assert tuple(item.mention_ordinal for item in mentions) == tuple(
        range(len(mentions))
    )
    if case["category"] == "unsupported":
        assert decision.outcomes == ()
        assert ids.calls == 0
        return
    assert len(decision.outcomes) == 1
    outcome = decision.outcomes[0]
    assert outcome.status is ReferenceStatus(str(case["status"]))
    assert outcome.confidence == UnitScore(str(case["confidence"]))
    assert outcome.candidate_evidence[0].rank_reason is ReferenceRankReason(
        str(case["reason"])
    )
    assert decision.blocks_generation is (
        outcome.status in {ReferenceStatus.AMBIGUOUS, ReferenceStatus.UNRESOLVED}
    )


def test_at_006_reference_resolution_isolated_sqlite(tmp_path: Path) -> None:
    connection = connect_database(apply_migrations(tmp_path / "at-006.sqlite3"))
    try:
        transactions = SQLiteTransactionBoundary(connection)
        projects = SQLiteProjectRepository(connection)
        conversations = SQLiteConversationRepository(connection)
        states = SQLiteConversationStateRepository(connection)
        messages = SQLiteMessageRepository(connection)
        entities = SQLiteEntityRepository(connection)
        runs = SQLiteProcessingRunRepository(connection)
        references = SQLiteReferenceResolutionRepository(connection)
        conversation = Conversation(
            identifier(1), None, "AT-006", NOW, NOW
        )
        source = _message("create Context for AI", number=10, sequence=0)
        declaration = _message('name "architecture"', number=11, sequence=1)
        current = _message("correct the app structure", number=12, sequence=2)
        with transactions.transaction():
            conversations.add(conversation)
            states.add(initial_conversation_state(conversation.id, updated_at=NOW))
            messages.add(source)
            messages.add(declaration)
            messages.add(current)

        project_clock = FixedClock()
        project = RegisterProjectService(
            projects=projects,
            entities=entities,
            messages=messages,
            clock=project_clock,
            id_generator=SequenceIds(100),
            transactions=transactions,
        ).execute(RegisterProjectInput("Context for AI", None, source.id))
        conversation = replace(conversation, project_id=project.project.id)
        conversations.update(conversation)
        named_clock = FixedClock()
        named = RegisterNamedItemService(
            conversations=conversations,
            projects=projects,
            entities=entities,
            messages=messages,
            clock=named_clock,
            id_generator=SequenceIds(102),
            transactions=transactions,
        ).execute(RegisterNamedItemInput(conversation.id, declaration.id, None, None))

        state = states.get(conversation.id)
        assert state is not None
        run = ProcessingRun(
            identifier(104),
            conversation.id,
            current.id,
            str(identifier(105)),
            ProcessingRunStatus.PERSISTED,
            state.version,
            "at-006",
            NOW,
            None,
        )
        runs.add(run)
        candidates = entities.list_reference_candidates(
            conversation_id=conversation.id,
            project_id=project.project.id,
        )
        mentions = DeterministicReferenceMentionExtractor().extract(
            ReferenceMentionExtractionRequest(current, (), candidates)
        )
        decision = DeterministicReferenceResolver(SequenceIds(106)).resolve(
            ReferenceResolutionRequest(
                run.id,
                current,
                (),
                state,
                mentions,
                candidates,
                (),
                NOW,
            )
        )
        references.add_all(decision.outcomes)

        assert tuple(item.surface_text for item in mentions) == ("the app",)
        outcome = decision.outcomes[0]
        assert outcome.status is ReferenceStatus.RESOLVED
        assert outcome.resolved_entity_id == project.entity.id
        assert outcome.source_message_id == source.id
        assert outcome.confidence == UnitScore("0.90")
        assert outcome.candidate_evidence[0].rank_reason is ReferenceRankReason.ACTIVE_STATE
        assert set(outcome.candidate_evidence[0].to_json_object()) == {
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
        assert references.list_for_run(run.id) == (outcome,)
        assert entities.get_named_item(named.named_item.id) == named.named_item
        assert entities.get(named.entity.id) == named.entity
        assert connection.execute("SELECT COUNT(*) FROM named_items").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM entity_registry").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM reference_resolutions").fetchone()[0] == 1
        stored = connection.execute(
            "SELECT candidate_evidence_json FROM reference_resolutions"
        ).fetchone()[0]
        assert json.loads(stored)[0]["rank_reason"] == "ACTIVE_STATE"
        assert project_clock.calls == named_clock.calls == 1
    finally:
        connection.close()


def test_at_007_task_0008_component_ambiguous_reference_blocks_without_provider() -> None:
    case = next(case for case in CASES if case["id"] == "tied-app")
    message, entities, mentions, decision, _ = _evaluate(case)

    assert tuple(item.entity_type for item in entities) == (
        EntityType.PROJECT,
        EntityType.NAMED_ITEM,
    )
    assert len(mentions) == 1
    outcome = decision.outcomes[0]
    assert outcome.status is ReferenceStatus.AMBIGUOUS
    assert outcome.confidence == UnitScore("1.00")
    assert outcome.resolved_entity_id is None
    assert outcome.source_message_id is None
    assert tuple(item.entity_type for item in outcome.candidate_evidence) == (
        EntityType.NAMED_ITEM,
        EntityType.PROJECT,
    )
    assert decision.blocks_generation is True
    assert decision.clarification_reason is ClarificationReason.AMBIGUOUS_REFERENCE
    assert decision.clarification_details is not None
    assert decision.clarification_details["mention_ordinal"] == 0
    assert decision.clarification_details["surface_text"] == "the app"
    assert decision.clarification_details["candidate_labels"] == (
        "App (named_item)",
        "App (project)",
    )
    assert tuple(inspect.signature(DeterministicReferenceResolver).parameters) == (
        "id_generator",
    )
    assert message.original_text == "fix the app"
