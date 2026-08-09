"""Offscreen interaction tests for the packaged CHAT-only QML shell."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import threading
import time

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QMetaObject,
    QObject,
    Qt,
)
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    CancellationCheckpoint,
    CancelledResult,
    NoRecoveryRequiredResult,
    ShellReadyResult,
)
from context_for_ai.domain.enums import FailureCode
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.main import StartupError, create_qml_engine
from context_for_ai.ui import ShellFacade, StartupFailureKind


def identifier(number: int) -> DomainId:
    return DomainId(f"56000000-0000-4000-8000-{number:012x}")


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


class FixedKeys:
    def __init__(self) -> None:
        self.calls = 0
        self.value = identifier(90)

    def new_key(self) -> DomainId:
        self.calls += 1
        return self.value


class BlockingSubmission:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls: list[tuple[object, object, int]] = []

    def execute(self, request: object, token: object) -> CancelledResult:
        self.calls.append((request, token, threading.get_ident()))
        self.entered.set()
        assert self.release.wait(timeout=5)
        return cancelled_result()


class NoRecovery:
    def execute(self, *_: object) -> NoRecoveryRequiredResult:
        return NoRecoveryRequiredResult()


class Scope:
    def __init__(self, submission: BlockingSubmission) -> None:
        self.process_user_message = submission
        self.recover_processing_run = NoRecovery()
        self.closed_thread_id: int | None = None

    def close(self) -> None:
        self.closed_thread_id = threading.get_ident()


class ScopeFactory:
    def __init__(self, submission: BlockingSubmission) -> None:
        self.submission = submission
        self.scopes: list[Scope] = []

    def open_foreground_scope(self) -> Scope:
        scope = Scope(self.submission)
        self.scopes.append(scope)
        return scope

    def open_startup_scope(self) -> object:
        raise AssertionError("The loaded facade must not reopen startup scope.")


def invoke(object_: QObject, method: str) -> None:
    assert QMetaObject.invokeMethod(
        object_,
        method,
        Qt.ConnectionType.DirectConnection,
    )


def dispose(
    application: QApplication,
    facade: ShellFacade,
    engine: object,
) -> None:
    if facade._controller.active_execution_id is not None:  # type: ignore[attr-defined]
        facade.request_cancellation()
    for root in tuple(engine.rootObjects()):
        root.close()
    engine.deleteLater()
    if facade._controller.active_execution_id is None:  # type: ignore[attr-defined]
        facade.dispose()
        facade.deleteLater()
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_nested_chat_component_preserves_exact_text_and_suppresses_duplicate(
    qt_application: QApplication,
) -> None:
    submission = BlockingSubmission()
    factory = ScopeFactory(submission)
    keys = FixedKeys()
    facade = ShellFacade(factory, keys)  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    facade.apply_preparation(ShellReadyResult(identifier(1), False))
    root = engine.rootObjects()[0]
    panel = root.findChild(QObject, "chatPanel")
    composer = root.findChild(QObject, "chatComposer")
    submit = root.findChild(QObject, "submitButton")
    cancel = root.findChild(QObject, "cancelButton")
    progress = root.findChild(QObject, "progressRow")
    status_message = root.findChild(QObject, "safeStatusMessage")
    exact_text = "  café ☕\nsecond line\t  "
    try:
        assert panel is not None
        assert composer is not None
        assert submit is not None
        assert cancel is not None
        assert progress is not None
        assert status_message is not None
        assert root.findChild(QObject, "chatNavigationItem") is not None

        composer.setProperty("text", "")
        qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        assert submit.property("enabled") is False
        invoke(panel, "submitCurrentText")
        assert keys.calls == 0

        composer.setProperty("text", exact_text)
        qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        assert submit.property("enabled") is True
        invoke(panel, "submitCurrentText")
        assert composer.property("text") == ""
        assert keys.calls == 1
        wait_until(qt_application, submission.entered.is_set)
        assert progress.property("visible") is True

        duplicate = " duplicate text remains \n"
        composer.setProperty("text", duplicate)
        qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        assert submit.property("enabled") is False
        invoke(panel, "submitCurrentText")
        assert composer.property("text") == duplicate
        assert keys.calls == 1
        assert len(submission.calls) == 1

        invoke(cancel, "clicked")
        assert facade.state == "CANCELLATION_REQUESTED"
        assert submission.calls[0][1].is_cancelled() is True
        submission.release.set()
        wait_until(
            qt_application,
            lambda: facade.state == "CANCELLED" and facade.submit_enabled,
        )

        request, _, worker_thread_id = submission.calls[0]
        assert request.user_text.encode("utf-8") == exact_text.encode("utf-8")
        assert request.project_id is None
        assert request.idempotency_key == keys.value
        assert factory.scopes[0].closed_thread_id == worker_thread_id
        assert status_message.property("text") == "The request was cancelled."
        assert composer.property("text") == duplicate
        assert submit.property("enabled") is True
    finally:
        submission.release.set()
        wait_until(
            qt_application,
            lambda: facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )
        dispose(qt_application, facade, engine)


def test_missing_nested_component_fails_closed_without_qml_diagnostics(
    qt_application: QApplication,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = Path(__file__).parents[2] / "src" / "context_for_ai" / "ui" / "qml"
    broken = tmp_path / "qml"
    shutil.copytree(source, broken)
    (broken / "components" / "ChatPanel.qml").unlink()
    facade = ShellFacade(ScopeFactory(BlockingSubmission()), FixedKeys())  # type: ignore[arg-type]

    with pytest.raises(StartupError) as captured:
        create_qml_engine(facade, qml_directory=broken)

    assert captured.value.failure.failure_kind is StartupFailureKind.QML_LOAD
    captured_output = capsys.readouterr()
    assert captured_output.out == ""
    assert captured_output.err == ""
    assert facade.state == "STARTUP"
    assert facade._controller.active_execution_id is None  # type: ignore[attr-defined]
    facade.dispose()
    facade.deleteLater()
    QCoreApplication.sendPostedEvents()


def test_idle_window_close_requests_one_immediate_safe_shutdown(
    qt_application: QApplication,
) -> None:
    facade = ShellFacade(ScopeFactory(BlockingSubmission()), FixedKeys())  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    facade.apply_preparation(ShellReadyResult(identifier(2), False))
    root = engine.rootObjects()[0]
    ready: list[int] = []
    facade.shutdownReady.connect(lambda: ready.append(threading.get_ident()))

    root.close()
    qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)

    assert facade.state == "SHUTDOWN"
    assert facade._controller.active_execution_id is None  # type: ignore[attr-defined]
    assert ready == [threading.get_ident()]
    assert root.isVisible() is False
    engine.deleteLater()
    facade.dispose()
    facade.deleteLater()
    qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
