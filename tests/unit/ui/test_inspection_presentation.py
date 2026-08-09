"""Qt-independent TASK-0016 presentation algebra and safe projection tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest

from context_for_ai.application import (
    CanonicalLabelView,
    ContextInspectionEmptyResult,
    ContextInspectionLoadFailureResult,
    ContextInspectionReadyResult,
    ContextInspectionView,
    InspectionAvailability,
    InspectionCheckpoint,
    InspectionCollection,
    InspectionRunOutcome,
    InspectionTargetView,
    InspectionValue,
    SafeTerminalKind,
    SafeTerminalStatusView,
)
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.ui.presentation import (
    ContextInspectionPageState,
    InspectionExecutionFailureView,
    InspectionTerminalEnvelope,
    Route,
    contained_inspection_result,
    context_inspection_presentation_view,
    inspection_result_presentation,
)


def identifier(number: int) -> DomainId:
    return DomainId(f"93000000-0000-4000-8000-{number:012d}")


def unavailable_value() -> InspectionValue[CanonicalLabelView]:
    return InspectionValue(
        InspectionAvailability.UNAVAILABLE,
        None,
        "Unavailable for this run.",
    )


def unavailable_collection() -> InspectionCollection[CanonicalLabelView]:
    return InspectionCollection(
        InspectionAvailability.UNAVAILABLE,
        (),
        "Unavailable for this run.",
    )


def minimal_view(
    outcome: InspectionRunOutcome = InspectionRunOutcome.PROCESSING,
) -> ContextInspectionView:
    scalar = unavailable_value()
    collection = unavailable_collection()
    terminal: InspectionValue[SafeTerminalStatusView]
    if outcome in {
        InspectionRunOutcome.CONTROLLED_FAILURE,
        InspectionRunOutcome.CANCELLED,
    }:
        terminal = InspectionValue(
            InspectionAvailability.AVAILABLE,
            SafeTerminalStatusView(
                SafeTerminalKind(
                    "CONTROLLED_FAILURE"
                    if outcome is InspectionRunOutcome.CONTROLLED_FAILURE
                    else "CANCELLED"
                ),
                (
                    "Controlled failure"
                    if outcome is InspectionRunOutcome.CONTROLLED_FAILURE
                    else "Cancelled"
                ),
                CanonicalLabelView("VALIDATION", "Validation"),
                CanonicalLabelView("PERSISTENCE_ERROR", "Persistence error"),
                "A safe terminal message.",
            ),
            (
                "Controlled failure"
                if outcome is InspectionRunOutcome.CONTROLLED_FAILURE
                else "Cancelled"
            ),
        )
    else:
        terminal = InspectionValue(
            InspectionAvailability.UNAVAILABLE,
            None,
            "Unavailable for this run.",
        )
    return ContextInspectionView(
        target=InspectionTargetView(
            4,
            "Request 4",
            outcome,
            InspectionCheckpoint.ACCEPTED,
            outcome.value.replace("_", " ").lower().capitalize(),
            "Accepted",
        ),
        active_project=scalar,
        active_topic=scalar,
        active_task=scalar,
        intent=scalar,
        expected_output_type=scalar,
        qualifier_evidence=collection,
        references=collection,
        constraints=collection,
        conflicts=collection,
        retrieved_memories=collection,
        confidence=scalar,
        validation=scalar,
        correction_count=scalar,
        clarification=scalar,
        terminal_status=terminal,
    )


def test_route_and_inspection_page_state_are_exact_closed_vocabularies() -> None:
    assert tuple(value.value for value in Route) == (
        "CHAT",
        "CONTEXT_INSPECTION",
        "MEMORY",
        "PROJECTS",
        "VALIDATION_HISTORY",
        "SETTINGS",
    )
    assert tuple(value.value for value in ContextInspectionPageState) == (
        "INACTIVE",
        "LOADING",
        "READY",
        "EMPTY",
        "CLARIFICATION",
        "CONTROLLED_FAILURE",
        "LOAD_ERROR",
        "SHUTDOWN",
    )


def test_inspection_execution_failure_is_exact_frozen_content_free_value() -> None:
    failure = InspectionExecutionFailureView()

    assert is_dataclass(failure)
    assert failure.__dataclass_params__.frozen is True
    assert "__slots__" in vars(type(failure))
    assert {value.name for value in fields(failure)} == {
        "result_kind",
        "code",
        "safe_message",
    }
    assert failure.result_kind == "INSPECTION_EXECUTION_FAILURE"
    assert failure.code == "INSPECTION_EXECUTION_FAILED"
    assert failure.safe_message == "Context inspection could not be loaded safely."
    with pytest.raises(FrozenInstanceError):
        failure.safe_message = "unsafe"  # type: ignore[misc]


def test_inspection_terminal_envelope_requires_positive_generation_and_safe_result() -> None:
    conversation_id = identifier(1)
    result = ContextInspectionEmptyResult()
    envelope = InspectionTerminalEnvelope(1, conversation_id, result)

    assert envelope == InspectionTerminalEnvelope(1, conversation_id, result)
    with pytest.raises(ValueError, match="positive"):
        InspectionTerminalEnvelope(0, conversation_id, result)
    with pytest.raises(ValueError, match="conversation"):
        InspectionTerminalEnvelope(1, object(), result)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="closed safe"):
        InspectionTerminalEnvelope(1, conversation_id, object())  # type: ignore[arg-type]


def test_inspection_boundary_contains_unknown_values_without_exception_text() -> None:
    empty = ContextInspectionEmptyResult()
    failure = ContextInspectionLoadFailureResult()

    assert contained_inspection_result(empty) is empty
    assert contained_inspection_result(failure) is failure
    contained = contained_inspection_result(
        RuntimeError("UNSAFE_EXCEPTION_SENTINEL /private/database.sqlite")
    )
    assert contained == InspectionExecutionFailureView()
    assert "UNSAFE" not in repr(contained)
    assert "private" not in repr(contained)


def test_safe_view_maps_to_exact_ordered_primitive_accessibility_tree() -> None:
    projection = context_inspection_presentation_view(minimal_view())

    assert projection.outcome == "PROCESSING"
    assert tuple(
        (section.accessible_id, section.accessible_name)
        for section in projection.sections
    ) == (
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
    assert tuple(
        scalar.accessible_name for scalar in projection.sections[0].scalars
    ) == (
        "Request: Request 4",
        "Outcome: Processing",
        "Processing checkpoint: Accepted",
    )
    top_level_collections = tuple(
        collection
        for section in projection.sections
        for collection in section.collections
        if collection.accessible_id
        in {
            "contextInspectionQualifiers",
            "contextInspectionReferences",
            "contextInspectionConstraints",
            "contextInspectionConflicts",
            "contextInspectionMemories",
        }
    )
    assert tuple(collection.accessible_id for collection in top_level_collections) == (
        "contextInspectionQualifiers",
        "contextInspectionReferences",
        "contextInspectionConstraints",
        "contextInspectionConflicts",
        "contextInspectionMemories",
    )
    assert all(collection.items == () for collection in top_level_collections)
    assert all(
        collection.display_text == "Unavailable for this run."
        for collection in top_level_collections
    )
    assert projection.sections[6].scalars[0].accessible_name == (
        "Confidence: Unavailable for this run."
    )
    assert projection.sections[7].scalars[0].accessible_name == (
        "Validation: Unavailable for this run."
    )
    assert projection.sections[8].scalars[-1].accessible_name == (
        "Final status: Unavailable for this run."
    )


@pytest.mark.parametrize(
    ("outcome", "refreshed", "state", "text"),
    (
        (
            InspectionRunOutcome.PROCESSING,
            False,
            ContextInspectionPageState.READY,
            "Context inspection loaded.",
        ),
        (
            InspectionRunOutcome.SUCCEEDED,
            True,
            ContextInspectionPageState.READY,
            "Context inspection refreshed.",
        ),
        (
            InspectionRunOutcome.CANCELLED,
            False,
            ContextInspectionPageState.READY,
            "Context inspection loaded.",
        ),
        (
            InspectionRunOutcome.CLARIFICATION,
            True,
            ContextInspectionPageState.CLARIFICATION,
            "Context inspection refreshed. Clarification is required.",
        ),
        (
            InspectionRunOutcome.CONTROLLED_FAILURE,
            False,
            ContextInspectionPageState.CONTROLLED_FAILURE,
            "Context inspection loaded. Processing ended with a controlled failure.",
        ),
    ),
)
def test_ready_result_maps_outcome_and_load_kind_to_exact_page_state(
    outcome: InspectionRunOutcome,
    refreshed: bool,
    state: ContextInspectionPageState,
    text: str,
) -> None:
    result = inspection_result_presentation(
        ContextInspectionReadyResult(minimal_view(outcome)),
        refreshed=refreshed,
    )

    assert result.state is state
    assert result.status_text == text
    assert result.announcement_text == text
    assert result.view is not None


@pytest.mark.parametrize(
    ("raw_result", "state", "text"),
    (
        (
            ContextInspectionEmptyResult(),
            ContextInspectionPageState.EMPTY,
            "No processed request is available for this conversation.",
        ),
        (
            ContextInspectionLoadFailureResult(),
            ContextInspectionPageState.LOAD_ERROR,
            "Context inspection could not be loaded safely.",
        ),
        (
            InspectionExecutionFailureView(),
            ContextInspectionPageState.LOAD_ERROR,
            "Context inspection could not be loaded safely.",
        ),
    ),
)
def test_non_view_results_map_to_exact_state_without_prior_data(
    raw_result: object,
    state: ContextInspectionPageState,
    text: str,
) -> None:
    result = inspection_result_presentation(raw_result, refreshed=True)  # type: ignore[arg-type]

    assert result.state is state
    assert result.status_text == text
    assert result.announcement_text == text
    assert result.view is None
