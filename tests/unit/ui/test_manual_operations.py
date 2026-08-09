"""Focused finite-state tests for the TASK-0017 manual controller."""

from __future__ import annotations

from dataclasses import dataclass
import os
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from context_for_ai.application.contracts import (
    ManualSettingKey,
    ManualSettingsUpdateSucceededResult,
    ProjectSelectionChangedResult,
    UiTheme,
)
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.ui.manual_operations import ManualOperationsController
from context_for_ai.ui.presentation import (
    ManualOperationKind,
    ManualOperationsTerminalEnvelope,
    ProjectsPageState,
    Route,
    SettingsPageState,
)


def identifier(number: int) -> DomainId:
    return DomainId(f"97000000-0000-4000-8000-{number:012d}")


@pytest.fixture(scope="module")
def qt_application() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    return application


class Owner(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.project_change_calls = 0
        self.visibility_values: list[bool] = []
        self.release_calls = 0

    def _current_project_changed(self) -> None:
        self.project_change_calls += 1

    def _apply_context_panel_visible(self, value: bool) -> None:
        self.visibility_values.append(value)

    def _owned_worker_released(self) -> None:
        self.release_calls += 1

    def _manual_announcement(self, *_: object) -> None:
        return


@dataclass(slots=True)
class Active:
    operation_id: int
    generation: int
    route: Route
    conversation_id: DomainId
    operation_kind: ManualOperationKind
    mutation: bool
    refreshed: bool = False
    thread: object = None
    worker: object = None
    terminal_consumed: bool = False
    thread_finished: bool = True


def controller(
    owner: Owner,
    *,
    theme_applier: object = lambda _theme: None,
) -> ManualOperationsController:
    value = ManualOperationsController(
        owner=owner,
        scope_factory=object(),
        theme_applier=theme_applier,  # type: ignore[arg-type]
    )
    value.set_initial_conversation(identifier(1))
    return value


def test_off_route_committed_selection_invalidates_without_reopening_page(
    qt_application: QApplication,
) -> None:
    owner = Owner()
    value = controller(owner)
    active = Active(
        operation_id=1,
        generation=1,
        route=Route.PROJECTS,
        conversation_id=identifier(1),
        operation_kind=ManualOperationKind.SELECT_PROJECT,
        mutation=True,
    )
    value._active = active  # type: ignore[assignment]
    value._route = Route.CHAT
    value._generation = 2

    value.receive_terminal(
        ManualOperationsTerminalEnvelope(
            1,
            1,
            Route.PROJECTS,
            identifier(1),
            ManualOperationKind.SELECT_PROJECT,
            ProjectSelectionChangedResult(None, 4),
        )
    )

    assert value.active_operation_id is None
    assert value.projects_state is ProjectsPageState.INACTIVE
    assert value.projects_status == ""
    assert owner.project_change_calls == 1
    assert value._project_state_version == 4


def test_shutdown_consumes_terminal_without_applying_global_effect(
    qt_application: QApplication,
) -> None:
    owner = Owner()
    value = controller(owner)
    active = Active(
        operation_id=2,
        generation=1,
        route=Route.PROJECTS,
        conversation_id=identifier(1),
        operation_kind=ManualOperationKind.SELECT_PROJECT,
        mutation=True,
    )
    value._active = active  # type: ignore[assignment]
    value.request_shutdown()

    value.receive_terminal(
        ManualOperationsTerminalEnvelope(
            2,
            1,
            Route.PROJECTS,
            identifier(1),
            ManualOperationKind.SELECT_PROJECT,
            ProjectSelectionChangedResult(None, 8),
        )
    )

    assert value.active_operation_id is None
    assert owner.project_change_calls == 0
    assert value._project_state_version == 0
    assert owner.release_calls == 1


def test_settings_apply_defect_is_safe_post_commit_presentation_failure(
    qt_application: QApplication,
) -> None:
    owner = Owner()

    def fail_theme(_theme: UiTheme) -> None:
        raise RuntimeError("UNSAFE /private/theme")

    value = controller(owner, theme_applier=fail_theme)
    value._route = Route.SETTINGS
    value._generation = 1
    value.settings_state = SettingsPageState.SAVING
    active = Active(
        operation_id=3,
        generation=1,
        route=Route.SETTINGS,
        conversation_id=identifier(1),
        operation_kind=ManualOperationKind.UPDATE_MANUAL_SETTINGS,
        mutation=True,
    )
    value._active = active  # type: ignore[assignment]

    value.receive_terminal(
        ManualOperationsTerminalEnvelope(
            3,
            1,
            Route.SETTINGS,
            identifier(1),
            ManualOperationKind.UPDATE_MANUAL_SETTINGS,
            ManualSettingsUpdateSucceededResult(
                UiTheme.DARK,
                False,
                (
                    ManualSettingKey.UI_THEME,
                    ManualSettingKey.UI_CONTEXT_PANEL_VISIBLE,
                ),
            ),
        )
    )

    assert value.settings_state is SettingsPageState.MUTATION_ERROR
    assert value.settings_status == (
        "Settings were saved but could not be applied completely. "
        "Restart the application to apply them."
    )
    assert "/private/theme" not in value.settings_status
    assert owner.visibility_values == []


def test_successful_settings_update_applies_both_preferences_before_ready(
    qt_application: QApplication,
) -> None:
    owner = Owner()
    applied_themes: list[UiTheme] = []
    value = controller(owner, theme_applier=applied_themes.append)
    value._route = Route.SETTINGS
    value._generation = 1
    value.settings_state = SettingsPageState.SAVING
    active = Active(
        operation_id=4,
        generation=1,
        route=Route.SETTINGS,
        conversation_id=identifier(1),
        operation_kind=ManualOperationKind.UPDATE_MANUAL_SETTINGS,
        mutation=True,
    )
    value._active = active  # type: ignore[assignment]

    value.receive_terminal(
        ManualOperationsTerminalEnvelope(
            4,
            1,
            Route.SETTINGS,
            identifier(1),
            ManualOperationKind.UPDATE_MANUAL_SETTINGS,
            ManualSettingsUpdateSucceededResult(
                UiTheme.DARK,
                False,
                (
                    ManualSettingKey.UI_THEME,
                    ManualSettingKey.UI_CONTEXT_PANEL_VISIBLE,
                ),
            ),
        )
    )

    assert applied_themes == [UiTheme.DARK]
    assert owner.visibility_values == [False]
    assert value.settings_state is SettingsPageState.READY
    assert value.settings_status == "Settings saved and applied."
    assert value.theme == UiTheme.DARK.value
    assert value.pending_theme == UiTheme.DARK.value
    assert value.context_panel_visible is False
    assert value.pending_context_panel_visible is False


def test_project_reselection_and_null_clear_are_facade_local_no_ops(
    qt_application: QApplication,
) -> None:
    owner = Owner()
    value = controller(owner)
    value._route = Route.PROJECTS
    value.projects_state = ProjectsPageState.READY
    value._active_project_views = (
        SimpleNamespace(private_project_id=identifier(2), is_current_association=True),
    )

    assert value.select_active_project(0) is False

    value._active_project_views = (
        SimpleNamespace(private_project_id=identifier(2), is_current_association=False),
    )
    assert value.clear_project_selection() is False
