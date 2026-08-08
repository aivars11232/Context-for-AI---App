"""Application services for atomic owner/entity registration in TASK-0008."""

from __future__ import annotations

from context_for_ai.application.contracts import (
    RegisterNamedItemInput,
    RegisterNamedItemOutput,
    RegisterProjectInput,
    RegisterProjectOutput,
    RegisterTaskInput,
    RegisterTaskOutput,
    RegisterTopicInput,
    RegisterTopicOutput,
)
from context_for_ai.context_engine.normalization import (
    normalize_display_label,
    normalize_phrase,
)
from context_for_ai.context_engine.reference_extraction import (
    parse_named_item_declaration,
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
from context_for_ai.domain.ports.repositories import (
    ConversationRepository,
    EntityRepository,
    MessageRepository,
    ProjectRepository,
    TaskRepository,
    TopicRepository,
)
from context_for_ai.domain.ports.system import Clock, IdGenerator, TransactionBoundary
from context_for_ai.domain.value_objects import DomainId


def _required_conversation(
    repository: ConversationRepository,
    conversation_id: DomainId,
) -> Conversation:
    conversation = repository.get(conversation_id)
    if conversation is None:
        raise PersistenceError("Conversation does not exist.")
    return conversation


def _required_project(
    repository: ProjectRepository,
    project_id: DomainId,
) -> Project:
    project = repository.get(project_id)
    if project is None:
        raise PersistenceError("Project does not exist.")
    return project


def _validated_source_message(
    repository: MessageRepository,
    source_message_id: DomainId | None,
    *,
    conversation_id: DomainId | None,
) -> Message | None:
    if source_message_id is None:
        return None
    message = repository.get(source_message_id)
    if message is None:
        raise PersistenceError("Entity source message does not exist.")
    if message.role is not MessageRole.USER:
        raise LifecycleInvariantError("Entity source message must have USER role.")
    if conversation_id is not None and message.conversation_id != conversation_id:
        raise LifecycleInvariantError(
            "Entity source message must belong to its owning conversation."
        )
    return message


def _project_activity(
    repository: ProjectRepository,
    project_id: DomainId | None,
) -> bool:
    if project_id is None:
        return True
    return _required_project(repository, project_id).status is ProjectStatus.ACTIVE


def _registration_ids(id_generator: IdGenerator) -> tuple[DomainId, DomainId]:
    owner_id = id_generator.new_id()
    entity_id = id_generator.new_id()
    if owner_id == entity_id:
        raise LifecycleInvariantError(
            "Registry ID generator must return a distinct owner and entity ID."
        )
    return owner_id, entity_id


class RegisterProjectService:
    """Create one ACTIVE project and its registry projection atomically."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        entities: EntityRepository,
        messages: MessageRepository,
        clock: Clock,
        id_generator: IdGenerator,
        transactions: TransactionBoundary,
    ) -> None:
        self._projects = projects
        self._entities = entities
        self._messages = messages
        self._clock = clock
        self._id_generator = id_generator
        self._transactions = transactions

    def execute(self, request: RegisterProjectInput) -> RegisterProjectOutput:
        with self._transactions.transaction():
            _validated_source_message(
                self._messages,
                request.source_message_id,
                conversation_id=None,
            )
            owner_id, entity_id = _registration_ids(self._id_generator)
            now = self._clock.now()
            project = Project(
                owner_id,
                request.name,
                request.description,
                ProjectStatus.ACTIVE,
                now,
                now,
            )
            entity = Entity(
                entity_id,
                EntityType.PROJECT,
                project.id,
                project.id,
                project.name,
                normalize_phrase(project.name),
                request.source_message_id,
                True,
                now,
                now,
            )
            self._projects.add(project)
            self._entities.add(entity)
        return RegisterProjectOutput(project, entity)


class RegisterTopicService:
    """Create one conversation topic and its registry projection atomically."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        projects: ProjectRepository,
        topics: TopicRepository,
        entities: EntityRepository,
        messages: MessageRepository,
        clock: Clock,
        id_generator: IdGenerator,
        transactions: TransactionBoundary,
    ) -> None:
        self._conversations = conversations
        self._projects = projects
        self._topics = topics
        self._entities = entities
        self._messages = messages
        self._clock = clock
        self._id_generator = id_generator
        self._transactions = transactions

    def execute(self, request: RegisterTopicInput) -> RegisterTopicOutput:
        with self._transactions.transaction():
            conversation = _required_conversation(
                self._conversations,
                request.conversation_id,
            )
            _validated_source_message(
                self._messages,
                request.source_message_id,
                conversation_id=conversation.id,
            )
            active = _project_activity(self._projects, conversation.project_id)
            owner_id, entity_id = _registration_ids(self._id_generator)
            now = self._clock.now()
            topic = Topic(
                owner_id,
                conversation.id,
                request.label,
                normalize_phrase(request.label),
                now,
                now,
            )
            entity = Entity(
                entity_id,
                EntityType.TOPIC,
                topic.id,
                conversation.project_id,
                topic.label,
                topic.normalized_label,
                request.source_message_id,
                active,
                now,
                now,
            )
            self._topics.add(topic)
            self._entities.add(entity)
        return RegisterTopicOutput(topic, entity)


class RegisterTaskService:
    """Create one OPEN conversation task and its registry projection atomically."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        projects: ProjectRepository,
        topics: TopicRepository,
        tasks: TaskRepository,
        entities: EntityRepository,
        messages: MessageRepository,
        clock: Clock,
        id_generator: IdGenerator,
        transactions: TransactionBoundary,
    ) -> None:
        self._conversations = conversations
        self._projects = projects
        self._topics = topics
        self._tasks = tasks
        self._entities = entities
        self._messages = messages
        self._clock = clock
        self._id_generator = id_generator
        self._transactions = transactions

    def execute(self, request: RegisterTaskInput) -> RegisterTaskOutput:
        with self._transactions.transaction():
            conversation = _required_conversation(
                self._conversations,
                request.conversation_id,
            )
            if request.topic_id is not None:
                topic = self._topics.get(request.topic_id)
                if topic is None or topic.conversation_id != conversation.id:
                    raise LifecycleInvariantError(
                        "A registered task topic must belong to its conversation."
                    )
            _validated_source_message(
                self._messages,
                request.source_message_id,
                conversation_id=conversation.id,
            )
            active = _project_activity(self._projects, conversation.project_id)
            owner_id, entity_id = _registration_ids(self._id_generator)
            now = self._clock.now()
            task = ConversationTask(
                owner_id,
                conversation.id,
                request.topic_id,
                request.title,
                TaskStatus.OPEN,
                now,
                now,
            )
            entity = Entity(
                entity_id,
                EntityType.TASK,
                task.id,
                conversation.project_id,
                task.title,
                normalize_phrase(task.title),
                request.source_message_id,
                active,
                now,
                now,
            )
            self._tasks.add(task)
            self._entities.add(entity)
        return RegisterTaskOutput(task, entity)


class RegisterNamedItemService:
    """Create one explicit named item and registry row atomically."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        projects: ProjectRepository,
        entities: EntityRepository,
        messages: MessageRepository,
        clock: Clock,
        id_generator: IdGenerator,
        transactions: TransactionBoundary,
    ) -> None:
        self._conversations = conversations
        self._projects = projects
        self._entities = entities
        self._messages = messages
        self._clock = clock
        self._id_generator = id_generator
        self._transactions = transactions

    def execute(self, request: RegisterNamedItemInput) -> RegisterNamedItemOutput:
        with self._transactions.transaction():
            conversation = _required_conversation(
                self._conversations,
                request.conversation_id,
            )
            if request.declaration_message_id is not None:
                message = _validated_source_message(
                    self._messages,
                    request.declaration_message_id,
                    conversation_id=conversation.id,
                )
                if message is None:  # pragma: no cover - guarded by the input mode
                    raise AssertionError("Declaration mode requires a source message.")
                declaration = parse_named_item_declaration(message.original_text)
                if declaration is None:
                    raise LifecycleInvariantError(
                        "Named-item declaration message does not match the canonical grammar."
                    )
                display_name = declaration.display_name
                normalized_name = declaration.normalized_name
                project_id = conversation.project_id
                source_message_id = message.id
            else:
                display_name = normalize_display_label(
                    request.explicit_ui_label  # type: ignore[arg-type]
                )
                if not display_name:
                    raise LifecycleInvariantError(
                        "Explicit UI named-item label must be non-empty after normalization."
                    )
                normalized_name = normalize_phrase(display_name)
                project_id = request.selected_project_id
                source_message_id = None

            active = _project_activity(self._projects, project_id)
            owner_id, entity_id = _registration_ids(self._id_generator)
            now = self._clock.now()
            named_item = NamedItem(
                owner_id,
                conversation.id,
                project_id,
                display_name,
                normalized_name,
                source_message_id,
                now,
                now,
            )
            entity = Entity(
                entity_id,
                EntityType.NAMED_ITEM,
                named_item.id,
                named_item.project_id,
                named_item.display_name,
                named_item.normalized_name,
                named_item.source_message_id,
                active,
                now,
                now,
            )
            self._entities.add_named_item(named_item, entity)
        return RegisterNamedItemOutput(named_item, entity)


__all__ = [
    "RegisterNamedItemService",
    "RegisterProjectService",
    "RegisterTaskService",
    "RegisterTopicService",
]
