"""Qt integration tests for the finite TASK-0016 inspection controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    CancellationCheckpoint,
    CancelledResult,
    ContextInspectionEmptyResult,
    ContextInspectionLoadFailureResult,
    ContextInspectionReadyResult,
    InspectContextRequest,
    InspectionRunOutcome,
    ShellReadyResult,
)
from context_for_ai.domain.entities import ConversationState
from context_for_ai.domain.enums import FailureCode, PipelineStage, ProcessingRunStatus
from context_for_ai.domain.lifecycle import SafeFailure
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.ui import ShellFacade
from context_for_ai.ui.presentation import InspectionTerminalEnvelope
from tests.unit.ui.test_inspection_presentation import minimal_view


def identifier(number: int) -> DomainId:
    return DomainId(f"94000000-0000-4000-8000-{number:012d}")


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


class BlockingInspection:
    def __init__(self, result: object) -> None:
        self.result = result
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[InspectContextRequest, int]] = []

    def execute(self, request: InspectContextRequest) -> object:
        self.calls.append((request, threading.get_ident()))
        self.entered.set()
        assert self.release.wait(timeout=5)
        return self.result


@dataclass(slots=True)
class InspectionScope:
    inspect_context: BlockingInspection
    opened_thread_id: int
    close_calls: int = 0
    closed_thread_id: int | None = None
    fail_on_close: bool = False

    def close(self) -> None:
        self.close_calls += 1
        self.closed_thread_id = threading.get_ident()
        if self.fail_on_close:
            raise RuntimeError("UNSAFE_INSPECTION_CLOSE /private/query.sqlite")


class InspectionScopeFactory:
    def __init__(self, inspections: list[BlockingInspection]) -> None:
        self.inspections = inspections
        self.open_thread_ids: list[int] = []
        self.scopes: list[InspectionScope] = []

    def open_inspection_scope(self) -> InspectionScope:
        thread_id = threading.get_ident()
        inspection = self.inspections[len(self.scopes)]
        scope = InspectionScope(inspection, thread_id)
        self.open_thread_ids.append(thread_id)
        self.scopes.append(scope)
        return scope

    def open_foreground_scope(self) -> object:
        raise AssertionError("Inspection must not open a foreground scope.")

    def open_startup_scope(self) -> object:
        raise AssertionError("Facade must not reopen startup scope.")


class DefectiveInspection(BlockingInspection):
    def execute(self, request: InspectContextRequest) -> object:
        self.calls.append((request, threading.get_ident()))
        self.entered.set()
        raise RuntimeError("UNSAFE_INSPECTION_EXECUTION /private/query.sqlite")


class DefectScopeFactory(InspectionScopeFactory):
    def __init__(self, inspection: BlockingInspection, mode: str) -> None:
        super().__init__([inspection])
        self.mode = mode

    def open_inspection_scope(self) -> InspectionScope:
        if self.mode == "open":
            raise RuntimeError("UNSAFE_INSPECTION_OPEN /private/query.sqlite")
        scope = super().open_inspection_scope()
        if self.mode == "close":
            scope.fail_on_close = True
        return scope


class BlockingForeground:
    def __init__(self, result: object | None = None) -> None:
        self.result = object() if result is None else result
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[object, object, int]] = []

    def execute(self, request: object, token: object) -> object:
        self.calls.append((request, token, threading.get_ident()))
        self.entered.set()
        assert self.release.wait(timeout=5)
        return self.result


@dataclass(slots=True)
class ForegroundScope:
    process_user_message: BlockingForeground
    recover_processing_run: object
    close_calls: int = 0
    closed_thread_id: int | None = None

    def close(self) -> None:
        self.close_calls += 1
        self.closed_thread_id = threading.get_ident()


class CombinedScopeFactory(InspectionScopeFactory):
    def __init__(
        self,
        inspections: list[BlockingInspection],
        foreground: BlockingForeground,
    ) -> None:
        super().__init__(inspections)
        self.foreground = foreground
        self.foreground_scopes: list[ForegroundScope] = []

    def open_foreground_scope(self) -> ForegroundScope:
        scope = ForegroundScope(self.foreground, object())
        self.foreground_scopes.append(scope)
        return scope


def ready_facade(factory: InspectionScopeFactory) -> ShellFacade:
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    facade.apply_preparation(ShellReadyResult(identifier(1), False))
    return facade


def preacceptance_cancellation() -> CancelledResult:
    return CancelledResult(
        None,
        None,
        None,
        None,
        None,
        None,
        FailureCode.CANCELLED_BY_USER,
        CancellationCheckpoint.BEFORE_ACCEPTANCE,
        None,
        False,
    )


def accepted_cancellation() -> CancelledResult:
    run_id = identifier(700)
    created_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    state = ConversationState(
        identifier(1),
        None,
        None,
        None,
        None,
        (),
        0,
        created_at,
    )
    failure = SafeFailure(
        identifier(702),
        run_id,
        PipelineStage.CONTEXT,
        FailureCode.CANCELLED_BY_USER,
        "The request was cancelled.",
        {},
        True,
        created_at,
    )
    return CancelledResult(
        run_id,
        identifier(701),
        ProcessingRunStatus.CANCELLED,
        state,
        None,
        None,
        FailureCode.CANCELLED_BY_USER,
        CancellationCheckpoint.AFTER_ACCEPTANCE,
        failure,
        True,
    )


def finish_and_dispose(
    application: QCoreApplication,
    facade: ShellFacade,
    inspections: list[BlockingInspection],
) -> None:
    for inspection in inspections:
        inspection.release.set()
    wait_until(
        application,
        lambda: facade._inspection.active_generation is None,  # type: ignore[attr-defined]
    )
    facade.dispose()
    facade.deleteLater()
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_first_load_is_responsive_finite_and_scope_thread_owned(
    qt_application: QCoreApplication,
) -> None:
    inspection = BlockingInspection(ContextInspectionEmptyResult())
    factory = InspectionScopeFactory([inspection])
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    gui_thread_id = threading.get_ident()
    try:
        assert facade.route == "CHAT"
        assert facade.inspection_page_state == "INACTIVE"
        assert facade.inspection_status_text == ""
        assert facade.inspection_announcement_revision == 0
        assert facade.navigate_to_context_inspection() is False

        facade.apply_preparation(ShellReadyResult(identifier(1), False))
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, inspection.entered.is_set)

        assert facade.route == "CONTEXT_INSPECTION"
        assert facade.inspection_page_state == "LOADING"
        assert facade.inspection_status_text == "Loading context inspection…"
        assert facade.inspection_refresh_enabled is False
        assert facade.inspection_has_view is False
        assert facade.inspection_announcement_text == "Loading context inspection."
        assert facade.inspection_announcement_revision == 1

        sentinels: list[bool] = []
        QTimer.singleShot(0, lambda: sentinels.append(True))
        wait_until(qt_application, lambda: sentinels == [True])

        inspection.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "EMPTY"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        request, use_case_thread_id = inspection.calls[0]
        scope = factory.scopes[0]
        assert request == InspectContextRequest(identifier(1))
        assert use_case_thread_id != gui_thread_id
        assert factory.open_thread_ids == [use_case_thread_id]
        assert scope.opened_thread_id == use_case_thread_id
        assert scope.closed_thread_id == use_case_thread_id
        assert scope.close_calls == 1
        assert facade.inspection_status_text == (
            "No processed request is available for this conversation."
        )
        assert facade.inspection_refresh_enabled is True
        assert facade.inspection_announcement_revision == 2
    finally:
        finish_and_dispose(qt_application, facade, [inspection])


def test_repeated_refreshes_collapse_into_exactly_one_latest_follow_up(
    qt_application: QCoreApplication,
) -> None:
    first = BlockingInspection(ContextInspectionLoadFailureResult())
    second = BlockingInspection(ContextInspectionEmptyResult())
    factory = InspectionScopeFactory([first, second])
    facade = ready_facade(factory)
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, first.entered.is_set)
        first_generation = facade._inspection.active_generation  # type: ignore[attr-defined]
        assert first_generation == 1

        assert facade.navigate_to_context_inspection() is True
        assert facade.refresh_context_inspection() is True
        assert facade.refresh_context_inspection() is True
        assert len(factory.scopes) == 1
        assert facade._inspection.refresh_required is True  # type: ignore[attr-defined]
        assert facade.inspection_page_state == "LOADING"
        assert facade.inspection_announcement_revision == 4

        first.release.set()
        wait_until(qt_application, second.entered.is_set)
        assert len(factory.scopes) == 2
        assert facade._inspection.active_generation == 4  # type: ignore[attr-defined]
        assert facade.inspection_page_state == "LOADING"
        assert facade.inspection_announcement_revision == 4

        second.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "EMPTY"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        assert len(factory.scopes) == 2
        assert facade.inspection_announcement_revision == 5
        assert all(scope.close_calls == 1 for scope in factory.scopes)
    finally:
        finish_and_dispose(qt_application, facade, [first, second])


def test_wrong_duplicate_and_navigation_away_deliveries_are_harmless(
    qt_application: QCoreApplication,
) -> None:
    inspection = BlockingInspection(ContextInspectionLoadFailureResult())
    factory = InspectionScopeFactory([inspection])
    facade = ready_facade(factory)
    conversation_id = identifier(1)
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, inspection.entered.is_set)
        generation = facade._inspection.active_generation  # type: ignore[attr-defined]
        assert generation is not None

        facade._inspection_terminal_received(
            InspectionTerminalEnvelope(
                generation + 1,
                conversation_id,
                ContextInspectionEmptyResult(),
            )
        )
        facade._inspection_terminal_received(
            InspectionTerminalEnvelope(
                generation,
                identifier(2),
                ContextInspectionEmptyResult(),
            )
        )
        assert facade.inspection_page_state == "LOADING"
        assert facade.inspection_announcement_revision == 1

        accepted = InspectionTerminalEnvelope(
            generation,
            conversation_id,
            ContextInspectionEmptyResult(),
        )
        facade._inspection_terminal_received(accepted)
        assert facade.inspection_page_state == "EMPTY"
        assert facade.inspection_announcement_revision == 2
        facade._inspection_terminal_received(
            InspectionTerminalEnvelope(
                generation,
                conversation_id,
                ContextInspectionLoadFailureResult(),
            )
        )
        assert facade.inspection_page_state == "EMPTY"
        assert facade.inspection_announcement_revision == 2

        assert facade.navigate_to_chat() is True
        assert facade.route == "CHAT"
        assert facade.inspection_page_state == "INACTIVE"
        assert facade.inspection_status_text == ""
        assert facade.inspection_has_view is False
        inspection.release.set()
        wait_until(
            qt_application,
            lambda: facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        facade._inspection_terminal_received(accepted)
        assert facade.route == "CHAT"
        assert facade.inspection_page_state == "INACTIVE"
        assert facade.inspection_announcement_revision == 2
    finally:
        finish_and_dispose(qt_application, facade, [inspection])


def test_shutdown_with_inspection_only_is_nonblocking_and_waits_for_close(
    qt_application: QCoreApplication,
) -> None:
    inspection = BlockingInspection(ContextInspectionEmptyResult())
    factory = InspectionScopeFactory([inspection])
    facade = ready_facade(factory)
    ready_threads: list[int] = []
    facade.shutdownReady.connect(lambda: ready_threads.append(threading.get_ident()))
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, inspection.entered.is_set)
        started = time.monotonic()
        facade.request_shutdown()
        elapsed = time.monotonic() - started

        assert elapsed < 0.1
        assert facade.state == "SHUTDOWN"
        assert facade.inspection_page_state == "SHUTDOWN"
        assert facade.inspection_status_text == ""
        assert facade.inspection_has_view is False
        assert facade.progress_visible is True
        assert facade.progress_label == "Closing safely…"
        assert facade.navigate_to_chat() is False
        assert facade.navigate_to_context_inspection() is False
        assert facade.refresh_context_inspection() is False
        assert ready_threads == []

        sentinels: list[bool] = []
        QTimer.singleShot(0, lambda: sentinels.append(True))
        wait_until(qt_application, lambda: sentinels == [True])
        inspection.release.set()
        wait_until(qt_application, lambda: len(ready_threads) == 1)

        assert ready_threads == [threading.get_ident()]
        assert factory.scopes[0].close_calls == 1
        assert factory.scopes[0].closed_thread_id == inspection.calls[0][1]
        assert facade.progress_visible is False
        facade.request_shutdown()
        assert len(ready_threads) == 1
    finally:
        finish_and_dispose(qt_application, facade, [inspection])


def test_joint_shutdown_waits_for_foreground_and_inspection_independently(
    qt_application: QCoreApplication,
) -> None:
    inspection = BlockingInspection(ContextInspectionEmptyResult())
    foreground = BlockingForeground()
    factory = CombinedScopeFactory([inspection], foreground)
    facade = ready_facade(factory)
    ready: list[bool] = []
    facade.shutdownReady.connect(lambda: ready.append(True))
    try:
        assert facade.navigate_to_context_inspection() is True
        assert facade.submit_exact("foreground and inspection") is True
        wait_until(qt_application, inspection.entered.is_set)
        wait_until(qt_application, foreground.entered.is_set)

        facade.request_shutdown()
        assert foreground.calls[0][1].is_cancelled() is True
        assert ready == []

        inspection.release.set()
        wait_until(
            qt_application,
            lambda: facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        assert ready == []
        assert facade.progress_visible is True

        foreground.release.set()
        wait_until(qt_application, lambda: ready == [True])
        assert facade._controller.active_execution_id is None  # type: ignore[attr-defined]
        assert facade._inspection.active_generation is None  # type: ignore[attr-defined]
        assert factory.scopes[0].close_calls == 1
        assert factory.foreground_scopes[0].close_calls == 1
        assert factory.foreground_scopes[0].closed_thread_id == foreground.calls[0][2]
        assert facade.progress_visible is False
    finally:
        inspection.release.set()
        foreground.release.set()
        finish_and_dispose(qt_application, facade, [inspection])


def test_refresh_clears_prior_view_before_load_error_is_applied(
    qt_application: QCoreApplication,
) -> None:
    first = BlockingInspection(ContextInspectionReadyResult(minimal_view()))
    second = BlockingInspection(ContextInspectionLoadFailureResult())
    factory = InspectionScopeFactory([first, second])
    facade = ready_facade(factory)
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, first.entered.is_set)
        first.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "READY"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        assert facade.inspection_has_view is True

        assert facade.refresh_context_inspection() is True
        assert facade.inspection_page_state == "LOADING"
        assert facade.inspection_status_text == "Loading context inspection…"
        assert facade.inspection_has_view is False
        wait_until(qt_application, second.entered.is_set)
        second.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "LOAD_ERROR"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        assert facade.inspection_status_text == (
            "Context inspection could not be loaded safely."
        )
        assert facade.inspection_has_view is False
        assert facade.inspection_refresh_enabled is True
    finally:
        finish_and_dispose(qt_application, facade, [first, second])


def test_conversation_project_and_terminal_invalidations_coalesce_to_latest_target(
    qt_application: QCoreApplication,
) -> None:
    first = BlockingInspection(ContextInspectionEmptyResult())
    second = BlockingInspection(ContextInspectionEmptyResult())
    factory = InspectionScopeFactory([first, second])
    facade = ready_facade(factory)
    latest_conversation = identifier(2)
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, first.entered.is_set)

        assert facade._current_project_changed() is True  # type: ignore[attr-defined]
        assert facade._current_conversation_changed(latest_conversation) is True  # type: ignore[attr-defined]
        facade._current_conversation_terminal()  # type: ignore[attr-defined]
        assert len(factory.scopes) == 1
        assert facade.conversation_id == str(latest_conversation)
        assert facade.inspection_page_state == "LOADING"
        assert facade.inspection_announcement_revision == 4

        first.release.set()
        wait_until(qt_application, second.entered.is_set)
        assert len(factory.scopes) == 2
        assert second.calls[0][0] == InspectContextRequest(latest_conversation)
        assert facade.inspection_announcement_revision == 4
        second.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "EMPTY"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        assert facade.inspection_announcement_revision == 5

        assert facade.navigate_to_chat() is True
        assert facade._current_project_changed() is False  # type: ignore[attr-defined]
        assert len(factory.scopes) == 2
    finally:
        finish_and_dispose(qt_application, facade, [first, second])


@pytest.mark.parametrize(
    ("foreground_result", "triggers_refresh"),
    (
        (preacceptance_cancellation(), False),
        (accepted_cancellation(), True),
    ),
)
def test_only_durably_accepted_foreground_cancellation_invalidates_inspection(
    qt_application: QCoreApplication,
    foreground_result: CancelledResult,
    triggers_refresh: bool,
) -> None:
    first = BlockingInspection(ContextInspectionEmptyResult())
    follow_up = BlockingInspection(ContextInspectionEmptyResult())
    foreground = BlockingForeground(foreground_result)
    inspections = [first, follow_up] if triggers_refresh else [first]
    factory = CombinedScopeFactory(inspections, foreground)
    facade = ready_facade(factory)
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, first.entered.is_set)
        first.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "EMPTY"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )

        assert facade.submit_exact("cancellation trigger boundary") is True
        wait_until(qt_application, foreground.entered.is_set)
        foreground.release.set()
        wait_until(
            qt_application,
            lambda: facade.state == "CANCELLED"
            and facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )

        if triggers_refresh:
            wait_until(qt_application, follow_up.entered.is_set)
            assert facade.inspection_page_state == "LOADING"
            assert len(factory.scopes) == 2
            follow_up.release.set()
            wait_until(
                qt_application,
                lambda: facade.inspection_page_state == "EMPTY"
                and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
            )
        else:
            qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
            assert len(factory.scopes) == 1
            assert facade.inspection_page_state == "EMPTY"
            assert facade.inspection_announcement_revision == 2
    finally:
        foreground.release.set()
        finish_and_dispose(qt_application, facade, inspections)


@pytest.mark.parametrize(
    ("outcome", "expected_state", "expected_status"),
    (
        (
            InspectionRunOutcome.PROCESSING,
            "READY",
            "Context inspection loaded.",
        ),
        (
            InspectionRunOutcome.SUCCEEDED,
            "READY",
            "Context inspection loaded.",
        ),
        (
            InspectionRunOutcome.CANCELLED,
            "READY",
            "Context inspection loaded.",
        ),
        (
            InspectionRunOutcome.CLARIFICATION,
            "CLARIFICATION",
            "Context inspection loaded. Clarification is required.",
        ),
        (
            InspectionRunOutcome.CONTROLLED_FAILURE,
            "CONTROLLED_FAILURE",
            "Context inspection loaded. Processing ended with a controlled failure.",
        ),
    ),
)
def test_queued_ready_outcome_selects_exact_facade_page_state(
    qt_application: QCoreApplication,
    outcome: InspectionRunOutcome,
    expected_state: str,
    expected_status: str,
) -> None:
    inspection = BlockingInspection(
        ContextInspectionReadyResult(minimal_view(outcome))
    )
    factory = InspectionScopeFactory([inspection])
    facade = ready_facade(factory)
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, inspection.entered.is_set)
        inspection.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == expected_state
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        assert facade.inspection_status_text == expected_status
        assert facade.inspection_has_view is True
        assert facade.inspection_refresh_enabled is True
    finally:
        finish_and_dispose(qt_application, facade, [inspection])


def test_held_inspection_does_not_block_foreground_cancellation_or_gui_events(
    qt_application: QCoreApplication,
) -> None:
    inspection = BlockingInspection(ContextInspectionEmptyResult())
    foreground = BlockingForeground(preacceptance_cancellation())
    factory = CombinedScopeFactory([inspection], foreground)
    facade = ready_facade(factory)
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(qt_application, inspection.entered.is_set)
        assert facade.submit_exact("cancel while inspection is held") is True
        wait_until(qt_application, foreground.entered.is_set)

        responsive: list[bool] = []
        QTimer.singleShot(0, lambda: responsive.append(True))
        wait_until(qt_application, lambda: responsive == [True])
        assert facade.request_cancellation() is True
        assert facade.state == "CANCELLATION_REQUESTED"
        assert foreground.calls[0][1].is_cancelled() is True
        assert facade._inspection.active_generation is not None  # type: ignore[attr-defined]

        foreground.release.set()
        wait_until(
            qt_application,
            lambda: facade.state == "CANCELLED"
            and facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )
        assert facade.inspection_page_state == "LOADING"
        assert len(factory.scopes) == 1
        inspection.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "EMPTY"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        assert len(factory.scopes) == 1
        assert factory.foreground_scopes[0].closed_thread_id == foreground.calls[0][2]
        assert factory.scopes[0].closed_thread_id == inspection.calls[0][1]
        assert foreground.calls[0][2] != inspection.calls[0][1]
    finally:
        foreground.release.set()
        finish_and_dispose(qt_application, facade, [inspection])


@pytest.mark.parametrize("mode", ["open", "execute", "close"])
def test_inspection_worker_defects_are_content_free_load_errors(
    qt_application: QCoreApplication,
    mode: str,
) -> None:
    inspection: BlockingInspection
    if mode == "execute":
        inspection = DefectiveInspection(ContextInspectionEmptyResult())
    else:
        inspection = BlockingInspection(ContextInspectionEmptyResult())
        inspection.release.set()
    factory = DefectScopeFactory(inspection, mode)
    facade = ready_facade(factory)
    try:
        assert facade.navigate_to_context_inspection() is True
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "LOAD_ERROR"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        assert facade.inspection_status_text == (
            "Context inspection could not be loaded safely."
        )
        assert facade.inspection_announcement_text == (
            "Context inspection could not be loaded safely."
        )
        assert facade.inspection_has_view is False
        safe_surface = (
            facade.inspection_status_text + facade.inspection_announcement_text
        )
        assert "UNSAFE_INSPECTION" not in safe_surface
        assert "/private/" not in safe_surface
        if mode == "open":
            assert factory.scopes == []
        else:
            assert factory.scopes[0].close_calls == 1
    finally:
        finish_and_dispose(qt_application, facade, [inspection])
