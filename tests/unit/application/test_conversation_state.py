from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Iterator

import pytest

from context_for_ai.application.contracts import (
    ApplyConversationStateTransitionInput,
    ArchiveProjectInput,
    PreparedOutputTransition,
    PreparedTaskTransition,
    PreparedTopicTransition,
    SelectProjectInput,
    TransitionTaskStatusInput,
)
from context_for_ai.application.conversation_state import (
    ApplyConversationStateTransitionService,
    ArchiveProjectService,
    SelectProjectService,
    TransitionTaskStatusService,
    calculate_prepared_state_transition,
)
from context_for_ai.domain.entities import (
    Conversation,
    ConversationState,
    ConversationTask,
    Project,
    Topic,
)
from context_for_ai.domain.enums import (
    IntentType,
    OutputType,
    ProcessingRunStatus,
    ProjectStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.errors import (
    ConcurrencyConflictError,
    PersistenceError,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(seconds=10)
HIGH = UnitScore("0.9")


def identifier(number: int) -> DomainId:
    return DomainId(f"30000000-0000-4000-8000-{number:012x}")


class FixedClock:
    def now(self) -> datetime:
        return LATER


class FakeProjectRepository:
    def __init__(self, *projects: Project) -> None:
        self.records = {project.id: project for project in projects}

    def get(self, project_id: DomainId) -> Project | None:
        return self.records.get(project_id)

    def update(self, project: Project) -> None:
        self.records[project.id] = project

    def capture(self) -> dict[DomainId, Project]:
        return dict(self.records)

    def restore(self, snapshot: dict[DomainId, Project]) -> None:
        self.records = snapshot


class FakeConversationRepository:
    def __init__(self, *conversations: Conversation) -> None:
        self.records = {
            conversation.id: conversation for conversation in conversations
        }
        self.update_count = 0

    def get(self, conversation_id: DomainId) -> Conversation | None:
        return self.records.get(conversation_id)

    def update(self, conversation: Conversation) -> None:
        self.records[conversation.id] = conversation
        self.update_count += 1

    def capture(self) -> tuple[dict[DomainId, Conversation], int]:
        return dict(self.records), self.update_count

    def restore(self, snapshot: tuple[dict[DomainId, Conversation], int]) -> None:
        self.records, self.update_count = snapshot


class FakeTopicRepository:
    def __init__(self, *topics: Topic) -> None:
        self.records = {topic.id: topic for topic in topics}

    def get(self, topic_id: DomainId) -> Topic | None:
        return self.records.get(topic_id)


class FakeTaskRepository:
    def __init__(self, *tasks: ConversationTask) -> None:
        self.records = {task.id: task for task in tasks}
        self.fail_update = False

    def get(self, task_id: DomainId) -> ConversationTask | None:
        return self.records.get(task_id)

    def update(self, task: ConversationTask) -> None:
        if self.fail_update:
            raise PersistenceError("Injected task update failure.")
        self.records[task.id] = task

    def capture(self) -> dict[DomainId, ConversationTask]:
        return dict(self.records)

    def restore(self, snapshot: dict[DomainId, ConversationTask]) -> None:
        self.records = snapshot


class FakeStateRepository:
    def __init__(self, state: ConversationState) -> None:
        self.state = state
        self.conflicts_remaining = 0
        self.compare_and_swap_calls = 0

    def get(self, conversation_id: DomainId) -> ConversationState | None:
        return self.state if self.state.conversation_id == conversation_id else None

    def compare_and_swap(
        self,
        *,
        expected_version: int,
        state: ConversationState,
    ) -> bool:
        self.compare_and_swap_calls += 1
        if self.conflicts_remaining:
            self.conflicts_remaining -= 1
            return False
        if self.state.version != expected_version:
            return False
        self.state = state
        return True

    def capture(self) -> ConversationState:
        return self.state

    def restore(self, snapshot: ConversationState) -> None:
        self.state = snapshot


class FakeProcessingRunRepository:
    def __init__(self, run: ProcessingRun | None = None) -> None:
        self.run = run

    def get_non_terminal(self) -> ProcessingRun | None:
        return self.run


class RollbackTransactionBoundary:
    def __init__(self, *repositories: object) -> None:
        self.repositories = repositories

    @contextmanager
    def transaction(self) -> Iterator[None]:
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


def project(number: int = 1, *, status: ProjectStatus = ProjectStatus.ACTIVE) -> Project:
    return Project(identifier(number), f"Project {number}", None, status, NOW, NOW)


def conversation(number: int = 2, project_id: DomainId | None = None) -> Conversation:
    return Conversation(identifier(number), project_id, None, NOW, NOW)


def state(
    conversation_id: DomainId,
    *,
    active_topic_id: DomainId | None = None,
    active_task_id: DomainId | None = None,
    previous_task_id: DomainId | None = None,
    expected_output_type: OutputType | None = None,
    topic_stack: tuple[DomainId, ...] = (),
    version: int = 0,
) -> ConversationState:
    return ConversationState(
        conversation_id,
        active_topic_id,
        active_task_id,
        previous_task_id,
        expected_output_type,
        topic_stack,
        version,
        NOW,
    )


def task(
    number: int,
    conversation_id: DomainId,
    *,
    status: TaskStatus = TaskStatus.OPEN,
    topic_id: DomainId | None = None,
) -> ConversationTask:
    return ConversationTask(
        identifier(number),
        conversation_id,
        topic_id,
        f"Task {number}",
        status,
        NOW,
        NOW,
    )


def test_project_switch_uses_conversation_as_sole_source_and_preserves_state() -> None:
    selected_project = project()
    stored_conversation = conversation()
    stored_state = state(
        stored_conversation.id,
        active_topic_id=identifier(3),
        active_task_id=identifier(4),
        expected_output_type=OutputType.TEXT_PLAN,
        topic_stack=(identifier(3),),
        version=2,
    )
    projects = FakeProjectRepository(selected_project)
    conversations = FakeConversationRepository(stored_conversation)
    states = FakeStateRepository(stored_state)
    service = SelectProjectService(
        projects=projects,
        conversations=conversations,
        states=states,
        clock=FixedClock(),
        transactions=RollbackTransactionBoundary(conversations, states),
    )

    result = service.execute(
        SelectProjectInput(stored_conversation.id, selected_project.id, 2)
    )
    repeated = service.execute(
        SelectProjectInput(stored_conversation.id, selected_project.id, 3)
    )

    assert result.conversation.project_id == selected_project.id
    assert result.state.version == 3
    assert result.state.active_topic_id == stored_state.active_topic_id
    assert result.state.active_task_id == stored_state.active_task_id
    assert result.state.expected_output_type == stored_state.expected_output_type
    assert repeated.state == result.state
    assert conversations.update_count == 1


def test_archived_project_cannot_be_selected() -> None:
    archived = project(status=ProjectStatus.ARCHIVED)
    stored_conversation = conversation()
    states = FakeStateRepository(state(stored_conversation.id))
    service = SelectProjectService(
        projects=FakeProjectRepository(archived),
        conversations=FakeConversationRepository(stored_conversation),
        states=states,
        clock=FixedClock(),
        transactions=RollbackTransactionBoundary(states),
    )

    with pytest.raises(LifecycleInvariantError, match="only an ACTIVE"):
        service.execute(SelectProjectInput(stored_conversation.id, archived.id, 0))


def test_prepared_transition_selects_owned_topic_and_starts_task_atomically() -> None:
    stored_conversation = conversation()
    topic = Topic(identifier(3), stored_conversation.id, "Topic", "topic", NOW, NOW)
    old_task = task(4, stored_conversation.id, status=TaskStatus.IN_PROGRESS)
    new_task = task(5, stored_conversation.id, topic_id=topic.id)
    states = FakeStateRepository(
        state(stored_conversation.id, active_task_id=old_task.id)
    )
    tasks = FakeTaskRepository(old_task, new_task)
    service = ApplyConversationStateTransitionService(
        topics=FakeTopicRepository(topic),
        tasks=tasks,
        states=states,
        clock=FixedClock(),
        transactions=RollbackTransactionBoundary(tasks, states),
    )

    result = service.execute(
        ApplyConversationStateTransitionInput(
            conversation_id=stored_conversation.id,
            expected_state_version=0,
            topic=PreparedTopicTransition(topic.id, HIGH),
            task=PreparedTaskTransition(new_task.id, HIGH),
            output=PreparedOutputTransition(
                IntentType.PLAN,
                OutputType.TEXT_PLAN,
                HIGH,
            ),
        )
    )

    assert result.state.version == 1
    assert result.state.active_topic_id == topic.id
    assert result.state.topic_stack == (topic.id,)
    assert result.state.active_task_id == new_task.id
    assert result.state.previous_task_id == old_task.id
    assert result.state.expected_output_type is OutputType.TEXT_PLAN
    assert result.selected_task is not None
    assert result.selected_task.status is TaskStatus.IN_PROGRESS
    assert tasks.get(new_task.id) == result.selected_task


def test_prepared_transition_calculation_is_pure_and_reusable() -> None:
    stored_conversation = conversation()
    selected_topic = Topic(
        identifier(3),
        stored_conversation.id,
        "Topic",
        "topic",
        NOW,
        NOW,
    )
    selected_task = task(4, stored_conversation.id, topic_id=selected_topic.id)
    original_state = state(stored_conversation.id)
    request = ApplyConversationStateTransitionInput(
        conversation_id=stored_conversation.id,
        expected_state_version=0,
        topic=PreparedTopicTransition(selected_topic.id, HIGH),
        task=PreparedTaskTransition(selected_task.id, HIGH),
        output=PreparedOutputTransition(IntentType.PLAN, OutputType.TEXT_PLAN, HIGH),
    )

    result = calculate_prepared_state_transition(
        current=original_state,
        request=request,
        stored_topic=selected_topic,
        stored_task=selected_task,
        updated_at=LATER,
    )

    assert original_state.version == 0
    assert selected_task.status is TaskStatus.OPEN
    assert result.state.version == 1
    assert result.state.active_topic_id == selected_topic.id
    assert result.state.active_task_id == selected_task.id
    assert result.state.expected_output_type is OutputType.TEXT_PLAN
    assert result.selected_task is not None
    assert result.selected_task.status is TaskStatus.IN_PROGRESS


def test_task_completion_clears_active_state_and_reopen_does_not_activate() -> None:
    stored_conversation = conversation()
    active_task = task(3, stored_conversation.id, status=TaskStatus.IN_PROGRESS)
    states = FakeStateRepository(
        state(stored_conversation.id, active_task_id=active_task.id)
    )
    tasks = FakeTaskRepository(active_task)
    service = TransitionTaskStatusService(
        tasks=tasks,
        states=states,
        clock=FixedClock(),
        transactions=RollbackTransactionBoundary(tasks, states),
    )

    completed = service.execute(
        TransitionTaskStatusInput(
            stored_conversation.id,
            active_task.id,
            TaskStatus.COMPLETED,
            0,
        )
    )
    reopened = service.execute(
        TransitionTaskStatusInput(
            stored_conversation.id,
            active_task.id,
            TaskStatus.OPEN,
            1,
        )
    )

    assert completed.state.active_task_id is None
    assert completed.state.previous_task_id == active_task.id
    assert completed.state.version == 1
    assert completed.task.status is TaskStatus.COMPLETED
    assert reopened.task.status is TaskStatus.OPEN
    assert reopened.state == completed.state


def test_state_conflict_replays_once_and_second_conflict_is_typed() -> None:
    selected_project = project()
    stored_conversation = conversation()
    projects = FakeProjectRepository(selected_project)

    conversations = FakeConversationRepository(stored_conversation)
    recovered_states = FakeStateRepository(state(stored_conversation.id))
    recovered_states.conflicts_remaining = 1
    recovered = SelectProjectService(
        projects=projects,
        conversations=conversations,
        states=recovered_states,
        clock=FixedClock(),
        transactions=RollbackTransactionBoundary(conversations, recovered_states),
    ).execute(SelectProjectInput(stored_conversation.id, selected_project.id, 0))

    conflicting_conversations = FakeConversationRepository(stored_conversation)
    conflicting_states = FakeStateRepository(state(stored_conversation.id))
    conflicting_states.conflicts_remaining = 2
    conflicting_service = SelectProjectService(
        projects=projects,
        conversations=conflicting_conversations,
        states=conflicting_states,
        clock=FixedClock(),
        transactions=RollbackTransactionBoundary(
            conflicting_conversations,
            conflicting_states,
        ),
    )

    with pytest.raises(ConcurrencyConflictError, match="after one"):
        conflicting_service.execute(
            SelectProjectInput(stored_conversation.id, selected_project.id, 0)
        )

    assert recovered.state.version == 1
    assert recovered_states.compare_and_swap_calls == 2
    assert conflicting_states.compare_and_swap_calls == 2
    assert conflicting_states.state.version == 0
    assert conflicting_conversations.get(stored_conversation.id).project_id is None


def test_failed_collaborator_write_rolls_back_state_transition() -> None:
    stored_conversation = conversation()
    active_task = task(3, stored_conversation.id, status=TaskStatus.IN_PROGRESS)
    original_state = state(stored_conversation.id, active_task_id=active_task.id)
    states = FakeStateRepository(original_state)
    tasks = FakeTaskRepository(active_task)
    tasks.fail_update = True
    service = TransitionTaskStatusService(
        tasks=tasks,
        states=states,
        clock=FixedClock(),
        transactions=RollbackTransactionBoundary(tasks, states),
    )

    with pytest.raises(PersistenceError, match="Injected"):
        service.execute(
            TransitionTaskStatusInput(
                stored_conversation.id,
                active_task.id,
                TaskStatus.CANCELLED,
                0,
            )
        )

    assert states.state == original_state
    assert tasks.get(active_task.id) == active_task


def test_archive_is_blocked_by_project_run_then_preserves_conversation() -> None:
    stored_project = project()
    stored_conversation = conversation(project_id=stored_project.id)
    run = ProcessingRun(
        identifier(10),
        stored_conversation.id,
        identifier(11),
        str(identifier(12)),
        ProcessingRunStatus.PERSISTED,
        0,
        "fixture",
        NOW,
        None,
    )
    projects = FakeProjectRepository(stored_project)
    conversations = FakeConversationRepository(stored_conversation)
    runs = FakeProcessingRunRepository(run)
    service = ArchiveProjectService(
        projects=projects,
        conversations=conversations,
        processing_runs=runs,
        clock=FixedClock(),
        transactions=RollbackTransactionBoundary(projects),
    )

    with pytest.raises(LifecycleInvariantError, match="cannot be archived"):
        service.execute(ArchiveProjectInput(stored_project.id))

    runs.run = None
    result = service.execute(ArchiveProjectInput(stored_project.id))

    assert result.project.status is ProjectStatus.ARCHIVED
    assert conversations.get(stored_conversation.id) == stored_conversation
