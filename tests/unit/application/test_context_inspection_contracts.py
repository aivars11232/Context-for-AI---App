"""Closed TASK-0016 context-inspection application contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass
import inspect
from typing import Protocol, get_type_hints

import pytest

import context_for_ai.application as application
from context_for_ai.application import (
    ActiveStateItemView,
    ActiveStateKind,
    CanonicalLabelView,
    ClarificationInspectionView,
    ConfidenceInspectionView,
    ConflictInspectionView,
    ConflictRuleView,
    ConstraintConditionView,
    ConstraintInspectionView,
    ContextInspectionEmptyResult,
    ContextInspectionLoadFailureResult,
    ContextInspectionReadyResult,
    ContextInspectionView,
    InspectContext,
    InspectContextRequest,
    InspectContextResult,
    InspectionApplicationScope,
    InspectionAvailability,
    InspectionCheckpoint,
    InspectionCollection,
    InspectionRunOutcome,
    InspectionScoreView,
    InspectionTargetView,
    InspectionValue,
    QualifierEvidenceView,
    ReferenceEvidenceView,
    ReferenceInspectionView,
    ReferenceMessageSourceView,
    RetrievedMemoryInspectionView,
    SafeTerminalKind,
    SafeTerminalStatusView,
    SafeValidationEvidenceView,
    SafeValidationViolationView,
    ShellApplicationScopeFactory,
    ValidationInspectionView,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import DomainId


def _id(value: int) -> DomainId:
    return DomainId(f"00000000-0000-0000-0000-{value:012d}")


def _label(code: str) -> CanonicalLabelView:
    return CanonicalLabelView(code=code, display_label=code.lower().capitalize())


def _score() -> InspectionScoreView:
    return InspectionScoreView(canonical_decimal="0.8", display_text="0.80")


def _unavailable_value() -> InspectionValue[CanonicalLabelView]:
    return InspectionValue(
        availability=InspectionAvailability.UNAVAILABLE,
        value=None,
        display_text="Unavailable for this run.",
    )


def _unavailable_collection() -> InspectionCollection[CanonicalLabelView]:
    return InspectionCollection(
        availability=InspectionAvailability.UNAVAILABLE,
        items=(),
        display_text="Unavailable for this run.",
    )


def _minimal_view() -> ContextInspectionView:
    unavailable_value = _unavailable_value()
    unavailable_collection = _unavailable_collection()
    return ContextInspectionView(
        target=InspectionTargetView(
            user_message_sequence=1,
            request_label="Request 1",
            outcome=InspectionRunOutcome.PROCESSING,
            checkpoint=InspectionCheckpoint.ACCEPTED,
            outcome_label="Processing",
            checkpoint_label="Accepted",
        ),
        active_project=unavailable_value,
        active_topic=unavailable_value,
        active_task=unavailable_value,
        intent=unavailable_value,
        expected_output_type=unavailable_value,
        qualifier_evidence=unavailable_collection,
        references=unavailable_collection,
        constraints=unavailable_collection,
        conflicts=unavailable_collection,
        retrieved_memories=unavailable_collection,
        confidence=unavailable_value,
        validation=unavailable_value,
        correction_count=unavailable_value,
        clarification=unavailable_value,
        terminal_status=unavailable_value,
    )


def test_inspect_context_protocol_uses_the_closed_request_and_result() -> None:
    assert issubclass(InspectContext, Protocol)
    assert InspectContext._is_protocol is True
    assert [
        name
        for name, method in inspect.getmembers(InspectContext, inspect.isfunction)
        if not name.startswith("_")
    ] == ["execute"]
    assert get_type_hints(InspectContext.execute) == {
        "request": InspectContextRequest,
        "return": InspectContextResult,
    }
    assert not hasattr(application, "InspectContextInput")
    assert not hasattr(application, "InspectContextOutput")


def test_inspection_scope_exposes_only_query_close_and_additive_factory_open() -> None:
    assert issubclass(InspectionApplicationScope, Protocol)
    assert get_type_hints(InspectionApplicationScope) == {
        "inspect_context": InspectContext,
    }
    assert [
        name
        for name, method in inspect.getmembers(
            InspectionApplicationScope,
            inspect.isfunction,
        )
        if not name.startswith("_")
    ] == ["close"]
    assert [
        name
        for name, method in inspect.getmembers(
            ShellApplicationScopeFactory,
            inspect.isfunction,
        )
        if not name.startswith("_")
    ] == [
        "open_foreground_scope",
        "open_inspection_scope",
        "open_manual_operations_scope",
        "open_startup_scope",
    ]
    assert get_type_hints(
        ShellApplicationScopeFactory.open_inspection_scope
    )["return"] is InspectionApplicationScope


def test_inspection_result_algebra_has_exact_closed_fields_and_messages() -> None:
    view = _minimal_view()
    ready = ContextInspectionReadyResult(view=view)
    empty = ContextInspectionEmptyResult()
    failure = ContextInspectionLoadFailureResult()

    assert set(InspectContextResult.__value__.__args__) == {
        ContextInspectionReadyResult,
        ContextInspectionEmptyResult,
        ContextInspectionLoadFailureResult,
    }
    assert {item.name for item in fields(ContextInspectionReadyResult)} == {
        "result_kind",
        "view",
    }
    assert {item.name for item in fields(ContextInspectionEmptyResult)} == {
        "result_kind",
        "safe_message",
    }
    assert {item.name for item in fields(ContextInspectionLoadFailureResult)} == {
        "result_kind",
        "code",
        "safe_message",
    }
    assert ready.result_kind == "CONTEXT_INSPECTION_READY"
    assert empty.result_kind == "CONTEXT_INSPECTION_EMPTY"
    assert empty.safe_message == (
        "No processed request is available for this conversation."
    )
    assert failure.result_kind == "CONTEXT_INSPECTION_LOAD_FAILURE"
    assert failure.code == "INSPECTION_LOAD_FAILED"
    assert failure.safe_message == "Context inspection could not be loaded safely."


def test_complete_inspection_view_and_nested_values_are_closed_immutable_types() -> None:
    expected_fields = {
        ContextInspectionView: {
            "target",
            "active_project",
            "active_topic",
            "active_task",
            "intent",
            "expected_output_type",
            "qualifier_evidence",
            "references",
            "constraints",
            "conflicts",
            "retrieved_memories",
            "confidence",
            "validation",
            "correction_count",
            "clarification",
            "terminal_status",
        },
        InspectionTargetView: {
            "user_message_sequence",
            "request_label",
            "outcome",
            "checkpoint",
            "outcome_label",
            "checkpoint_label",
        },
        ActiveStateItemView: {"kind", "display_name"},
        QualifierEvidenceView: {"ordinal", "kind", "rule_id", "matched_text"},
        ReferenceMessageSourceView: {"message_sequence", "display_text"},
        ReferenceEvidenceView: {
            "rank",
            "candidate_display_name",
            "candidate_type",
            "score",
            "rank_reason",
            "evidence_message",
            "is_active",
            "activity_display_text",
        },
        ReferenceInspectionView: {
            "mention_number",
            "surface_text",
            "status",
            "resolved_display_name",
            "source_message",
            "confidence",
            "evidence",
        },
        ConstraintConditionView: {
            "grammar_version",
            "kind",
            "expected_value",
            "evaluation",
        },
        ConstraintInspectionView: {
            "ordinal",
            "type",
            "underlying_type",
            "scope",
            "normalized_rule",
            "priority",
            "source_kind",
            "source_text",
            "confidence",
            "resolution_status",
            "condition",
        },
        ConflictRuleView: {
            "constraint_ordinal",
            "type",
            "normalized_rule",
            "source_text",
        },
        ConflictInspectionView: {"ordinal", "rules"},
        RetrievedMemoryInspectionView: {
            "rank",
            "content",
            "scope",
            "memory_confidence",
            "retrieval_score",
            "reasons",
        },
        ConfidenceInspectionView: {
            "overall",
            "interpretation",
            "references",
            "retrieval",
        },
        SafeValidationViolationView: {"ordinal", "code", "message"},
        SafeValidationEvidenceView: {
            "ordinal",
            "check_id",
            "severity",
            "outcome",
            "violation_code",
            "warning_code",
            "explanation",
        },
        ValidationInspectionView: {
            "attempt_number",
            "status",
            "score",
            "violations",
            "evidence",
        },
        ClarificationInspectionView: {"reason", "question_text"},
        SafeTerminalStatusView: {
            "kind",
            "kind_label",
            "stage",
            "code",
            "safe_message",
        },
    }
    for dto_type, names in expected_fields.items():
        assert is_dataclass(dto_type)
        assert dto_type.__dataclass_params__.frozen is True
        assert "__slots__" in vars(dto_type)
        assert {item.name for item in fields(dto_type)} == names

    view = _minimal_view()
    with pytest.raises(FrozenInstanceError):
        view.target.request_label = "changed"  # type: ignore[misc]


def test_collection_backed_views_normalize_to_tuples() -> None:
    rule_one = ConflictRuleView(1, _label("REQUIRED"), "keep", "keep")
    rule_two = ConflictRuleView(2, _label("FORBIDDEN"), "remove", "remove")
    conflict = ConflictInspectionView(ordinal=1, rules=[rule_one, rule_two])
    memory = RetrievedMemoryInspectionView(
        rank=1,
        content="safe memory",
        scope=_label("GLOBAL"),
        memory_confidence=_score(),
        retrieval_score=_score(),
        reasons=[f"factor_{index}=0.8" for index in range(7)],
    )
    validation = ValidationInspectionView(
        attempt_number=1,
        status=_label("PASSED"),
        score=_score(),
        violations=[],
        evidence=[],
    )

    assert isinstance(conflict.rules, tuple)
    assert isinstance(memory.reasons, tuple)
    assert isinstance(validation.violations, tuple)
    assert isinstance(validation.evidence, tuple)


def test_safe_value_and_collection_availability_invariants_are_closed() -> None:
    available = InspectionValue(
        InspectionAvailability.AVAILABLE,
        _label("ANSWER"),
        "Answer",
    )
    empty = InspectionCollection(
        InspectionAvailability.EMPTY,
        (),
        "None recorded.",
    )

    assert available.value == _label("ANSWER")
    assert empty.items == ()
    with pytest.raises(LifecycleInvariantError):
        InspectionValue(InspectionAvailability.EMPTY, None, "None recorded.")
    with pytest.raises(LifecycleInvariantError):
        InspectionValue(
            InspectionAvailability.AVAILABLE,
            None,
            "Unavailable for this run.",
        )
    with pytest.raises(LifecycleInvariantError):
        InspectionCollection(
            InspectionAvailability.EMPTY,
            (_label("ANSWER"),),
            "None recorded.",
        )


def test_request_and_closed_enums_are_exact() -> None:
    assert InspectContextRequest(_id(1)).conversation_id == _id(1)
    assert {item.value for item in InspectionAvailability} == {
        "AVAILABLE",
        "EMPTY",
        "NOT_APPLICABLE",
        "UNAVAILABLE",
    }
    assert {item.value for item in InspectionRunOutcome} == {
        "PROCESSING",
        "SUCCEEDED",
        "CLARIFICATION",
        "CONTROLLED_FAILURE",
        "CANCELLED",
    }
    assert {item.value for item in InspectionCheckpoint} == {
        "ACCEPTED",
        "CONTEXT_COMMITTED",
        "VALIDATION_COMMITTED",
        "CLARIFICATION_COMMITTED",
        "TERMINAL_WITHOUT_CONTEXT",
    }
    assert {item.value for item in ActiveStateKind} == {"PROJECT", "TOPIC", "TASK"}
    assert {item.value for item in SafeTerminalKind} == {
        "CONTROLLED_FAILURE",
        "CANCELLED",
    }
