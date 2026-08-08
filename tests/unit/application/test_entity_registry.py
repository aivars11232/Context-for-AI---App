"""Focused application tests for TASK-0008 owner/entity registration."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import pytest

from context_for_ai.application.contracts import (
    RegisterNamedItemInput,
    RegisterProjectInput,
    RegisterTaskInput,
    RegisterTopicInput,
)
from context_for_ai.application.entity_registry import (
    RegisterNamedItemService,
    RegisterProjectService,
    RegisterTaskService,
    RegisterTopicService,
)
from context_for_ai.domain.entities import (
    Conversation,
    ConversationTask,
    Entity,
    Message,
    NamedItem,
    Project,
    Topic,
)
from context_for_ai.domain.enums import (
    EntityType,
    MessageRole,
    ProjectStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.value_objects import DomainId


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"50000000-0000-4000-8000-{number:012d}")


class FixedClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW


class SequenceIds:
    def __init__(self, values: tuple[DomainId, ...]) -> None:
        self.values = list(values)
        self.calls: list[DomainId] = []

    def new_id(self) -> DomainId:
        value = self.values.pop(0)
        self.calls.append(value)
        return value


class ProjectRepository:
    def __init__(self, *records: Project) -> None:
        self.records = {record.id: record for record in records}

    def add(self, project: Project) -> None:
        if project.id in self.records:
            raise PersistenceError("Duplicate project.")
        self.records[project.id] = project

    def get(self, project_id: DomainId) -> Project | None:
        return self.records.get(project_id)

    def capture(self):
        return dict(self.records)

    def restore(self, snapshot) -> None:
        self.records = snapshot


class ConversationRepository:
    def __init__(self, *records: Conversation) -> None:
        self.records = {record.id: record for record in records}

    def get(self, conversation_id: DomainId) -> Conversation | None:
        return self.records.get(conversation_id)


class TopicRepository:
    def __init__(self) -> None:
        self.records: dict[DomainId, Topic] = {}

    def add(self, topic: Topic) -> None:
        self.records[topic.id] = topic

    def get(self, topic_id: DomainId) -> Topic | None:
        return self.records.get(topic_id)

    def capture(self):
        return dict(self.records)

    def restore(self, snapshot) -> None:
        self.records = snapshot


class TaskRepository:
    def __init__(self) -> None:
        self.records: dict[DomainId, ConversationTask] = {}

    def add(self, task: ConversationTask) -> None:
        self.records[task.id] = task

    def capture(self):
        return dict(self.records)

    def restore(self, snapshot) -> None:
        self.records = snapshot


class MessageRepository:
    def __init__(self, *records: Message) -> None:
        self.records = {record.id: record for record in records}

    def get(self, message_id: DomainId) -> Message | None:
        return self.records.get(message_id)


class EntityRepository:
    def __init__(self) -> None:
        self.entities: dict[DomainId, Entity] = {}
        self.named_items: dict[DomainId, NamedItem] = {}
        self.fail_add = False
        self.fail_named_after_owner = False

    def add(self, entity: Entity) -> None:
        if self.fail_add:
            raise PersistenceError("Injected entity failure.")
        self.entities[entity.id] = entity

    def add_named_item(self, named_item: NamedItem, entity: Entity) -> None:
        self.named_items[named_item.id] = named_item
        if self.fail_named_after_owner:
            raise PersistenceError("Injected named-item entity failure.")
        self.entities[entity.id] = entity

    def capture(self):
        return dict(self.entities), dict(self.named_items)

    def restore(self, snapshot) -> None:
        self.entities, self.named_items = snapshot


class RollbackTransactions:
    def __init__(self, *repositories: object) -> None:
        self.repositories = repositories
        self.entries = 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.entries += 1
        snapshots = [
            (repository, repository.capture())
            for repository in self.repositories
            if hasattr(repository, "capture")
        ]
        try:
            yield
        except BaseException:
            for repository, snapshot in snapshots:
                repository.restore(snapshot)
            raise


def test_four_registration_services_create_canonical_owner_projections() -> None:
    project = Project(
        identifier(1), "Existing", None, ProjectStatus.ACTIVE, NOW, NOW
    )
    conversation = Conversation(identifier(2), project.id, None, NOW, NOW)
    project_source = Message(
        identifier(3), conversation.id, MessageRole.USER, "create project", NOW, 0
    )
    topic_source = Message(
        identifier(4), conversation.id, MessageRole.USER, "topic: Design", NOW, 1
    )
    task_source = Message(
        identifier(5), conversation.id, MessageRole.USER, "task: Build", NOW, 2
    )
    declaration = Message(
        identifier(6),
        conversation.id,
        MessageRole.USER,
        'name "  CAFE\u0301   Architecture "',
        NOW,
        3,
    )
    projects = ProjectRepository(project)
    conversations = ConversationRepository(conversation)
    topics = TopicRepository()
    tasks = TaskRepository()
    messages = MessageRepository(project_source, topic_source, task_source, declaration)
    entities = EntityRepository()
    transactions = RollbackTransactions(projects, topics, tasks, entities)
    clock = FixedClock()
    ids = SequenceIds(tuple(identifier(number) for number in range(100, 108)))

    registered_project = RegisterProjectService(
        projects=projects,
        entities=entities,
        messages=messages,
        clock=clock,
        id_generator=ids,
        transactions=transactions,
    ).execute(RegisterProjectInput("Context for AI", None, project_source.id))
    registered_topic = RegisterTopicService(
        conversations=conversations,
        projects=projects,
        topics=topics,
        entities=entities,
        messages=messages,
        clock=clock,
        id_generator=ids,
        transactions=transactions,
    ).execute(RegisterTopicInput(conversation.id, "Design", topic_source.id))
    registered_task = RegisterTaskService(
        conversations=conversations,
        projects=projects,
        topics=topics,
        tasks=tasks,
        entities=entities,
        messages=messages,
        clock=clock,
        id_generator=ids,
        transactions=transactions,
    ).execute(
        RegisterTaskInput(
            conversation.id,
            registered_topic.topic.id,
            "Build Registry",
            task_source.id,
        )
    )
    registered_named = RegisterNamedItemService(
        conversations=conversations,
        projects=projects,
        entities=entities,
        messages=messages,
        clock=clock,
        id_generator=ids,
        transactions=transactions,
    ).execute(RegisterNamedItemInput(conversation.id, declaration.id, None, None))

    assert registered_project.entity.entity_type is EntityType.PROJECT
    assert registered_project.entity.id != registered_project.project.id
    assert registered_project.entity.source_message_id == project_source.id
    assert registered_topic.entity.project_id == project.id
    assert registered_topic.entity.source_message_id == topic_source.id
    assert registered_task.task.status is TaskStatus.OPEN
    assert registered_task.entity.is_active is True
    assert registered_named.named_item.display_name == "CAFÉ Architecture"
    assert registered_named.named_item.normalized_name == "café architecture"
    assert registered_named.named_item.project_id == project.id
    assert registered_named.entity.source_message_id == declaration.id
    assert tuple(ids.calls) == tuple(identifier(number) for number in range(100, 108))
    assert clock.calls == 4
    assert transactions.entries == 4


def test_explicit_ui_named_item_uses_selected_nullable_project_and_null_source() -> None:
    conversation = Conversation(identifier(2), identifier(1), None, NOW, NOW)
    projects = ProjectRepository(
        Project(identifier(1), "Project", None, ProjectStatus.ACTIVE, NOW, NOW)
    )
    entities = EntityRepository()
    clock = FixedClock()
    result = RegisterNamedItemService(
        conversations=ConversationRepository(conversation),
        projects=projects,
        entities=entities,
        messages=MessageRepository(),
        clock=clock,
        id_generator=SequenceIds((identifier(10), identifier(11))),
        transactions=RollbackTransactions(entities),
    ).execute(RegisterNamedItemInput(conversation.id, None, "  UI   Label  ", None))

    assert result.named_item.display_name == "UI Label"
    assert result.named_item.project_id is None
    assert result.named_item.source_message_id is None
    assert result.entity.is_active is True
    assert clock.calls == 1


def test_registration_rejects_wrong_role_and_cross_conversation_sources() -> None:
    conversation = Conversation(identifier(2), None, None, NOW, NOW)
    other_conversation = Conversation(identifier(3), None, None, NOW, NOW)
    assistant = Message(
        identifier(4), conversation.id, MessageRole.ASSISTANT, "topic", NOW, 0
    )
    other_user = Message(
        identifier(5), other_conversation.id, MessageRole.USER, "topic", NOW, 0
    )
    base = dict(
        conversations=ConversationRepository(conversation, other_conversation),
        projects=ProjectRepository(),
        topics=TopicRepository(),
        entities=EntityRepository(),
        messages=MessageRepository(assistant, other_user),
        clock=FixedClock(),
        id_generator=SequenceIds((identifier(10), identifier(11))),
        transactions=RollbackTransactions(),
    )
    service = RegisterTopicService(**base)

    with pytest.raises(LifecycleInvariantError, match="USER role"):
        service.execute(RegisterTopicInput(conversation.id, "Topic", assistant.id))
    with pytest.raises(LifecycleInvariantError, match="owning conversation"):
        service.execute(RegisterTopicInput(conversation.id, "Topic", other_user.id))


def test_second_write_failure_rolls_back_owner_and_named_item_rows() -> None:
    projects = ProjectRepository()
    entities = EntityRepository()
    entities.fail_add = True
    transactions = RollbackTransactions(projects, entities)
    service = RegisterProjectService(
        projects=projects,
        entities=entities,
        messages=MessageRepository(),
        clock=FixedClock(),
        id_generator=SequenceIds((identifier(10), identifier(11))),
        transactions=transactions,
    )

    with pytest.raises(PersistenceError, match="Injected entity"):
        service.execute(RegisterProjectInput("Rolled back", None, None))
    assert projects.records == {}
    assert entities.entities == {}

    conversation = Conversation(identifier(20), None, None, NOW, NOW)
    entities.fail_add = False
    entities.fail_named_after_owner = True
    named_transactions = RollbackTransactions(entities)
    named_service = RegisterNamedItemService(
        conversations=ConversationRepository(conversation),
        projects=ProjectRepository(),
        entities=entities,
        messages=MessageRepository(),
        clock=FixedClock(),
        id_generator=SequenceIds((identifier(21), identifier(22))),
        transactions=named_transactions,
    )

    with pytest.raises(PersistenceError, match="named-item entity"):
        named_service.execute(
            RegisterNamedItemInput(conversation.id, None, "Rolled back", None)
        )
    assert entities.named_items == {}
    assert entities.entities == {}
