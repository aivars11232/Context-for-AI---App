"""TASK-0008 owner registry and reference integration against isolated SQLite."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from context_for_ai.application import (
    RegisterNamedItemInput,
    RegisterNamedItemService,
    RegisterProjectInput,
    RegisterProjectService,
    RegisterTaskInput,
    RegisterTaskService,
    RegisterTopicInput,
    RegisterTopicService,
)
from context_for_ai.context_engine import (
    DeterministicReferenceMentionExtractor,
    DeterministicReferenceResolver,
)
from context_for_ai.domain.decisions import (
    ReferenceCandidateEvidence,
    ReferenceOutcome,
)
from context_for_ai.domain.entities import (
    Conversation,
    Entity,
    Message,
    Project,
)
from context_for_ai.domain.enums import (
    EntityType,
    MessageRole,
    ProcessingRunStatus,
    ProjectStatus,
    ReferenceRankReason,
    ReferenceStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.context import (
    ReferenceMentionExtractionRequest,
    ReferenceResolutionRequest,
)
from context_for_ai.domain.ports.errors import PersistenceError
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
    SQLiteTaskRepository,
    SQLiteTopicRepository,
    SQLiteTransactionBoundary,
    apply_migrations,
    connect_database,
)


BASE_TIME = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"60000000-0000-4000-8000-{number:012d}")


def stamp(seconds: int) -> datetime:
    return BASE_TIME + timedelta(seconds=seconds)


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

    def new_id(self) -> DomainId:
        return self.values.pop(0)


class FailingEntityAdd:
    def add(self, entity: Entity) -> None:
        raise PersistenceError("Injected registry insertion failure.")


@pytest.fixture
def database(tmp_path: Path) -> SimpleNamespace:
    path = apply_migrations(tmp_path / "task-0008.sqlite3")
    connection = connect_database(path)
    bundle = SimpleNamespace(
        connection=connection,
        transactions=SQLiteTransactionBoundary(connection),
        projects=SQLiteProjectRepository(connection),
        conversations=SQLiteConversationRepository(connection),
        states=SQLiteConversationStateRepository(connection),
        topics=SQLiteTopicRepository(connection),
        tasks=SQLiteTaskRepository(connection),
        messages=SQLiteMessageRepository(connection),
        entities=SQLiteEntityRepository(connection),
        runs=SQLiteProcessingRunRepository(connection),
        references=SQLiteReferenceResolutionRepository(connection),
    )
    try:
        yield bundle
    finally:
        connection.close()


def seed_conversation(
    database: SimpleNamespace,
    *,
    conversation_number: int = 1,
    messages: tuple[tuple[int, str, MessageRole], ...] = (),
) -> tuple[Conversation, tuple[Message, ...]]:
    conversation = Conversation(
        identifier(conversation_number),
        None,
        "TASK-0008",
        stamp(0),
        stamp(0),
    )
    records = tuple(
        Message(
            identifier(number),
            conversation.id,
            role,
            text,
            stamp(sequence + 1),
            sequence,
        )
        for sequence, (number, text, role) in enumerate(messages)
    )
    with database.transactions.transaction():
        database.conversations.add(conversation)
        database.states.add(
            initial_conversation_state(conversation.id, updated_at=stamp(0))
        )
        for message in records:
            database.messages.add(message)
    return conversation, records


def project_service(
    database: SimpleNamespace,
    ids: SequenceIds,
    *,
    clock_value: datetime,
    entities: object | None = None,
) -> RegisterProjectService:
    return RegisterProjectService(
        projects=database.projects,
        entities=database.entities if entities is None else entities,  # type: ignore[arg-type]
        messages=database.messages,
        clock=FixedClock(clock_value),
        id_generator=ids,
        transactions=database.transactions,
    )


def add_run(
    database: SimpleNamespace,
    *,
    number: int,
    conversation: Conversation,
    message: Message,
) -> ProcessingRun:
    state = database.states.get(conversation.id)
    assert state is not None
    run = ProcessingRun(
        identifier(number),
        conversation.id,
        message.id,
        str(identifier(number + 1000)),
        ProcessingRunStatus.PERSISTED,
        state.version,
        "task-0008-integration",
        stamp(message.sequence_number + 20),
        None,
    )
    database.runs.add(run)
    return run


def test_registration_lifecycle_and_scoped_stale_candidates(
    database: SimpleNamespace,
) -> None:
    conversation, messages = seed_conversation(
        database,
        messages=(
            (10, "create Context for AI", MessageRole.USER),
            (11, "topic: Architecture", MessageRole.USER),
            (12, "task: Implement registry", MessageRole.USER),
            (13, 'name "Reference Layer"', MessageRole.USER),
        ),
    )
    project_source, topic_source, task_source, declaration = messages
    ids = SequenceIds(*(identifier(number) for number in range(100, 114)))

    registered_project = project_service(
        database, ids, clock_value=stamp(10)
    ).execute(RegisterProjectInput("Context for AI", None, project_source.id))
    conversation = replace(
        conversation,
        project_id=registered_project.project.id,
        updated_at=stamp(11),
    )
    database.conversations.update(conversation)
    registered_topic = RegisterTopicService(
        conversations=database.conversations,
        projects=database.projects,
        topics=database.topics,
        entities=database.entities,
        messages=database.messages,
        clock=FixedClock(stamp(12)),
        id_generator=ids,
        transactions=database.transactions,
    ).execute(RegisterTopicInput(conversation.id, "Architecture", topic_source.id))
    registered_task = RegisterTaskService(
        conversations=database.conversations,
        projects=database.projects,
        topics=database.topics,
        tasks=database.tasks,
        entities=database.entities,
        messages=database.messages,
        clock=FixedClock(stamp(13)),
        id_generator=ids,
        transactions=database.transactions,
    ).execute(
        RegisterTaskInput(
            conversation.id,
            registered_topic.topic.id,
            "Implement Registry",
            task_source.id,
        )
    )
    named_service = RegisterNamedItemService(
        conversations=database.conversations,
        projects=database.projects,
        entities=database.entities,
        messages=database.messages,
        clock=FixedClock(stamp(14)),
        id_generator=ids,
        transactions=database.transactions,
    )
    registered_named = named_service.execute(
        RegisterNamedItemInput(conversation.id, declaration.id, None, None)
    )
    registered_unscoped = named_service.execute(
        RegisterNamedItemInput(conversation.id, None, "Global Label", None)
    )

    assert {
        registered_project.entity.entity_type,
        registered_topic.entity.entity_type,
        registered_task.entity.entity_type,
        registered_named.entity.entity_type,
    } == set(EntityType)
    assert all(
        output.entity.id != output.entity.native_id
        for output in (
            registered_project,
            registered_topic,
            registered_task,
            registered_named,
            registered_unscoped,
        )
    )
    assert registered_topic.entity.source_message_id == topic_source.id
    assert registered_task.entity.source_message_id == task_source.id
    assert registered_named.named_item.source_message_id == declaration.id

    with pytest.raises(PersistenceError):
        named_service.execute(
            RegisterNamedItemInput(conversation.id, declaration.id, None, None)
        )
    assert database.connection.execute(
        "SELECT COUNT(*) FROM named_items WHERE normalized_name = 'reference layer'"
    ).fetchone()[0] == 1

    renamed_project = replace(
        registered_project.project,
        name="Context Registry",
        updated_at=stamp(20),
    )
    renamed_topic = replace(
        registered_topic.topic,
        label="Reference Resolution",
        normalized_label="reference resolution",
        updated_at=stamp(21),
    )
    renamed_task = replace(
        registered_task.task,
        title="Implement Resolver",
        updated_at=stamp(22),
    )
    renamed_owner = replace(
        registered_named.named_item,
        display_name="Reference Engine",
        normalized_name="reference engine",
        updated_at=stamp(23),
    )
    renamed_entity = replace(
        registered_named.entity,
        display_name="Reference Engine",
        normalized_name="reference engine",
        updated_at=stamp(23),
    )
    database.projects.update(renamed_project)
    database.topics.update(renamed_topic)
    database.tasks.update(renamed_task)
    database.entities.update_named_item(renamed_owner, renamed_entity)
    assert database.entities.get(registered_project.entity.id).display_name == "Context Registry"
    assert database.entities.get(registered_topic.entity.id).display_name == "Reference Resolution"
    assert database.entities.get(registered_task.entity.id).display_name == "Implement Resolver"
    assert database.entities.get(registered_named.entity.id) == renamed_entity

    second_project = project_service(
        database, ids, clock_value=stamp(24)
    ).execute(RegisterProjectInput("Second Project", None, project_source.id))
    conversation = replace(
        conversation,
        project_id=second_project.project.id,
        updated_at=stamp(25),
    )
    database.conversations.update(conversation)
    assert database.entities.get(registered_topic.entity.id).project_id == second_project.project.id
    assert database.entities.get(registered_task.entity.id).project_id == second_project.project.id
    assert database.entities.get(registered_named.entity.id).project_id == registered_project.project.id
    switched_ids = {
        item.id
        for item in database.entities.list_reference_candidates(
            conversation_id=conversation.id,
            project_id=second_project.project.id,
        )
    }
    assert registered_named.entity.id not in switched_ids
    assert registered_unscoped.entity.id in switched_ids

    conversation = replace(
        conversation,
        project_id=registered_project.project.id,
        updated_at=stamp(26),
    )
    database.conversations.update(conversation)
    completed = replace(
        renamed_task,
        status=TaskStatus.COMPLETED,
        updated_at=stamp(27),
    )
    database.tasks.update(completed)
    assert database.entities.get(registered_task.entity.id).is_active is False
    reopened = replace(completed, status=TaskStatus.OPEN, updated_at=stamp(28))
    database.tasks.update(reopened)
    assert database.entities.get(registered_task.entity.id).is_active is True

    archived = replace(
        renamed_project,
        status=ProjectStatus.ARCHIVED,
        updated_at=stamp(29),
    )
    database.projects.update(archived)
    stale = database.entities.list_reference_candidates(
        conversation_id=conversation.id,
        project_id=archived.id,
    )
    stale_by_id = {item.id: item for item in stale}
    for entity_id in (
        registered_project.entity.id,
        registered_topic.entity.id,
        registered_task.entity.id,
        registered_named.entity.id,
    ):
        assert stale_by_id[entity_id].is_active is False
    assert stale_by_id[registered_unscoped.entity.id].is_active is True


def test_registration_and_named_item_second_write_failures_roll_back(
    database: SimpleNamespace,
) -> None:
    conversation, (source,) = seed_conversation(
        database,
        messages=((10, "create project", MessageRole.USER),),
    )
    failed_project_id = identifier(100)
    with pytest.raises(PersistenceError, match="Injected registry"):
        project_service(
            database,
            SequenceIds(failed_project_id, identifier(101)),
            clock_value=stamp(10),
            entities=FailingEntityAdd(),
        ).execute(RegisterProjectInput("Rollback", None, source.id))
    assert database.projects.get(failed_project_id) is None

    registered = project_service(
        database,
        SequenceIds(identifier(102), identifier(103)),
        clock_value=stamp(11),
    ).execute(RegisterProjectInput("Existing", None, source.id))
    before = database.connection.execute("SELECT COUNT(*) FROM named_items").fetchone()[0]
    named_service = RegisterNamedItemService(
        conversations=database.conversations,
        projects=database.projects,
        entities=database.entities,
        messages=database.messages,
        clock=FixedClock(stamp(12)),
        id_generator=SequenceIds(identifier(104), registered.entity.id),
        transactions=database.transactions,
    )
    with pytest.raises(PersistenceError):
        named_service.execute(
            RegisterNamedItemInput(conversation.id, None, "Rollback Item", None)
        )
    assert database.connection.execute("SELECT COUNT(*) FROM named_items").fetchone()[0] == before

    other = Conversation(identifier(20), None, None, stamp(13), stamp(13))
    other_message = Message(
        identifier(21), other.id, MessageRole.USER, "topic", stamp(14), 0
    )
    with database.transactions.transaction():
        database.conversations.add(other)
        database.states.add(initial_conversation_state(other.id, updated_at=stamp(13)))
        database.messages.add(other_message)
    topic_service = RegisterTopicService(
        conversations=database.conversations,
        projects=database.projects,
        topics=database.topics,
        entities=database.entities,
        messages=database.messages,
        clock=FixedClock(stamp(15)),
        id_generator=SequenceIds(identifier(105), identifier(106)),
        transactions=database.transactions,
    )
    with pytest.raises(LifecycleInvariantError, match="owning conversation"):
        topic_service.execute(
            RegisterTopicInput(conversation.id, "Wrong source", other_message.id)
        )
    assert database.topics.get(identifier(105)) is None


def test_reference_lineage_prior_query_exact_persistence_and_zero_mentions(
    database: SimpleNamespace,
) -> None:
    conversation, messages = seed_conversation(
        database,
        messages=(
            (10, "create Context for AI", MessageRole.USER),
            (11, "correct the app structure", MessageRole.USER),
            (12, "same as before", MessageRole.USER),
            (13, "plain request", MessageRole.USER),
        ),
    )
    source, prior_message, current_message, plain_message = messages
    project = project_service(
        database,
        SequenceIds(identifier(100), identifier(101)),
        clock_value=stamp(10),
    ).execute(RegisterProjectInput("Context for AI", None, source.id))
    conversation = replace(
        conversation,
        project_id=project.project.id,
        updated_at=stamp(11),
    )
    database.conversations.update(conversation)
    candidates = database.entities.list_reference_candidates(
        conversation_id=conversation.id,
        project_id=project.project.id,
    )
    state = database.states.get(conversation.id)
    assert state is not None

    extractor = DeterministicReferenceMentionExtractor()
    prior_mentions = extractor.extract(
        ReferenceMentionExtractionRequest(prior_message, (), candidates)
    )
    prior_run = add_run(
        database,
        number=200,
        conversation=conversation,
        message=prior_message,
    )
    prior_decision = DeterministicReferenceResolver(
        SequenceIds(identifier(300))
    ).resolve(
        ReferenceResolutionRequest(
            prior_run.id,
            prior_message,
            (),
            state,
            prior_mentions,
            candidates,
            (),
            stamp(30),
        )
    )
    database.references.add_all(prior_decision.outcomes)
    prior_outcome = prior_decision.outcomes[0]
    assert prior_outcome.source_message_id == source.id
    database.runs.update(
        replace(
            prior_run,
            status=ProcessingRunStatus.FAILED,
            completed_at=stamp(31),
        )
    )

    current_mentions = extractor.extract(
        ReferenceMentionExtractionRequest(current_message, (), candidates)
    )
    current_run = add_run(
        database,
        number=201,
        conversation=conversation,
        message=current_message,
    )
    current_decision = DeterministicReferenceResolver(
        SequenceIds(identifier(301))
    ).resolve(
        ReferenceResolutionRequest(
            current_run.id,
            current_message,
            (prior_message,),
            state,
            current_mentions,
            candidates,
            (prior_outcome,),
            stamp(32),
        )
    )
    database.references.add_all(current_decision.outcomes)
    current_outcome = current_decision.outcomes[0]

    assert current_outcome.status is ReferenceStatus.RESOLVED
    assert current_outcome.confidence == UnitScore("0.80")
    assert current_outcome.source_message_id == prior_message.id
    assert database.references.list_resolved_for_messages(
        (prior_message.id, current_message.id)
    ) == (prior_outcome, current_outcome)
    stored_json = database.connection.execute(
        "SELECT candidate_evidence_json FROM reference_resolutions WHERE id = ?",
        (str(current_outcome.id),),
    ).fetchone()[0]
    assert json.loads(stored_json) == [
        {
            key: value
            for key, value in current_outcome.candidate_evidence[0].to_json_object().items()
        }
    ]
    assert database.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 4

    empty_mentions = extractor.extract(
        ReferenceMentionExtractionRequest(plain_message, (), candidates)
    )
    empty_decision = DeterministicReferenceResolver(SequenceIds()).resolve(
        ReferenceResolutionRequest(
            identifier(999),
            plain_message,
            (),
            state,
            empty_mentions,
            candidates,
            (),
            stamp(33),
        )
    )
    database.references.add_all(empty_decision.outcomes)
    assert empty_decision.outcomes == ()
    assert database.connection.execute(
        "SELECT COUNT(*) FROM reference_resolutions"
    ).fetchone()[0] == 2


def test_invalid_later_evidence_rolls_back_the_complete_outcome_tuple(
    database: SimpleNamespace,
) -> None:
    conversation, (source, current) = seed_conversation(
        database,
        messages=(
            (10, "create project", MessageRole.USER),
            (11, "it and that", MessageRole.USER),
        ),
    )
    project = project_service(
        database,
        SequenceIds(identifier(100), identifier(101)),
        clock_value=stamp(10),
    ).execute(RegisterProjectInput("Context for AI", None, source.id))
    conversation = replace(
        conversation,
        project_id=project.project.id,
        updated_at=stamp(11),
    )
    database.conversations.update(conversation)
    run = add_run(database, number=200, conversation=conversation, message=current)

    def evidence(display_name: str) -> ReferenceCandidateEvidence:
        return ReferenceCandidateEvidence(
            1,
            project.entity.id,
            EntityType.PROJECT,
            display_name,
            project.entity.normalized_name,
            UnitScore("0.90"),
            ReferenceRankReason.ACTIVE_STATE,
            source.id,
            None,
            None,
            None,
            True,
        )

    valid = ReferenceOutcome(
        identifier(300),
        run.id,
        current.id,
        0,
        "it",
        ReferenceStatus.RESOLVED,
        project.entity.id,
        source.id,
        UnitScore("0.90"),
        (evidence(project.entity.display_name),),
        stamp(30),
    )
    invalid = ReferenceOutcome(
        identifier(301),
        run.id,
        current.id,
        1,
        "that",
        ReferenceStatus.RESOLVED,
        project.entity.id,
        source.id,
        UnitScore("0.90"),
        (evidence("Tampered display"),),
        stamp(30),
    )

    with pytest.raises(LifecycleInvariantError, match="stored entity snapshot"):
        database.references.add_all((valid, invalid))
    assert database.references.list_for_run(run.id) == ()
