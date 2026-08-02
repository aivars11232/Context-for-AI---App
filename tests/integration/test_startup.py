"""Minimal application startup integration coverage for AT-001."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from PySide6.QtGui import QGuiApplication

from context_for_ai.main import bootstrap_application, create_qml_engine


def test_offscreen_startup_validates_config_applies_schema_and_creates_qml_root(
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

    assert tables == {
        "clarification_requests",
        "constraints",
        "context_packets",
        "conversation_states",
        "conversations",
        "correction_attempts",
        "entity_registry",
        "evaluation_cases",
        "evaluation_runs",
        "memories",
        "memory_revisions",
        "memory_sources",
        "messages",
        "model_requests",
        "model_responses",
        "named_items",
        "pipeline_failures",
        "processing_runs",
        "projects",
        "reference_resolutions",
        "retrieval_exclusions",
        "retrieval_results",
        "schema_migrations",
        "settings",
        "tasks",
        "topics",
        "validation_results",
    }
    assert engine.rootObjects()
    assert engine.rootObjects()[0].objectName() == "contextForAiRoot"
    for root in engine.rootObjects():
        root.close()
    application.quit()
