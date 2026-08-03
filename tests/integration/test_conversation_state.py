from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from context_for_ai.application import (
    ApplyConversationStateTransitionInput,
    ApplyConversationStateTransitionService,
    ArchiveProjectInput,
    ArchiveProjectService,
    PreparedOutputTransition,
    PreparedTaskTransition,
    PreparedTopicTransition,
    SelectProjectInput,
    SelectProjectService,
    TransitionTaskStatusInput,
    TransitionTaskStatusService,
)
from context_for_ai.domain.entities import (
    Conversation,
    ConversationState,
    ConversationTask,
    Message,
    Project,
    Topic,
)
from context_for_ai.domain.enums import (
    IntentType,
    MessageRole,
    OutputType,
    ProcessingRunStatus,
    ProjectStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.state_transitions import initial_conversation_state
from context_for_ai.domain.value_objects import DomainId, UnitScore
from context_for_ai.infrastructure.database import (
    SQLiteConversationRepository,
    SQLiteConversationStateRepository,
    SQLiteMessageRepository,
    SQLiteProcessingRunRepository,
    SQLiteProjectRepository,
    SQLiteTaskRepository,
    SQLiteTopicRepository,
    SQLiteTransactionBoundary,
    apply_migrations,
    connect_database,
)


BASE_TIME = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
HIGH = UnitScore("0.95")


def identifier(number: int) -> DomainId:
    return DomainId(f"40000000-0000-4000-8000-{number:012x}")


def stamp(seconds: int) -> datetime:
    return BASE_TIME + timedelta(seconds=seconds)


class FixedClock:
    def now(self) -> datetime:
        return stamp(100)


def repositories(connection: sqlite3.Connection) -> SimpleNamespace:
    return SimpleNamespace(
        transactions=SQLiteTransactionBoundary(connection),
        projects=SQLiteProjectRepository(connection),
        conversations=SQLiteConversationRepository(connection),
        topics=SQLiteTopicRepository(connection),
        tasks=SQLiteTaskRepository(connection),
        states=SQLiteConversationStateRepository(connection),
        messages=SQLiteMessageRepository(connection),
        runs=SQLiteProcessingRunRepository(connection),
    )


def services(bundle: SimpleNamespace) -> SimpleNamespace:
    clock = FixedClock()
    return SimpleNamespace(
        select_project=SelectProjectService(
            projects=bundle.projects,
            conversations=bundle.conversations,
            states=bundle.states,
            clock=clock,
            transactions=bundle.transactions,
        ),
        apply_state=ApplyConversationStateTransitionService(
            topics=bundle.topics,
            tasks=bundle.tasks,
            states=bundle.states,
            clock=clock,
            transactions=bundle.transactions,
        ),
        task_status=TransitionTaskStatusService(
            tasks=bundle.tasks,
            states=bundle.states,
            clock=clock,
            transactions=bundle.transactions,
        ),
        archive_project=ArchiveProjectService(
            projects=bundle.projects,
            conversations=bundle.conversations,
            processing_runs=bundle.runs,
            clock=clock,
            transactions=bundle.transactions,
        ),
    )


def test_at_003_state_lifecycle_through_public_use_cases_survives_restart(
    tmp_path: Path,
) -> None:
    database_path = apply_migrations(tmp_path / "at-003.sqlite3")
    connection = connect_database(database_path)
    bundle = repositories(connection)
    use_cases = services(bundle)

    project = Project(
        identifier(1),
        "AT-003 project",
        None,
        ProjectStatus.ACTIVE,
        stamp(0),
        stamp(0),
    )
    conversation = Conversation(identifier(2), None, "AT-003", stamp(1), stamp(1))
    topic = Topic(identifier(3), conversation.id, "State", "state", stamp(2), stamp(2))
    first_task = ConversationTask(
        identifier(4),
        conversation.id,
        topic.id,
        "First task",
        TaskStatus.OPEN,
        stamp(3),
        stamp(3),
    )
    second_task = ConversationTask(
        identifier(5),
        conversation.id,
        topic.id,
        "Second task",
        TaskStatus.OPEN,
        stamp(4),
        stamp(4),
    )
    with bundle.transactions.transaction():
        bundle.projects.add(project)
        bundle.conversations.add(conversation)
        bundle.topics.add(topic)
        bundle.tasks.add(first_task)
        bundle.tasks.add(second_task)
        bundle.states.add(initial_conversation_state(conversation.id, updated_at=stamp(5)))

    selected = use_cases.select_project.execute(
        SelectProjectInput(conversation.id, project.id, 0)
    )
    first_selected = use_cases.apply_state.execute(
        ApplyConversationStateTransitionInput(
            conversation_id=conversation.id,
            expected_state_version=selected.state.version,
            topic=PreparedTopicTransition(topic.id, HIGH),
            task=PreparedTaskTransition(first_task.id, HIGH),
            output=PreparedOutputTransition(IntentType.PLAN, OutputType.TEXT_PLAN, HIGH),
        )
    )
    continued = use_cases.apply_state.execute(
        ApplyConversationStateTransitionInput(
            conversation_id=conversation.id,
            expected_state_version=first_selected.state.version,
            output=PreparedOutputTransition(
                IntentType.CONTINUE,
                OutputType.TEXT_ANSWER,
                HIGH,
            ),
        )
    )
    second_selected = use_cases.apply_state.execute(
        ApplyConversationStateTransitionInput(
            conversation_id=conversation.id,
            expected_state_version=continued.state.version,
            task=PreparedTaskTransition(second_task.id, HIGH),
        )
    )

    assert selected.state.version == 1
    assert selected.conversation.project_id == project.id
    assert first_selected.state.version == 2
    assert continued.state == first_selected.state
    assert continued.state.active_task_id == first_task.id
    assert second_selected.state.version == 3
    assert second_selected.state.active_task_id == second_task.id
    assert second_selected.state.previous_task_id == first_task.id
    assert bundle.tasks.get(first_task.id).status is TaskStatus.IN_PROGRESS

    completed = use_cases.task_status.execute(
        TransitionTaskStatusInput(
            conversation.id,
            second_task.id,
            TaskStatus.COMPLETED,
            second_selected.state.version,
        )
    )
    assert completed.state.version == 4
    assert completed.state.active_task_id is None
    assert completed.state.previous_task_id == second_task.id
    assert completed.task.status is TaskStatus.COMPLETED

    user_message = Message(
        identifier(6),
        conversation.id,
        MessageRole.USER,
        "terminal fixture",
        stamp(20),
        0,
    )
    run = ProcessingRun(
        identifier(7),
        conversation.id,
        user_message.id,
        str(identifier(8)),
        ProcessingRunStatus.PERSISTED,
        completed.state.version,
        "task-0006-fixture",
        stamp(21),
        None,
    )
    with bundle.transactions.transaction():
        bundle.messages.add(user_message)
        bundle.runs.add(run)
        run = replace(run, status=ProcessingRunStatus.CONTEXT_READY)
        bundle.runs.update(run)
        run = replace(run, status=ProcessingRunStatus.GENERATING)
        bundle.runs.update(run)
        run = replace(
            run,
            status=ProcessingRunStatus.SUCCEEDED,
            completed_at=stamp(22),
        )
        bundle.runs.update(run)

    archived = use_cases.archive_project.execute(ArchiveProjectInput(project.id))
    assert archived.project.status is ProjectStatus.ARCHIVED
    assert bundle.conversations.get(conversation.id).project_id == project.id

    other_conversation = Conversation(identifier(9), None, None, stamp(30), stamp(30))
    with bundle.transactions.transaction():
        bundle.conversations.add(other_conversation)
        bundle.states.add(
            initial_conversation_state(other_conversation.id, updated_at=stamp(30))
        )
    with pytest.raises(LifecycleInvariantError, match="only an ACTIVE"):
        use_cases.select_project.execute(
            SelectProjectInput(other_conversation.id, project.id, 0)
        )

    connection.close()
    reopened = connect_database(database_path)
    reloaded = repositories(reopened)
    try:
        assert reloaded.projects.get(project.id).status is ProjectStatus.ARCHIVED
        assert reloaded.conversations.get(conversation.id).project_id == project.id
        assert reloaded.states.get(conversation.id) == completed.state
        assert reloaded.tasks.get(first_task.id).status is TaskStatus.IN_PROGRESS
        assert reloaded.tasks.get(second_task.id).status is TaskStatus.COMPLETED
    finally:
        reopened.close()


def test_topic_overflow_stale_replay_and_project_switch_have_one_source_of_truth(
    tmp_path: Path,
) -> None:
    database_path = apply_migrations(tmp_path / "state-switch.sqlite3")
    connection = connect_database(database_path)
    bundle = repositories(connection)
    use_cases = services(bundle)
    first_project = Project(
        identifier(20), "First", None, ProjectStatus.ACTIVE, stamp(0), stamp(0)
    )
    second_project = Project(
        identifier(21), "Second", None, ProjectStatus.ACTIVE, stamp(0), stamp(0)
    )
    conversation = Conversation(
        identifier(22), first_project.id, None, stamp(1), stamp(1)
    )
    active_task = ConversationTask(
        identifier(23),
        conversation.id,
        None,
        "Preserved task",
        TaskStatus.IN_PROGRESS,
        stamp(2),
        stamp(2),
    )
    topics = tuple(
        Topic(
            identifier(number),
            conversation.id,
            f"Topic {number}",
            f"topic {number}",
            stamp(number),
            stamp(number),
        )
        for number in range(30, 41)
    )
    with bundle.transactions.transaction():
        bundle.projects.add(first_project)
        bundle.projects.add(second_project)
        bundle.conversations.add(conversation)
        bundle.tasks.add(active_task)
        for topic in topics:
            bundle.topics.add(topic)
        bundle.states.add(
            ConversationState(
                conversation.id,
                None,
                active_task.id,
                None,
                OutputType.TEXT_CODE,
                (),
                0,
                stamp(3),
            )
        )

    current = bundle.states.get(conversation.id)
    assert current is not None
    for topic in topics:
        current = use_cases.apply_state.execute(
            ApplyConversationStateTransitionInput(
                conversation_id=conversation.id,
                expected_state_version=current.version,
                topic=PreparedTopicTransition(topic.id, HIGH),
            )
        ).state

    assert current.version == 11
    assert current.topic_stack == tuple(topic.id for topic in topics[-10:])

    replayed_from_stale_version = use_cases.apply_state.execute(
        ApplyConversationStateTransitionInput(
            conversation_id=conversation.id,
            expected_state_version=0,
            topic=PreparedTopicTransition(topics[4].id, HIGH),
        )
    ).state
    switched = use_cases.select_project.execute(
        SelectProjectInput(
            conversation.id,
            second_project.id,
            replayed_from_stale_version.version,
        )
    )

    assert replayed_from_stale_version.version == 12
    assert replayed_from_stale_version.topic_stack[-1] == topics[4].id
    assert switched.state.version == 13
    assert switched.state.topic_stack == replayed_from_stale_version.topic_stack
    assert switched.state.active_task_id == active_task.id
    assert switched.state.expected_output_type is OutputType.TEXT_CODE
    assert bundle.conversations.get(conversation.id).project_id == second_project.id
    state_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(conversation_states)")
    }
    assert "active_project_id" not in state_columns
    assert "project_id" not in state_columns
    connection.close()


def test_global_nonterminal_run_constraint_remains_a_persistence_boundary(
    tmp_path: Path,
) -> None:
    database_path = apply_migrations(tmp_path / "global-run.sqlite3")
    connection = connect_database(database_path)
    bundle = repositories(connection)
    first_conversation = Conversation(identifier(50), None, None, stamp(0), stamp(0))
    second_conversation = Conversation(identifier(51), None, None, stamp(0), stamp(0))
    first_message = Message(
        identifier(52), first_conversation.id, MessageRole.USER, "first", stamp(1), 0
    )
    second_message = Message(
        identifier(53), second_conversation.id, MessageRole.USER, "second", stamp(1), 0
    )
    first_run = ProcessingRun(
        identifier(54),
        first_conversation.id,
        first_message.id,
        str(identifier(55)),
        ProcessingRunStatus.PERSISTED,
        0,
        "fixture",
        stamp(2),
        None,
    )
    second_run = ProcessingRun(
        identifier(56),
        second_conversation.id,
        second_message.id,
        str(identifier(57)),
        ProcessingRunStatus.PERSISTED,
        0,
        "fixture",
        stamp(2),
        None,
    )
    with bundle.transactions.transaction():
        bundle.conversations.add(first_conversation)
        bundle.conversations.add(second_conversation)
        bundle.states.add(
            initial_conversation_state(first_conversation.id, updated_at=stamp(0))
        )
        bundle.states.add(
            initial_conversation_state(second_conversation.id, updated_at=stamp(0))
        )
        bundle.messages.add(first_message)
        bundle.runs.add(first_run)

    with pytest.raises(PersistenceError):
        with bundle.transactions.transaction():
            bundle.messages.add(second_message)
            bundle.runs.add(second_run)

    assert bundle.runs.get_non_terminal() == first_run
    assert bundle.messages.get(second_message.id) is None
    assert bundle.runs.get(second_run.id) is None
    connection.close()
