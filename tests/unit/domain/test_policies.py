"""Tests for canonical domain transition, confidence, and lifecycle policies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from context_for_ai.domain.entities import (
    ConversationState,
    ConversationTask,
    Memory,
    MemorySource,
)
from context_for_ai.domain.enums import (
    MemoryEffectiveStatus,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    ModelRequestStatus,
    ProcessingRunStatus,
    ProjectStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import (
    InvalidStateTransitionError,
    LifecycleInvariantError,
)
from context_for_ai.domain.policies import (
    ConfidenceBand,
    PriorityBand,
    confidence_band,
    memory_effective_status,
    require_active_task_consistency,
    require_memory_provenance,
    require_model_request_transition,
    require_priority_band,
    require_processing_run_transition,
    require_project_transition,
    require_task_transition,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"30000000-0000-4000-8000-{number:012d}")


def memory(*, status: MemoryStatus = MemoryStatus.ACTIVE, expires_at: datetime | None = None) -> Memory:
    deleted_at = NOW if status is MemoryStatus.DELETED else None
    return Memory(
        identifier(5),
        identifier(1),
        None,
        MemoryType.PROJECT_FACT,
        MemoryScope.CONVERSATION,
        status,
        "Remembered fact",
        ("fact",),
        (),
        UnitScore("0.5"),
        UnitScore("1"),
        expires_at,
        NOW - timedelta(days=1),
        NOW,
        deleted_at,
    )


def assert_exact_transitions(
    statuses: type[ProjectStatus]
    | type[TaskStatus]
    | type[ProcessingRunStatus]
    | type[ModelRequestStatus],
    expected: dict[object, set[object]],
    policy: object,
) -> None:
    for current in statuses:
        allowed: set[object] = set()
        for target in statuses:
            try:
                policy(current, target)  # type: ignore[operator]
            except InvalidStateTransitionError:
                pass
            else:
                allowed.add(target)
        assert allowed == expected[current]


def test_priority_bands_are_exact_and_unknown_numbers_are_rejected() -> None:
    assert {band.value for band in PriorityBand} == {0, 400, 500, 600, 800, 900, 1000}
    assert require_priority_band(1000) is PriorityBand.CURRENT_HARD
    with pytest.raises(LifecycleInvariantError, match="Unknown canonical"):
        require_priority_band(700)
    with pytest.raises(LifecycleInvariantError, match="integer"):
        require_priority_band(True)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        ("1", ConfidenceBand.HIGH),
        ("0.80", ConfidenceBand.HIGH),
        ("0.799", ConfidenceBand.MEDIUM),
        ("0.50", ConfidenceBand.MEDIUM),
        ("0.499", ConfidenceBand.LOW),
        ("0", ConfidenceBand.LOW),
    ],
)
def test_confidence_band_uses_unrounded_thresholds(
    score: str,
    expected: ConfidenceBand,
) -> None:
    assert confidence_band(UnitScore(score)) is expected


def test_project_transition_is_archive_only_and_blocks_active_runs() -> None:
    assert_exact_transitions(
        ProjectStatus,
        {
            ProjectStatus.ACTIVE: {ProjectStatus.ARCHIVED},
            ProjectStatus.ARCHIVED: set(),
        },
        require_project_transition,
    )
    with pytest.raises(LifecycleInvariantError, match="cannot be archived"):
        require_project_transition(
            ProjectStatus.ACTIVE,
            ProjectStatus.ARCHIVED,
            has_non_terminal_run=True,
        )


def test_task_transitions_match_explicit_start_terminal_and_reopen_rules() -> None:
    assert_exact_transitions(
        TaskStatus,
        {
            TaskStatus.OPEN: {
                TaskStatus.IN_PROGRESS,
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
            },
            TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETED, TaskStatus.CANCELLED},
            TaskStatus.COMPLETED: {TaskStatus.OPEN},
            TaskStatus.CANCELLED: {TaskStatus.OPEN},
        },
        require_task_transition,
    )


def test_processing_run_transitions_match_contract_and_terminal_states_are_final() -> None:
    assert_exact_transitions(
        ProcessingRunStatus,
        {
            ProcessingRunStatus.PERSISTED: {
                ProcessingRunStatus.CONTEXT_READY,
                ProcessingRunStatus.NEEDS_CLARIFICATION,
                ProcessingRunStatus.CONTROLLED_FAILURE,
                ProcessingRunStatus.FAILED,
            },
            ProcessingRunStatus.CONTEXT_READY: {
                ProcessingRunStatus.GENERATING,
                ProcessingRunStatus.FAILED,
                ProcessingRunStatus.CANCELLED,
            },
            ProcessingRunStatus.GENERATING: {
                ProcessingRunStatus.SUCCEEDED,
                ProcessingRunStatus.REVISING,
                ProcessingRunStatus.CONTROLLED_FAILURE,
                ProcessingRunStatus.FAILED,
                ProcessingRunStatus.CANCELLED,
            },
            ProcessingRunStatus.REVISING: {
                ProcessingRunStatus.SUCCEEDED,
                ProcessingRunStatus.REVISING,
                ProcessingRunStatus.CONTROLLED_FAILURE,
                ProcessingRunStatus.FAILED,
                ProcessingRunStatus.CANCELLED,
            },
            ProcessingRunStatus.SUCCEEDED: set(),
            ProcessingRunStatus.NEEDS_CLARIFICATION: set(),
            ProcessingRunStatus.CONTROLLED_FAILURE: set(),
            ProcessingRunStatus.FAILED: set(),
            ProcessingRunStatus.CANCELLED: set(),
        },
        require_processing_run_transition,
    )


def test_recovery_allows_only_nonterminal_run_to_failed() -> None:
    for current in (
        ProcessingRunStatus.PERSISTED,
        ProcessingRunStatus.CONTEXT_READY,
        ProcessingRunStatus.GENERATING,
        ProcessingRunStatus.REVISING,
    ):
        require_processing_run_transition(
            current,
            ProcessingRunStatus.FAILED,
            recovery=True,
        )
    with pytest.raises(InvalidStateTransitionError):
        require_processing_run_transition(
            ProcessingRunStatus.SUCCEEDED,
            ProcessingRunStatus.FAILED,
            recovery=True,
        )
    with pytest.raises(InvalidStateTransitionError):
        require_processing_run_transition(
            ProcessingRunStatus.PERSISTED,
            ProcessingRunStatus.CANCELLED,
            recovery=True,
        )


def test_model_request_transitions_are_one_way_and_terminal_states_are_final() -> None:
    assert_exact_transitions(
        ModelRequestStatus,
        {
            ModelRequestStatus.PENDING: {ModelRequestStatus.IN_FLIGHT},
            ModelRequestStatus.IN_FLIGHT: {
                ModelRequestStatus.SUCCEEDED,
                ModelRequestStatus.TIMED_OUT,
                ModelRequestStatus.CANCELLED,
                ModelRequestStatus.FAILED,
            },
            ModelRequestStatus.SUCCEEDED: set(),
            ModelRequestStatus.TIMED_OUT: set(),
            ModelRequestStatus.CANCELLED: set(),
            ModelRequestStatus.FAILED: set(),
        },
        require_model_request_transition,
    )


def test_active_task_must_match_conversation_and_be_nonterminal() -> None:
    state = ConversationState(
        identifier(1),
        None,
        identifier(2),
        None,
        None,
        (),
        0,
        NOW,
    )
    active_task = ConversationTask(
        identifier(2),
        state.conversation_id,
        None,
        "Active task",
        TaskStatus.IN_PROGRESS,
        NOW,
        NOW,
    )

    require_active_task_consistency(state, active_task)
    with pytest.raises(LifecycleInvariantError, match="cannot be terminal"):
        require_active_task_consistency(
            state,
            ConversationTask(
                active_task.id,
                active_task.conversation_id,
                None,
                active_task.title,
                TaskStatus.COMPLETED,
                NOW,
                NOW,
            ),
        )


def test_memory_provenance_and_effective_status_do_not_mutate_memory() -> None:
    active = memory(expires_at=NOW + timedelta(hours=1))
    expired = memory(expires_at=NOW - timedelta(seconds=1))
    deleted = memory(
        status=MemoryStatus.DELETED,
        expires_at=NOW - timedelta(seconds=1),
    )
    source = MemorySource(
        identifier(6),
        active.id,
        MemorySourceKind.MANUAL_ENTRY,
        None,
        "Manual entry",
        NOW,
    )

    require_memory_provenance(active, (source,))
    assert memory_effective_status(active, NOW) is MemoryEffectiveStatus.ACTIVE
    assert memory_effective_status(expired, NOW) is MemoryEffectiveStatus.EXPIRED
    assert memory_effective_status(deleted, NOW) is MemoryEffectiveStatus.DELETED
    assert expired.status is MemoryStatus.ACTIVE
    with pytest.raises(LifecycleInvariantError, match="at least one"):
        require_memory_provenance(active, ())
    with pytest.raises(LifecycleInvariantError, match="must belong"):
        require_memory_provenance(
            active,
            (
                MemorySource(
                    identifier(7),
                    identifier(99),
                    MemorySourceKind.MANUAL_ENTRY,
                    None,
                    "Wrong memory",
                    NOW,
                ),
            ),
        )
