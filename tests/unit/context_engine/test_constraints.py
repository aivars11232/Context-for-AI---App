"""Public-behavior tests for deterministic TASK-0007 constraints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from context_for_ai.context_engine.constraints import DeterministicConstraintEngine
from context_for_ai.domain.decisions import (
    Constraint,
    ConstraintSourceEvidence,
    InterpretationDecision,
    QualifierMatch,
    RequestInterpretation,
)
from context_for_ai.domain.entities import ConversationState, Message
from context_for_ai.domain.enums import (
    ClarificationReason,
    ConditionEvaluation,
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    IntentType,
    MessageRole,
    OutputType,
    QualifierKind,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import PriorityBand
from context_for_ai.domain.ports.context import ConstraintEvaluationRequest
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore
from context_for_ai.infrastructure.configuration import load_configuration


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"72000000-0000-4000-8000-{number:012x}")


class FixedIds:
    def __init__(self, start: int = 100) -> None:
        self._next = start

    def new_id(self) -> DomainId:
        result = identifier(self._next)
        self._next += 1
        return result


def message(text: str, *, sequence: int = 8) -> Message:
    return Message(identifier(2), identifier(1), MessageRole.USER, text, NOW, sequence)


def state(output: OutputType = OutputType.TEXT_ANSWER) -> ConversationState:
    return ConversationState(identifier(1), None, None, None, output, (), 4, NOW)


def qualifier(
    kind: QualifierKind,
    rule_id: str,
    matched_text: str,
    captures: dict[str, object],
) -> QualifierMatch:
    return QualifierMatch(
        kind,
        rule_id,
        matched_text,
        matched_text,
        0,
        len(matched_text),
        FrozenJsonObject(captures),
    )


def interpretation(
    source: Message,
    *,
    qualifiers: tuple[QualifierMatch, ...] = (),
    output: OutputType = OutputType.TEXT_ANSWER,
    clarification_reason: ClarificationReason | None = None,
) -> InterpretationDecision:
    details = (
        None
        if clarification_reason is None
        else FrozenJsonObject({"candidate_intents": ["EDIT_TEXT"]})
    )
    result = RequestInterpretation(
        identifier(3),
        source.id,
        IntentType.EDIT_TEXT,
        output,
        "edit-text",
        qualifiers,
        UnitScore("1"),
        "fixture interpretation",
        NOW,
    )
    return InterpretationDecision(
        result,
        "mvp-context-rules-v2",
        (),
        None,
        None,
        (),
        clarification_reason,
        details,
    )


def eligible(
    number: int,
    constraint_type: ConstraintType,
    rule: str,
    target_key: str,
    priority: int,
    *,
    source_kind: ConstraintSourceKind = ConstraintSourceKind.CURRENT_MESSAGE,
    sequence: int | None = 1,
    created_at: datetime = NOW,
) -> tuple[Constraint, ConstraintSourceEvidence]:
    constraint = Constraint(
        identifier(number),
        identifier(3),
        identifier(2),
        number,
        constraint_type,
        None,
        ConstraintScope.CURRENT_RESPONSE,
        rule,
        priority,
        source_kind,
        rule,
        UnitScore("1"),
        ConstraintResolutionStatus.ACTIVE,
        None,
        None,
        created_at,
    )
    evidence = ConstraintSourceEvidence(
        constraint.id,
        target_key,
        (f"fixture.{number}",),
        (rule,),
        sequence,
        created_at,
        ("fixture",),
    )
    return constraint, evidence


def evaluate(
    fixture_application_root: Path,
    source: Message,
    decision: InterpretationDecision,
    *,
    eligible_items: tuple[tuple[Constraint, ConstraintSourceEvidence], ...] = (),
    active_project_name: str | None = None,
) -> object:
    settings = load_configuration(
        application_root=fixture_application_root,
        environ={},
    ).context
    constraints = tuple(item[0] for item in eligible_items)
    evidence = tuple(item[1] for item in eligible_items)
    request = ConstraintEvaluationRequest(
        source,
        state(decision.interpretation.expected_output_type),
        decision,
        (),
        constraints,
        evidence,
        active_project_name,
        NOW,
    )
    return DeterministicConstraintEngine(settings, FixedIds()).evaluate(request)  # type: ignore[arg-type]


def test_every_qualifier_mapping_and_fixed_policy_are_observable(
    fixture_application_root: Path,
) -> None:
    source = message("qualifier fixture")
    qualifiers = (
        qualifier(QualifierKind.ONLY, "only", "only", {"target": "remove blue line", "action": "remove", "object": "blue line"}),
        qualifier(QualifierKind.EXACTLY, "exactly", "exactly", {"target": "use three words", "action": "use", "object": "three words"}),
        qualifier(QualifierKind.APPROXIMATE, "could", "could", {"target": "use python", "action": "use", "object": "python"}),
        qualifier(QualifierKind.PROHIBITION, "do-not", "do not", {"target": "change anything else", "action": "change", "object": "anything else"}),
        qualifier(QualifierKind.PRESERVATION, "preserve", "without changing", {"object": "layout"}),
        qualifier(QualifierKind.SUBSTITUTION, "instead", "instead of", {"action": "use", "replacement": "rust", "replaced": "python"}),
        qualifier(QualifierKind.PRIOR_REFERENCE, "prior", "same as before", {"reference": "same as before"}),
        qualifier(QualifierKind.SEQUENTIAL, "sequential", "one at a time", {"structure": "one ordered step at a time"}),
    )

    result = evaluate(
        fixture_application_root,
        source,
        interpretation(source, qualifiers=qualifiers),
    )
    rules = {constraint.normalized_rule for constraint in result.constraints}

    assert rules == {
        "MUST_REMOVE:BLUE_LINE",
        "MUST_PRESERVE:UNSPECIFIED_CONTENT",
        "MUST_EXACTLY:USE_THREE_WORDS",
        "PREFER_USE:PYTHON",
        "MUST_NOT_CHANGE:UNSPECIFIED_CONTENT",
        "MUST_PRESERVE:LAYOUT",
        "MUST_NOT_USE:PYTHON",
        "MUST_USE:RUST",
        "MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME",
        "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
    }
    assert result.response_policy.text_only is True
    assert result.response_policy.actions_allowed is False
    derived = next(
        item
        for item in result.constraints
        if item.source_kind is ConstraintSourceKind.DERIVED_OUTPUT_POLICY
    )
    assert derived.priority == 1000
    assert len(result.evidence) == len(result.constraints)


@pytest.mark.parametrize(
    ("text", "output", "active_project", "evaluation"),
    [
        ("if output type is text_answer, require use python", OutputType.TEXT_ANSWER, None, ConditionEvaluation.TRUE),
        ("if output type is text_answer, require use python", OutputType.TEXT_PLAN, None, ConditionEvaluation.FALSE),
        ('if active project is "alpha", preserve layout', OutputType.TEXT_ANSWER, "Alpha", ConditionEvaluation.TRUE),
        ('if active project is "alpha", do not change layout', OutputType.TEXT_ANSWER, "Beta", ConditionEvaluation.FALSE),
    ],
)
def test_supported_conditions_are_typed_and_true_or_inactive(
    fixture_application_root: Path,
    text: str,
    output: OutputType,
    active_project: str | None,
    evaluation: ConditionEvaluation,
) -> None:
    source = message(text)
    result = evaluate(
        fixture_application_root,
        source,
        interpretation(source, output=output),
        active_project_name=active_project,
    )
    conditional = next(
        item for item in result.constraints if item.constraint_type is ConstraintType.CONDITIONAL
    )

    assert conditional.condition.evaluation is evaluation
    assert conditional.priority == PriorityBand.TRUE_CONDITIONAL
    assert conditional.resolution_status is (
        ConstraintResolutionStatus.ACTIVE
        if evaluation is ConditionEvaluation.TRUE
        else ConstraintResolutionStatus.INACTIVE
    )


@pytest.mark.parametrize(
    "text",
    [
        "if output type is unknown, require use python",
        "if output type is text_answer require use python",
        "if active project is alpha, preserve layout",
    ],
)
def test_unknown_malformed_and_unquoted_conditions_require_clarification(
    fixture_application_root: Path,
    text: str,
) -> None:
    source = message(text)
    result = evaluate(fixture_application_root, source, interpretation(source))

    assert result.clarification_reason is ClarificationReason.UNSUPPORTED_CONDITION
    assert result.conflict_groups == ()


def test_higher_priority_and_newer_source_override_lower_opposition(
    fixture_application_root: Path,
) -> None:
    source = message("edit text")
    high = eligible(10, ConstraintType.REQUIRED, "MUST_USE:PYTHON", "USE:PYTHON", 1000, sequence=1)
    low = eligible(11, ConstraintType.FORBIDDEN, "MUST_NOT_USE:PYTHON", "USE:PYTHON", 600, source_kind=ConstraintSourceKind.CORRECTION_MEMORY, sequence=9)
    result = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(high, low),
    )
    by_id = {item.id: item for item in result.constraints}

    assert by_id[high[0].id].resolution_status is ConstraintResolutionStatus.ACTIVE
    assert by_id[low[0].id].resolution_status is ConstraintResolutionStatus.OVERRIDDEN

    older = eligible(12, ConstraintType.REQUIRED, "MUST_USE:RUST", "USE:RUST", 1000, sequence=1)
    newer = eligible(13, ConstraintType.FORBIDDEN, "MUST_NOT_USE:RUST", "USE:RUST", 1000, sequence=2)
    recency_result = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(older, newer),
    )
    by_id = {item.id: item for item in recency_result.constraints}
    assert by_id[older[0].id].resolution_status is ConstraintResolutionStatus.OVERRIDDEN
    assert by_id[newer[0].id].resolution_status is ConstraintResolutionStatus.ACTIVE


def test_hard_beats_soft_and_soft_tie_has_total_order(
    fixture_application_root: Path,
) -> None:
    source = message("edit text")
    soft = eligible(20, ConstraintType.PREFERRED, "PREFER_USE:PYTHON", "USE:PYTHON", 1000)
    hard = eligible(21, ConstraintType.FORBIDDEN, "MUST_NOT_USE:PYTHON", "USE:PYTHON", 400, source_kind=ConstraintSourceKind.RETRIEVED_MEMORY)
    result = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(soft, hard),
    )
    by_id = {item.id: item for item in result.constraints}
    assert by_id[soft[0].id].resolution_status is ConstraintResolutionStatus.OVERRIDDEN
    assert by_id[hard[0].id].resolution_status is ConstraintResolutionStatus.ACTIVE

    preferred = eligible(22, ConstraintType.PREFERRED, "PREFER_USE:RUST", "USE:RUST", 500, source_kind=ConstraintSourceKind.PREFERENCE_MEMORY)
    optional = eligible(23, ConstraintType.OPTIONAL, "MAY_USE:RUST", "USE:RUST", 500, source_kind=ConstraintSourceKind.PREFERENCE_MEMORY)
    soft_result = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(preferred, optional),
    )
    by_id = {item.id: item for item in soft_result.constraints}
    assert by_id[optional[0].id].resolution_status is ConstraintResolutionStatus.ACTIVE
    assert by_id[preferred[0].id].resolution_status is ConstraintResolutionStatus.OVERRIDDEN
    assert soft_result.clarification_reason is None


def test_equal_hard_opposition_and_required_change_preserve_stop_deterministically(
    fixture_application_root: Path,
) -> None:
    source = message("edit text")
    required = eligible(30, ConstraintType.REQUIRED, "MUST_USE:PYTHON", "USE:PYTHON", 1000)
    forbidden = eligible(31, ConstraintType.FORBIDDEN, "MUST_NOT_USE:PYTHON", "USE:PYTHON", 1000)
    result = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(required, forbidden),
    )

    assert result.clarification_reason is ClarificationReason.HARD_CONSTRAINT_CONFLICT
    assert len(result.conflict_groups) == 1
    assert result.conflict_groups[0].id.startswith("hard-conflict-")
    assert all(
        item.resolution_status is ConstraintResolutionStatus.CONFLICTING
        for item in result.constraints
        if item.id in {required[0].id, forbidden[0].id}
    )

    change = eligible(32, ConstraintType.REQUIRED, "MUST_CHANGE:LAYOUT", "CHANGE:LAYOUT", 1000)
    preserve = eligible(33, ConstraintType.PRESERVE, "MUST_PRESERVE:LAYOUT", "PRESERVE:LAYOUT", 1000)
    preserve_result = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(change, preserve),
    )
    assert preserve_result.clarification_reason is ClarificationReason.HARD_CONSTRAINT_CONFLICT


def test_assumptions_are_redundant_or_material_and_never_binding(
    fixture_application_root: Path,
) -> None:
    source = message("edit text")
    explicit = eligible(40, ConstraintType.REQUIRED, "MUST_USE:PYTHON", "USE:PYTHON", 1000)
    assumption = eligible(41, ConstraintType.ASSUMED, "ASSUME_USE:PYTHON", "USE:PYTHON", 0, source_kind=ConstraintSourceKind.ASSUMPTION)
    redundant = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(explicit, assumption),
    )
    by_id = {item.id: item for item in redundant.constraints}
    assert by_id[assumption[0].id].resolution_status is ConstraintResolutionStatus.OVERRIDDEN
    assert redundant.clarification_reason is None

    material_assumption = eligible(42, ConstraintType.ASSUMED, "ASSUME_USE:RUST", "USE:RUST", 0, source_kind=ConstraintSourceKind.ASSUMPTION)
    material = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(material_assumption,),
    )
    assert material.clarification_reason is ClarificationReason.MATERIAL_ASSUMPTION
    assert material.clarification_details["assumed_rule"] == "ASSUME_USE:RUST"

    invalid = eligible(43, ConstraintType.ASSUMED, "ASSUME_USE:GO", "USE:GO", 400, source_kind=ConstraintSourceKind.RETRIEVED_MEMORY)
    with pytest.raises(LifecycleInvariantError, match="ASSUMED constraints"):
        evaluate(
            fixture_application_root,
            source,
            interpretation(source),
            eligible_items=(invalid,),
        )


def test_clarification_precedence_is_interpretation_condition_conflict_assumption(
    fixture_application_root: Path,
) -> None:
    source = message("if output type is unknown, require use python")
    conflict_a = eligible(50, ConstraintType.REQUIRED, "MUST_USE:PYTHON", "USE:PYTHON", 1000)
    conflict_b = eligible(51, ConstraintType.FORBIDDEN, "MUST_NOT_USE:PYTHON", "USE:PYTHON", 1000)
    assumption = eligible(52, ConstraintType.ASSUMED, "ASSUME_USE:RUST", "USE:RUST", 0, source_kind=ConstraintSourceKind.ASSUMPTION)

    condition_first = evaluate(
        fixture_application_root,
        source,
        interpretation(source),
        eligible_items=(conflict_a, conflict_b, assumption),
    )
    assert condition_first.clarification_reason is ClarificationReason.UNSUPPORTED_CONDITION

    interpretation_first = evaluate(
        fixture_application_root,
        source,
        interpretation(
            source,
            clarification_reason=ClarificationReason.UNSUPPORTED_INTENT,
        ),
        eligible_items=(conflict_a, conflict_b, assumption),
    )
    assert interpretation_first.clarification_reason is ClarificationReason.UNSUPPORTED_INTENT
    assert interpretation_first.constraints == ()

    ordinary = message("edit text")
    conflict_first = evaluate(
        fixture_application_root,
        ordinary,
        interpretation(ordinary),
        eligible_items=(conflict_a, conflict_b, assumption),
    )
    assert conflict_first.clarification_reason is ClarificationReason.HARD_CONSTRAINT_CONFLICT
