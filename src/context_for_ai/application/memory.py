"""Explicit manual-memory lifecycle application services for TASK-0009."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from context_for_ai.application.contracts import (
    CreateMemoryInput,
    EditMemoryInput,
    GetMemoryInput,
    ListMemoriesInput,
    MemoryListOutput,
    MemoryOutput,
    SoftDeleteMemoryInput,
)
from context_for_ai.domain.entities import Memory, MemoryRevision, MemorySource
from context_for_ai.domain.enums import (
    LocalActor,
    MemoryRevisionOperation,
    MemorySourceKind,
    MemoryStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import (
    memory_effective_status,
    memory_revision_metadata,
)
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.ports.records import MemoryRecord
from context_for_ai.domain.ports.repositories import MemoryRepository
from context_for_ai.domain.ports.system import Clock, IdGenerator, TransactionBoundary
from context_for_ai.domain.value_objects import DomainId, ensure_utc


def _required_memory(
    repository: MemoryRepository,
    memory_id: DomainId,
) -> MemoryRecord:
    record = repository.get(memory_id)
    if record is None:
        raise PersistenceError("Memory does not exist.")
    return record


def _new_distinct_ids(
    id_generator: IdGenerator,
    count: int,
    *,
    forbidden: frozenset[DomainId] = frozenset(),
) -> tuple[DomainId, ...]:
    identifiers = tuple(id_generator.new_id() for _ in range(count))
    if len(set(identifiers)) != len(identifiers) or set(identifiers) & forbidden:
        raise LifecycleInvariantError(
            "Memory ID generator must return fresh distinct identifiers."
        )
    return identifiers


def _history_ids(record: MemoryRecord) -> frozenset[DomainId]:
    return frozenset(
        {
            record.memory.id,
            *(source.id for source in record.sources),
            *(revision.id for revision in record.revisions),
        }
    )


def _output(record: MemoryRecord, evaluated_at: datetime) -> MemoryOutput:
    normalized_time = ensure_utc(evaluated_at)
    return MemoryOutput(
        record,
        normalized_time,
        memory_effective_status(record.memory, normalized_time),
    )


def _edit_evidence(
    *,
    record: MemoryRecord,
    updated: Memory,
    description: str,
    operation: MemoryRevisionOperation,
    source_id: DomainId,
    revision_id: DomainId,
) -> tuple[MemorySource, MemoryRevision]:
    source = MemorySource(
        source_id,
        updated.id,
        MemorySourceKind.USER_EDIT,
        None,
        description,
        updated.updated_at,
    )
    revision = MemoryRevision(
        revision_id,
        updated.id,
        record.revisions[-1].revision_number + 1,
        operation,
        updated.content,
        memory_revision_metadata(updated, source.id),
        LocalActor.LOCAL_USER,
        updated.updated_at,
    )
    return source, revision


class CreateMemoryService:
    """Create one independent ACTIVE memory with initial manual history."""

    def __init__(
        self,
        *,
        memories: MemoryRepository,
        clock: Clock,
        id_generator: IdGenerator,
        transactions: TransactionBoundary,
    ) -> None:
        self._memories = memories
        self._clock = clock
        self._id_generator = id_generator
        self._transactions = transactions

    def execute(self, request: CreateMemoryInput) -> MemoryOutput:
        with self._transactions.transaction():
            now = ensure_utc(self._clock.now())
            memory_id, source_id, revision_id = _new_distinct_ids(
                self._id_generator,
                3,
            )
            memory = Memory(
                memory_id,
                request.conversation_id,
                request.project_id,
                request.memory_type,
                request.scope,
                MemoryStatus.ACTIVE,
                request.content,
                request.keywords,
                request.topic_terms,
                request.importance,
                request.confidence,
                request.expires_at,
                now,
                now,
                None,
            )
            source = MemorySource(
                source_id,
                memory.id,
                MemorySourceKind.MANUAL_ENTRY,
                None,
                request.source_description,
                now,
            )
            revision = MemoryRevision(
                revision_id,
                memory.id,
                1,
                MemoryRevisionOperation.CREATE,
                memory.content,
                memory_revision_metadata(memory, source.id),
                LocalActor.LOCAL_USER,
                now,
            )
            self._memories.add(memory, source, revision)
            stored = _required_memory(self._memories, memory.id)
            output = _output(stored, now)
        return output


class GetMemoryService:
    """Inspect one memory with complete history and effective status."""

    def __init__(self, *, memories: MemoryRepository, clock: Clock) -> None:
        self._memories = memories
        self._clock = clock

    def execute(self, request: GetMemoryInput) -> MemoryOutput:
        evaluated_at = ensure_utc(self._clock.now())
        return _output(
            _required_memory(self._memories, request.memory_id),
            evaluated_at,
        )


class ListMemoriesService:
    """Inspect ordered memories selected only by their stored status."""

    def __init__(self, *, memories: MemoryRepository, clock: Clock) -> None:
        self._memories = memories
        self._clock = clock

    def execute(self, request: ListMemoriesInput) -> MemoryListOutput:
        evaluated_at = ensure_utc(self._clock.now())
        records = self._memories.list_by_status(request.status)
        if any(record.memory.status is not request.status for record in records):
            raise PersistenceError(
                "Memory stored-status query returned an inconsistent aggregate."
            )
        outputs = tuple(_output(record, evaluated_at) for record in records)
        return MemoryListOutput(outputs, evaluated_at)


class EditMemoryService:
    """Replace the editable fields of one non-deleted memory atomically."""

    def __init__(
        self,
        *,
        memories: MemoryRepository,
        clock: Clock,
        id_generator: IdGenerator,
        transactions: TransactionBoundary,
    ) -> None:
        self._memories = memories
        self._clock = clock
        self._id_generator = id_generator
        self._transactions = transactions

    def execute(self, request: EditMemoryInput) -> MemoryOutput:
        with self._transactions.transaction():
            current = _required_memory(self._memories, request.memory_id)
            if current.memory.status is MemoryStatus.DELETED:
                raise LifecycleInvariantError("A deleted memory cannot be edited.")
            now = ensure_utc(self._clock.now())
            source_id, revision_id = _new_distinct_ids(
                self._id_generator,
                2,
                forbidden=_history_ids(current),
            )
            updated = replace(
                current.memory,
                content=request.content,
                keywords=request.keywords,
                topic_terms=request.topic_terms,
                importance=request.importance,
                confidence=request.confidence,
                expires_at=request.expires_at,
                updated_at=now,
            )
            source, revision = _edit_evidence(
                record=current,
                updated=updated,
                description=request.source_description,
                operation=MemoryRevisionOperation.EDIT,
                source_id=source_id,
                revision_id=revision_id,
            )
            self._memories.update_with_revision(updated, source, revision)
            stored = _required_memory(self._memories, updated.id)
            output = _output(stored, now)
        return output


class SoftDeleteMemoryService:
    """Soft-delete one memory while preserving its content and history."""

    def __init__(
        self,
        *,
        memories: MemoryRepository,
        clock: Clock,
        id_generator: IdGenerator,
        transactions: TransactionBoundary,
    ) -> None:
        self._memories = memories
        self._clock = clock
        self._id_generator = id_generator
        self._transactions = transactions

    def execute(self, request: SoftDeleteMemoryInput) -> MemoryOutput:
        with self._transactions.transaction():
            current = _required_memory(self._memories, request.memory_id)
            if current.memory.status is MemoryStatus.DELETED:
                raise LifecycleInvariantError(
                    "A deleted memory cannot be deleted again."
                )
            now = ensure_utc(self._clock.now())
            source_id, revision_id = _new_distinct_ids(
                self._id_generator,
                2,
                forbidden=_history_ids(current),
            )
            deleted = replace(
                current.memory,
                status=MemoryStatus.DELETED,
                updated_at=now,
                deleted_at=now,
            )
            source, revision = _edit_evidence(
                record=current,
                updated=deleted,
                description=request.source_description,
                operation=MemoryRevisionOperation.SOFT_DELETE,
                source_id=source_id,
                revision_id=revision_id,
            )
            self._memories.update_with_revision(deleted, source, revision)
            stored = _required_memory(self._memories, deleted.id)
            output = _output(stored, now)
        return output


__all__ = [
    "CreateMemoryService",
    "EditMemoryService",
    "GetMemoryService",
    "ListMemoriesService",
    "SoftDeleteMemoryService",
]
