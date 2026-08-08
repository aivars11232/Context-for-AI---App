"""Focused unit tests for explicit TASK-0009 manual-memory services."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
from context_for_ai.domain.entities import Memory, MemoryRevision, MemorySource
from context_for_ai.domain.enums import (
    MemoryEffectiveStatus,
    MemoryRevisionOperation,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import memory_revision_metadata
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.ports.records import MemoryRecord
from context_for_ai.domain.value_objects import DomainId, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"60000000-0000-4000-8000-{number:012d}")


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

    def new_id(self) -> DomainId:
        value = self.values.pop(0)
        self.calls.append(value)
        return value


class MemoryRepository:
    def __init__(self) -> None:
        self.records: dict[DomainId, MemoryRecord] = {}
        self.get_calls: list[DomainId] = []
        self.list_calls: list[MemoryStatus] = []
        self.fail_after_add = False
        self.fail_after_update = False

    def add(
        self,
        memory: Memory,
        source: MemorySource,
        revision: MemoryRevision,
    ) -> None:
        self.records[memory.id] = MemoryRecord(
            memory,
            (source,),
            (revision,),
        )
        if self.fail_after_add:
            raise PersistenceError("Injected memory add failure.")

    def get(self, memory_id: DomainId) -> MemoryRecord | None:
        self.get_calls.append(memory_id)
        return self.records.get(memory_id)

    def list_by_status(self, status: MemoryStatus) -> tuple[MemoryRecord, ...]:
        self.list_calls.append(status)
        records = sorted(
            (
                record
                for record in self.records.values()
                if record.memory.status is status
            ),
            key=lambda record: str(record.memory.id),
        )
        records.sort(key=lambda record: record.memory.updated_at, reverse=True)
        return tuple(records)

    def list_retrieval_candidates(self) -> tuple[MemoryRecord, ...]:
        raise AssertionError("Manual create must not perform duplicate lookup.")

    def update_with_revision(
        self,
        memory: Memory,
        source: MemorySource,
        revision: MemoryRevision,
    ) -> None:
        current = self.records[memory.id]
        sources = tuple(
            sorted(
                (*current.sources, source),
                key=lambda item: (item.created_at, str(item.id)),
            )
        )
        revisions = (*current.revisions, revision)
        self.records[memory.id] = MemoryRecord(memory, sources, revisions)
        if self.fail_after_update:
            raise PersistenceError("Injected memory update failure.")

    def capture(self) -> dict[DomainId, MemoryRecord]:
        return dict(self.records)

    def restore(self, snapshot: dict[DomainId, MemoryRecord]) -> None:
        self.records = snapshot


class RollbackTransactions:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository
        self.entries = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.entries += 1
        snapshot = self.repository.capture()
        try:
            yield
        except BaseException:
            self.repository.restore(snapshot)
            raise


def create_input(
    *,
    content: str = "Remember SQLite transactions",
    expires_at: datetime | None = None,
) -> CreateMemoryInput:
    return CreateMemoryInput(
        identifier(90),
        None,
        MemoryType.PROJECT_FACT,
        MemoryScope.CONVERSATION,
        content,
        ("SQLite", "transaction"),
        ("Persistence",),
        UnitScore("0.75"),
        UnitScore("0.9"),
        expires_at,
        "Created explicitly",
    )


def create_memory(
    repository: MemoryRepository,
    *,
    memory_id: int = 1,
    at: datetime = NOW,
    expires_at: datetime | None = None,
) -> MemoryRecord:
    result = CreateMemoryService(
        memories=repository,
        clock=FixedClock(at),
        id_generator=SequenceIds(
            identifier(memory_id),
            identifier(memory_id + 100),
            identifier(memory_id + 200),
        ),
        transactions=RollbackTransactions(repository),
    ).execute(create_input(content=f"Memory {memory_id}", expires_at=expires_at))
    return result.record


def test_create_writes_one_canonical_aggregate_and_reloads_it() -> None:
    repository = MemoryRepository()
    clock = FixedClock(NOW)
    ids = SequenceIds(identifier(1), identifier(2), identifier(3))
    transactions = RollbackTransactions(repository)

    output = CreateMemoryService(
        memories=repository,
        clock=clock,
        id_generator=ids,
        transactions=transactions,
    ).execute(create_input())

    memory = output.record.memory
    source = output.record.sources[0]
    revision = output.record.revisions[0]
    assert memory.id == identifier(1)
    assert memory.status is MemoryStatus.ACTIVE
    assert memory.created_at == memory.updated_at == NOW
    assert memory.deleted_at is None
    assert source.id == identifier(2)
    assert source.source_kind is MemorySourceKind.MANUAL_ENTRY
    assert source.source_message_id is None
    assert source.created_at == NOW
    assert revision.id == identifier(3)
    assert revision.revision_number == 1
    assert revision.operation is MemoryRevisionOperation.CREATE
    assert revision.metadata == memory_revision_metadata(memory, source.id)
    assert revision.created_at == NOW
    assert output.evaluated_at == NOW
    assert output.effective_status is MemoryEffectiveStatus.ACTIVE
    assert repository.get_calls == [memory.id]
    assert clock.calls == 1
    assert ids.calls == [
        identifier(1),
        identifier(2),
        identifier(3),
    ]
    assert transactions.entries == 1


def test_edit_replaces_only_editable_fields_and_appends_history() -> None:
    repository = MemoryRepository()
    original = create_memory(repository)
    update_time = NOW + timedelta(hours=1)
    clock = FixedClock(update_time)
    ids = SequenceIds(identifier(4), identifier(5))

    output = EditMemoryService(
        memories=repository,
        clock=clock,
        id_generator=ids,
        transactions=RollbackTransactions(repository),
    ).execute(
        EditMemoryInput(
            original.memory.id,
            "Edited memory",
            ("edited",),
            ("new topic",),
            UnitScore("0.8"),
            UnitScore("0.95"),
            NOW + timedelta(days=30),
            "Explicit correction",
        )
    )

    edited = output.record.memory
    assert (
        edited.id,
        edited.created_at,
        edited.memory_type,
        edited.scope,
        edited.conversation_id,
        edited.project_id,
    ) == (
        original.memory.id,
        original.memory.created_at,
        original.memory.memory_type,
        original.memory.scope,
        original.memory.conversation_id,
        original.memory.project_id,
    )
    assert edited.content == "Edited memory"
    assert edited.keywords == ("edited",)
    assert edited.topic_terms == ("new topic",)
    assert edited.updated_at == update_time
    assert edited.status is MemoryStatus.ACTIVE
    assert tuple(source.source_kind for source in output.record.sources) == (
        MemorySourceKind.MANUAL_ENTRY,
        MemorySourceKind.USER_EDIT,
    )
    revision = output.record.revisions[-1]
    assert revision.revision_number == 2
    assert revision.operation is MemoryRevisionOperation.EDIT
    assert revision.metadata == memory_revision_metadata(
        edited,
        output.record.sources[-1].id,
    )
    assert output.record.sources[-1].created_at == revision.created_at == update_time
    assert clock.calls == 1
    assert ids.calls == [identifier(4), identifier(5)]


def test_soft_delete_preserves_content_and_rejects_later_mutation() -> None:
    repository = MemoryRepository()
    original = create_memory(repository)
    delete_time = NOW + timedelta(hours=1)
    clock = FixedClock(delete_time)

    output = SoftDeleteMemoryService(
        memories=repository,
        clock=clock,
        id_generator=SequenceIds(identifier(4), identifier(5)),
        transactions=RollbackTransactions(repository),
    ).execute(SoftDeleteMemoryInput(original.memory.id, "No longer needed"))

    deleted = output.record.memory
    assert deleted.status is MemoryStatus.DELETED
    assert deleted.deleted_at == deleted.updated_at == delete_time
    assert (
        deleted.content,
        deleted.keywords,
        deleted.topic_terms,
        deleted.importance,
        deleted.confidence,
        deleted.expires_at,
    ) == (
        original.memory.content,
        original.memory.keywords,
        original.memory.topic_terms,
        original.memory.importance,
        original.memory.confidence,
        original.memory.expires_at,
    )
    assert output.record.revisions[-1].operation is MemoryRevisionOperation.SOFT_DELETE
    assert output.effective_status is MemoryEffectiveStatus.DELETED
    assert clock.calls == 1

    unchanged = repository.records[deleted.id]
    repeated_clock = FixedClock(delete_time + timedelta(hours=1))
    repeated_ids = SequenceIds(identifier(6), identifier(7))
    with pytest.raises(LifecycleInvariantError, match="deleted again"):
        SoftDeleteMemoryService(
            memories=repository,
            clock=repeated_clock,
            id_generator=repeated_ids,
            transactions=RollbackTransactions(repository),
        ).execute(SoftDeleteMemoryInput(deleted.id, "Again"))
    with pytest.raises(LifecycleInvariantError, match="cannot be edited"):
        EditMemoryService(
            memories=repository,
            clock=repeated_clock,
            id_generator=repeated_ids,
            transactions=RollbackTransactions(repository),
        ).execute(
            EditMemoryInput(
                deleted.id,
                deleted.content,
                deleted.keywords,
                deleted.topic_terms,
                deleted.importance,
                deleted.confidence,
                deleted.expires_at,
                "Restore attempt",
            )
        )
    assert repository.records[deleted.id] == unchanged
    assert repeated_clock.calls == 0
    assert repeated_ids.calls == []


def test_get_and_stored_status_list_use_one_read_only_query_time() -> None:
    repository = MemoryRepository()
    first = create_memory(
        repository,
        memory_id=10,
        at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )
    second = create_memory(
        repository,
        memory_id=20,
        at=NOW + timedelta(minutes=15),
    )
    evaluated_at = NOW + timedelta(hours=1)
    snapshot = repository.capture()

    get_clock = FixedClock(evaluated_at)
    inspected = GetMemoryService(memories=repository, clock=get_clock).execute(
        GetMemoryInput(first.memory.id)
    )
    list_clock = FixedClock(evaluated_at)
    listed = ListMemoriesService(memories=repository, clock=list_clock).execute(
        ListMemoriesInput(MemoryStatus.ACTIVE)
    )

    assert inspected.effective_status is MemoryEffectiveStatus.EXPIRED
    assert inspected.evaluated_at == evaluated_at
    assert tuple(item.record.memory.id for item in listed.records) == (
        second.memory.id,
        first.memory.id,
    )
    assert tuple(item.effective_status for item in listed.records) == (
        MemoryEffectiveStatus.ACTIVE,
        MemoryEffectiveStatus.EXPIRED,
    )
    assert all(item.evaluated_at == evaluated_at for item in listed.records)
    assert listed.evaluated_at == evaluated_at
    assert get_clock.calls == list_clock.calls == 1
    assert repository.list_calls == [MemoryStatus.ACTIVE]
    assert repository.records == snapshot

    missing_clock = FixedClock(evaluated_at)
    with pytest.raises(PersistenceError, match="Memory does not exist"):
        GetMemoryService(memories=repository, clock=missing_clock).execute(
            GetMemoryInput(identifier(999))
        )
    assert missing_clock.calls == 1


def test_mutation_failure_rolls_back_the_complete_aggregate() -> None:
    repository = MemoryRepository()
    repository.fail_after_add = True
    with pytest.raises(PersistenceError, match="add failure"):
        CreateMemoryService(
            memories=repository,
            clock=FixedClock(NOW),
            id_generator=SequenceIds(identifier(1), identifier(2), identifier(3)),
            transactions=RollbackTransactions(repository),
        ).execute(create_input())
    assert repository.records == {}

    repository.fail_after_add = False
    original = create_memory(repository)
    repository.fail_after_update = True
    snapshot = repository.capture()
    with pytest.raises(PersistenceError, match="update failure"):
        EditMemoryService(
            memories=repository,
            clock=FixedClock(NOW + timedelta(hours=1)),
            id_generator=SequenceIds(identifier(4), identifier(5)),
            transactions=RollbackTransactions(repository),
        ).execute(
            EditMemoryInput(
                original.memory.id,
                "Rolled back",
                original.memory.keywords,
                original.memory.topic_terms,
                original.memory.importance,
                original.memory.confidence,
                original.memory.expires_at,
                "Should roll back",
            )
        )
    assert repository.records == snapshot


def test_missing_and_duplicate_generated_ids_fail_before_any_write() -> None:
    repository = MemoryRepository()
    clock = FixedClock(NOW)
    duplicate = identifier(1)

    with pytest.raises(LifecycleInvariantError, match="fresh distinct"):
        CreateMemoryService(
            memories=repository,
            clock=clock,
            id_generator=SequenceIds(duplicate, duplicate, identifier(2)),
            transactions=RollbackTransactions(repository),
        ).execute(create_input())

    assert repository.records == {}
    assert clock.calls == 1
