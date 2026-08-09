"""TASK-0016-owned AT-013 context-inspection acceptance slices."""

from __future__ import annotations

import os
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt, QTimer
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    ContextInspectionReadyResult,
    InspectionAvailability,
    InspectionCheckpoint,
    ShellReadyResult,
)
from context_for_ai.main import create_qml_engine
from context_for_ai.ui import ShellFacade
from tests.integration.test_context_inspection_facade import (
    BlockingInspection,
    FixedKeys,
    InspectionScopeFactory,
    identifier,
    wait_until,
)
from tests.integration.test_context_inspection_qml import (
    SECTION_IDENTITIES,
    interface_for,
    rich_ready_result,
    walk_accessible,
)
from tests.qt_accessibility_recorder import AnnouncementRecorder, RecordedAnnouncement


REPOSITORY_ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def qt_application() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    QAccessible.setActive(True)
    return application


def test_task_0016_qml_boundary_contains_only_presentation_owned_inputs() -> None:
    qml_paths = (
        REPOSITORY_ROOT / "src/context_for_ai/ui/qml/Main.qml",
        *(
            REPOSITORY_ROOT / "src/context_for_ai/ui/qml/components" / name
            for name in (
                "ContextInspectionPage.qml",
                "InspectionCollection.qml",
                "InspectionScalarList.qml",
                "InspectionSection.qml",
            )
        ),
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in qml_paths)

    for prohibited in (
        "sqlite",
        "repository",
        "ModelGateway",
        "ContextPacket",
        "packet_json",
        "SELECT ",
        "Timer {",
        "MEMORY",
        "PROJECTS",
        "VALIDATION_HISTORY",
        "SETTINGS",
    ):
        assert prohibited not in source
    assert "shellFacade.navigate_to_chat()" in source
    assert "shellFacade.navigate_to_context_inspection()" in source
    assert "page.facade.refresh_context_inspection()" in source


def test_task_0016_at_013_complete_result_is_safe_and_historically_owned() -> None:
    result = rich_ready_result()

    assert isinstance(result, ContextInspectionReadyResult)
    view = result.view
    assert view.target.request_label == "Request 4"
    assert view.target.checkpoint is InspectionCheckpoint.VALIDATION_COMMITTED
    assert view.active_project.value.display_name == "Current canonical project"
    assert view.active_topic.value.display_name == "Planning"
    assert view.active_task.value.display_name == "Write the plan"
    assert view.qualifier_evidence.availability is InspectionAvailability.AVAILABLE
    assert view.references.items[0].evidence[0].score.display_text == "1.00"
    assert view.constraints.items[0].source_text == (
        "MVP text-only/no-actions policy"
    )
    assert view.conflicts.display_text == "None recorded."
    assert view.retrieved_memories.items[0].reasons == (
        "project_match=0",
        "topic_match=0",
        "keyword_jaccard=0.5",
        "recency=1",
        "importance=0.5",
        "scope_match=1",
        "correction_match=0",
    )
    assert view.confidence.value.overall.display_text == "0.91"
    assert view.validation.value.attempt_number == 1
    assert view.correction_count.display_text == "0"

    safe_surface = repr(result)
    for prohibited in (
        "UNSAFE_RENDERED_PROMPT_SENTINEL",
        "UNSAFE_REQUEST_SENTINEL",
        "UNSAFE_RESPONSE_SENTINEL",
        "UNSAFE_PROVIDER_SENTINEL",
        "unsafe-provider-model",
    ):
        assert prohibited not in safe_surface


def test_task_0016_at_013_real_page_is_accessible_coalesced_and_async(
    qt_application: QApplication,
) -> None:
    first = BlockingInspection(rich_ready_result())
    second = BlockingInspection(rich_ready_result())
    factory = InspectionScopeFactory([first, second])
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    facade.apply_preparation(ShellReadyResult(identifier(1), False))
    root = engine.rootObjects()[0]
    navigation = root.findChild(QObject, "contextInspectionNavigation")
    page = root.findChild(QObject, "contextInspectionPage")
    assert navigation is not None
    assert page is not None
    shutdown_threads: list[int] = []
    facade.shutdownReady.connect(
        lambda: shutdown_threads.append(threading.get_ident())
    )
    polite = QAccessible.AnnouncementPoliteness.Polite
    try:
        with AnnouncementRecorder() as recorder:
            assert QMetaObject.invokeMethod(
                navigation,
                "clicked",
                Qt.ConnectionType.DirectConnection,
            )
            wait_until(qt_application, first.entered.is_set)
            assert facade.route == "CONTEXT_INSPECTION"
            assert facade.inspection_page_state == "LOADING"

            assert facade.refresh_context_inspection() is True
            assert facade.refresh_context_inspection() is True
            assert len(factory.scopes) == 1
            assert recorder.announcements == [
                RecordedAnnouncement("Loading context inspection.", polite),
                RecordedAnnouncement("Loading context inspection.", polite),
                RecordedAnnouncement("Loading context inspection.", polite),
            ]

            first.release.set()
            wait_until(qt_application, second.entered.is_set)
            assert len(factory.scopes) == 2
            assert facade.inspection_page_state == "LOADING"
            second.release.set()
            wait_until(
                qt_application,
                lambda: facade.inspection_page_state == "READY"
                and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
            )

            tree = tuple(walk_accessible(interface_for(page)))
            ordered_sections = tuple(
                item.text(QAccessible.Text.Identifier)
                for item in tree
                if item.text(QAccessible.Text.Identifier).startswith(
                    "contextInspectionSection"
                )
            )
            assert ordered_sections == tuple(value[0] for value in SECTION_IDENTITIES)
            assert recorder.announcements[-1] == RecordedAnnouncement(
                "Context inspection refreshed.",
                polite,
            )
            assert len(recorder.announcements) == 4

            facade.request_shutdown()
            assert facade.inspection_page_state == "SHUTDOWN"
            assert shutdown_threads == [threading.get_ident()]
            responsive: list[bool] = []
            QTimer.singleShot(0, lambda: responsive.append(True))
            wait_until(qt_application, lambda: responsive == [True])
            assert len(recorder.announcements) == 4
    finally:
        first.release.set()
        second.release.set()
        for qml_root in tuple(engine.rootObjects()):
            qml_root.close()
        engine.deleteLater()
        facade.dispose()
        facade.deleteLater()
        qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
