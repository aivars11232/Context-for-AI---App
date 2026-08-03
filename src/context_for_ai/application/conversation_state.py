"""Application use cases for deterministic versioned conversation state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

from context_for_ai.application.contracts import (
    ApplyConversationStateTransitionInput,
    ApplyConversationStateTransitionOutput,
    ArchiveProjectInput,
    ArchiveProjectOutput,
    SelectProjectInput,
    SelectProjectOutput,
    TransitionTaskStatusInput,
    TransitionTaskStatusOutput,
)
from context_for_ai.domain.entities import (
    Conversation,
    ConversationState,
    ConversationTask,
    Project,
)
from context_for_ai.domain.enums import ProjectStatus, TaskStatus
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import (
    ConfidenceBand,
    confidence_band,
    is_terminal_task,
    require_project_transition,
    require_task_transition,
)
from context_for_ai.domain.ports.errors import (
    ConcurrencyConflictError,
    PersistenceError,
)
from context_for_ai.domain.ports.repositories import (
    ConversationRepository,
    ConversationStateRepository,
    ProcessingRunRepository,
    ProjectRepository,
    TaskRepository,
    TopicRepository,
)
from context_for_ai.domain.ports.system import Clock, TransactionBoundary
from context_for_ai.domain.state_transitions import (
    clear_terminal_active_task,
    touch_conversation_state,
    transition_conversation_state,
)
from context_for_ai.domain.value_objects import DomainId


_ResultT = TypeVar("_ResultT")
_Persist = Callable[[], None]
_VersionedBuilder = Callable[
    [ConversationState], tuple[ConversationState, _ResultT, _Persist]
]


class _RetryStateTransition(Exception):
    """Roll back one attempt before replaying its deterministic transition."""


def _required_state(
    repository: ConversationStateRepository,
    conversation_id: DomainId,
) -> ConversationState:
    state = repository.get(conversation_id)
    if state is None:
        raise PersistenceError("Conversation state does not exist.")
    return state


def _execute_versioned(
    *,
    conversation_id: DomainId,
    expected_version: int,
    states: ConversationStateRepository,
    transactions: TransactionBoundary,
    build: _VersionedBuilder[_ResultT],
) -> tuple[ConversationState, _ResultT]:
    """Run one CAS mutation and replay it once after a rolled-back conflict."""

    for attempt in range(2):
        try:
            with transactions.transaction():
                current = _required_state(states, conversation_id)
                if attempt == 0 and current.version != expected_version:
                    raise _RetryStateTransition
                next_state, result, persist = build(current)
                if next_state is not current and not states.compare_and_swap(
                    expected_version=current.version,
                    state=next_state,
                ):
                    raise _RetryStateTransition
                persist()
                return next_state, result
        except _RetryStateTransition:
            if attempt == 1:
                raise ConcurrencyConflictError(
                    "Conversation state still conflicted after one deterministic replay."
                ) from None
    raise AssertionError("The bounded conversation-state retry loop did not terminate.")


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


def _required_task(repository: TaskRepository, task_id: DomainId) -> ConversationTask:
    task = repository.get(task_id)
    if task is None:
        raise PersistenceError("Task does not exist.")
    return task


class SelectProjectService:
    """Atomically update the sole project association and touch state once."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        conversations: ConversationRepository,
        states: ConversationStateRepository,
        clock: Clock,
        transactions: TransactionBoundary,
    ) -> None:
        self._projects = projects
        self._conversations = conversations
        self._states = states
        self._clock = clock
        self._transactions = transactions

    def execute(self, request: SelectProjectInput) -> SelectProjectOutput:
        def build(
            current: ConversationState,
        ) -> tuple[ConversationState, Conversation, _Persist]:
            conversation = _required_conversation(
                self._conversations,
                request.conversation_id,
            )
            if request.project_id is not None:
                project = _required_project(self._projects, request.project_id)
                if project.status is not ProjectStatus.ACTIVE:
                    raise LifecycleInvariantError(
                        "A conversation may select only an ACTIVE project."
                    )
            if conversation.project_id == request.project_id:
                return current, conversation, lambda: None
            now = self._clock.now()
            updated_conversation = replace(
                conversation,
                project_id=request.project_id,
                updated_at=now,
            )
            next_state = touch_conversation_state(current, updated_at=now)
            return (
                next_state,
                updated_conversation,
                lambda: self._conversations.update(updated_conversation),
            )

        state, conversation = _execute_versioned(
            conversation_id=request.conversation_id,
            expected_version=request.expected_state_version,
            states=self._states,
            transactions=self._transactions,
            build=build,
        )
        return SelectProjectOutput(conversation=conversation, state=state)


class ApplyConversationStateTransitionService:
    """Apply prepared topic, task, and output proposals in one state write."""

    def __init__(
        self,
        *,
        topics: TopicRepository,
        tasks: TaskRepository,
        states: ConversationStateRepository,
        clock: Clock,
        transactions: TransactionBoundary,
    ) -> None:
        self._topics = topics
        self._tasks = tasks
        self._states = states
        self._clock = clock
        self._transactions = transactions

    def execute(
        self,
        request: ApplyConversationStateTransitionInput,
    ) -> ApplyConversationStateTransitionOutput:
        def build(
            current: ConversationState,
        ) -> tuple[ConversationState, ConversationTask | None, _Persist]:
            now = self._clock.now()
            topic = request.topic
            if (
                topic is not None
                and confidence_band(topic.confidence) is ConfidenceBand.HIGH
            ):
                stored_topic = self._topics.get(topic.topic_id)
                if (
                    stored_topic is None
                    or stored_topic.conversation_id != request.conversation_id
                ):
                    raise LifecycleInvariantError(
                        "A selected topic must belong to the state conversation."
                    )

            selected_task: ConversationTask | None = None
            stored_task: ConversationTask | None = None
            task = request.task
            if (
                task is not None
                and confidence_band(task.confidence) is ConfidenceBand.HIGH
            ):
                stored_task = _required_task(self._tasks, task.task_id)
                if stored_task.conversation_id != request.conversation_id:
                    raise LifecycleInvariantError(
                        "A selected task must belong to the state conversation."
                    )
                if is_terminal_task(stored_task.status):
                    raise LifecycleInvariantError("An active task cannot be terminal.")
                selected_task = (
                    replace(
                        stored_task,
                        status=TaskStatus.IN_PROGRESS,
                        updated_at=now,
                    )
                    if stored_task.status is TaskStatus.OPEN
                    else stored_task
                )

            output = request.output
            next_state = transition_conversation_state(
                current,
                topic_id=None if topic is None else topic.topic_id,
                topic_confidence=None if topic is None else topic.confidence,
                task_id=None if task is None else task.task_id,
                task_confidence=None if task is None else task.confidence,
                intent=None if output is None else output.intent,
                expected_output_type=(
                    None if output is None else output.expected_output_type
                ),
                output_confidence=None if output is None else output.confidence,
                updated_at=now,
            )

            def persist() -> None:
                if selected_task is not None and selected_task != stored_task:
                    self._tasks.update(selected_task)

            return next_state, selected_task, persist

        state, selected_task = _execute_versioned(
            conversation_id=request.conversation_id,
            expected_version=request.expected_state_version,
            states=self._states,
            transactions=self._transactions,
            build=build,
        )
        return ApplyConversationStateTransitionOutput(
            state=state,
            selected_task=selected_task,
        )


class TransitionTaskStatusService:
    """Apply explicit terminal or reopen operations with active-state cleanup."""

    def __init__(
        self,
        *,
        tasks: TaskRepository,
        states: ConversationStateRepository,
        clock: Clock,
        transactions: TransactionBoundary,
    ) -> None:
        self._tasks = tasks
        self._states = states
        self._clock = clock
        self._transactions = transactions

    def execute(
        self,
        request: TransitionTaskStatusInput,
    ) -> TransitionTaskStatusOutput:
        def build(
            current: ConversationState,
        ) -> tuple[ConversationState, ConversationTask, _Persist]:
            task = _required_task(self._tasks, request.task_id)
            if task.conversation_id != request.conversation_id:
                raise LifecycleInvariantError(
                    "A task-status transition must use its owning conversation."
                )
            if request.target_status is TaskStatus.IN_PROGRESS:
                raise LifecycleInvariantError(
                    "A task becomes IN_PROGRESS only when explicitly selected."
                )
            if task.status is request.target_status:
                return current, task, lambda: None
            require_task_transition(task.status, request.target_status)
            now = self._clock.now()
            next_state = (
                clear_terminal_active_task(
                    current,
                    task_id=task.id,
                    updated_at=now,
                )
                if is_terminal_task(request.target_status)
                else current
            )
            updated_task = replace(
                task,
                status=request.target_status,
                updated_at=now,
            )
            return next_state, updated_task, lambda: self._tasks.update(updated_task)

        state, task = _execute_versioned(
            conversation_id=request.conversation_id,
            expected_version=request.expected_state_version,
            states=self._states,
            transactions=self._transactions,
            build=build,
        )
        return TransitionTaskStatusOutput(task=task, state=state)


class ArchiveProjectService:
    """Apply the explicit archive lifecycle operation used by AT-003."""

    def __init__(
        self,
        *,
        projects: ProjectRepository,
        conversations: ConversationRepository,
        processing_runs: ProcessingRunRepository,
        clock: Clock,
        transactions: TransactionBoundary,
    ) -> None:
        self._projects = projects
        self._conversations = conversations
        self._processing_runs = processing_runs
        self._clock = clock
        self._transactions = transactions

    def execute(self, request: ArchiveProjectInput) -> ArchiveProjectOutput:
        with self._transactions.transaction():
            project = _required_project(self._projects, request.project_id)
            active_run = self._processing_runs.get_non_terminal()
            active_run_is_for_project = False
            if active_run is not None:
                conversation = _required_conversation(
                    self._conversations,
                    active_run.conversation_id,
                )
                active_run_is_for_project = conversation.project_id == project.id
            require_project_transition(
                project.status,
                ProjectStatus.ARCHIVED,
                has_non_terminal_run=active_run_is_for_project,
            )
            archived = replace(
                project,
                status=ProjectStatus.ARCHIVED,
                updated_at=self._clock.now(),
            )
            self._projects.update(archived)
        return ArchiveProjectOutput(project=archived)


__all__ = [
    "ApplyConversationStateTransitionService",
    "ArchiveProjectService",
    "SelectProjectService",
    "TransitionTaskStatusService",
]
