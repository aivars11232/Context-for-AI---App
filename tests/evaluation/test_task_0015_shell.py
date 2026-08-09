"""TASK-0015-owned AT-001 and AT-013 shell acceptance slices."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer
from PySide6.QtWidgets import QApplication

from context_for_ai.application import ShellReadyResult
from context_for_ai.main import (
    bootstrap_application,
    create_qml_engine,
    prepare_application_shell,
)
from context_for_ai.ui import ShellFacade
from tests.integration.test_qml_shell import (
    BlockingSubmission,
    FixedKeys,
    ScopeFactory,
    wait_until,
)


REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def qt_application() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    return application


def dispose(
    application: QApplication,
    facade: ShellFacade,
    engine: object,
) -> None:
    for root in tuple(engine.rootObjects()):
        root.close()
    engine.deleteLater()
    facade.dispose()
    facade.deleteLater()
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_task_0015_at_001_real_startup_creates_one_chat_shell(
    qt_application: QApplication,
    fixture_application_root: Path,
) -> None:
    startup = bootstrap_application(
        application_root=fixture_application_root,
        environ={},
    )
    preparation = prepare_application_shell(startup.scope_factory)
    assert isinstance(preparation, ShellReadyResult)
    facade = ShellFacade(startup.scope_factory, startup.idempotency_keys)
    engine = create_qml_engine(facade)
    facade.apply_preparation(preparation)
    root = engine.rootObjects()[0]
    try:
        assert preparation.initial_conversation_created is True
        assert len(engine.rootObjects()) == 1
        assert root.objectName() == "contextForAiRoot"
        assert root.findChild(QObject, "chatPanel") is not None
        assert root.findChild(QObject, "chatComposer") is not None
        assert root.findChild(QObject, "chatNavigationItem") is not None
        assert facade.route == "CHAT"
        assert facade.state == "IDLE"
        assert facade.submit_enabled is True
        assert facade._controller.active_execution_id is None  # type: ignore[attr-defined]

        qml_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(
                (
                    REPOSITORY_ROOT
                    / "src"
                    / "context_for_ai"
                    / "ui"
                    / "qml"
                ).rglob("*.qml")
            )
        )
        assert "CONTEXT_INSPECTION" in qml_text
        for deferred_route in (
            "Memory",
            "Projects",
            "Validation History",
            "Settings",
        ):
            assert deferred_route not in qml_text
    finally:
        facade.request_shutdown()
        dispose(qt_application, facade, engine)


def test_task_0015_at_013_shell_remains_live_and_shuts_down_asynchronously(
    qt_application: QApplication,
) -> None:
    first = BlockingSubmission()
    factory = ScopeFactory(first)
    keys = FixedKeys()
    facade = ShellFacade(factory, keys)  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    facade.apply_preparation(ShellReadyResult(keys.value, False))
    root = engine.rootObjects()[0]
    panel = root.findChild(QObject, "chatPanel")
    composer = root.findChild(QObject, "chatComposer")
    gui_thread_id = threading.get_ident()
    exact_text = "  evaluation café ☕\n  "
    shutdown_ready: list[int] = []
    facade.shutdownReady.connect(lambda: shutdown_ready.append(threading.get_ident()))
    try:
        composer.setProperty("text", exact_text)
        assert panel.metaObject().invokeMethod is not None
        assert facade.submit_exact(composer.property("text")) is True
        composer.setProperty("text", "")
        wait_until(qt_application, first.entered.is_set)
        assert facade.submit_exact("suppressed duplicate") is False
        assert keys.calls == 1

        sentinels: list[int] = []
        for ordinal in range(3):
            QTimer.singleShot(0, lambda value=ordinal: sentinels.append(value))
        wait_until(qt_application, lambda: sorted(sentinels) == [0, 1, 2])
        assert facade.request_cancellation() is True
        assert facade.state == "CANCELLATION_REQUESTED"
        assert facade.request_cancellation() is False
        first.release.set()
        wait_until(
            qt_application,
            lambda: facade.state == "CANCELLED" and facade.submit_enabled,
        )

        first_request, _, first_thread_id = first.calls[0]
        assert first_request.user_text.encode("utf-8") == exact_text.encode("utf-8")
        assert first_request.project_id is None
        assert first_thread_id != gui_thread_id
        assert factory.scopes[0].closed_thread_id == first_thread_id

        second = BlockingSubmission()
        factory.submission = second
        assert facade.submit_exact("shutdown execution") is True
        wait_until(qt_application, second.entered.is_set)
        facade.request_shutdown()
        assert facade.state == "SHUTDOWN"
        assert facade.submit_enabled is False
        assert shutdown_ready == []
        assert second.calls[0][1].is_cancelled() is True
        responsive: list[bool] = []
        QTimer.singleShot(0, lambda: responsive.append(True))
        wait_until(qt_application, lambda: responsive == [True])
        second.release.set()
        wait_until(qt_application, lambda: len(shutdown_ready) == 1)

        second_thread_id = second.calls[0][2]
        assert factory.scopes[1].closed_thread_id == second_thread_id
        assert second_thread_id != gui_thread_id
        assert shutdown_ready == [gui_thread_id]
        assert facade.state == "SHUTDOWN"
        assert facade.status_kind == ""

        shell_tree = ast.parse(
            (
                REPOSITORY_ROOT
                / "src"
                / "context_for_ai"
                / "ui"
                / "shell.py"
            ).read_text(encoding="utf-8")
        )
        called_methods = {
            node.func.attr
            for node in ast.walk(shell_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "wait" not in called_methods
        assert "terminate" not in called_methods
    finally:
        first.release.set()
        if "second" in locals():
            second.release.set()
        wait_until(
            qt_application,
            lambda: facade._controller.active_execution_id is None,  # type: ignore[attr-defined]
        )
        dispose(qt_application, facade, engine)
