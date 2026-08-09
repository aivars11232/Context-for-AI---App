"""Qt integration tests for the finite TASK-0017 manual worker role."""

from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    ContextInspectionEmptyResult,
    InitialUiPreferences,
    MemoryInspectionEmptyResult,
    ShellReadyResult,
    UiTheme,
    ValidationHistoryEmptyResult,
)
from context_for_ai.domain.enums import MemoryStatus
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.ui import ShellFacade
from tests.integration.test_context_inspection_facade import (
    BlockingForeground,
    BlockingInspection,
    CombinedScopeFactory,
    preacceptance_cancellation,
)


def identifier(number: int) -> DomainId:
    return DomainId(f"98000000-0000-4000-8000-{number:012d}")


@pytest.fixture(scope="module")
def qt_application() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    return application


def wait_until(
    application: QCoreApplication,
    predicate: object,
    *,
    timeout: float = 5,
) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():  # type: ignore[operator]
        application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out while pumping the Qt event loop.")
        time.sleep(0.001)
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


class FixedKeys:
    def new_key(self) -> DomainId:
        return identifier(999)


class BlockingUseCase:
    def __init__(self, result: object) -> None:
        self.result = result
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[object, int]] = []

    def execute(self, request: object) -> object:
        self.calls.append((request, threading.get_ident()))
        self.entered.set()
        assert self.release.wait(timeout=5)
        return self.result


@dataclass(slots=True)
class ManualScope:
    use_case: BlockingUseCase
    opened_thread_id: int
    close_calls: int = 0
    closed_thread_id: int | None = None

    @property
    def inspect_memories(self) -> BlockingUseCase:
        return self.use_case

    @property
    def create_memory_with_guidance(self) -> BlockingUseCase:
        return self.use_case

    @property
    def edit_memory_for_presentation(self) -> BlockingUseCase:
        return self.use_case

    @property
    def soft_delete_memory_for_presentation(self) -> BlockingUseCase:
        return self.use_case

    @property
    def inspect_projects(self) -> BlockingUseCase:
        return self.use_case

    @property
    def select_project_for_presentation(self) -> BlockingUseCase:
        return self.use_case

    @property
    def archive_project_for_presentation(self) -> BlockingUseCase:
        return self.use_case

    @property
    def inspect_validation_history(self) -> BlockingUseCase:
        return self.use_case

    @property
    def inspect_manual_settings(self) -> BlockingUseCase:
        return self.use_case

    @property
    def update_manual_settings(self) -> BlockingUseCase:
        return self.use_case

    def close(self) -> None:
        self.close_calls += 1
        self.closed_thread_id = threading.get_ident()


class ManualScopeFactory:
    def __init__(self, use_cases: list[BlockingUseCase]) -> None:
        self.use_cases = use_cases
        self.scopes: list[ManualScope] = []
        self.open_thread_ids: list[int] = []

    def open_manual_operations_scope(self) -> ManualScope:
        thread_id = threading.get_ident()
        scope = ManualScope(self.use_cases[len(self.scopes)], thread_id)
        self.open_thread_ids.append(thread_id)
        self.scopes.append(scope)
        return scope


class ThreeWorkerFactory(CombinedScopeFactory):
    def __init__(
        self,
        inspection: BlockingInspection,
        foreground: BlockingForeground,
        manual: BlockingUseCase,
    ) -> None:
        super().__init__([inspection], foreground)
        self.manual = manual
        self.manual_scopes: list[ManualScope] = []

    def open_manual_operations_scope(self) -> ManualScope:
        scope = ManualScope(self.manual, threading.get_ident())
        self.manual_scopes.append(scope)
        return scope


def ready_facade(
    factory: ManualScopeFactory,
    *,
    context_visible: bool = True,
) -> ShellFacade:
    facade = ShellFacade(
        factory,  # type: ignore[arg-type]
        FixedKeys(),
        initial_preferences=InitialUiPreferences(UiTheme.SYSTEM, context_visible),
    )
    facade.apply_preparation(ShellReadyResult(identifier(1), False))
    return facade


def finish(
    application: QCoreApplication,
    facade: ShellFacade,
    use_cases: list[BlockingUseCase],
) -> None:
    for use_case in use_cases:
        use_case.release.set()
    wait_until(application, lambda: facade._manual.active_operation_id is None)
    facade.dispose()
    facade.deleteLater()
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_manual_load_is_responsive_finite_and_scope_thread_owned(
    qt_application: QApplication,
) -> None:
    use_case = BlockingUseCase(
        MemoryInspectionEmptyResult(
            MemoryStatus.ACTIVE,
            "2026-08-09 12:00:00 UTC",
        )
    )
    factory = ManualScopeFactory([use_case])
    facade = ready_facade(factory)
    gui_thread_id = threading.get_ident()
    try:
        assert facade.navigate_to_memory() is True
        wait_until(qt_application, use_case.entered.is_set)
        assert facade.route == "MEMORY"
        assert facade.memory_page_state == "LOADING"
        assert facade.memory_status_text == "Loading memories."

        responsive: list[bool] = []
        QTimer.singleShot(0, lambda: responsive.append(True))
        wait_until(qt_application, lambda: responsive == [True])

        use_case.release.set()
        wait_until(
            qt_application,
            lambda: facade.memory_page_state == "EMPTY"
            and facade._manual.active_operation_id is None,
        )
        worker_thread_id = use_case.calls[0][1]
        scope = factory.scopes[0]
        assert worker_thread_id != gui_thread_id
        assert factory.open_thread_ids == [worker_thread_id]
        assert scope.opened_thread_id == worker_thread_id
        assert scope.closed_thread_id == worker_thread_id
        assert scope.close_calls == 1
    finally:
        finish(qt_application, facade, [use_case])


def test_latest_pending_read_replaces_earlier_routes(
    qt_application: QApplication,
) -> None:
    first = BlockingUseCase(
        MemoryInspectionEmptyResult(
            MemoryStatus.ACTIVE,
            "2026-08-09 12:00:00 UTC",
        )
    )
    latest = BlockingUseCase(ValidationHistoryEmptyResult())
    factory = ManualScopeFactory([first, latest])
    facade = ready_facade(factory)
    try:
        assert facade.navigate_to_memory() is True
        wait_until(qt_application, first.entered.is_set)
        assert facade.navigate_to_projects() is True
        assert facade.navigate_to_validation_history() is True
        assert facade._manual.pending_read_route.value == "VALIDATION_HISTORY"
        assert len(factory.scopes) == 1

        first.release.set()
        wait_until(qt_application, latest.entered.is_set)
        assert len(factory.scopes) == 2
        assert facade.route == "VALIDATION_HISTORY"
        assert facade.memory_page_state == "INACTIVE"

        latest.release.set()
        wait_until(
            qt_application,
            lambda: facade.validation_history_page_state == "EMPTY"
            and facade._manual.active_operation_id is None,
        )
        assert len(factory.scopes) == 2
    finally:
        finish(qt_application, facade, [first, latest])


def test_context_visibility_guard_and_shutdown_wait_for_manual_worker(
    qt_application: QApplication,
) -> None:
    use_case = BlockingUseCase(
        MemoryInspectionEmptyResult(
            MemoryStatus.ACTIVE,
            "2026-08-09 12:00:00 UTC",
        )
    )
    factory = ManualScopeFactory([use_case])
    facade = ready_facade(factory, context_visible=False)
    shutdown_ready: list[bool] = []
    facade.shutdownReady.connect(lambda: shutdown_ready.append(True))
    try:
        assert facade.context_navigation_visible is False
        assert facade.navigate_to_context_inspection() is False
        assert facade.route == "CHAT"

        assert facade.navigate_to_memory() is True
        wait_until(qt_application, use_case.entered.is_set)
        facade.request_shutdown()
        assert facade.memory_page_state == "SHUTDOWN"
        assert facade.progress_visible is True
        assert shutdown_ready == []

        use_case.release.set()
        wait_until(qt_application, lambda: shutdown_ready == [True])
        assert facade.progress_visible is False
        assert factory.scopes[0].close_calls == 1
    finally:
        finish(qt_application, facade, [use_case])


def test_shutdown_waits_asynchronously_for_all_three_worker_roles(
    qt_application: QApplication,
) -> None:
    inspection = BlockingInspection(ContextInspectionEmptyResult())
    foreground = BlockingForeground(preacceptance_cancellation())
    manual = BlockingUseCase(
        MemoryInspectionEmptyResult(
            MemoryStatus.ACTIVE,
            "2026-08-09 12:00:00 UTC",
        )
    )
    factory = ThreeWorkerFactory(inspection, foreground, manual)
    facade = ready_facade(factory)  # type: ignore[arg-type]
    ready: list[bool] = []
    facade.shutdownReady.connect(lambda: ready.append(True))
    try:
        assert facade.submit_exact("Keep the GUI responsive") is True
        wait_until(qt_application, foreground.entered.is_set)
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, inspection.entered.is_set)
        assert facade.navigate_to_memory() is True
        wait_until(qt_application, manual.entered.is_set)

        facade.request_shutdown()
        assert facade.progress_visible is True
        assert ready == []

        manual.release.set()
        wait_until(qt_application, lambda: facade._manual.active_operation_id is None)
        assert ready == []

        inspection.release.set()
        wait_until(
            qt_application,
            lambda: facade._inspection.active_generation is None,
        )
        assert ready == []

        foreground.release.set()
        wait_until(qt_application, lambda: ready == [True])
        assert facade.progress_visible is False
        assert factory.manual_scopes[0].close_calls == 1
        assert factory.scopes[0].close_calls == 1
        assert factory.foreground_scopes[0].close_calls == 1
    finally:
        manual.release.set()
        inspection.release.set()
        foreground.release.set()
        wait_until(
            qt_application,
            lambda: facade._manual.active_operation_id is None
            and facade._inspection.active_generation is None
            and facade._controller.active_execution_id is None,
        )
        facade.dispose()
        facade.deleteLater()
        qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
