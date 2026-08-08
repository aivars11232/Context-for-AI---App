"""TASK-0009-owned deterministic component passes for AT-008 and AT-014."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Iterator

import pytest

import context_for_ai.application as application
from context_for_ai.application import (
    CreateMemoryInput,
    CreateMemoryService,
    EditMemoryInput,
    EditMemoryService,
    GetMemoryInput,
    GetMemoryService,
    ListMemoriesInput,
    ListMemoriesService,
    SoftDeleteMemoryInput,
    SoftDeleteMemoryService,
)
from context_for_ai.context_engine import DeterministicContextRetriever
from context_for_ai.context_engine.prompt_rendering import _plan_initial
from context_for_ai.domain import MEMORY_REVISION_SCHEMA_VERSION
from context_for_ai.domain.decisions import (
    CONTEXT_PACKET_SCHEMA_VERSION,
    PROMPT_POLICY_VERSION,
    ContextPacket,
    RetrievalResult,
)
from context_for_ai.domain.entities import Conversation, Memory, Message, Project
from context_for_ai.domain.enums import (
    MemoryEffectiveStatus,
    MemoryRevisionOperation,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    MessageRole,
    ProcessingRunStatus,
    ProjectStatus,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.context import ContextBudgetExceeded, RetrievalRequest
from context_for_ai.domain.ports.records import ContextPacketRecord, MemoryRecord
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore
from context_for_ai.infrastructure.database import (
    SQLiteContextPacketRepository,
    SQLiteConversationRepository,
    SQLiteMemoryRepository,
    SQLiteMessageRepository,
    SQLiteProcessingRunRepository,
    SQLiteProjectRepository,
    SQLiteTransactionBoundary,
    apply_migrations,
    connect_database,
)


FIXTURE_VERSION = "task-0009-deterministic-v1"
BASE_TIME = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
EVALUATED_AT = BASE_TIME + timedelta(days=100)


def identifier(number: int) -> DomainId:
    return DomainId(f"90000000-0000-4000-8000-{number:012d}")


def caller_packet_fixture(
    *,
    packet_id: DomainId,
    run: ProcessingRun,
    message: Message,
    created_at: datetime,
    results: tuple[RetrievalResult, ...],
    memories: tuple[Memory, ...],
) -> ContextPacket:
    assert tuple(value.memory_id for value in results) == tuple(
        value.id for value in memories
    )
    confidence = Decimal("1") if not results else results[0].score.value
    payload: dict[str, object] = {
        "schema_version": CONTEXT_PACKET_SCHEMA_VERSION,
        "trace": {
            "processing_run_id": str(run.id),
            "conversation_id": str(run.conversation_id),
            "user_message_id": str(message.id),
            "state_version": 0,
            "configuration_fingerprint": run.configuration_fingerprint,
        },
        "request": {
            "original_text": message.original_text,
            "intent": "ANSWER",
            "intent_rule_id": "task-0009-fixture",
            "expected_output_type": "TEXT_ANSWER",
            "qualifiers": (),
            "confidence": confidence,
        },
        "active_state": {
            "project_id": None,
            "topic_id": None,
            "task_id": None,
            "previous_task_id": None,
            "topic_stack": (),
        },
        "validation_context": {
            "rule_set_version": "fixture-validation-v1",
            "active_topic": None,
            "output_shape_rule": {
                "id": "fixture-shape-answer",
                "output_type": "TEXT_ANSWER",
                "shape": "NON_EMPTY_TEXT",
            },
            "preserve_change_verb_list_id": "fixture-preserve-v1",
            "preserve_change_verbs": ("change",),
            "action_markers": ("TOOL_CALL:",),
        },
        "references": (),
        "constraints": (),
        "retrieval": tuple(
            {
                "memory_id": str(memory.id),
                "content": memory.content,
                "score": result.score.value,
                "rank": result.rank,
                "reasons": result.reasons,
                "scope": memory.scope.value,
                "confidence": memory.confidence.value,
            }
            for result, memory in zip(results, memories, strict=True)
        ),
        "confidence": {
            "interpretation": confidence,
            "references": None,
            "retrieval": None if not results else results[0].score.value,
            "overall": confidence,
        },
        "response_policy": {
            "output_type": "TEXT_ANSWER",
            "validate_before_display": True,
            "text_only": True,
            "no_actions": True,
            "streaming": False,
            "correction_limit": 2,
            "model_generation_limit": 3,
            "absolute_model_generation_cap": 3,
        },
        "rendering": {
            "prompt_policy_version": PROMPT_POLICY_VERSION,
            "token_estimator": "conservative_utf8_v1",
            "token_budget": 10000,
            "mandatory_estimated_tokens": 0,
            "estimated_prompt_tokens": 0,
            "included_sections": (),
            "omitted_sections": (),
        },
    }
    plan = _plan_initial(
        context_packet_id=packet_id,
        packet_json=FrozenJsonObject(payload),
        effective_budget=10000,
    )
    assert not isinstance(plan, ContextBudgetExceeded)
    payload["rendering"] = plan.metadata.to_json_object()
    return ContextPacket(
        packet_id,
        run.id,
        message.id,
        FrozenJsonObject(payload),
        CONTEXT_PACKET_SCHEMA_VERSION,
        PROMPT_POLICY_VERSION,
        run.configuration_fingerprint,
        created_at,
    )


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class SequenceIds:
    def __init__(self, *values: DomainId) -> None:
        self.values = list(values)
        self.calls: list[DomainId] = []

    @classmethod
    def consecutive(cls, start: int, count: int) -> SequenceIds:
        return cls(*(identifier(number) for number in range(start, start + count)))

    def new_id(self) -> DomainId:
        value = self.values.pop(0)
        self.calls.append(value)
        return value


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    opened = connect_database(
        apply_migrations(tmp_path / f"{FIXTURE_VERSION}.sqlite3")
    )
    try:
        yield opened
    finally:
        opened.close()


def repositories(connection: sqlite3.Connection) -> SimpleNamespace:
    return SimpleNamespace(
        transactions=SQLiteTransactionBoundary(connection),
        projects=SQLiteProjectRepository(connection),
        conversations=SQLiteConversationRepository(connection),
        messages=SQLiteMessageRepository(connection),
        runs=SQLiteProcessingRunRepository(connection),
        memories=SQLiteMemoryRepository(connection),
        packets=SQLiteContextPacketRepository(connection),
    )


@dataclass(frozen=True, slots=True)
class FixedScope:
    project: Project
    conversation: Conversation
    other_project: Project
    other_conversation: Conversation
    message: Message
    run: ProcessingRun


def seed_scope(bundle: SimpleNamespace) -> FixedScope:
    project = Project(
        identifier(1),
        "Context for AI",
        None,
        ProjectStatus.ACTIVE,
        BASE_TIME,
        BASE_TIME,
    )
    other_project = Project(
        identifier(2),
        "Other project",
        None,
        ProjectStatus.ACTIVE,
        BASE_TIME,
        BASE_TIME,
    )
    conversation = Conversation(
        identifier(3),
        project.id,
        "AT-008",
        BASE_TIME,
        BASE_TIME,
    )
    other_conversation = Conversation(
        identifier(4),
        other_project.id,
        "Other",
        BASE_TIME,
        BASE_TIME,
    )
    message = Message(
        identifier(5),
        conversation.id,
        MessageRole.USER,
        "Use SQLite guidance",
        BASE_TIME,
        0,
    )
    run = ProcessingRun(
        identifier(6),
        conversation.id,
        message.id,
        str(identifier(7)),
        ProcessingRunStatus.PERSISTED,
        0,
        FIXTURE_VERSION,
        BASE_TIME,
        None,
    )
    with bundle.transactions.transaction():
        bundle.projects.add(project)
        bundle.projects.add(other_project)
        bundle.conversations.add(conversation)
        bundle.conversations.add(other_conversation)
        bundle.messages.add(message)
        bundle.runs.add(run)
    return FixedScope(
        project,
        conversation,
        other_project,
        other_conversation,
        message,
        run,
    )


def create_input(
    *,
    scope: MemoryScope,
    content: str,
    conversation_id: DomainId | None = None,
    project_id: DomainId | None = None,
    memory_type: MemoryType = MemoryType.PROJECT_FACT,
    keywords: tuple[str, ...] = (),
    topic_terms: tuple[str, ...] = (),
    importance: str = "0.5",
    expires_at: datetime | None = None,
) -> CreateMemoryInput:
    return CreateMemoryInput(
        conversation_id,
        project_id,
        memory_type,
        scope,
        content,
        keywords,
        topic_terms,
        UnitScore(importance),
        UnitScore("0.9"),
        expires_at,
        "Explicit deterministic fixture",
    )


def persist_memory(
    bundle: SimpleNamespace,
    *,
    id_start: int,
    at: datetime,
    scope: MemoryScope,
    content: str,
    conversation_id: DomainId | None = None,
    project_id: DomainId | None = None,
    memory_type: MemoryType = MemoryType.PROJECT_FACT,
    keywords: tuple[str, ...] = (),
    topic_terms: tuple[str, ...] = (),
    importance: str = "0.5",
    expires_at: datetime | None = None,
) -> MemoryRecord:
    return CreateMemoryService(
        memories=bundle.memories,
        clock=FixedClock(at),
        id_generator=SequenceIds.consecutive(id_start, 3),
        transactions=bundle.transactions,
    ).execute(
        create_input(
            scope=scope,
            content=content,
            conversation_id=conversation_id,
            project_id=project_id,
            memory_type=memory_type,
            keywords=keywords,
            topic_terms=topic_terms,
            importance=importance,
            expires_at=expires_at,
        )
    ).record


def direct_memory(
    number: int,
    *,
    scope: MemoryScope,
    content: str,
    importance: str,
    updated_at: datetime,
    conversation_id: DomainId | None = None,
    project_id: DomainId | None = None,
    memory_type: MemoryType = MemoryType.PROJECT_FACT,
    keywords: tuple[str, ...] = (),
    topic_terms: tuple[str, ...] = (),
) -> Memory:
    return Memory(
        identifier(number),
        conversation_id,
        project_id,
        memory_type,
        scope,
        MemoryStatus.ACTIVE,
        content,
        keywords,
        topic_terms,
        UnitScore(importance),
        UnitScore("1"),
        None,
        EVALUATED_AT - timedelta(days=365),
        updated_at,
        None,
    )


def test_at_008_retrieval_matrix_persists_caller_packet_without_mutation(
    connection: sqlite3.Connection,
) -> None:
    assert FIXTURE_VERSION == "task-0009-deterministic-v1"
    bundle = repositories(connection)
    scope = seed_scope(bundle)
    project_memory = persist_memory(
        bundle,
        id_start=100,
        at=EVALUATED_AT,
        scope=MemoryScope.PROJECT,
        project_id=scope.project.id,
        content="Project guidance",
        keywords=("sqlite",),
        importance="0.9",
    )
    conversation_memory = persist_memory(
        bundle,
        id_start=110,
        at=EVALUATED_AT,
        scope=MemoryScope.CONVERSATION,
        conversation_id=scope.conversation.id,
        content="Conversation guidance",
        keywords=("sqlite",),
        importance="0.9",
    )
    retained = persist_memory(
        bundle,
        id_start=120,
        at=EVALUATED_AT,
        scope=MemoryScope.GLOBAL,
        content="Same-memory!",
        keywords=("sqlite",),
        importance="1",
    )
    duplicate = persist_memory(
        bundle,
        id_start=130,
        at=EVALUATED_AT,
        scope=MemoryScope.GLOBAL,
        content="samememory",
        keywords=("sqlite",),
        importance="0.8",
    )
    threshold_equal = persist_memory(
        bundle,
        id_start=140,
        at=EVALUATED_AT - timedelta(days=90),
        scope=MemoryScope.GLOBAL,
        content="Threshold equality",
        importance="0.5",
    )
    limit_exceeded = persist_memory(
        bundle,
        id_start=150,
        at=EVALUATED_AT - timedelta(days=90),
        scope=MemoryScope.GLOBAL,
        content="Limit exclusion",
        importance="0.5",
    )
    below_threshold = persist_memory(
        bundle,
        id_start=160,
        at=EVALUATED_AT - timedelta(days=90),
        scope=MemoryScope.GLOBAL,
        content="Below threshold",
        importance="0",
    )
    cross_conversation = persist_memory(
        bundle,
        id_start=170,
        at=EVALUATED_AT,
        scope=MemoryScope.CONVERSATION,
        conversation_id=scope.other_conversation.id,
        content="Cross conversation",
        keywords=("sqlite",),
        importance="1",
    )
    cross_project = persist_memory(
        bundle,
        id_start=180,
        at=EVALUATED_AT,
        scope=MemoryScope.PROJECT,
        project_id=scope.other_project.id,
        content="Cross project",
        keywords=("sqlite",),
        importance="1",
    )
    expired = persist_memory(
        bundle,
        id_start=190,
        at=EVALUATED_AT,
        scope=MemoryScope.GLOBAL,
        content="Expired",
        expires_at=EVALUATED_AT,
    )
    deleted_source = persist_memory(
        bundle,
        id_start=200,
        at=EVALUATED_AT,
        scope=MemoryScope.GLOBAL,
        content="Deleted",
    )
    deleted = SoftDeleteMemoryService(
        memories=bundle.memories,
        clock=FixedClock(EVALUATED_AT),
        id_generator=SequenceIds.consecutive(203, 2),
        transactions=bundle.transactions,
    ).execute(
        SoftDeleteMemoryInput(deleted_source.memory.id, "Explicit deletion")
    ).record

    considered_records = bundle.memories.list_retrieval_candidates()
    before = considered_records
    evidence_ids = SequenceIds.consecutive(300, len(considered_records))
    request = RetrievalRequest(
        identifier(250),
        scope.run.id,
        scope.message.id,
        scope.conversation.id,
        scope.project.id,
        None,
        "sqlite",
        tuple(record.memory for record in reversed(considered_records)),
        UnitScore("0.08"),
        4,
        EVALUATED_AT,
    )
    decision = DeterministicContextRetriever(evidence_ids).retrieve(request)

    assert bundle.memories.list_retrieval_candidates() == before
    assert tuple(item.rank for item in decision.selected) == (0, 1, 2, 3)
    assert tuple(item.memory_id for item in decision.selected) == (
        project_memory.memory.id,
        conversation_memory.memory.id,
        retained.memory.id,
        threshold_equal.memory.id,
    )
    assert decision.selected[0].score == UnitScore("0.73")
    assert decision.selected[-1].score == UnitScore("0.08")
    assert all(len(item.reasons) == 7 for item in decision.selected)
    assert decision.selected[0].reasons == (
        "project_match=1",
        "topic_match=0",
        "keyword_jaccard=1",
        "recency=1",
        "importance=0.9",
        "scope_match=0.8",
        "correction_match=0",
    )
    exclusion_by_memory = {
        item.memory_id: item for item in decision.excluded
    }
    assert exclusion_by_memory[cross_conversation.memory.id].exclusion_reason is (
        RetrievalExclusionReason.SCOPE_MISMATCH
    )
    assert exclusion_by_memory[cross_project.memory.id].exclusion_reason is (
        RetrievalExclusionReason.SCOPE_MISMATCH
    )
    assert exclusion_by_memory[deleted.memory.id].exclusion_reason is (
        RetrievalExclusionReason.DELETED
    )
    assert exclusion_by_memory[expired.memory.id].exclusion_reason is (
        RetrievalExclusionReason.EXPIRED
    )
    assert exclusion_by_memory[below_threshold.memory.id].exclusion_reason is (
        RetrievalExclusionReason.SCORE_BELOW_THRESHOLD
    )
    assert exclusion_by_memory[duplicate.memory.id].exclusion_reason is (
        RetrievalExclusionReason.DUPLICATE_CONTENT
    )
    assert exclusion_by_memory[limit_exceeded.memory.id].exclusion_reason is (
        RetrievalExclusionReason.LIMIT_EXCEEDED
    )
    assert {
        item.exclusion_reason for item in decision.excluded
    } == set(RetrievalExclusionReason)
    assert len(decision.selected) + len(decision.excluded) == len(considered_records)
    assert evidence_ids.calls == [
        identifier(number)
        for number in range(300, 300 + len(considered_records))
    ]

    memory_by_id = {value.memory.id: value.memory for value in considered_records}
    packet = caller_packet_fixture(
        packet_id=request.context_packet_id,
        run=scope.run,
        message=scope.message,
        created_at=EVALUATED_AT,
        results=decision.selected,
        memories=tuple(memory_by_id[value.memory_id] for value in decision.selected),
    )
    packet_record = ContextPacketRecord(packet, decision.selected, decision.excluded)
    bundle.packets.add(packet_record)
    stored = bundle.packets.get(packet.id)
    assert stored is not None
    assert stored.packet == packet
    assert tuple(item.memory_id for item in stored.retrieval_results) == tuple(
        item.memory_id for item in decision.selected
    )
    assert tuple(item.reasons for item in stored.retrieval_results) == tuple(
        item.reasons for item in decision.selected
    )
    assert tuple(float(item.score.value) for item in stored.retrieval_results) == tuple(
        float(item.score.value) for item in decision.selected
    )
    assert stored.retrieval_exclusions == decision.excluded
    assert bundle.memories.list_retrieval_candidates() == before


def test_at_008_repeating_decimal_and_total_tie_breaking_are_exact() -> None:
    correction = direct_memory(
        400,
        scope=MemoryScope.PROJECT,
        project_id=identifier(20),
        conversation_id=identifier(21),
        content="Correction",
        importance="0.8",
        updated_at=EVALUATED_AT,
        memory_type=MemoryType.CORRECTION_RULE,
        keywords=("sqlite transactions",),
        topic_terms=("persistence",),
    )
    exact = DeterministicContextRetriever(SequenceIds.consecutive(500, 1)).retrieve(
        RetrievalRequest(
            identifier(501),
            identifier(502),
            identifier(503),
            identifier(21),
            identifier(20),
            "persistence",
            "sqlite safe",
            (correction,),
            UnitScore("0"),
            1,
            EVALUATED_AT,
        )
    )
    assert exact.selected[0].score.value == Decimal(
        "0.8366666666666666666666666667"
    )
    assert exact.selected[0].reasons[2] == (
        "keyword_jaccard=0.3333333333333333333333333333"
    )

    global_higher_importance = direct_memory(
        410,
        scope=MemoryScope.GLOBAL,
        content="Global",
        importance="0.7",
        updated_at=EVALUATED_AT,
    )
    conversation_lower_importance = direct_memory(
        411,
        scope=MemoryScope.CONVERSATION,
        conversation_id=identifier(21),
        content="Conversation",
        importance="0.5",
        updated_at=EVALUATED_AT,
    )
    newer = direct_memory(
        412,
        scope=MemoryScope.GLOBAL,
        content="Newer",
        importance="0.5",
        updated_at=EVALUATED_AT - timedelta(days=100),
    )
    smaller_uuid = direct_memory(
        413,
        scope=MemoryScope.GLOBAL,
        content="Smaller UUID",
        importance="0.5",
        updated_at=EVALUATED_AT - timedelta(days=100),
    )
    larger_uuid = direct_memory(
        414,
        scope=MemoryScope.GLOBAL,
        content="Larger UUID",
        importance="0.5",
        updated_at=EVALUATED_AT - timedelta(days=100),
    )
    older = direct_memory(
        415,
        scope=MemoryScope.GLOBAL,
        content="Older",
        importance="0.5",
        updated_at=EVALUATED_AT - timedelta(days=120),
    )
    tied = DeterministicContextRetriever(
        SequenceIds.consecutive(520, 6)
    ).retrieve(
        RetrievalRequest(
            identifier(519),
            identifier(502),
            identifier(503),
            identifier(21),
            identifier(20),
            None,
            "",
            (
                older,
                larger_uuid,
                conversation_lower_importance,
                smaller_uuid,
                global_higher_importance,
                newer,
            ),
            UnitScore("0"),
            6,
            EVALUATED_AT,
        )
    )
    assert tied.selected[0].score == tied.selected[1].score == UnitScore("0.2")
    assert tuple(item.memory_id for item in tied.selected) == (
        global_higher_importance.id,
        conversation_lower_importance.id,
        newer.id,
        smaller_uuid.id,
        larger_uuid.id,
        older.id,
    )


def test_at_014_manual_lifecycle_history_expiry_and_tombstone(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    scope = seed_scope(bundle)
    expires_at = BASE_TIME + timedelta(hours=2)
    create_clock = FixedClock(BASE_TIME)
    created = CreateMemoryService(
        memories=bundle.memories,
        clock=create_clock,
        id_generator=SequenceIds.consecutive(600, 3),
        transactions=bundle.transactions,
    ).execute(
        create_input(
            scope=MemoryScope.PROJECT,
            project_id=scope.project.id,
            content="Manual memory",
            keywords=("manual",),
            topic_terms=("lifecycle",),
            importance="0.5",
            expires_at=expires_at,
        )
    )
    duplicate = persist_memory(
        bundle,
        id_start=610,
        at=BASE_TIME + timedelta(minutes=1),
        scope=MemoryScope.PROJECT,
        project_id=scope.project.id,
        content=created.record.memory.content,
        keywords=created.record.memory.keywords,
        topic_terms=created.record.memory.topic_terms,
        importance="0.5",
        expires_at=expires_at,
    )
    assert duplicate.memory.id != created.record.memory.id

    edit_time = BASE_TIME + timedelta(hours=1)
    edited = EditMemoryService(
        memories=bundle.memories,
        clock=FixedClock(edit_time),
        id_generator=SequenceIds.consecutive(603, 2),
        transactions=bundle.transactions,
    ).execute(
        EditMemoryInput(
            created.record.memory.id,
            "Edited manual memory",
            ("manual", "edited"),
            ("lifecycle",),
            UnitScore("0.75"),
            UnitScore("0.95"),
            expires_at,
            "Explicit edit",
        )
    )
    assert tuple(item.source_kind for item in edited.record.sources) == (
        MemorySourceKind.MANUAL_ENTRY,
        MemorySourceKind.USER_EDIT,
    )
    assert tuple(item.operation for item in edited.record.revisions) == (
        MemoryRevisionOperation.CREATE,
        MemoryRevisionOperation.EDIT,
    )
    assert tuple(item.revision_number for item in edited.record.revisions) == (1, 2)
    assert all(
        item.metadata["schema_version"] == MEMORY_REVISION_SCHEMA_VERSION
        and item.metadata["source_id"]
        == str(
            next(
                source.id
                for source in edited.record.sources
                if str(source.id) == item.metadata["source_id"]
            )
        )
        for item in edited.record.revisions
    )

    counts_before_expiry = connection.execute(
        """
        SELECT
          (SELECT count(*) FROM memory_sources WHERE memory_id = ?),
          (SELECT count(*) FROM memory_revisions WHERE memory_id = ?)
        """,
        (str(edited.record.memory.id), str(edited.record.memory.id)),
    ).fetchone()
    inspected = GetMemoryService(
        memories=bundle.memories,
        clock=FixedClock(expires_at),
    ).execute(GetMemoryInput(edited.record.memory.id))
    listed = ListMemoriesService(
        memories=bundle.memories,
        clock=FixedClock(expires_at),
    ).execute(ListMemoriesInput(MemoryStatus.ACTIVE))
    counts_after_expiry = connection.execute(
        """
        SELECT
          (SELECT count(*) FROM memory_sources WHERE memory_id = ?),
          (SELECT count(*) FROM memory_revisions WHERE memory_id = ?)
        """,
        (str(edited.record.memory.id), str(edited.record.memory.id)),
    ).fetchone()
    assert inspected.record.memory.status is MemoryStatus.ACTIVE
    assert inspected.effective_status is MemoryEffectiveStatus.EXPIRED
    assert any(
        item.record.memory.id == inspected.record.memory.id
        and item.effective_status is MemoryEffectiveStatus.EXPIRED
        for item in listed.records
    )
    assert tuple(counts_after_expiry) == tuple(counts_before_expiry) == (2, 2)

    delete_time = expires_at + timedelta(hours=1)
    deleted = SoftDeleteMemoryService(
        memories=bundle.memories,
        clock=FixedClock(delete_time),
        id_generator=SequenceIds.consecutive(605, 2),
        transactions=bundle.transactions,
    ).execute(
        SoftDeleteMemoryInput(edited.record.memory.id, "Explicit soft delete")
    )
    assert deleted.record.memory.status is MemoryStatus.DELETED
    assert deleted.record.memory.deleted_at == delete_time
    assert deleted.record.memory.content == edited.record.memory.content
    assert deleted.effective_status is MemoryEffectiveStatus.DELETED
    assert tuple(item.revision_number for item in deleted.record.revisions) == (1, 2, 3)
    assert deleted.record.revisions[-1].operation is (
        MemoryRevisionOperation.SOFT_DELETE
    )
    assert connection.execute(
        "SELECT count(*) FROM memory_sources WHERE memory_id = ?",
        (str(deleted.record.memory.id),),
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT count(*) FROM memory_revisions WHERE memory_id = ?",
        (str(deleted.record.memory.id),),
    ).fetchone()[0] == 3

    with pytest.raises(LifecycleInvariantError, match="cannot be edited"):
        EditMemoryService(
            memories=bundle.memories,
            clock=FixedClock(delete_time + timedelta(hours=1)),
            id_generator=SequenceIds.consecutive(620, 2),
            transactions=bundle.transactions,
        ).execute(
            EditMemoryInput(
                deleted.record.memory.id,
                "Restore",
                deleted.record.memory.keywords,
                deleted.record.memory.topic_terms,
                deleted.record.memory.importance,
                deleted.record.memory.confidence,
                deleted.record.memory.expires_at,
                "Restore",
            )
        )
    with pytest.raises(LifecycleInvariantError, match="deleted again"):
        SoftDeleteMemoryService(
            memories=bundle.memories,
            clock=FixedClock(delete_time + timedelta(hours=1)),
            id_generator=SequenceIds.consecutive(622, 2),
            transactions=bundle.transactions,
        ).execute(
            SoftDeleteMemoryInput(deleted.record.memory.id, "Again")
        )
    assert not hasattr(application, "RestoreMemoryService")
    assert create_clock.calls == 1
