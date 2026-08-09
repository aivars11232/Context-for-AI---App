"""Real SQLite transaction coverage for TASK-0017 manual operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from context_for_ai.application import (
    ArchiveProjectPresentationRequest,
    CreateMemoryPresentationRequest,
    EditMemoryPresentationRequest,
    InspectManualSettingsRequest,
    InspectMemoriesRequest,
    InspectProjectsRequest,
    ManualSettingKey,
    ManualSettingsReadyResult,
    ManualSettingsUpdateSucceededResult,
    MemoryDuplicateDecision,
    MemoryInspectionReadyResult,
    MemoryMutationStaleResult,
    MemoryMutationSucceededResult,
    PrepareApplicationShellRequest,
    ProjectArchiveSucceededResult,
    ProjectInspectionReadyResult,
    ProjectSelectionChangedResult,
    ProjectSelectionUnchangedResult,
    SelectProjectPresentationRequest,
    SettingUpdate,
    ShellReadyResult,
    SoftDeleteMemoryPresentationRequest,
    UiTheme,
    UpdateManualSettingsRequest,
)
from context_for_ai.bootstrap import ProductionShellScopeFactory
from context_for_ai.domain.entities import Project
from context_for_ai.domain.enums import (
    MemoryScope,
    MemoryStatus,
    MemoryType,
    ProjectStatus,
)
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.infrastructure.configuration import load_configuration
from context_for_ai.infrastructure.database import (
    SQLiteProjectRepository,
    apply_migrations,
    connect_database,
)


NOW = datetime(2026, 8, 9, 16, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"99000000-0000-4000-8000-{number:012d}")


class IncrementingClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        value = NOW + timedelta(seconds=self.calls)
        self.calls += 1
        return value


class FixedIds:
    def __init__(self) -> None:
        self.calls = 0

    def new_id(self) -> DomainId:
        self.calls += 1
        return identifier(100 + self.calls)


class RecordingTrace:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


def factory(
    fixture_application_root: Path,
    tmp_path: Path,
) -> tuple[ProductionShellScopeFactory, RecordingTrace, Path, ShellReadyResult]:
    database_path = apply_migrations(tmp_path / "manual-operations.sqlite3")
    trace = RecordingTrace()
    value = ProductionShellScopeFactory(
        configuration=load_configuration(
            application_root=fixture_application_root,
            environ={},
        ),
        database_path=database_path,
        trace_logger=trace,
        clock=IncrementingClock(),
        id_generator=FixedIds(),
    )
    startup = value.open_startup_scope()
    prepared = startup.prepare_application_shell.execute(
        PrepareApplicationShellRequest()
    )
    startup.close()
    assert isinstance(prepared, ShellReadyResult)
    return value, trace, database_path, prepared


def test_project_replay_no_op_and_archive_preserve_association(
    fixture_application_root: Path,
    tmp_path: Path,
) -> None:
    value, _, database_path, prepared = factory(
        fixture_application_root,
        tmp_path,
    )
    second_project_id = identifier(2)
    connection = connect_database(database_path)
    SQLiteProjectRepository(connection).add(
        Project(
            second_project_id,
            "Second project",
            "Durable project",
            ProjectStatus.ACTIVE,
            NOW,
            NOW,
        )
    )
    connection.close()

    scope = value.open_manual_operations_scope()
    inspected = scope.inspect_projects.execute(
        InspectProjectsRequest(prepared.conversation_id)
    )
    scope.close()
    assert isinstance(inspected, ProjectInspectionReadyResult)
    assert inspected.view.conversation_state_version == 0

    scope = value.open_manual_operations_scope()
    changed = scope.select_project_for_presentation.execute(
        SelectProjectPresentationRequest(
            prepared.conversation_id,
            second_project_id,
            999,
        )
    )
    scope.close()
    assert isinstance(changed, ProjectSelectionChangedResult)
    assert changed.conversation_state_version == 1

    scope = value.open_manual_operations_scope()
    unchanged = scope.select_project_for_presentation.execute(
        SelectProjectPresentationRequest(
            prepared.conversation_id,
            second_project_id,
            0,
        )
    )
    scope.close()
    assert isinstance(unchanged, ProjectSelectionUnchangedResult)
    assert unchanged.conversation_state_version == 1

    scope = value.open_manual_operations_scope()
    archived = scope.archive_project_for_presentation.execute(
        ArchiveProjectPresentationRequest(second_project_id, True)
    )
    scope.close()
    assert isinstance(archived, ProjectArchiveSucceededResult)
    assert archived.archived_project.is_current_association is True

    scope = value.open_manual_operations_scope()
    after = scope.inspect_projects.execute(
        InspectProjectsRequest(prepared.conversation_id)
    )
    scope.close()
    assert isinstance(after, ProjectInspectionReadyResult)
    assert after.view.current_association is not None
    assert after.view.current_association.display_text == (
        "Second project — Archived (current association)"
    )


def test_memory_history_traces_and_settings_are_durable_across_fresh_scopes(
    fixture_application_root: Path,
    tmp_path: Path,
) -> None:
    value, trace, _, prepared = factory(fixture_application_root, tmp_path)
    create_request = CreateMemoryPresentationRequest(
        conversation_id=prepared.conversation_id,
        memory_type=MemoryType.PROJECT_FACT,
        scope=MemoryScope.CONVERSATION,
        content="Exact durable content",
        keywords=("one", ""),
        topic_terms=("topic",),
        importance=Decimal("0.8"),
        confidence=Decimal("0.9"),
        expires_at=None,
        source_description="Created manually",
        duplicate_decision=MemoryDuplicateDecision.CHECK,
    )
    scope = value.open_manual_operations_scope()
    created = scope.create_memory_with_guidance.execute(create_request)
    scope.close()
    assert isinstance(created, MemoryMutationSucceededResult)
    memory_id = created.affected.private_memory_id
    assert memory_id is not None

    scope = value.open_manual_operations_scope()
    edited = scope.edit_memory_for_presentation.execute(
        EditMemoryPresentationRequest(
            memory_id,
            1,
            "Exact edited content",
            ("one", ""),
            ("topic",),
            Decimal("0.7"),
            Decimal("0.85"),
            None,
            "Edited manually",
        )
    )
    scope.close()
    assert isinstance(edited, MemoryMutationSucceededResult)
    assert edited.revision_number == 2

    scope = value.open_manual_operations_scope()
    stale = scope.edit_memory_for_presentation.execute(
        EditMemoryPresentationRequest(
            memory_id,
            1,
            "Must not persist",
            (),
            (),
            Decimal("0.5"),
            Decimal("0.5"),
            None,
            "Stale attempt",
        )
    )
    scope.close()
    assert isinstance(stale, MemoryMutationStaleResult)

    scope = value.open_manual_operations_scope()
    deleted = scope.soft_delete_memory_for_presentation.execute(
        SoftDeleteMemoryPresentationRequest(memory_id, 2, "Deleted manually")
    )
    scope.close()
    assert isinstance(deleted, MemoryMutationSucceededResult)
    assert deleted.revision_number == 3

    scope = value.open_manual_operations_scope()
    inspected = scope.inspect_memories.execute(
        InspectMemoriesRequest(MemoryStatus.DELETED, memory_id)
    )
    scope.close()
    assert isinstance(inspected, MemoryInspectionReadyResult)
    assert inspected.view.items[0].details.content == "Exact edited content"
    assert tuple(
        revision.revision_number
        for revision in inspected.view.items[0].details.revisions
    ) == (1, 2, 3)
    assert tuple(source.description for source in inspected.view.items[0].details.sources) == (
        "Created manually",
        "Edited manually",
        "Deleted manually",
    )

    mutation_events = [
        event
        for event in trace.events
        if getattr(event, "event_name", "").startswith("memory_")
    ]
    assert tuple(event.event_name for event in mutation_events) == (
        "memory_created",
        "memory_edited",
        "memory_soft_deleted",
    )
    assert all(event.stage.value == "MEMORY" for event in mutation_events)

    scope = value.open_manual_operations_scope()
    updated = scope.update_manual_settings.execute(
        UpdateManualSettingsRequest(
            (
                SettingUpdate(ManualSettingKey.UI_THEME.value, UiTheme.DARK),
                SettingUpdate(
                    ManualSettingKey.UI_CONTEXT_PANEL_VISIBLE.value,
                    False,
                ),
            )
        )
    )
    scope.close()
    assert isinstance(updated, ManualSettingsUpdateSucceededResult)

    scope = value.open_manual_operations_scope()
    settings = scope.inspect_manual_settings.execute(InspectManualSettingsRequest())
    scope.close()
    assert isinstance(settings, ManualSettingsReadyResult)
    assert settings.view.theme is UiTheme.DARK
    assert settings.view.context_panel_visible is False
