"""Minimal application startup integration coverage for AT-001."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from PySide6.QtGui import QGuiApplication

from context_for_ai.main import bootstrap_application, create_qml_engine


def test_offscreen_startup_validates_config_bootstraps_ledger_and_creates_qml_root(
    fixture_application_root: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    resources = bootstrap_application(application_root=fixture_application_root, environ={})
    application = QGuiApplication.instance() or QGuiApplication([])
    engine = create_qml_engine()

    with sqlite3.connect(resources.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert tables == {"schema_migrations"}
    assert engine.rootObjects()
    assert engine.rootObjects()[0].objectName() == "contextForAiRoot"
    for root in engine.rootObjects():
        root.close()
    application.quit()
