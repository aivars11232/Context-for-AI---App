"""Immutable canonical entities for the dependency-free domain layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from context_for_ai.domain.enums import (
    EntityType,
    LocalActor,
    MemoryRevisionOperation,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    MessageRole,
    OutputType,
    ProjectStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    ensure_utc,
)


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _optional_text(field_name: str, value: str | None) -> None:
    if value is not None and not isinstance(value, str):
        raise LifecycleInvariantError(f"{field_name} must be text or null.")


def _normalize_time(instance: object, field_name: str) -> datetime:
    value = ensure_utc(getattr(instance, field_name))
    object.__setattr__(instance, field_name, value)
    return value


def _normalize_optional_time(instance: object, field_name: str) -> datetime | None:
    raw_value = getattr(instance, field_name)
    if raw_value is None:
        return None
    value = ensure_utc(raw_value)
    object.__setattr__(instance, field_name, value)
    return value


def _validate_time_order(created_at: datetime, updated_at: datetime) -> None:
    if updated_at < created_at:
        raise LifecycleInvariantError("updated_at cannot precede created_at.")


def _freeze_text_values(field_name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(values, str):
        raise LifecycleInvariantError(f"{field_name} must be a collection of text values.")
    frozen = tuple(values)
    if any(not isinstance(value, str) for value in frozen):
        raise LifecycleInvariantError(f"{field_name} may contain only text values.")
    return frozen


@dataclass(frozen=True, slots=True)
class Project:
    id: DomainId
    name: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _required_text("Project.name", self.name)
        _optional_text("Project.description", self.description)
        created_at = _normalize_time(self, "created_at")
        updated_at = _normalize_time(self, "updated_at")
        _validate_time_order(created_at, updated_at)


@dataclass(frozen=True, slots=True)
class Conversation:
    id: DomainId
    project_id: DomainId | None
    title: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _optional_text("Conversation.title", self.title)
        created_at = _normalize_time(self, "created_at")
        updated_at = _normalize_time(self, "updated_at")
        _validate_time_order(created_at, updated_at)


@dataclass(frozen=True, slots=True)
class Topic:
    id: DomainId
    conversation_id: DomainId
    label: str
    normalized_label: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _required_text("Topic.label", self.label)
        _required_text("Topic.normalized_label", self.normalized_label)
        created_at = _normalize_time(self, "created_at")
        updated_at = _normalize_time(self, "updated_at")
        _validate_time_order(created_at, updated_at)


@dataclass(frozen=True, slots=True)
class ConversationTask:
    id: DomainId
    conversation_id: DomainId
    topic_id: DomainId | None
    title: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _required_text("ConversationTask.title", self.title)
        created_at = _normalize_time(self, "created_at")
        updated_at = _normalize_time(self, "updated_at")
        _validate_time_order(created_at, updated_at)


@dataclass(frozen=True, slots=True)
class ConversationState:
    conversation_id: DomainId
    active_topic_id: DomainId | None
    active_task_id: DomainId | None
    previous_task_id: DomainId | None
    expected_output_type: OutputType | None
    topic_stack: tuple[DomainId, ...]
    version: int
    updated_at: datetime

    def __post_init__(self) -> None:
        topic_stack = tuple(self.topic_stack)
        object.__setattr__(self, "topic_stack", topic_stack)
        if len(topic_stack) > 10:
            raise LifecycleInvariantError("ConversationState.topic_stack is limited to 10 IDs.")
        if len(set(topic_stack)) != len(topic_stack):
            raise LifecycleInvariantError("ConversationState.topic_stack cannot contain duplicates.")
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or self.version < 0
        ):
            raise LifecycleInvariantError("ConversationState.version must be non-negative.")
        _normalize_time(self, "updated_at")


@dataclass(frozen=True, slots=True)
class Message:
    id: DomainId
    conversation_id: DomainId
    role: MessageRole
    original_text: str
    created_at: datetime
    sequence_number: int

    def __post_init__(self) -> None:
        if not isinstance(self.original_text, str):
            raise LifecycleInvariantError("Message.original_text must be exact text.")
        if (
            not isinstance(self.sequence_number, int)
            or isinstance(self.sequence_number, bool)
            or self.sequence_number < 0
        ):
            raise LifecycleInvariantError("Message.sequence_number must be non-negative.")
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class NamedItem:
    id: DomainId
    conversation_id: DomainId
    project_id: DomainId | None
    display_name: str
    normalized_name: str
    source_message_id: DomainId | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _required_text("NamedItem.display_name", self.display_name)
        _required_text("NamedItem.normalized_name", self.normalized_name)
        created_at = _normalize_time(self, "created_at")
        updated_at = _normalize_time(self, "updated_at")
        _validate_time_order(created_at, updated_at)


@dataclass(frozen=True, slots=True)
class Entity:
    id: DomainId
    entity_type: EntityType
    native_id: DomainId
    project_id: DomainId | None
    display_name: str
    normalized_name: str
    source_message_id: DomainId | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _required_text("Entity.display_name", self.display_name)
        _required_text("Entity.normalized_name", self.normalized_name)
        if not isinstance(self.is_active, bool):
            raise LifecycleInvariantError("Entity.is_active must be boolean.")
        created_at = _normalize_time(self, "created_at")
        updated_at = _normalize_time(self, "updated_at")
        _validate_time_order(created_at, updated_at)


@dataclass(frozen=True, slots=True)
class Memory:
    id: DomainId
    conversation_id: DomainId | None
    project_id: DomainId | None
    memory_type: MemoryType
    scope: MemoryScope
    status: MemoryStatus
    content: str
    keywords: tuple[str, ...]
    topic_terms: tuple[str, ...]
    importance: UnitScore
    confidence: UnitScore
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise LifecycleInvariantError("Memory.content must be text.")
        object.__setattr__(self, "keywords", _freeze_text_values("Memory.keywords", self.keywords))
        object.__setattr__(
            self,
            "topic_terms",
            _freeze_text_values("Memory.topic_terms", self.topic_terms),
        )
        created_at = _normalize_time(self, "created_at")
        updated_at = _normalize_time(self, "updated_at")
        _validate_time_order(created_at, updated_at)
        expires_at = _normalize_optional_time(self, "expires_at")
        deleted_at = _normalize_optional_time(self, "deleted_at")

        if self.scope is MemoryScope.CONVERSATION and self.conversation_id is None:
            raise LifecycleInvariantError("Conversation-scoped memory requires conversation_id.")
        if self.scope is MemoryScope.PROJECT and self.project_id is None:
            raise LifecycleInvariantError("Project-scoped memory requires project_id.")
        if self.scope is MemoryScope.GLOBAL and (
            self.conversation_id is not None or self.project_id is not None
        ):
            raise LifecycleInvariantError("Global memory cannot have conversation_id or project_id.")
        if self.status is MemoryStatus.ACTIVE and deleted_at is not None:
            raise LifecycleInvariantError("Active memory requires null deleted_at.")
        if self.status is MemoryStatus.DELETED and deleted_at is None:
            raise LifecycleInvariantError("Deleted memory requires deleted_at.")
        if deleted_at is not None and deleted_at < created_at:
            raise LifecycleInvariantError("Memory.deleted_at cannot precede created_at.")
        if expires_at is not None and expires_at.tzinfo is None:
            raise LifecycleInvariantError("Memory.expires_at must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class MemorySource:
    id: DomainId
    memory_id: DomainId
    source_kind: MemorySourceKind
    source_message_id: DomainId | None
    description: str
    created_at: datetime

    def __post_init__(self) -> None:
        _required_text("MemorySource.description", self.description)
        if (
            self.source_kind is MemorySourceKind.USER_MESSAGE
            and self.source_message_id is None
        ):
            raise LifecycleInvariantError(
                "USER_MESSAGE memory source requires source_message_id."
            )
        _normalize_time(self, "created_at")


@dataclass(frozen=True, slots=True)
class MemoryRevision:
    id: DomainId
    memory_id: DomainId
    revision_number: int
    operation: MemoryRevisionOperation
    content_snapshot: str
    metadata: FrozenJsonObject
    performed_by: LocalActor
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.revision_number, int)
            or isinstance(self.revision_number, bool)
            or self.revision_number < 1
        ):
            raise LifecycleInvariantError("MemoryRevision.revision_number must be positive.")
        if not isinstance(self.content_snapshot, str):
            raise LifecycleInvariantError("MemoryRevision.content_snapshot must be text.")
        if self.performed_by is not LocalActor.LOCAL_USER:
            raise LifecycleInvariantError("Memory changes must be performed by LOCAL_USER.")
        if not isinstance(self.metadata, FrozenJsonObject):
            object.__setattr__(self, "metadata", FrozenJsonObject(self.metadata))
        _normalize_time(self, "created_at")
