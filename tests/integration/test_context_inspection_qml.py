"""Offscreen QML and native accessibility coverage for context inspection."""

from __future__ import annotations

from dataclasses import replace
import os
from typing import Iterable

import pytest
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt
from PySide6.QtGui import QAccessible, QAccessibleInterface
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    ContextInspectionReadyResult,
    InspectContextRequest,
    ShellReadyResult,
)
from context_for_ai.main import create_qml_engine
from context_for_ai.domain.enums import (
    ClarificationReason,
    FailureCode,
    PipelineStage,
    ProcessingRunStatus,
)
from context_for_ai.domain.lifecycle import SafeFailure
from context_for_ai.domain.value_objects import FrozenJsonObject
from context_for_ai.ui import ShellFacade
from tests.integration.test_context_inspection_facade import (
    BlockingInspection,
    FixedKeys,
    InspectionScopeFactory,
    identifier,
    wait_until,
)
from tests.qt_accessibility_recorder import (
    AnnouncementRecorder,
    RecordedAnnouncement,
)
from tests.unit.ui.test_inspection_presentation import minimal_view
from tests.unit.application.test_inspect_context import (
    clarification_fixture,
    corrected_packet_fixture,
    rich_packet_fixture,
    service_fixture,
)


SECTION_IDENTITIES = (
    ("contextInspectionSectionTarget", "Inspected request"),
    ("contextInspectionSectionActiveState", "Active state"),
    ("contextInspectionSectionInterpretation", "Interpretation"),
    ("contextInspectionSectionReferences", "References"),
    ("contextInspectionSectionConstraints", "Constraints and conflicts"),
    ("contextInspectionSectionMemories", "Retrieved memories"),
    ("contextInspectionSectionConfidence", "Confidence"),
    ("contextInspectionSectionValidation", "Validation"),
    ("contextInspectionSectionFinalStatus", "Final status"),
)


@pytest.fixture(scope="module")
def qt_application() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    QAccessible.setActive(True)
    return application


def invoke(object_: QObject, method: str) -> None:
    assert QMetaObject.invokeMethod(
        object_,
        method,
        Qt.ConnectionType.DirectConnection,
    )


def interface_for(object_: QObject) -> QAccessibleInterface:
    interface = QAccessible.queryAccessibleInterface(object_)
    assert interface is not None
    assert interface.isValid()
    return interface


def identity(interface: QAccessibleInterface) -> tuple[QAccessible.Role, str, str]:
    return (
        interface.role(),
        interface.text(QAccessible.Text.Name),
        interface.text(QAccessible.Text.Identifier),
    )


def walk_accessible(interface: QAccessibleInterface) -> Iterable[QAccessibleInterface]:
    yield interface
    for index in range(interface.childCount()):
        child = interface.child(index)
        if child is not None and child.isValid():
            yield from walk_accessible(child)


def dispose(
    application: QApplication,
    facade: ShellFacade,
    engine: object,
    inspection: BlockingInspection,
) -> None:
    inspection.release.set()
    wait_until(
        application,
        lambda: facade._inspection.active_generation is None,  # type: ignore[attr-defined]
    )
    facade.request_shutdown()
    for root in tuple(engine.rootObjects()):
        root.close()
    engine.deleteLater()
    facade.dispose()
    facade.deleteLater()
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_context_page_loads_real_safe_models_and_exact_accessible_tree(
    qt_application: QApplication,
) -> None:
    inspection = BlockingInspection(ContextInspectionReadyResult(minimal_view()))
    factory = InspectionScopeFactory([inspection])
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    qml_warnings: list[str] = []
    engine.warnings.connect(
        lambda warnings: qml_warnings.extend(warning.toString() for warning in warnings)
    )
    facade.apply_preparation(ShellReadyResult(identifier(1), False))
    root = engine.rootObjects()[0]
    navigation = root.findChild(QObject, "contextInspectionNavigation")
    page = root.findChild(QObject, "contextInspectionPage")
    refresh = root.findChild(QObject, "contextInspectionRefresh")
    status = root.findChild(QObject, "contextInspectionStatus")
    try:
        assert navigation is not None
        assert page is not None
        assert refresh is not None
        assert status is not None
        assert identity(interface_for(navigation)) == (
            QAccessible.Role.Button,
            "Context inspection",
            "contextInspectionNavigation",
        )

        invoke(navigation, "clicked")
        wait_until(qt_application, inspection.entered.is_set)
        assert facade.inspection_page_state == "LOADING"
        assert status.property("visible") is True
        assert identity(interface_for(page)) == (
            QAccessible.Role.Pane,
            "Context inspection",
            "contextInspectionPage",
        )
        assert identity(interface_for(status)) == (
            QAccessible.Role.StaticText,
            "Loading context inspection…",
            "contextInspectionStatus",
        )
        assert identity(interface_for(refresh)) == (
            QAccessible.Role.Button,
            "Refresh context inspection",
            "contextInspectionRefresh",
        )

        inspection.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "READY"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        qt_application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        assert facade.inspection_has_view is True
        assert facade.inspection_status_text == "Context inspection loaded."

        section_repeater = root.findChild(QObject, "contextInspectionSectionRepeater")
        assert section_repeater is not None
        assert section_repeater.property("count") == 9, tuple(qml_warnings)
        page_tree = tuple(walk_accessible(interface_for(page)))
        interfaces_by_id = {
            item.text(QAccessible.Text.Identifier): item
            for item in page_tree
            if item.text(QAccessible.Text.Identifier)
        }
        for accessible_id, accessible_name in SECTION_IDENTITIES:
            section_interface = interfaces_by_id[accessible_id]
            assert identity(section_interface) == (
                QAccessible.Role.Grouping,
                accessible_name,
                accessible_id,
            )
        ordered_section_ids = tuple(
            item.text(QAccessible.Text.Identifier)
            for item in page_tree
            if item.text(QAccessible.Text.Identifier).startswith(
                "contextInspectionSection"
            )
        )
        assert ordered_section_ids == tuple(value[0] for value in SECTION_IDENTITIES)

        collection_identities = (
            ("contextInspectionQualifiers", "Qualifier evidence"),
            ("contextInspectionReferences", "References"),
            ("contextInspectionConstraints", "Constraints"),
            ("contextInspectionConflicts", "Conflicts"),
            ("contextInspectionMemories", "Retrieved memories"),
        )
        for accessible_id, accessible_name in collection_identities:
            assert identity(interfaces_by_id[accessible_id]) == (
                QAccessible.Role.List,
                accessible_name,
                accessible_id,
            )

        static_names = tuple(
            item.text(QAccessible.Text.Name)
            for item in page_tree
            if item.role() is QAccessible.Role.StaticText
        )
        assert "Request: Request 4" in static_names
        assert "Outcome: Processing" in static_names
        assert "Processing checkpoint: Accepted" in static_names
        assert "Confidence: Unavailable for this run." in static_names
        assert "Validation: Unavailable for this run." in static_names
        assert "Final status: Unavailable for this run." in static_names
        assert "References: Unavailable for this run." in static_names
    finally:
        dispose(qt_application, facade, engine, inspection)


def test_each_accepted_inspection_revision_announces_once_with_polite_priority(
    qt_application: QApplication,
) -> None:
    first = BlockingInspection(ContextInspectionReadyResult(minimal_view()))
    second = BlockingInspection(ContextInspectionReadyResult(minimal_view()))
    factory = InspectionScopeFactory([first, second])
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    facade.apply_preparation(ShellReadyResult(identifier(2), False))
    root = engine.rootObjects()[0]
    navigation = root.findChild(QObject, "contextInspectionNavigation")
    assert navigation is not None
    polite = QAccessible.AnnouncementPoliteness.Polite
    try:
        with AnnouncementRecorder() as recorder:
            invoke(navigation, "clicked")
            wait_until(qt_application, first.entered.is_set)
            assert recorder.announcements == [
                RecordedAnnouncement("Loading context inspection.", polite)
            ]

            first.release.set()
            wait_until(
                qt_application,
                lambda: facade.inspection_page_state == "READY"
                and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
            )
            assert recorder.announcements == [
                RecordedAnnouncement("Loading context inspection.", polite),
                RecordedAnnouncement("Context inspection loaded.", polite),
            ]

            assert facade.refresh_context_inspection() is True
            wait_until(qt_application, second.entered.is_set)
            assert recorder.announcements[-1] == RecordedAnnouncement(
                "Loading context inspection.",
                polite,
            )
            assert len(recorder.announcements) == 3

            second.release.set()
            wait_until(
                qt_application,
                lambda: facade.inspection_page_state == "READY"
                and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
            )
            assert recorder.announcements == [
                RecordedAnnouncement("Loading context inspection.", polite),
                RecordedAnnouncement("Context inspection loaded.", polite),
                RecordedAnnouncement("Loading context inspection.", polite),
                RecordedAnnouncement("Context inspection refreshed.", polite),
            ]
            assert facade.navigate_to_chat() is True
            facade.request_shutdown()
            qt_application.processEvents(
                QEventLoop.ProcessEventsFlag.AllEvents,
                10,
            )
            assert len(recorder.announcements) == 4
    finally:
        first.release.set()
        second.release.set()
        dispose(qt_application, facade, engine, second)


def rich_ready_result() -> ContextInspectionReadyResult:
    rich = rich_packet_fixture()
    service, _, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source, rich.assistant),
        runs=(rich.run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=(rich.task,),
        packets=(rich.packet,),
        references=(rich.reference,),
        constraints=(rich.constraint,),
        model_requests=(rich.request,),
        model_responses=(rich.response,),
        validations=(rich.validation,),
    )
    result = service.execute(InspectContextRequest(rich.conversation.id))
    assert isinstance(result, ContextInspectionReadyResult)
    return result


def hard_conflict_ready_result() -> ContextInspectionReadyResult:
    fixture = clarification_fixture(ClarificationReason.HARD_CONSTRAINT_CONFLICT)
    service, _, _ = service_fixture(
        conversations=(fixture.conversation,),
        states=(fixture.state,),
        messages=(fixture.source,),
        runs=(fixture.run,),
        references=fixture.references,
        constraints=fixture.constraints,
        clarifications=(fixture.clarification,),
    )
    result = service.execute(InspectContextRequest(fixture.conversation.id))
    assert isinstance(result, ContextInspectionReadyResult)
    return result


def failed_validation_ready_result() -> ContextInspectionReadyResult:
    rich = corrected_packet_fixture()
    request = rich.requests[0]
    response = rich.responses[0]
    validation = rich.validations[0]
    completed_at = response.created_at
    failed_run = replace(
        rich.run,
        status=ProcessingRunStatus.CONTROLLED_FAILURE,
        completed_at=completed_at,
    )
    failure = SafeFailure(
        identifier(980),
        failed_run.id,
        PipelineStage.VALIDATION,
        FailureCode.VALIDATION_EXHAUSTED,
        "The response did not pass validation.",
        FrozenJsonObject({"unsafe": "UNSAFE_VALIDATION_FAILURE_DETAIL"}),
        True,
        completed_at,
    )
    service, _, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source,),
        runs=(failed_run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=(rich.task,),
        packets=(rich.packet,),
        references=(rich.reference,),
        constraints=(rich.constraint,),
        model_requests=(request,),
        model_responses=(response,),
        validations=(validation,),
        failures=(failure,),
    )
    result = service.execute(InspectContextRequest(rich.conversation.id))
    assert isinstance(result, ContextInspectionReadyResult)
    return result


def test_rich_safe_view_reaches_nested_qml_accessibility_without_sentinels(
    qt_application: QApplication,
) -> None:
    inspection = BlockingInspection(rich_ready_result())
    factory = InspectionScopeFactory([inspection])
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    facade.apply_preparation(ShellReadyResult(identifier(1), False))
    root = engine.rootObjects()[0]
    navigation = root.findChild(QObject, "contextInspectionNavigation")
    page = root.findChild(QObject, "contextInspectionPage")
    assert navigation is not None
    assert page is not None
    try:
        invoke(navigation, "clicked")
        wait_until(qt_application, inspection.entered.is_set)
        inspection.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "READY"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        tree = tuple(walk_accessible(interface_for(page)))
        identities = {
            item.text(QAccessible.Text.Identifier): identity(item)
            for item in tree
            if item.text(QAccessible.Text.Identifier)
        }
        assert identities["contextInspectionReferenceEvidence-1"] == (
            QAccessible.Role.List,
            "Evidence for reference 1",
            "contextInspectionReferenceEvidence-1",
        )
        assert identities["contextInspectionValidationViolations"] == (
            QAccessible.Role.List,
            "Validation violations",
            "contextInspectionValidationViolations",
        )
        assert identities["contextInspectionValidationEvidence"] == (
            QAccessible.Role.List,
            "Validation evidence",
            "contextInspectionValidationEvidence",
        )

        item_names = tuple(
            item.text(QAccessible.Text.Name)
            for item in tree
            if item.role() is QAccessible.Role.ListItem
        )
        assert "Qualifier 1: Approximate, briefly" in item_names
        assert "Reference 1: Planner, Resolved" in item_names
        assert "Reference 1 evidence 1: Exact name, score 1.00" in item_names
        assert "Constraint 1: Forbidden, Active" in item_names
        assert "Retrieved memory 1: score 0.80" in item_names
        assert "Validation evidence 1: Topic, Passed" in item_names

        static_names = tuple(
            item.text(QAccessible.Text.Name)
            for item in tree
            if item.role() is QAccessible.Role.StaticText
        )
        for exact_name in (
            "Active project: Current canonical project",
            "Active topic: Planning",
            "Active task: Write the plan",
            "Intent: Explain",
            "Expected output type: Text explanation",
            "Overall confidence: 0.91",
            "Reference confidence: 1.00",
            "Validation attempt: 1",
            "Validation status: Passed",
            "Validation score: 1.00",
            "Correction count: 0",
            "Validation violations: None recorded.",
        ):
            assert exact_name in static_names
        rendered_qml = "\n".join(
            str(value)
            for child in root.findChildren(QObject)
            if (value := child.property("text")) is not None
        )
        exposed_accessibility = "\n".join(
            item.text(QAccessible.Text.Name)
            + item.text(QAccessible.Text.Description)
            + item.text(QAccessible.Text.Value)
            + item.text(QAccessible.Text.Identifier)
            for item in tree
        )
        for prohibited in (
            "UNSAFE_RENDERED_PROMPT_SENTINEL",
            "UNSAFE_REQUEST_SENTINEL",
            "UNSAFE_RESPONSE_SENTINEL",
            "UNSAFE_PROVIDER_SENTINEL",
            "unsafe-provider-model",
        ):
            assert prohibited not in repr(inspection.result)
            assert prohibited not in rendered_qml
            assert prohibited not in exposed_accessibility
            assert prohibited not in facade.inspection_announcement_text
    finally:
        dispose(qt_application, facade, engine, inspection)


def test_conflict_and_validation_violation_templates_reach_native_accessibility(
    qt_application: QApplication,
) -> None:
    conflict = BlockingInspection(hard_conflict_ready_result())
    validation = BlockingInspection(failed_validation_ready_result())
    factory = InspectionScopeFactory([conflict, validation])
    facade = ShellFacade(factory, FixedKeys())  # type: ignore[arg-type]
    engine = create_qml_engine(facade)
    facade.apply_preparation(ShellReadyResult(identifier(1), False))
    root = engine.rootObjects()[0]
    navigation = root.findChild(QObject, "contextInspectionNavigation")
    page = root.findChild(QObject, "contextInspectionPage")
    assert navigation is not None
    assert page is not None
    try:
        invoke(navigation, "clicked")
        wait_until(qt_application, conflict.entered.is_set)
        conflict.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "CLARIFICATION"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        conflict_tree = tuple(walk_accessible(interface_for(page)))
        conflict_ids = {
            item.text(QAccessible.Text.Identifier): item
            for item in conflict_tree
            if item.text(QAccessible.Text.Identifier)
        }
        assert identity(conflict_ids["contextInspectionConflictRules-1"]) == (
            QAccessible.Role.List,
            "Rules in conflict 1",
            "contextInspectionConflictRules-1",
        )
        conflict_item_names = tuple(
            item.text(QAccessible.Text.Name)
            for item in conflict_tree
            if item.role() is QAccessible.Role.ListItem
        )
        assert "Conflict 1: 2 rules" in conflict_item_names
        assert (
            "Conflict 1 rule 1: Required, MUST_USE:SAFE_FORMAT"
            in conflict_item_names
        )
        assert (
            "Conflict 1 rule 2: Forbidden, MUST_NOT_USE:SAFE_FORMAT"
            in conflict_item_names
        )

        assert facade.refresh_context_inspection() is True
        wait_until(qt_application, validation.entered.is_set)
        validation.release.set()
        wait_until(
            qt_application,
            lambda: facade.inspection_page_state == "CONTROLLED_FAILURE"
            and facade._inspection.active_generation is None,  # type: ignore[attr-defined]
        )
        validation_tree = tuple(walk_accessible(interface_for(page)))
        validation_item_names = tuple(
            item.text(QAccessible.Text.Name)
            for item in validation_tree
            if item.role() is QAccessible.Role.ListItem
        )
        assert "Validation violation 1: Topic mismatch" in validation_item_names
        assert (
            "Validation violation 2: Output type mismatch"
            in validation_item_names
        )
        assert "Validation evidence 1: Topic, Failed" in validation_item_names
        static_names = tuple(
            item.text(QAccessible.Text.Name)
            for item in validation_tree
            if item.role() is QAccessible.Role.StaticText
        )
        assert "Correction count: 0" in static_names
        assert "Final outcome: Controlled failure" in static_names
        assert "Failure code: Validation exhausted" in static_names
        assert "UNSAFE_VALIDATION_FAILURE_DETAIL" not in "\n".join(
            item.text(QAccessible.Text.Name)
            + item.text(QAccessible.Text.Description)
            + item.text(QAccessible.Text.Value)
            for item in validation_tree
        )
    finally:
        conflict.release.set()
        validation.release.set()
        dispose(qt_application, facade, engine, validation)
