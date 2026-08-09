"""Offscreen populated-QML and accessibility coverage for TASK-0017 pages."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time

import pytest
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt
from PySide6.QtGui import QAccessible, QAccessibleInterface
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    CanonicalLabelView,
    CorrectionHistoryView,
    InspectManualSettingsRequest,
    InspectMemoriesRequest,
    InspectProjectsRequest,
    InspectionCheckpoint,
    InspectionRunOutcome,
    InspectionScoreView,
    InspectionTargetView,
    MemoryDuplicateGuidanceResult,
    ShellReadyResult,
    ValidationAttemptOutcome,
    ValidationAttemptReportView,
    ValidationHistoryAttemptView,
    ValidationHistoryCollection,
    ValidationHistoryReadyResult,
    ValidationHistoryView,
)
from context_for_ai.application.manual_settings import InspectManualSettingsService
from context_for_ai.bootstrap.shell_composition import configuration_snapshot_from
from context_for_ai.domain.enums import MemoryStatus
from context_for_ai.infrastructure.configuration import load_configuration
from context_for_ai.main import create_qml_engine
from context_for_ai.ui import ShellFacade
from tests.qt_accessibility_recorder import AnnouncementRecorder
from tests.unit.application.test_manual_memory import (
    _create_request,
    _services as memory_services,
)
from tests.unit.application.test_manual_projects import _fixture as project_fixture
from tests.unit.application.test_manual_settings import _Boundary, _Settings


@pytest.fixture(scope="module")
def qt_application() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    QAccessible.setActive(True)
    return application


def wait_until(
    application: QApplication,
    predicate: object,
    *,
    timeout: float = 5,
) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():  # type: ignore[operator]
        application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out while pumping the QML event loop.")
        time.sleep(0.001)
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def invoke(object_: QObject, method: str) -> None:
    assert QMetaObject.invokeMethod(object_, method, Qt.ConnectionType.DirectConnection)


def interface_for(object_: QObject) -> QAccessibleInterface:
    interface = QAccessible.queryAccessibleInterface(object_)
    assert interface is not None and interface.isValid()
    return interface


def identity(interface: QAccessibleInterface) -> tuple[QAccessible.Role, str, str]:
    return (
        interface.role(),
        interface.text(QAccessible.Text.Name),
        interface.text(QAccessible.Text.Identifier),
    )


def accessible_ids(object_: QObject) -> set[str]:
    pending = [interface_for(object_)]
    values: set[str] = set()
    while pending:
        interface = pending.pop()
        identifier = interface.text(QAccessible.Text.Identifier)
        if identifier:
            values.add(identifier)
        for index in range(interface.childCount()):
            child = interface.child(index)
            if child is not None and child.isValid():
                pending.append(child)
    return values


class FixedKeys:
    def new_key(self) -> object:
        raise AssertionError("Manual page loads must not allocate idempotency keys.")


class ImmediateUseCase:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[object] = []

    def execute(self, request: object) -> object:
        self.calls.append(request)
        return self.result


@dataclass(slots=True)
class Scope:
    use_case: ImmediateUseCase
    close_calls: int = 0

    def __getattr__(self, name: str) -> ImmediateUseCase:
        if name in {
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
        }:
            return self.use_case
        raise AttributeError(name)

    def close(self) -> None:
        self.close_calls += 1


class Factory:
    def __init__(self, results: tuple[object, ...]) -> None:
        self.use_cases = [ImmediateUseCase(result) for result in results]
        self.scopes: list[Scope] = []

    def open_manual_operations_scope(self) -> Scope:
        scope = Scope(self.use_cases[len(self.scopes)])
        self.scopes.append(scope)
        return scope


def label(code: str) -> CanonicalLabelView:
    rendered = " ".join(word.lower() for word in code.split("_"))
    return CanonicalLabelView(code, rendered[0].upper() + rendered[1:])


def validation_result() -> ValidationHistoryReadyResult:
    score = InspectionScoreView("0.8", "0.80")
    first = ValidationHistoryAttemptView(
        1,
        label("INITIAL"),
        label(ValidationAttemptOutcome.VALIDATED.value),
        ValidationAttemptReportView(label("PASSED"), score, (), ()),
        "",
        None,
        None,
    )
    second = ValidationHistoryAttemptView(
        2,
        label("REVISION"),
        label(ValidationAttemptOutcome.WAITING.value),
        None,
        "Validation has not completed for this attempt.",
        None,
        1,
    )
    return ValidationHistoryReadyResult(
        ValidationHistoryView(
            InspectionTargetView(
                4,
                "Request 4",
                InspectionRunOutcome.PROCESSING,
                InspectionCheckpoint.ACCEPTED,
                "Processing",
                "Accepted",
            ),
            ValidationHistoryCollection((first, second), ""),
            (CorrectionHistoryView(1, 1, 2),),
            1,
            None,
        )
    )


def test_all_manual_pages_render_populated_safe_models_and_accessibility(
    qt_application: QApplication,
    fixture_application_root: object,
) -> None:
    memory = memory_services()
    memory["create"].execute(_create_request(memory))
    memory_result = memory["inspect"].execute(
        InspectMemoriesRequest(MemoryStatus.ACTIVE)
    )
    projects = project_fixture()
    project_result = projects.inspect.execute(
        InspectProjectsRequest(projects.conversation.id)
    )
    settings_result = InspectManualSettingsService(
        settings=_Settings(),
        snapshots=_Boundary(),
        configuration=configuration_snapshot_from(
            load_configuration(
                application_root=fixture_application_root,  # type: ignore[arg-type]
                environ={},
            )
        ),
    ).execute(InspectManualSettingsRequest())
    factory = Factory(
        (memory_result, project_result, validation_result(), settings_result)
    )
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    qml_warnings: list[str] = []
    engine.warnings.connect(
        lambda warnings: qml_warnings.extend(
            warning.toString() for warning in warnings
        )
    )
    facade.apply_preparation(ShellReadyResult(memory["conversation"].id, False))
    root = engine.rootObjects()[0]
    expected_navigation = (
        ("memoryNavigation", "Memory"),
        ("projectsNavigation", "Projects"),
        ("validationHistoryNavigation", "Validation history"),
        ("settingsNavigation", "Settings"),
    )
    try:
        for object_name, accessible_name in expected_navigation:
            navigation = root.findChild(QObject, object_name)
            assert navigation is not None
            assert identity(interface_for(navigation)) == (
                QAccessible.Role.Button,
                accessible_name,
                object_name,
            )

        with AnnouncementRecorder() as recorder:
            invoke(root.findChild(QObject, "memoryNavigation"), "clicked")
            wait_until(
                qt_application,
                lambda: facade.memory_page_state == "READY"
                and facade._manual.active_operation_id is None,
            )
            assert facade.select_memory(0) is True
            qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
            memory_list = root.findChild(QObject, "memoryList")
            assert memory_list is not None
            assert memory_list.property("count") == 1, tuple(qml_warnings)
            assert "memoryItem-1" in accessible_ids(memory_list), tuple(qml_warnings)
            assert "memorySource-1" in accessible_ids(
                root.findChild(QObject, "memorySources")
            )
            assert "memoryRevision-1" in accessible_ids(
                root.findChild(QObject, "memoryRevisions")
            )
            assert identity(interface_for(root.findChild(QObject, "memoryPage"))) == (
                QAccessible.Role.Pane,
                "Memory",
                "memoryPage",
            )
            wait_until(qt_application, lambda: len(recorder.announcements) >= 2)
            assert len(recorder.announcements) == 2

            delete_button = root.findChild(QObject, "memorySoftDelete")
            invoke(delete_button, "forceActiveFocus")
            wait_until(qt_application, lambda: delete_button.property("activeFocus"))
            invoke(delete_button, "clicked")
            wait_until(
                qt_application,
                lambda: facade.memory_page_state == "DELETE_CONFIRMATION",
            )
            delete_dialog = root.findChild(QObject, "memoryDeleteDialog")
            delete_cancel = root.findChild(QObject, "memoryDeleteCancel")
            assert identity(interface_for(delete_dialog)) == (
                QAccessible.Role.Dialog,
                "Soft-delete memory?",
                "memoryDeleteDialog",
            )
            assert interface_for(delete_dialog).text(
                QAccessible.Text.Description
            ) == (
                "This memory will remain available in Deleted with its provenance "
                "and revision history. It cannot be edited, deleted again, or restored."
            )
            wait_until(qt_application, lambda: delete_cancel.property("activeFocus"))
            invoke(delete_cancel, "clicked")
            wait_until(qt_application, lambda: facade.memory_page_state == "READY")
            wait_until(qt_application, lambda: delete_button.property("activeFocus"))
            assert len(recorder.announcements) == 2

            invoke(root.findChild(QObject, "projectsNavigation"), "clicked")
            wait_until(
                qt_application,
                lambda: facade.projects_page_state == "READY"
                and facade._manual.active_operation_id is None,
            )
            assert "activeProject-1" in accessible_ids(
                root.findChild(QObject, "activeProjectList")
            )
            assert "archivedProject-1" in accessible_ids(
                root.findChild(QObject, "archivedProjectList")
            )
            projects_status = root.findChild(QObject, "projectsStatus")
            assert projects_status is not None
            try:
                wait_until(qt_application, lambda: len(recorder.announcements) >= 4)
            except AssertionError as error:
                raise AssertionError(
                    (
                        facade.projects_announcement_revision,
                        projects_status.property("announcementRevision"),
                        projects_status.property("announcedRevision"),
                        projects_status.property("announcementText"),
                        projects_status.property("visible"),
                        recorder.announcements,
                    )
                ) from error
            assert len(recorder.announcements) == 4, recorder.announcements

            projects_page = root.findChild(QObject, "projectsPage")
            assert projects_page.setProperty("archiveRow", 0)
            assert projects_page.setProperty("archiveEligible", True)
            archive_button = root.findChild(QObject, "projectArchive")
            invoke(archive_button, "forceActiveFocus")
            wait_until(qt_application, lambda: archive_button.property("activeFocus"))
            invoke(archive_button, "clicked")
            wait_until(
                qt_application,
                lambda: facade.projects_page_state == "ARCHIVE_CONFIRMATION",
            )
            archive_dialog = root.findChild(QObject, "projectArchiveDialog")
            archive_cancel = root.findChild(QObject, "projectArchiveCancel")
            assert identity(interface_for(archive_dialog)) == (
                QAccessible.Role.Dialog,
                "Archive project?",
                "projectArchiveDialog",
            )
            assert interface_for(archive_dialog).text(
                QAccessible.Text.Description
            ) == (
                "This hides the project from new selection. Existing conversation "
                "associations, messages, memories, and project data are preserved."
            )
            wait_until(qt_application, lambda: archive_cancel.property("activeFocus"))
            invoke(archive_cancel, "clicked")
            wait_until(qt_application, lambda: facade.projects_page_state == "READY")
            wait_until(qt_application, lambda: archive_button.property("activeFocus"))
            assert len(recorder.announcements) == 4

            invoke(root.findChild(QObject, "validationHistoryNavigation"), "clicked")
            wait_until(
                qt_application,
                lambda: facade.validation_history_page_state == "READY"
                and facade._manual.active_operation_id is None,
            )
            assert "validationAttempt-1" in accessible_ids(
                root.findChild(QObject, "validationHistoryAttempts")
            )
            assert "validationCorrection-1" in accessible_ids(
                root.findChild(QObject, "validationHistoryCorrections")
            )
            wait_until(qt_application, lambda: len(recorder.announcements) >= 6)
            assert len(recorder.announcements) == 6, recorder.announcements

            invoke(root.findChild(QObject, "settingsNavigation"), "clicked")
            wait_until(
                qt_application,
                lambda: facade.settings_page_state == "READY"
                and facade._manual.active_operation_id is None,
            )
            fingerprint = root.findChild(QObject, "settingsConfigurationFingerprint")
            assert fingerprint is not None
            assert fingerprint.property("text") == (
                "Configuration fingerprint: "
                + facade.settings_configuration_fingerprint
            )
            assert len(facade.settings_configuration_fingerprint) == 64
            assert "configurationField-1-1" in accessible_ids(
                root.findChild(QObject, "settingsConfiguration")
            )
            settings_status = root.findChild(QObject, "settingsStatus")
            assert settings_status is not None
            wait_until(qt_application, lambda: len(recorder.announcements) >= 8)
            assert len(recorder.announcements) == 8, (
                facade.settings_announcement_revision,
                settings_status.property("announcementRevision"),
                settings_status.property("announcedRevision"),
                settings_status.property("announcementText"),
            )
            assert recorder.announcements[-1].message == "Settings loaded."
    finally:
        facade.request_shutdown()
        for qml_root in tuple(engine.rootObjects()):
            qml_root.close()
        engine.deleteLater()
        facade.dispose()
        facade.deleteLater()
        qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_duplicate_guidance_dialog_is_native_advisory_and_focuses_return(
    qt_application: QApplication,
) -> None:
    memory = memory_services()
    memory["create"].execute(_create_request(memory))
    inspected = memory["inspect"].execute(
        InspectMemoriesRequest(MemoryStatus.ACTIVE)
    )
    guidance = memory["create"].execute(_create_request(memory))
    assert isinstance(guidance, MemoryDuplicateGuidanceResult)
    factory = Factory((inspected, guidance))
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    facade.apply_preparation(ShellReadyResult(memory["conversation"].id, False))
    root = engine.rootObjects()[0]
    try:
        with AnnouncementRecorder() as recorder:
            invoke(root.findChild(QObject, "memoryNavigation"), "clicked")
            wait_until(
                qt_application,
                lambda: facade.memory_page_state == "READY"
                and facade._manual.active_operation_id is None,
            )
            assert facade.begin_create_memory() is True
            assert facade.submit_memory_editor(
                "PROJECT_FACT",
                "PROJECT",
                "Remember, SQLite transactions!",
                "sqlite",
                "transactions",
                "0.8",
                "0.9",
                "",
                "Explicit local note",
            ) is True
            wait_until(
                qt_application,
                lambda: facade.memory_page_state == "DUPLICATE_GUIDANCE"
                and facade._manual.active_operation_id is None,
            )

            dialog = root.findChild(QObject, "memoryDuplicateDialog")
            return_button = root.findChild(QObject, "memoryDuplicateReturn")
            assert identity(interface_for(dialog)) == (
                QAccessible.Role.Dialog,
                "Possible duplicate memories",
                "memoryDuplicateDialog",
            )
            assert interface_for(dialog).text(QAccessible.Text.Description) == (
                "Review possible duplicates before creating a separate memory."
            )
            wait_until(qt_application, lambda: return_button.property("activeFocus"))
            assert len(recorder.announcements) == 4

            invoke(return_button, "clicked")
            wait_until(qt_application, lambda: facade.memory_page_state == "EDITING")
            assert len(recorder.announcements) == 4
    finally:
        facade.request_shutdown()
        for qml_root in tuple(engine.rootObjects()):
            qml_root.close()
        engine.deleteLater()
        facade.dispose()
        facade.deleteLater()
        qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
