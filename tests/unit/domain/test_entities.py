"""Tests for immutable canonical domain entities."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from context_for_ai.domain.entities import (
    Conversation,
    ConversationState,
    ConversationTask,
    Entity,
    Memory,
    MemoryRevision,
    MemorySource,
    Message,
    NamedItem,
    Project,
    Topic,
)
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
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"00000000-0000-4000-8000-{number:012d}")


def active_memory(**changes: object) -> Memory:
    values: dict[str, object] = {
        "id": identifier(20),
        "conversation_id": identifier(2),
        "project_id": None,
        "memory_type": MemoryType.PROJECT_FACT,
        "scope": MemoryScope.CONVERSATION,
        "status": MemoryStatus.ACTIVE,
        "content": "Exact remembered text",
        "keywords": ("exact", "text"),
        "topic_terms": ("domain",),
        "importance": UnitScore("0.75"),
        "confidence": UnitScore("0.90"),
        "expires_at": None,
        "created_at": NOW,
        "updated_at": NOW,
        "deleted_at": None,
    }
    values.update(changes)
    return Memory(**values)  # type: ignore[arg-type]


def test_core_entities_retain_canonical_fields_and_exact_message_text() -> None:
    project = Project(
        identifier(1),
        "Context for AI",
        None,
        ProjectStatus.ACTIVE,
        NOW,
        NOW,
    )
    conversation = Conversation(identifier(2), project.id, "Domain work", NOW, NOW)
    topic = Topic(identifier(3), conversation.id, "Primitives", "primitives", NOW, NOW)
    task = ConversationTask(
        identifier(4),
        conversation.id,
        topic.id,
        "Implement domain types",
        TaskStatus.IN_PROGRESS,
        NOW,
        NOW,
    )
    message = Message(
        identifier(5),
        conversation.id,
        MessageRole.USER,
        "  Keep this Unicode exactly: café ☕  ",
        NOW,
        0,
    )
    named_item = NamedItem(
        identifier(6),
        conversation.id,
        project.id,
        "Domain model",
        "domain model",
        message.id,
        NOW,
        NOW,
    )
    entity = Entity(
        identifier(7),
        EntityType.NAMED_ITEM,
        named_item.id,
        project.id,
        named_item.display_name,
        named_item.normalized_name,
        message.id,
        True,
        NOW,
        NOW,
    )

    assert conversation.project_id == project.id
    assert task.topic_id == topic.id
    assert message.original_text == "  Keep this Unicode exactly: café ☕  "
    assert entity.native_id == named_item.id


def test_entities_have_value_equality_and_are_frozen() -> None:
    first = Project(identifier(1), "Project", None, ProjectStatus.ACTIVE, NOW, NOW)
    second = Project(identifier(1), "Project", None, ProjectStatus.ACTIVE, NOW, NOW)

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.name = "Changed"  # type: ignore[misc]


def test_conversation_state_freezes_stack_and_enforces_version_and_limit() -> None:
    stack = [identifier(number) for number in range(10, 20)]
    state = ConversationState(
        identifier(2),
        stack[-1],
        identifier(4),
        identifier(8),
        OutputType.TEXT_ANSWER,
        stack,  # type: ignore[arg-type]
        0,
        NOW,
    )
    stack.clear()

    assert len(state.topic_stack) == 10
    assert state.topic_stack[-1] == identifier(19)
    with pytest.raises(LifecycleInvariantError, match="limited to 10"):
        ConversationState(
            identifier(2),
            None,
            None,
            None,
            None,
            tuple(identifier(number) for number in range(30, 41)),
            0,
            NOW,
        )
    with pytest.raises(LifecycleInvariantError, match="cannot contain duplicates"):
        ConversationState(
            identifier(2),
            None,
            None,
            None,
            None,
            (identifier(3), identifier(3)),
            0,
            NOW,
        )
    with pytest.raises(LifecycleInvariantError, match="non-negative"):
        ConversationState(identifier(2), None, None, None, None, (), -1, NOW)


def test_memory_scope_and_deleted_timestamp_invariants_are_enforced() -> None:
    with pytest.raises(LifecycleInvariantError, match="requires conversation_id"):
        active_memory(conversation_id=None)
    with pytest.raises(LifecycleInvariantError, match="requires project_id"):
        active_memory(
            conversation_id=None,
            scope=MemoryScope.PROJECT,
            project_id=None,
        )
    with pytest.raises(LifecycleInvariantError, match="Global memory"):
        active_memory(scope=MemoryScope.GLOBAL)
    with pytest.raises(LifecycleInvariantError, match="requires deleted_at"):
        active_memory(status=MemoryStatus.DELETED)
    with pytest.raises(LifecycleInvariantError, match="requires null deleted_at"):
        active_memory(deleted_at=NOW)

    deleted = active_memory(
        status=MemoryStatus.DELETED,
        deleted_at=NOW + timedelta(minutes=1),
    )
    assert deleted.status is MemoryStatus.DELETED


def test_memory_source_and_revision_preserve_manual_provenance() -> None:
    memory = active_memory()
    source = MemorySource(
        identifier(21),
        memory.id,
        MemorySourceKind.MANUAL_ENTRY,
        None,
        "Entered explicitly in memory management",
        NOW,
    )
    revision = MemoryRevision(
        identifier(22),
        memory.id,
        1,
        MemoryRevisionOperation.CREATE,
        memory.content,
        FrozenJsonObject({"scope": memory.scope.value}),
        LocalActor.LOCAL_USER,
        NOW,
    )

    assert source.source_message_id is None
    assert revision.metadata["scope"] == "CONVERSATION"
    with pytest.raises(LifecycleInvariantError, match="requires source_message_id"):
        MemorySource(
            identifier(23),
            memory.id,
            MemorySourceKind.USER_MESSAGE,
            None,
            "From a user message",
            NOW,
        )
    with pytest.raises(LifecycleInvariantError, match="LOCAL_USER"):
        MemoryRevision(
            identifier(24),
            memory.id,
            2,
            MemoryRevisionOperation.EDIT,
            "Changed",
            FrozenJsonObject({}),
            LocalActor.SYSTEM_RECOVERY,
            NOW,
        )
