"""TASK-0017-owned AT-014 manual-operations acceptance slices."""

from __future__ import annotations

import ast
from dataclasses import fields, replace
from decimal import Decimal
import os
from pathlib import Path

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    ArchiveProjectPresentationRequest,
    CreateMemoryPresentationRequest,
    EditMemoryPresentationRequest,
    InspectManualSettingsRequest,
    InspectMemoriesRequest,
    InspectProjectsRequest,
    ManualOperationsApplicationScope,
    ManualSettingKey,
    ManualSettingsReadyResult,
    ManualSettingsUpdateSucceededResult,
    MemoryDuplicateDecision,
    MemoryDuplicateGuidanceResult,
    MemoryInspectionReadyResult,
    MemoryMutationStaleResult,
    MemoryMutationSucceededResult,
    ProjectArchiveSucceededResult,
    ProjectInspectionReadyResult,
    ProjectSelectionChangedResult,
    ProjectSelectionUnchangedResult,
    SelectProjectPresentationRequest,
    SettingUpdate,
    SoftDeleteMemoryPresentationRequest,
    StartupApplicationScope,
    UiTheme,
    UpdateManualSettingsRequest,
)
from context_for_ai.domain.entities import Project
from context_for_ai.domain.enums import (
    MemoryScope,
    MemoryStatus,
    MemoryType,
    ProjectStatus,
)
from context_for_ai.infrastructure.configuration import load_configuration
from context_for_ai.infrastructure.database import (
    SQLiteProjectRepository,
    connect_database,
)
from context_for_ai.ui import (
    MemoryPageState,
    ProjectsPageState,
    Route,
    SettingsPageState,
    ShellFacade,
    ShellState,
    ValidationHistoryPageState,
)
from context_for_ai.ui.presentation import (
    ManualOperationKind,
    ManualOperationsTerminalEnvelope,
)
from tests.integration.test_manual_operations_facade import (
    test_shutdown_waits_asynchronously_for_all_three_worker_roles as exercise_three_worker_shutdown,
)
from tests.integration.test_manual_operations_qml import (
    test_all_manual_pages_render_populated_safe_models_and_accessibility as exercise_manual_accessibility,
)
from tests.integration.test_manual_operations_qml import (
    test_duplicate_guidance_dialog_is_native_advisory_and_focuses_return as exercise_duplicate_accessibility,
)
from tests.integration.test_manual_operations_sqlite import (
    NOW as SQLITE_NOW,
)
from tests.integration.test_manual_operations_sqlite import (
    factory as production_factory,
)
from tests.integration.test_manual_operations_sqlite import (
    identifier as sqlite_identifier,
)
from tests.unit.application.test_manual_validation_history import (
    test_attempts_and_correction_project_safely_without_candidate_or_provider_data as exercise_validation_redaction,
)
from tests.unit.application.test_manual_validation_history import (
    test_latest_target_uses_user_message_sequence_not_run_time as exercise_latest_validation_target,
)


REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def qt_application() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    QAccessible.setActive(True)
    return application


def _execute(factory: object, use_case: str, request: object) -> object:
    scope = factory.open_manual_operations_scope()  # type: ignore[attr-defined]
    try:
        return getattr(scope, use_case).execute(request)
    finally:
        scope.close()


def test_task_0017_at_014_closed_contract_and_qml_boundary() -> None:
    assert tuple(Route) == (
        Route.CHAT,
        Route.CONTEXT_INSPECTION,
        Route.MEMORY,
        Route.PROJECTS,
        Route.VALIDATION_HISTORY,
        Route.SETTINGS,
    )
    assert tuple(MemoryPageState) == tuple(
        MemoryPageState(value)
        for value in (
            "INACTIVE",
            "LOADING",
            "READY",
            "EMPTY",
            "EDITING",
            "DUPLICATE_GUIDANCE",
            "DELETE_CONFIRMATION",
            "SAVING",
            "LOAD_ERROR",
            "MUTATION_ERROR",
            "SHUTDOWN",
        )
    )
    assert tuple(ProjectsPageState) == tuple(
        ProjectsPageState(value)
        for value in (
            "INACTIVE",
            "LOADING",
            "READY",
            "EMPTY",
            "ARCHIVE_CONFIRMATION",
            "SAVING",
            "LOAD_ERROR",
            "MUTATION_ERROR",
            "SHUTDOWN",
        )
    )
    assert tuple(ValidationHistoryPageState) == tuple(
        ValidationHistoryPageState(value)
        for value in (
            "INACTIVE",
            "LOADING",
            "READY",
            "EMPTY",
            "LOAD_ERROR",
            "SHUTDOWN",
        )
    )
    assert tuple(SettingsPageState) == tuple(
        SettingsPageState(value)
        for value in (
            "INACTIVE",
            "LOADING",
            "READY",
            "SAVING",
            "VALIDATION_ERROR",
            "LOAD_ERROR",
            "MUTATION_ERROR",
            "SHUTDOWN",
        )
    )
    assert tuple(state.value for state in ShellState) == (
        "STARTUP",
        "RECOVERY",
        "IDLE",
        "PENDING",
        "CANCELLATION_REQUESTED",
        "CANCELLED",
        "CLARIFICATION",
        "SUCCESS",
        "CONTROLLED_FAILURE",
        "BUSY",
        "EXISTING_RUN",
        "PERSISTENCE_FAILURE",
        "RECOVERY_FAILURE",
        "SHUTDOWN",
    )

    facade_actions = (
        "navigate_to_memory",
        "refresh_memories",
        "set_memory_filter",
        "select_memory",
        "begin_create_memory",
        "begin_edit_memory",
        "submit_memory_editor",
        "return_from_duplicate_guidance",
        "proceed_with_duplicate_create",
        "request_memory_soft_delete",
        "cancel_memory_soft_delete",
        "confirm_memory_soft_delete",
        "navigate_to_projects",
        "refresh_projects",
        "select_active_project",
        "clear_project_selection",
        "request_project_archive",
        "cancel_project_archive",
        "confirm_project_archive",
        "navigate_to_validation_history",
        "refresh_validation_history",
        "navigate_to_settings",
        "refresh_settings",
        "set_pending_theme",
        "set_pending_context_panel_visible",
        "save_settings",
    )
    assert all(callable(ShellFacade.__dict__.get(name)) for name in facade_actions)
    assert set(StartupApplicationScope.__annotations__) == {
        "prepare_application_shell",
        "load_initial_ui_preferences",
    }
    assert set(ManualOperationsApplicationScope.__annotations__) == {
        "inspect_memories",
        "create_memory_with_guidance",
        "edit_memory_for_presentation",
        "soft_delete_memory_for_presentation",
        "inspect_projects",
        "select_project_for_presentation",
        "archive_project_for_presentation",
        "inspect_validation_history",
        "inspect_manual_settings",
        "update_manual_settings",
    }
    assert tuple(item.name for item in fields(ManualOperationsTerminalEnvelope)) == (
        "operation_id",
        "generation",
        "route",
        "conversation_id",
        "operation_kind",
        "result",
    )
    assert tuple(kind.value for kind in ManualOperationKind) == (
        "INSPECT_MEMORIES",
        "CREATE_MEMORY",
        "EDIT_MEMORY",
        "SOFT_DELETE_MEMORY",
        "INSPECT_PROJECTS",
        "SELECT_PROJECT",
        "ARCHIVE_PROJECT",
        "INSPECT_VALIDATION_HISTORY",
        "INSPECT_MANUAL_SETTINGS",
        "UPDATE_MANUAL_SETTINGS",
    )

    qml_directory = REPOSITORY_ROOT / "src/context_for_ai/ui/qml"
    main_source = (qml_directory / "Main.qml").read_text(encoding="utf-8")
    qml_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(qml_directory.rglob("*.qml"))
    )
    navigation_ids = (
        "chatNavigationItem",
        "contextInspectionNavigation",
        "memoryNavigation",
        "projectsNavigation",
        "validationHistoryNavigation",
        "settingsNavigation",
    )
    assert tuple(main_source.index(value) for value in navigation_ids) == tuple(
        sorted(main_source.index(value) for value in navigation_ids)
    )
    for component in (
        "MemoryPage",
        "ProjectsPage",
        "ValidationHistoryPage",
        "SettingsPage",
    ):
        assert f"{component} {{" in main_source
        assert (qml_directory / "components" / f"{component}.qml").is_file()
    for prohibited in (
        "sqlite",
        "repository",
        "ModelGateway",
        "ContextPacket",
        "packet_json",
        "SELECT ",
        "Timer {",
    ):
        assert prohibited not in qml_source
    for accessible_id in (
        "memoryDuplicateDialog",
        "memoryDeleteDialog",
        "projectArchiveDialog",
        "validationHistoryAttempts",
        "validationHistoryCorrections",
        "settingsConfiguration",
        "settingsConfigurationFingerprint",
    ):
        assert f'Accessible.id: "{accessible_id}"' in qml_source

    presentation_trees = tuple(
        ast.parse((REPOSITORY_ROOT / path).read_text(encoding="utf-8"))
        for path in (
            "src/context_for_ai/ui/manual_operations.py",
            "src/context_for_ai/ui/shell.py",
        )
    )
    called_attributes = {
        node.func.attr
        for tree in presentation_trees
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "wait" not in called_attributes
    assert "terminate" not in called_attributes


def test_task_0017_at_014_real_sqlite_memory_guidance_history_and_traces(
    fixture_application_root: Path,
    tmp_path: Path,
) -> None:
    factory, trace, _, prepared = production_factory(
        fixture_application_root,
        tmp_path,
    )
    create_request = CreateMemoryPresentationRequest(
        conversation_id=prepared.conversation_id,
        memory_type=MemoryType.USER_PREFERENCE,
        scope=MemoryScope.CONVERSATION,
        content="Keep terminal context precise.",
        keywords=("terminal", "context"),
        topic_terms=("precision",),
        importance=Decimal("0.8"),
        confidence=Decimal("0.9"),
        expires_at=None,
        source_description="Created manually",
        duplicate_decision=MemoryDuplicateDecision.CHECK,
    )

    created = _execute(
        factory,
        "create_memory_with_guidance",
        create_request,
    )
    assert isinstance(created, MemoryMutationSucceededResult)
    first_id = created.affected.private_memory_id
    assert first_id is not None

    guidance = _execute(
        factory,
        "create_memory_with_guidance",
        create_request,
    )
    assert isinstance(guidance, MemoryDuplicateGuidanceResult)
    assert tuple(item.content for item in guidance.candidates) == (
        "Keep terminal context precise.",
    )
    assert tuple(event.event_name for event in trace.events) == ("memory_created",)
    assert str(first_id) not in repr(guidance)

    proceeded = _execute(
        factory,
        "create_memory_with_guidance",
        replace(
            create_request,
            duplicate_decision=MemoryDuplicateDecision.PROCEED,
            source_description="Created separately",
        ),
    )
    assert isinstance(proceeded, MemoryMutationSucceededResult)
    assert proceeded.affected.private_memory_id != first_id

    edited = _execute(
        factory,
        "edit_memory_for_presentation",
        EditMemoryPresentationRequest(
            first_id,
            1,
            "Keep terminal context exact.",
            ("terminal", "exact"),
            ("precision",),
            Decimal("0.7"),
            Decimal("0.85"),
            None,
            "Edited manually",
        ),
    )
    assert isinstance(edited, MemoryMutationSucceededResult)
    assert edited.revision_number == 2

    stale = _execute(
        factory,
        "edit_memory_for_presentation",
        EditMemoryPresentationRequest(
            first_id,
            1,
            "This stale value must not persist.",
            (),
            (),
            Decimal("0.5"),
            Decimal("0.5"),
            None,
            "Stale attempt",
        ),
    )
    assert isinstance(stale, MemoryMutationStaleResult)

    deleted = _execute(
        factory,
        "soft_delete_memory_for_presentation",
        SoftDeleteMemoryPresentationRequest(first_id, 2, "Deleted manually"),
    )
    assert isinstance(deleted, MemoryMutationSucceededResult)
    assert deleted.revision_number == 3

    active = _execute(
        factory,
        "inspect_memories",
        InspectMemoriesRequest(MemoryStatus.ACTIVE),
    )
    removed = _execute(
        factory,
        "inspect_memories",
        InspectMemoriesRequest(MemoryStatus.DELETED, first_id),
    )
    assert isinstance(active, MemoryInspectionReadyResult)
    assert len(active.view.items) == 1
    assert isinstance(removed, MemoryInspectionReadyResult)
    assert removed.view.selected_ordinal == 1
    details = removed.view.items[0].details
    assert details.content == "Keep terminal context exact."
    assert tuple(item.revision_number for item in details.revisions) == (1, 2, 3)
    assert tuple(item.description for item in details.sources) == (
        "Created manually",
        "Edited manually",
        "Deleted manually",
    )
    assert tuple(event.event_name for event in trace.events) == (
        "memory_created",
        "memory_created",
        "memory_edited",
        "memory_soft_deleted",
    )
    assert all(event.stage.value == "MEMORY" for event in trace.events)


def test_task_0017_at_014_real_sqlite_project_settings_and_configuration(
    fixture_application_root: Path,
    tmp_path: Path,
) -> None:
    factory, _, database_path, prepared = production_factory(
        fixture_application_root,
        tmp_path,
    )
    second_project_id = sqlite_identifier(2)
    connection = connect_database(database_path)
    try:
        SQLiteProjectRepository(connection).add(
            Project(
                second_project_id,
                "Second project",
                "Durable project",
                ProjectStatus.ACTIVE,
                SQLITE_NOW,
                SQLITE_NOW,
            )
        )
    finally:
        connection.close()

    projects = _execute(
        factory,
        "inspect_projects",
        InspectProjectsRequest(prepared.conversation_id),
    )
    assert isinstance(projects, ProjectInspectionReadyResult)
    assert projects.view.conversation_state_version == 0

    changed = _execute(
        factory,
        "select_project_for_presentation",
        SelectProjectPresentationRequest(
            prepared.conversation_id,
            second_project_id,
            999,
        ),
    )
    assert isinstance(changed, ProjectSelectionChangedResult)
    assert changed.conversation_state_version == 1
    unchanged = _execute(
        factory,
        "select_project_for_presentation",
        SelectProjectPresentationRequest(
            prepared.conversation_id,
            second_project_id,
            0,
        ),
    )
    assert isinstance(unchanged, ProjectSelectionUnchangedResult)
    assert unchanged.conversation_state_version == 1

    archived = _execute(
        factory,
        "archive_project_for_presentation",
        ArchiveProjectPresentationRequest(second_project_id, True),
    )
    assert isinstance(archived, ProjectArchiveSucceededResult)
    after_archive = _execute(
        factory,
        "inspect_projects",
        InspectProjectsRequest(prepared.conversation_id),
    )
    assert isinstance(after_archive, ProjectInspectionReadyResult)
    assert after_archive.view.current_association is not None
    assert after_archive.view.current_association.display_text == (
        "Second project — Archived (current association)"
    )
    assert str(second_project_id) not in repr(after_archive)

    settings = _execute(
        factory,
        "inspect_manual_settings",
        InspectManualSettingsRequest(),
    )
    assert isinstance(settings, ManualSettingsReadyResult)
    assert settings.view.theme is UiTheme.SYSTEM
    assert settings.view.context_panel_visible is True
    configuration = settings.view.configuration
    assert tuple(category.name.value for category in configuration.categories) == (
        "Application",
        "Model",
        "Storage",
        "Memory",
        "Validation",
        "Logging",
        "Security",
    )
    assert sum(len(category.fields) for category in configuration.categories) == 19
    assert len(configuration.fingerprint) == 64
    assert {
        field.origin.display_label
        for category in configuration.categories
        for field in category.fields
    } == {"Local YAML", "Fixed MVP rule"}
    loaded = load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    rendered = repr(settings)
    assert loaded.model.name not in rendered
    assert loaded.model.base_url not in rendered
    assert str(loaded.app.data_directory) not in rendered

    updated = _execute(
        factory,
        "update_manual_settings",
        UpdateManualSettingsRequest(
            (
                SettingUpdate(ManualSettingKey.UI_THEME.value, UiTheme.DARK),
                SettingUpdate(
                    ManualSettingKey.UI_CONTEXT_PANEL_VISIBLE.value,
                    False,
                ),
            )
        ),
    )
    assert isinstance(updated, ManualSettingsUpdateSucceededResult)
    startup_scope = factory.open_startup_scope()
    try:
        preferences = startup_scope.load_initial_ui_preferences.execute()
    finally:
        startup_scope.close()
    assert preferences.theme is UiTheme.DARK
    assert preferences.context_panel_visible is False


def test_task_0017_at_014_validation_history_is_independent_and_redacted() -> None:
    exercise_latest_validation_target()
    exercise_validation_redaction()


def test_task_0017_at_014_native_pages_and_three_workers_are_accessible_async(
    qt_application: QApplication,
    fixture_application_root: Path,
) -> None:
    exercise_manual_accessibility(qt_application, fixture_application_root)
    exercise_duplicate_accessibility(qt_application)
    exercise_three_worker_shutdown(qt_application)
