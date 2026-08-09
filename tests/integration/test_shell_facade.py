"""Qt event-loop integration tests for the finite shell foreground worker."""

from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    CancellationCheckpoint,
    CancelledResult,
    ConfigurationErrorValue,
    ConfigurationFailureResult,
    NoRecoveryRequiredResult,
    RecoveryRequiredResult,
    ShellReadyResult,
)
from context_for_ai.domain.enums import FailureCode
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.ui import (
    ExecutionKind,
    ForegroundTerminalEnvelope,
    ShellFacade,
)


def identifier(number: int) -> DomainId:
    return DomainId(f"54000000-0000-4000-8000-{number:012x}")


def cancelled_result() -> CancelledResult:
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
    def __init__(self) -> None:
        self.calls = 0
        self.keys = (identifier(90), identifier(91))

    def new_key(self) -> DomainId:
        value = self.keys[self.calls]
        self.calls += 1
        return value


class BlockingUseCase:
    def __init__(self, result: object) -> None:
        self.result = result
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[object, object, int]] = []

    def execute(self, request: object, token: object) -> object:
        self.calls.append((request, token, threading.get_ident()))
        self.entered.set()
        assert self.release.wait(timeout=5)
        return self.result


class ImmediateUseCase:
    def __init__(self, result: object, *, raises: bool = False) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[object, object, int]] = []

    def execute(self, request: object, token: object) -> object:
        self.calls.append((request, token, threading.get_ident()))
        if self.raises:
            raise RuntimeError("secret worker defect /private/path")
        return self.result


@dataclass(slots=True)
class RecordingScope:
    process_user_message: object
    recover_processing_run: object
    opened_thread_id: int
    closed_thread_id: int | None = None
    close_calls: int = 0

    def close(self) -> None:
        self.close_calls += 1
        self.closed_thread_id = threading.get_ident()


class RecordingScopeFactory:
    def __init__(
        self,
        submission: object,
        recovery: object | None = None,
        *,
        fail_open: bool = False,
    ) -> None:
        self.submission = submission
        self.recovery = recovery or ImmediateUseCase(NoRecoveryRequiredResult())
        self.fail_open = fail_open
        self.open_thread_ids: list[int] = []
        self.scopes: list[RecordingScope] = []

    def open_foreground_scope(self) -> RecordingScope:
        thread_id = threading.get_ident()
        self.open_thread_ids.append(thread_id)
        if self.fail_open:
            raise RuntimeError("secret open defect /private/database.sqlite3")
        scope = RecordingScope(self.submission, self.recovery, thread_id)
        self.scopes.append(scope)
        return scope

    def open_startup_scope(self) -> object:
        raise AssertionError("Facade must not open a startup scope.")


def ready_facade(
    factory: RecordingScopeFactory,
    keys: FixedKeys,
) -> ShellFacade:
    facade = ShellFacade(factory, keys)  # type: ignore[arg-type]
    facade.apply_preparation(ShellReadyResult(identifier(1), False))
    return facade


def dispose_facade(application: QCoreApplication, facade: ShellFacade) -> None:
    facade.dispose()
    facade.deleteLater()
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_submission_is_exact_responsive_cancelable_and_scope_owned(
    qt_application: QCoreApplication,
) -> None:
    submission = BlockingUseCase(cancelled_result())
    factory = RecordingScopeFactory(submission)
    keys = FixedKeys()
    facade = ready_facade(factory, keys)
    gui_thread_id = threading.get_ident()
    snapshots: list[tuple[str, bool, int | None, int, bool]] = []
    gui_delivery_threads: list[QThread] = []

    def record_change() -> None:
        snapshots.append(
            (
                facade.state,
                facade.submit_enabled,
                facade._controller.active_execution_id,  # type: ignore[attr-defined]
                threading.get_ident(),
                bool(factory.scopes and factory.scopes[0].close_calls),
            )
        )
        gui_delivery_threads.append(QThread.currentThread())

    facade.changed.connect(record_change)
    exact_text = "  café ☕\nsecond line\t  "
    try:
        assert facade.route == "CHAT"
        assert facade.state == "IDLE"
        assert facade.input_enabled is True
        assert facade.submit_exact("") is False
        assert keys.calls == 0

        assert facade.submit_exact(exact_text) is True
        assert keys.calls == 1
        wait_until(qt_application, submission.entered.is_set)
        assert facade.state == "PENDING"
        assert facade.progress_visible is True
        assert facade.progress_label == "Processing…"
        assert facade.submit_exact("duplicate must remain local") is False
        assert keys.calls == 1
        assert len(submission.calls) == 1

        sentinel_processed: list[bool] = []
        QTimer.singleShot(0, lambda: sentinel_processed.append(True))
        wait_until(qt_application, lambda: sentinel_processed == [True])

        assert facade.request_cancellation() is True
        assert facade.state == "CANCELLATION_REQUESTED"
        assert facade.progress_label == "Cancelling…"
        assert facade.request_cancellation() is False
        request, token, use_case_thread_id = submission.calls[0]
        assert token.is_cancelled() is True
        assert request.user_text.encode("utf-8") == exact_text.encode("utf-8")
        assert request.project_id is None
        assert request.idempotency_key == keys.keys[0]

        submission.release.set()
        wait_until(
            qt_application,
            lambda: facade.state == "CANCELLED" and facade.submit_enabled,
        )

        scope = factory.scopes[0]
        assert factory.open_thread_ids == [use_case_thread_id]
        assert scope.opened_thread_id == use_case_thread_id
        assert scope.closed_thread_id == use_case_thread_id
        assert scope.close_calls == 1
        assert use_case_thread_id != gui_thread_id
        assert facade.status_kind == "CANCELLED"
        assert facade.status_message == "The request was cancelled."
        assert any(
            state == "CANCELLED" and not enabled and active is not None and closed
            for state, enabled, active, _, closed in snapshots
        )
        assert snapshots[-1][0:3] == ("CANCELLED", True, None)
        assert all(thread_id == gui_thread_id for _, _, _, thread_id, _ in snapshots)
        assert all(thread is facade.thread() for thread in gui_delivery_threads)
    finally:
        submission.release.set()
        wait_until(
            qt_application,
            lambda: facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )
        dispose_facade(qt_application, facade)


def test_startup_recovery_allocates_no_key_and_returns_to_idle(
    qt_application: QCoreApplication,
) -> None:
    recovery = ImmediateUseCase(NoRecoveryRequiredResult())
    factory = RecordingScopeFactory(ImmediateUseCase(cancelled_result()), recovery)
    keys = FixedKeys()
    facade = ShellFacade(factory, keys)  # type: ignore[arg-type]
    states: list[str] = []
    facade.changed.connect(lambda: states.append(facade.state))
    try:
        facade.apply_preparation(
            RecoveryRequiredResult(identifier(2), identifier(3))
        )
        assert facade.state == "RECOVERY"
        assert facade.progress_label == "Recovering an interrupted request…"
        wait_until(
            qt_application,
            lambda: facade.state == "IDLE" and facade.submit_enabled,
        )

        assert keys.calls == 0
        assert len(recovery.calls) == 1
        assert facade.conversation_id == str(identifier(3))
        assert states[0] == "RECOVERY"
        assert "IDLE" in states
        assert factory.scopes[0].close_calls == 1
    finally:
        wait_until(
            qt_application,
            lambda: facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )
        dispose_facade(qt_application, facade)


@pytest.mark.parametrize("fail_open", (False, True))
def test_worker_or_scope_defect_is_contained_after_scope_close_when_opened(
    qt_application: QCoreApplication,
    fail_open: bool,
) -> None:
    submission = ImmediateUseCase(cancelled_result(), raises=not fail_open)
    factory = RecordingScopeFactory(submission, fail_open=fail_open)
    facade = ready_facade(factory, FixedKeys())
    try:
        assert facade.submit_exact("trigger contained defect") is True
        wait_until(
            qt_application,
            lambda: facade.state == "CONTROLLED_FAILURE"
            and facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )

        assert facade.status_kind == "FOREGROUND_EXECUTION_FAILURE"
        assert facade.status_message == "Processing could not be completed safely."
        assert "/private/" not in facade.status_message
        assert facade.submit_enabled is False
        if fail_open:
            assert factory.scopes == []
        else:
            assert factory.scopes[0].close_calls == 1
            assert factory.scopes[0].closed_thread_id == factory.open_thread_ids[0]
    finally:
        dispose_facade(qt_application, facade)


def test_stale_duplicate_and_late_terminal_envelopes_cannot_replace_state(
    qt_application: QCoreApplication,
) -> None:
    submission = BlockingUseCase(cancelled_result())
    factory = RecordingScopeFactory(submission)
    facade = ready_facade(factory, FixedKeys())
    configuration = ConfigurationFailureResult(
        ConfigurationErrorValue("models.yaml", "model.name")
    )
    try:
        assert facade.submit_exact("one execution") is True
        wait_until(qt_application, submission.entered.is_set)
        active_id = facade._controller.active_execution_id  # type: ignore[attr-defined]
        assert active_id is not None

        facade._terminal_received(
            ForegroundTerminalEnvelope(
                active_id + 1,
                ExecutionKind.SUBMISSION,
                configuration,
            )
        )
        facade._terminal_received(
            ForegroundTerminalEnvelope(
                active_id,
                ExecutionKind.RECOVERY,
                NoRecoveryRequiredResult(),
            )
        )
        assert facade.state == "PENDING"

        accepted = ForegroundTerminalEnvelope(
            active_id,
            ExecutionKind.SUBMISSION,
            configuration,
        )
        facade._terminal_received(accepted)
        assert facade.state == "CONTROLLED_FAILURE"
        first_message = facade.status_message
        facade._terminal_received(
            ForegroundTerminalEnvelope(
                active_id,
                ExecutionKind.SUBMISSION,
                cancelled_result(),
            )
        )
        assert facade.status_message == first_message

        submission.release.set()
        wait_until(
            qt_application,
            lambda: facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )
        assert facade.state == "CONTROLLED_FAILURE"
        assert facade.submit_enabled is False
        facade._terminal_received(accepted)
        assert facade.state == "CONTROLLED_FAILURE"
        assert facade.status_message == first_message
    finally:
        submission.release.set()
        wait_until(
            qt_application,
            lambda: facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )
        dispose_facade(qt_application, facade)


def test_shutdown_is_asynchronous_responsive_and_terminal_content_is_hidden(
    qt_application: QCoreApplication,
) -> None:
    submission = BlockingUseCase(cancelled_result())
    factory = RecordingScopeFactory(submission)
    facade = ready_facade(factory, FixedKeys())
    shutdown_ready: list[int] = []
    facade.shutdownReady.connect(lambda: shutdown_ready.append(threading.get_ident()))
    try:
        assert facade.submit_exact("close while held") is True
        wait_until(qt_application, submission.entered.is_set)
        started = time.monotonic()
        facade.request_shutdown()
        elapsed = time.monotonic() - started

        assert elapsed < 0.1
        assert facade.state == "SHUTDOWN"
        assert facade.submit_enabled is False
        assert facade.progress_visible is True
        assert facade.progress_label == "Closing safely…"
        assert shutdown_ready == []
        assert submission.calls[0][1].is_cancelled() is True

        sentinels: list[str] = []
        QTimer.singleShot(0, lambda: sentinels.append("processed"))
        wait_until(qt_application, lambda: sentinels == ["processed"])
        submission.release.set()
        wait_until(qt_application, lambda: len(shutdown_ready) == 1)

        assert facade.state == "SHUTDOWN"
        assert facade.status_kind == ""
        assert facade.status_message == ""
        assert facade.progress_visible is False
        assert facade._controller.active_execution_id is None  # type: ignore[attr-defined]
        assert shutdown_ready == [threading.get_ident()]
        assert factory.scopes[0].close_calls == 1
        facade.request_shutdown()
        assert len(shutdown_ready) == 1
    finally:
        submission.release.set()
        wait_until(
            qt_application,
            lambda: facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )
        dispose_facade(qt_application, facade)
