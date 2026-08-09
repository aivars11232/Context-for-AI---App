"""Focused TASK-0017 safe manual-memory adapter tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from context_for_ai.application.contracts import (
    CreateMemoryInput,
    CreateMemoryPresentationRequest,
    EditMemoryPresentationRequest,
    InspectMemoriesRequest,
    MemoryDuplicateDecision,
    MemoryDuplicateGuidanceResult,
    MemoryInspectionReadyResult,
    MemoryMutationStaleResult,
    MemoryMutationSucceededResult,
    SoftDeleteMemoryPresentationRequest,
)
from context_for_ai.application.manual_memory import (
    CreateMemoryPresentationService,
    EditMemoryPresentationService,
    InspectMemoriesService,
    SoftDeleteMemoryPresentationService,
)
from context_for_ai.application.memory import (
    CreateMemoryService,
    EditMemoryService,
    ListMemoriesService,
    SoftDeleteMemoryService,
)
from context_for_ai.domain.entities import Conversation, MemoryRevision, MemorySource, Project
from context_for_ai.domain.enums import MemoryScope, MemoryStatus, MemoryType, ProjectStatus
from context_for_ai.domain.ports.records import MemoryRecord
from context_for_ai.domain.value_objects import DomainId, UnitScore


NOW = datetime(2026, 8, 9, 10, 11, 12, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"71000000-0000-4000-8000-{number:012d}")


class _Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class _Ids:
    def __init__(self, start: int = 100) -> None:
        self.next = start
        self.calls = 0

    def new_id(self) -> DomainId:
        value = identifier(self.next)
        self.next += 1
        self.calls += 1
        return value


class _Memories:
    def __init__(self) -> None:
        self.records: dict[DomainId, MemoryRecord] = {}

    def add(self, memory, source: MemorySource, revision: MemoryRevision) -> None:  # type: ignore[no-untyped-def]
        self.records[memory.id] = MemoryRecord(memory, (source,), (revision,))

    def get(self, memory_id: DomainId) -> MemoryRecord | None:
        return self.records.get(memory_id)

    def list_by_status(self, status: MemoryStatus) -> tuple[MemoryRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self.records.values()
                    if record.memory.status is status
                ),
                key=lambda record: (-record.memory.updated_at.timestamp(), str(record.memory.id)),
            )
        )

    def list_retrieval_candidates(self) -> tuple[MemoryRecord, ...]:
        return tuple(self.records.values())

    def update_with_revision(self, memory, source, revision) -> None:  # type: ignore[no-untyped-def]
        current = self.records[memory.id]
        sources = tuple(
            sorted(
                (*current.sources, source),
                key=lambda item: (item.created_at, str(item.id)),
            )
        )
        self.records[memory.id] = MemoryRecord(
            memory,
            sources,
            (*current.revisions, revision),
        )


class _Transactions:
    def __init__(self, memories: _Memories) -> None:
        self.memories = memories
        self.depth = 0
        self.commits = 0

    @contextmanager
    def transaction(self):  # type: ignore[no-untyped-def]
        outer = self.depth == 0
        snapshot = dict(self.memories.records) if outer else None
        self.depth += 1
        try:
            yield
        except BaseException:
            if outer and snapshot is not None:
                self.memories.records = snapshot
            raise
        else:
            if outer:
                self.commits += 1
        finally:
            self.depth -= 1


class _Snapshots:
    def __init__(self) -> None:
        self.entries = 0

    @contextmanager
    def snapshot(self):  # type: ignore[no-untyped-def]
        self.entries += 1
        yield


class _Conversations:
    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation

    def get(self, conversation_id: DomainId) -> Conversation | None:
        return self.conversation if self.conversation.id == conversation_id else None


class _Projects:
    def __init__(self, project: Project) -> None:
        self.project = project

    def get(self, project_id: DomainId) -> Project | None:
        return self.project if self.project.id == project_id else None

    def list_by_status(self, status: ProjectStatus) -> tuple[Project, ...]:
        return (self.project,) if self.project.status is status else ()


class _Trace:
    def __init__(self, transactions: _Transactions) -> None:
        self.transactions = transactions
        self.events = []

    def emit(self, event) -> None:  # type: ignore[no-untyped-def]
        assert self.transactions.depth == 0
        self.events.append(event)


class _Configuration:
    configuration_fingerprint = "a" * 64


def _services():  # type: ignore[no-untyped-def]
    project = Project(identifier(1), "Alpha", None, ProjectStatus.ACTIVE, NOW, NOW)
    conversation = Conversation(identifier(2), project.id, "Main", NOW, NOW)
    memories = _Memories()
    transactions = _Transactions(memories)
    clock = _Clock()
    ids = _Ids()
    conversations = _Conversations(conversation)
    projects = _Projects(project)
    trace = _Trace(transactions)
    raw_create = CreateMemoryService(
        memories=memories,
        clock=clock,
        id_generator=ids,
        transactions=transactions,
    )
    raw_edit = EditMemoryService(
        memories=memories,
        clock=clock,
        id_generator=ids,
        transactions=transactions,
    )
    raw_delete = SoftDeleteMemoryService(
        memories=memories,
        clock=clock,
        id_generator=ids,
        transactions=transactions,
    )
    common = dict(
        memories=memories,
        conversations=conversations,
        projects=projects,
        transactions=transactions,
        trace_logger=trace,
        configuration=_Configuration(),
    )
    return {
        "project": project,
        "conversation": conversation,
        "memories": memories,
        "transactions": transactions,
        "clock": clock,
        "ids": ids,
        "trace": trace,
        "raw_create": raw_create,
        "create": CreateMemoryPresentationService(
            create_memory=raw_create,
            clock=clock,
            **common,
        ),
        "edit": EditMemoryPresentationService(edit_memory=raw_edit, **common),
        "delete": SoftDeleteMemoryPresentationService(
            soft_delete_memory=raw_delete,
            **common,
        ),
        "inspect": InspectMemoriesService(
            list_memories=ListMemoriesService(memories=memories, clock=clock),
            conversations=conversations,
            projects=projects,
            snapshots=_Snapshots(),
        ),
    }


def _create_request(services, *, decision=MemoryDuplicateDecision.CHECK):  # type: ignore[no-untyped-def]
    return CreateMemoryPresentationRequest(
        conversation_id=services["conversation"].id,
        memory_type=MemoryType.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        content="Remember, SQLite transactions!",
        keywords=("sqlite",),
        topic_terms=("transactions",),
        importance=Decimal("0.8"),
        confidence=Decimal("0.9"),
        expires_at=None,
        source_description="Explicit local note",
        duplicate_decision=decision,
    )


def test_inspection_keeps_expired_active_and_exposes_safe_history() -> None:
    services = _services()
    output = services["raw_create"].execute(
        CreateMemoryInput(
            conversation_id=None,
            project_id=services["project"].id,
            memory_type=MemoryType.PROJECT_FACT,
            scope=MemoryScope.PROJECT,
            content="Expired but stored active",
            keywords=(),
            topic_terms=(),
            importance=UnitScore("0.5"),
            confidence=UnitScore("0.6"),
            expires_at=NOW - timedelta(seconds=1),
            source_description="Seed",
        )
    )
    services["clock"].calls = 0

    result = services["inspect"].execute(InspectMemoriesRequest(MemoryStatus.ACTIVE))

    assert isinstance(result, MemoryInspectionReadyResult)
    item = result.view.items[0]
    assert item.summary.stored_status.display_label == "Active"
    assert item.summary.effective_status.display_label == "Expired"
    assert item.summary.owner.display_text == "Project: Alpha"
    assert item.details.sources[0].description == "Seed"
    assert item.details.revisions[0].content_snapshot == "Expired but stored active"
    assert services["clock"].calls == 1
    assert str(output.record.memory.id) not in repr(result)


def test_duplicate_check_writes_nothing_and_proceed_creates_independent_memory() -> None:
    services = _services()
    first = services["create"].execute(_create_request(services))
    assert isinstance(first, MemoryMutationSucceededResult)
    initial_ids = set(services["memories"].records)
    initial_id_calls = services["ids"].calls
    initial_events = len(services["trace"].events)
    duplicate_request = replace(
        _create_request(services),
        content="remember sqlite transactions",
    )

    guidance = services["create"].execute(duplicate_request)

    assert isinstance(guidance, MemoryDuplicateGuidanceResult)
    assert set(services["memories"].records) == initial_ids
    assert services["ids"].calls == initial_id_calls
    assert len(services["trace"].events) == initial_events

    proceeded = services["create"].execute(
        replace(duplicate_request, duplicate_decision=MemoryDuplicateDecision.PROCEED)
    )

    assert isinstance(proceeded, MemoryMutationSucceededResult)
    assert len(services["memories"].records) == 2
    assert len(services["trace"].events) == initial_events + 1


def test_edit_stale_rejects_then_success_adds_one_revision_and_trace() -> None:
    services = _services()
    created = services["create"].execute(_create_request(services))
    assert isinstance(created, MemoryMutationSucceededResult)
    memory_id = next(iter(services["memories"].records))
    trace_count = len(services["trace"].events)
    request = EditMemoryPresentationRequest(
        memory_id=memory_id,
        expected_revision_number=0,
        content="Updated",
        keywords=("exact",),
        topic_terms=(),
        importance=Decimal("0.4"),
        confidence=Decimal("0.7"),
        expires_at=None,
        source_description="Correction",
    )

    stale = services["edit"].execute(request)
    assert isinstance(stale, MemoryMutationStaleResult)
    assert len(services["memories"].records[memory_id].revisions) == 1
    assert len(services["trace"].events) == trace_count

    succeeded = services["edit"].execute(replace(request, expected_revision_number=1))
    assert isinstance(succeeded, MemoryMutationSucceededResult)
    assert len(services["memories"].records[memory_id].revisions) == 2
    event = services["trace"].events[-1]
    assert event.event_name == "memory_edited"
    assert event.memory_id == memory_id
    assert event.conversation_id is None
    assert event.processing_run_id is None


def test_soft_delete_preserves_content_and_adds_tombstone_revision() -> None:
    services = _services()
    created = services["create"].execute(_create_request(services))
    assert isinstance(created, MemoryMutationSucceededResult)
    memory_id = next(iter(services["memories"].records))
    original_content = services["memories"].records[memory_id].memory.content

    deleted = services["delete"].execute(
        SoftDeleteMemoryPresentationRequest(memory_id, 1, "No longer current")
    )

    assert isinstance(deleted, MemoryMutationSucceededResult)
    record = services["memories"].records[memory_id]
    assert record.memory.status is MemoryStatus.DELETED
    assert record.memory.content == original_content
    assert len(record.sources) == 2
    assert len(record.revisions) == 2
    assert services["trace"].events[-1].event_name == "memory_soft_deleted"
