"""Tests for canonical domain transition, confidence, and lifecycle policies."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from context_for_ai.domain.entities import (
    ConversationState,
    ConversationTask,
    Memory,
    MemoryRevision,
    MemorySource,
)
from context_for_ai.domain.enums import (
    LocalActor,
    MemoryEffectiveStatus,
    MemoryRevisionOperation,
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
    MEMORY_REVISION_SCHEMA_VERSION,
    ConfidenceBand,
    PriorityBand,
    confidence_band,
    memory_revision_metadata,
    memory_effective_status,
    overall_confidence,
    require_active_task_consistency,
    require_memory_provenance,
    require_memory_history,
    require_model_request_transition,
    require_priority_band,
    require_processing_run_transition,
    require_project_transition,
    require_task_transition,
    requires_confidence_clarification,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


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


def manual_history() -> tuple[
    Memory,
    tuple[MemorySource, ...],
    tuple[MemoryRevision, ...],
]:
    created = Memory(
        identifier(50),
        identifier(1),
        None,
        MemoryType.PROJECT_FACT,
        MemoryScope.CONVERSATION,
        MemoryStatus.ACTIVE,
        "First snapshot",
        ("Fact", ""),
        ("Topic",),
        UnitScore("0.5000"),
        UnitScore("1.0"),
        None,
        NOW,
        NOW,
        None,
    )
    create_source = MemorySource(
        identifier(51),
        created.id,
        MemorySourceKind.MANUAL_ENTRY,
        None,
        "Created manually",
        NOW,
    )
    create_revision = MemoryRevision(
        identifier(61),
        created.id,
        1,
        MemoryRevisionOperation.CREATE,
        created.content,
        memory_revision_metadata(created, create_source.id),
        LocalActor.LOCAL_USER,
        NOW,
    )

    edit_time = NOW + timedelta(hours=1)
    edited = replace(
        created,
        content="Edited snapshot",
        keywords=("Fact", "exact"),
        topic_terms=("Topic", "SQLite"),
        importance=UnitScore("0.75"),
        confidence=UnitScore("0.90"),
        expires_at=NOW + timedelta(days=30),
        updated_at=edit_time,
    )
    edit_source = MemorySource(
        identifier(52),
        edited.id,
        MemorySourceKind.USER_EDIT,
        None,
        "Edited manually",
        edit_time,
    )
    edit_revision = MemoryRevision(
        identifier(62),
        edited.id,
        2,
        MemoryRevisionOperation.EDIT,
        edited.content,
        memory_revision_metadata(edited, edit_source.id),
        LocalActor.LOCAL_USER,
        edit_time,
    )

    delete_time = NOW + timedelta(hours=2)
    deleted = replace(
        edited,
        status=MemoryStatus.DELETED,
        updated_at=delete_time,
        deleted_at=delete_time,
    )
    delete_source = MemorySource(
        identifier(53),
        deleted.id,
        MemorySourceKind.USER_EDIT,
        None,
        "Soft-deleted manually",
        delete_time,
    )
    delete_revision = MemoryRevision(
        identifier(63),
        deleted.id,
        3,
        MemoryRevisionOperation.SOFT_DELETE,
        deleted.content,
        memory_revision_metadata(deleted, delete_source.id),
        LocalActor.LOCAL_USER,
        delete_time,
    )
    return (
        deleted,
        (create_source, edit_source, delete_source),
        (create_revision, edit_revision, delete_revision),
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


def test_overall_confidence_uses_exact_weights_and_renormalizes_omissions() -> None:
    assert overall_confidence(interpretation=UnitScore("0.73")) == UnitScore("0.73")
    assert overall_confidence(
        interpretation=UnitScore("0.80"),
        reference_resolution=UnitScore("0.60"),
        retrieval=UnitScore("0.40"),
    ) == UnitScore("0.66")
    assert overall_confidence(
        interpretation=UnitScore("0.80"),
        retrieval=UnitScore("0.40"),
    ) == UnitScore("0.6857142857142857142857142857")


@pytest.mark.parametrize(
    ("score", "material", "expected"),
    [
        ("0.80", True, False),
        ("0.799", True, True),
        ("0.50", False, False),
        ("0.499", True, True),
        ("0", False, False),
    ],
)
def test_confidence_gate_blocks_only_material_non_high_results(
    score: str,
    material: bool,
    expected: bool,
) -> None:
    assert requires_confidence_clarification(
        UnitScore(score),
        material=material,
    ) is expected


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
                ProcessingRunStatus.CANCELLED,
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


def test_memory_revision_metadata_and_history_are_complete_and_canonical() -> None:
    current, sources, revisions = manual_history()

    require_memory_history(current, sources, revisions)

    create_metadata = revisions[0].metadata
    assert set(create_metadata) == {
        "schema_version",
        "source_id",
        "memory_type",
        "scope",
        "conversation_id",
        "project_id",
        "status",
        "keywords",
        "topic_terms",
        "importance",
        "confidence",
        "expires_at",
        "memory_created_at",
        "updated_at",
        "deleted_at",
    }
    assert create_metadata["schema_version"] == MEMORY_REVISION_SCHEMA_VERSION
    assert create_metadata["importance"] == "0.5"
    assert create_metadata["confidence"] == "1"
    assert create_metadata["updated_at"] == "2026-08-02T10:00:00Z"
    assert revisions[-1].metadata["status"] == MemoryStatus.DELETED.value
    assert revisions[-1].metadata["deleted_at"] == "2026-08-02T12:00:00Z"


def test_memory_history_rejects_noncanonical_metadata_and_revision_gaps() -> None:
    current, sources, revisions = manual_history()
    create_metadata = {
        key: revisions[0].metadata[key]
        for key in revisions[0].metadata
    }
    create_metadata["extra"] = "not allowed"

    with pytest.raises(LifecycleInvariantError, match="exactly"):
        require_memory_history(
            current,
            sources,
            (replace(revisions[0], metadata=FrozenJsonObject(create_metadata)), *revisions[1:]),
        )
    with pytest.raises(LifecycleInvariantError, match="consecutive"):
        require_memory_history(
            current,
            sources,
            (revisions[0], replace(revisions[1], revision_number=3), revisions[2]),
        )


def test_memory_history_rejects_immutable_changes_and_delete_content_changes() -> None:
    current, sources, revisions = manual_history()
    altered_edit = replace(
        current,
        memory_type=MemoryType.USER_PREFERENCE,
        status=MemoryStatus.ACTIVE,
        updated_at=revisions[1].created_at,
        deleted_at=None,
    )
    immutable_revision = replace(
        revisions[1],
        metadata=memory_revision_metadata(altered_edit, sources[1].id),
    )

    with pytest.raises(LifecycleInvariantError, match="immutable"):
        require_memory_history(
            current,
            sources,
            (revisions[0], immutable_revision, revisions[2]),
        )

    changed_delete = replace(current, content="Changed while deleting")
    changed_delete_revision = replace(
        revisions[2],
        content_snapshot=changed_delete.content,
        metadata=memory_revision_metadata(changed_delete, sources[2].id),
    )
    with pytest.raises(LifecycleInvariantError, match="preserve"):
        require_memory_history(
            changed_delete,
            sources,
            (revisions[0], revisions[1], changed_delete_revision),
        )


def test_memory_history_rejects_reused_sources_final_mismatch_and_post_delete_edit() -> None:
    current, sources, revisions = manual_history()
    edited_snapshot = replace(
        current,
        status=MemoryStatus.ACTIVE,
        updated_at=revisions[1].created_at,
        deleted_at=None,
    )
    reused_source_revision = replace(
        revisions[1],
        metadata=memory_revision_metadata(edited_snapshot, sources[0].id),
    )
    with pytest.raises(LifecycleInvariantError, match="distinct"):
        require_memory_history(
            current,
            sources,
            (revisions[0], reused_source_revision, revisions[2]),
        )

    mismatched_current = replace(edited_snapshot, content="Not the final snapshot")
    with pytest.raises(LifecycleInvariantError, match="final"):
        require_memory_history(
            mismatched_current,
            sources[:2],
            revisions[:2],
        )

    restore_time = NOW + timedelta(hours=3)
    restored = replace(
        current,
        status=MemoryStatus.ACTIVE,
        updated_at=restore_time,
        deleted_at=None,
    )
    restore_source = MemorySource(
        identifier(54),
        restored.id,
        MemorySourceKind.USER_EDIT,
        None,
        "Forbidden restore",
        restore_time,
    )
    restore_revision = MemoryRevision(
        identifier(64),
        restored.id,
        4,
        MemoryRevisionOperation.EDIT,
        restored.content,
        memory_revision_metadata(restored, restore_source.id),
        LocalActor.LOCAL_USER,
        restore_time,
    )
    with pytest.raises(LifecycleInvariantError, match="follow SOFT_DELETE"):
        require_memory_history(
            restored,
            (*sources, restore_source),
            (*revisions, restore_revision),
        )
