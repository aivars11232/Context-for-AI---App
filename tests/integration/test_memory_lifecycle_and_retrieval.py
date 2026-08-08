"""End-to-end SQLite coverage for TASK-0009 lifecycle and retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Iterator

import pytest

from context_for_ai.application.contracts import (
    CreateMemoryInput,
    EditMemoryInput,
    GetMemoryInput,
    ListMemoriesInput,
    SoftDeleteMemoryInput,
)
from context_for_ai.application.memory import (
    CreateMemoryService,
    EditMemoryService,
    GetMemoryService,
    ListMemoriesService,
    SoftDeleteMemoryService,
)
from context_for_ai.context_engine.retrieval import DeterministicContextRetriever
from context_for_ai.domain.decisions import (
    CONTEXT_PACKET_SCHEMA_VERSION,
    ContextPacket,
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.entities import Conversation, Message, Project
from context_for_ai.domain.enums import (
    MemoryEffectiveStatus,
    MemoryRevisionOperation,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MessageRole,
    ProcessingRunStatus,
    ProjectStatus,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.context import RetrievalRequest
from context_for_ai.domain.ports.errors import PersistenceError
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


BASE_TIME = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"80000000-0000-4000-8000-{number:012d}")


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
    opened = connect_database(apply_migrations(tmp_path / "task-0009.sqlite3"))
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
class ScopeFixture:
    project: Project
    conversation: Conversation
    other_project: Project
    other_conversation: Conversation
    message: Message
    run: ProcessingRun


def seed_scope(bundle: SimpleNamespace) -> ScopeFixture:
    project = Project(
        identifier(1),
        "Primary",
        None,
        ProjectStatus.ACTIVE,
        BASE_TIME,
        BASE_TIME,
    )
    other_project = Project(
        identifier(2),
        "Other",
        None,
        ProjectStatus.ACTIVE,
        BASE_TIME,
        BASE_TIME,
    )
    conversation = Conversation(
        identifier(3),
        project.id,
        "Primary conversation",
        BASE_TIME,
        BASE_TIME,
    )
    other_conversation = Conversation(
        identifier(4),
        other_project.id,
        "Other conversation",
        BASE_TIME,
        BASE_TIME,
    )
    message = Message(
        identifier(5),
        conversation.id,
        MessageRole.USER,
        "Recall SQLite guidance",
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
        "task-0009-fingerprint",
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
    return ScopeFixture(
        project,
        conversation,
        other_project,
        other_conversation,
        message,
        run,
    )


def create_input(
    *,
    conversation_id: DomainId | None,
    project_id: DomainId | None,
    scope: MemoryScope,
    content: str,
    expires_at: datetime | None = None,
    importance: str = "0.5",
) -> CreateMemoryInput:
    return CreateMemoryInput(
        conversation_id,
        project_id,
        MemoryType.PROJECT_FACT,
        scope,
        content,
        ("sqlite",),
        ("persistence",),
        UnitScore(importance),
        UnitScore("0.9"),
        expires_at,
        "Explicit integration creation",
    )


def create_memory(
    bundle: SimpleNamespace,
    *,
    id_start: int,
    at: datetime,
    conversation_id: DomainId | None,
    project_id: DomainId | None,
    scope: MemoryScope,
    content: str,
    expires_at: datetime | None = None,
    importance: str = "0.5",
) -> MemoryRecord:
    return CreateMemoryService(
        memories=bundle.memories,
        clock=FixedClock(at),
        id_generator=SequenceIds.consecutive(id_start, 3),
        transactions=bundle.transactions,
    ).execute(
        create_input(
            conversation_id=conversation_id,
            project_id=project_id,
            scope=scope,
            content=content,
            expires_at=expires_at,
            importance=importance,
        )
    ).record


def aggregate_counts(
    connection: sqlite3.Connection,
    memory_id: DomainId,
) -> tuple[int, int, int]:
    return (
        connection.execute(
            "SELECT count(*) FROM memories WHERE id = ?",
            (str(memory_id),),
        ).fetchone()[0],
        connection.execute(
            "SELECT count(*) FROM memory_sources WHERE memory_id = ?",
            (str(memory_id),),
        ).fetchone()[0],
        connection.execute(
            "SELECT count(*) FROM memory_revisions WHERE memory_id = ?",
            (str(memory_id),),
        ).fetchone()[0],
    )


def test_real_services_round_trip_history_expiry_and_deleted_restrictions(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    scope = seed_scope(bundle)
    expires_at = BASE_TIME + timedelta(hours=2)
    create_clock = FixedClock(BASE_TIME + timedelta(minutes=1))
    created = CreateMemoryService(
        memories=bundle.memories,
        clock=create_clock,
        id_generator=SequenceIds.consecutive(100, 3),
        transactions=bundle.transactions,
    ).execute(
        create_input(
            conversation_id=scope.conversation.id,
            project_id=None,
            scope=MemoryScope.CONVERSATION,
            content="Keep this exact memory",
            expires_at=expires_at,
        )
    )
    duplicate = create_memory(
        bundle,
        id_start=110,
        at=BASE_TIME + timedelta(minutes=2),
        conversation_id=scope.conversation.id,
        project_id=None,
        scope=MemoryScope.CONVERSATION,
        content=created.record.memory.content,
        expires_at=expires_at,
    )
    assert duplicate.memory.id != created.record.memory.id

    edit_time = BASE_TIME + timedelta(hours=1)
    edited = EditMemoryService(
        memories=bundle.memories,
        clock=FixedClock(edit_time),
        id_generator=SequenceIds.consecutive(103, 2),
        transactions=bundle.transactions,
    ).execute(
        EditMemoryInput(
            created.record.memory.id,
            "Keep this edited memory",
            ("sqlite", "transaction"),
            ("persistence", "history"),
            UnitScore("0.75"),
            UnitScore("0.95"),
            expires_at,
            "Explicit integration edit",
        )
    )
    assert tuple(item.operation for item in edited.record.revisions) == (
        MemoryRevisionOperation.CREATE,
        MemoryRevisionOperation.EDIT,
    )
    assert aggregate_counts(connection, edited.record.memory.id) == (1, 2, 2)

    before_expiry_read = aggregate_counts(connection, edited.record.memory.id)
    evaluation_time = expires_at
    inspected = GetMemoryService(
        memories=bundle.memories,
        clock=FixedClock(evaluation_time),
    ).execute(GetMemoryInput(edited.record.memory.id))
    listed = ListMemoriesService(
        memories=bundle.memories,
        clock=FixedClock(evaluation_time),
    ).execute(ListMemoriesInput(MemoryStatus.ACTIVE))
    assert inspected.effective_status is MemoryEffectiveStatus.EXPIRED
    assert any(
        item.record.memory.id == inspected.record.memory.id
        and item.effective_status is MemoryEffectiveStatus.EXPIRED
        for item in listed.records
    )
    assert aggregate_counts(connection, edited.record.memory.id) == before_expiry_read

    delete_time = evaluation_time + timedelta(hours=1)
    deleted = SoftDeleteMemoryService(
        memories=bundle.memories,
        clock=FixedClock(delete_time),
        id_generator=SequenceIds.consecutive(105, 2),
        transactions=bundle.transactions,
    ).execute(
        SoftDeleteMemoryInput(
            edited.record.memory.id,
            "Explicit integration deletion",
        )
    )
    assert deleted.effective_status is MemoryEffectiveStatus.DELETED
    assert deleted.record.memory.content == edited.record.memory.content
    assert tuple(item.operation for item in deleted.record.revisions) == (
        MemoryRevisionOperation.CREATE,
        MemoryRevisionOperation.EDIT,
        MemoryRevisionOperation.SOFT_DELETE,
    )
    assert aggregate_counts(connection, deleted.record.memory.id) == (1, 3, 3)
    assert bundle.memories.get(deleted.record.memory.id) == deleted.record

    with pytest.raises(LifecycleInvariantError, match="deleted again"):
        SoftDeleteMemoryService(
            memories=bundle.memories,
            clock=FixedClock(delete_time + timedelta(hours=1)),
            id_generator=SequenceIds.consecutive(120, 2),
            transactions=bundle.transactions,
        ).execute(
            SoftDeleteMemoryInput(deleted.record.memory.id, "Repeated deletion")
        )
    with pytest.raises(LifecycleInvariantError, match="cannot be edited"):
        EditMemoryService(
            memories=bundle.memories,
            clock=FixedClock(delete_time + timedelta(hours=1)),
            id_generator=SequenceIds.consecutive(122, 2),
            transactions=bundle.transactions,
        ).execute(
            EditMemoryInput(
                deleted.record.memory.id,
                "Restore attempt",
                deleted.record.memory.keywords,
                deleted.record.memory.topic_terms,
                deleted.record.memory.importance,
                deleted.record.memory.confidence,
                deleted.record.memory.expires_at,
                "Restore attempt",
            )
        )
    assert aggregate_counts(connection, deleted.record.memory.id) == (1, 3, 3)
    assert create_clock.calls == 1


def test_all_candidate_retrieval_is_pure_and_packet_evidence_round_trips(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    scope = seed_scope(bundle)
    evaluated_at = BASE_TIME + timedelta(hours=4)
    records = (
        create_memory(
            bundle,
            id_start=160,
            at=BASE_TIME + timedelta(minutes=3),
            conversation_id=None,
            project_id=None,
            scope=MemoryScope.GLOBAL,
            content="Global guidance",
        ),
        create_memory(
            bundle,
            id_start=130,
            at=BASE_TIME + timedelta(minutes=1),
            conversation_id=scope.conversation.id,
            project_id=None,
            scope=MemoryScope.CONVERSATION,
            content="Conversation guidance",
        ),
        create_memory(
            bundle,
            id_start=150,
            at=BASE_TIME + timedelta(minutes=2),
            conversation_id=None,
            project_id=scope.project.id,
            scope=MemoryScope.PROJECT,
            content="Project guidance",
        ),
        create_memory(
            bundle,
            id_start=120,
            at=BASE_TIME + timedelta(minutes=4),
            conversation_id=scope.other_conversation.id,
            project_id=None,
            scope=MemoryScope.CONVERSATION,
            content="Other conversation",
        ),
        create_memory(
            bundle,
            id_start=140,
            at=BASE_TIME + timedelta(minutes=5),
            conversation_id=None,
            project_id=scope.other_project.id,
            scope=MemoryScope.PROJECT,
            content="Other project",
        ),
        create_memory(
            bundle,
            id_start=170,
            at=BASE_TIME + timedelta(minutes=6),
            conversation_id=None,
            project_id=None,
            scope=MemoryScope.GLOBAL,
            content="Expired guidance",
            expires_at=evaluated_at,
        ),
    )
    deleted_record = create_memory(
        bundle,
        id_start=180,
        at=BASE_TIME + timedelta(minutes=7),
        conversation_id=None,
        project_id=None,
        scope=MemoryScope.GLOBAL,
        content="Deleted guidance",
    )
    deleted = SoftDeleteMemoryService(
        memories=bundle.memories,
        clock=FixedClock(BASE_TIME + timedelta(hours=1)),
        id_generator=SequenceIds.consecutive(183, 2),
        transactions=bundle.transactions,
    ).execute(
        SoftDeleteMemoryInput(deleted_record.memory.id, "Delete integration memory")
    ).record

    candidates = bundle.memories.list_retrieval_candidates()
    expected_ids = sorted(
        (record.memory.id for record in (*records, deleted)),
        key=str,
    )
    assert [record.memory.id for record in candidates] == expected_ids
    before_retrieval = candidates
    decision = DeterministicContextRetriever(
        SequenceIds.consecutive(300, len(candidates))
    ).retrieve(
        RetrievalRequest(
            identifier(250),
            scope.run.id,
            scope.message.id,
            scope.conversation.id,
            scope.project.id,
            "Persistence",
            "SQLite guidance",
            tuple(record.memory for record in reversed(candidates)),
            UnitScore("0"),
            10,
            evaluated_at,
        )
    )
    assert bundle.memories.list_retrieval_candidates() == before_retrieval
    assert {result.memory_id for result in decision.selected} == {
        records[0].memory.id,
        records[1].memory.id,
        records[2].memory.id,
    }
    exclusions = {
        item.memory_id: item.exclusion_reason for item in decision.excluded
    }
    assert exclusions[records[3].memory.id] is RetrievalExclusionReason.SCOPE_MISMATCH
    assert exclusions[records[4].memory.id] is RetrievalExclusionReason.SCOPE_MISMATCH
    assert exclusions[records[5].memory.id] is RetrievalExclusionReason.EXPIRED
    assert exclusions[deleted.memory.id] is RetrievalExclusionReason.DELETED
    assert len(decision.selected) + len(decision.excluded) == len(candidates)

    packet = ContextPacket(
        identifier(250),
        scope.run.id,
        scope.message.id,
        FrozenJsonObject({"fixture": "caller supplied"}),
        CONTEXT_PACKET_SCHEMA_VERSION,
        "prompt-policy-v1",
        scope.run.configuration_fingerprint,
        evaluated_at,
    )
    packet_record = ContextPacketRecord(
        packet,
        decision.selected,
        decision.excluded,
    )
    bundle.packets.add(packet_record)
    stored = bundle.packets.get(packet.id)
    assert stored is not None
    assert stored.packet == packet
    assert tuple(item.rank for item in stored.retrieval_results) == tuple(
        range(len(stored.retrieval_results))
    )
    assert tuple(item.memory_id for item in stored.retrieval_exclusions) == tuple(
        sorted(
            (item.memory_id for item in stored.retrieval_exclusions),
            key=str,
        )
    )
    assert tuple(item.id for item in stored.retrieval_results) == tuple(
        item.id for item in packet_record.retrieval_results
    )
    assert tuple(item.reasons for item in stored.retrieval_results) == tuple(
        item.reasons for item in packet_record.retrieval_results
    )
    assert tuple(float(item.score.value) for item in stored.retrieval_results) == tuple(
        float(item.score.value) for item in packet_record.retrieval_results
    )
    assert stored.retrieval_exclusions == packet_record.retrieval_exclusions


def test_memory_service_rolls_back_late_source_and_revision_failures(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    scope = seed_scope(bundle)
    first = create_memory(
        bundle,
        id_start=400,
        at=BASE_TIME + timedelta(minutes=1),
        conversation_id=None,
        project_id=scope.project.id,
        scope=MemoryScope.PROJECT,
        content="First",
    )
    second = create_memory(
        bundle,
        id_start=410,
        at=BASE_TIME + timedelta(minutes=2),
        conversation_id=None,
        project_id=scope.project.id,
        scope=MemoryScope.PROJECT,
        content="Second",
    )
    first_before = bundle.memories.get(first.memory.id)
    assert first_before is not None

    colliding_revision_id = second.revisions[0].id
    edit_source_id = identifier(420)
    with pytest.raises(PersistenceError):
        EditMemoryService(
            memories=bundle.memories,
            clock=FixedClock(BASE_TIME + timedelta(hours=1)),
            id_generator=SequenceIds(edit_source_id, colliding_revision_id),
            transactions=bundle.transactions,
        ).execute(
            EditMemoryInput(
                first.memory.id,
                "Must roll back",
                first.memory.keywords,
                first.memory.topic_terms,
                first.memory.importance,
                first.memory.confidence,
                first.memory.expires_at,
                "Late revision collision",
            )
        )
    assert bundle.memories.get(first.memory.id) == first_before
    assert connection.execute(
        "SELECT count(*) FROM memory_sources WHERE id = ?",
        (str(edit_source_id),),
    ).fetchone()[0] == 0

    new_memory_id = identifier(430)
    new_source_id = identifier(431)
    with pytest.raises(PersistenceError):
        CreateMemoryService(
            memories=bundle.memories,
            clock=FixedClock(BASE_TIME + timedelta(hours=2)),
            id_generator=SequenceIds(
                new_memory_id,
                new_source_id,
                colliding_revision_id,
            ),
            transactions=bundle.transactions,
        ).execute(
            create_input(
                conversation_id=None,
                project_id=scope.project.id,
                scope=MemoryScope.PROJECT,
                content="Create must roll back",
            )
        )
    assert bundle.memories.get(new_memory_id) is None
    assert connection.execute(
        "SELECT count(*) FROM memory_sources WHERE id = ?",
        (str(new_source_id),),
    ).fetchone()[0] == 0


def test_packet_insert_rolls_back_packet_result_and_late_exclusion_failure(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    scope = seed_scope(bundle)
    stored_memory = create_memory(
        bundle,
        id_start=500,
        at=BASE_TIME + timedelta(minutes=1),
        conversation_id=None,
        project_id=None,
        scope=MemoryScope.GLOBAL,
        content="Persisted memory",
    )
    packet = ContextPacket(
        identifier(510),
        scope.run.id,
        scope.message.id,
        FrozenJsonObject({}),
        CONTEXT_PACKET_SCHEMA_VERSION,
        "prompt-policy-v1",
        scope.run.configuration_fingerprint,
        BASE_TIME + timedelta(hours=1),
    )
    result = RetrievalResult(
        identifier(511),
        packet.id,
        stored_memory.memory.id,
        0,
        UnitScore("0.5"),
        (
            "project_match=0",
            "topic_match=0",
            "keyword_jaccard=0",
            "recency=1",
            "importance=0.5",
            "scope_match=0.6",
            "correction_match=0",
        ),
        packet.created_at,
    )
    missing_memory_id = identifier(999)
    exclusion = RetrievalExclusion(
        identifier(512),
        packet.id,
        missing_memory_id,
        RetrievalExclusionReason.SCOPE_MISMATCH,
        None,
        FrozenJsonObject(
            {
                "scope": MemoryScope.CONVERSATION.value,
                "request_conversation_id": str(scope.conversation.id),
                "request_project_id": str(scope.project.id),
                "memory_conversation_id": str(scope.other_conversation.id),
                "memory_project_id": None,
            }
        ),
        packet.created_at,
    )

    with pytest.raises(PersistenceError):
        bundle.packets.add(ContextPacketRecord(packet, (result,), (exclusion,)))

    assert bundle.packets.get(packet.id) is None
    assert connection.execute(
        "SELECT count(*) FROM retrieval_results WHERE context_packet_id = ?",
        (str(packet.id),),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM retrieval_exclusions WHERE context_packet_id = ?",
        (str(packet.id),),
    ).fetchone()[0] == 0
