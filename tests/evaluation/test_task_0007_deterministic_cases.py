"""Versioned deterministic evaluation cases for TASK-0007."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from context_for_ai.context_engine.constraints import DeterministicConstraintEngine
from context_for_ai.context_engine.interpretation import DeterministicInterpretationEngine
from context_for_ai.domain.decisions import (
    Constraint,
    ConstraintSourceEvidence,
    InterpretationDecision,
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
from context_for_ai.domain.policies import (
    ConfidenceBand,
    confidence_band,
    overall_confidence,
    requires_confidence_clarification,
)
from context_for_ai.domain.ports.context import (
    ConstraintEvaluationRequest,
    InterpretationRequest,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore
from context_for_ai.infrastructure.configuration import load_configuration


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "deterministic_interpretation"
CONFIGURATION_ROOT = Path(__file__).parents[1] / "fixtures" / "complete_configuration"
DOCUMENT = yaml.safe_load((FIXTURE_ROOT / "cases.yaml").read_text(encoding="utf-8"))
VERSION = (FIXTURE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
CASES = tuple(DOCUMENT["cases"])
FIXED = DOCUMENT["fixed"]
NOW = datetime.fromisoformat(FIXED["evaluated_at"].replace("Z", "+00:00"))
SETTINGS = load_configuration(application_root=CONFIGURATION_ROOT, environ={}).context


class FixedIds:
    def __init__(self) -> None:
        self._value = 100

    def new_id(self) -> DomainId:
        result = DomainId(f"73000000-0000-4000-8000-{self._value:012x}")
        self._value += 1
        return result


def _message(text: str) -> Message:
    return Message(
        DomainId(FIXED["message_id"]),
        DomainId(FIXED["conversation_id"]),
        MessageRole.USER,
        text,
        NOW,
        8,
    )


def _state(output: OutputType | None = None) -> ConversationState:
    return ConversationState(
        DomainId(FIXED["conversation_id"]),
        None,
        None,
        None,
        output,
        (),
        4,
        NOW,
    )


def _interpret(case: dict[str, object]) -> InterpretationDecision:
    prior = case.get("prior_output")
    source = _message(str(case["message"]))
    return DeterministicInterpretationEngine(SETTINGS).interpret(  # type: ignore[arg-type]
        InterpretationRequest(
            DomainId(FIXED["processing_run_id"]),
            source,
            _state(None if prior is None else OutputType(str(prior))),
            NOW,
        )
    )


def _manual_interpretation(source: Message, output: OutputType) -> InterpretationDecision:
    return InterpretationDecision(
        RequestInterpretation(
            DomainId(FIXED["processing_run_id"]),
            source.id,
            IntentType.EDIT_TEXT,
            output,
            "fixture",
            (),
            UnitScore("1"),
            "fixture",
            NOW,
        ),
        "mvp-context-rules-v2",
        (),
        None,
        None,
        (),
        None,
        None,
    )


def _eligible(
    number: int,
    constraint_type: ConstraintType,
    rule: str,
    target: str,
    priority: int,
    *,
    sequence: int = 1,
    source: ConstraintSourceKind = ConstraintSourceKind.CURRENT_MESSAGE,
) -> tuple[Constraint, ConstraintSourceEvidence]:
    constraint_id = DomainId(f"73000000-0000-4000-8000-{number:012x}")
    constraint = Constraint(
        constraint_id,
        DomainId(FIXED["processing_run_id"]),
        DomainId(FIXED["message_id"]),
        number,
        constraint_type,
        None,
        ConstraintScope.CURRENT_RESPONSE,
        rule,
        priority,
        source,
        rule,
        UnitScore("1"),
        ConstraintResolutionStatus.ACTIVE,
        None,
        None,
        NOW,
    )
    evidence = ConstraintSourceEvidence(
        constraint_id,
        target,
        (str(number),),
        (rule,),
        sequence,
        NOW,
        ("fixture",),
    )
    return constraint, evidence


def _constrain(
    source: Message,
    interpretation: InterpretationDecision,
    items: tuple[tuple[Constraint, ConstraintSourceEvidence], ...] = (),
    active_project: str | None = None,
):
    return DeterministicConstraintEngine(SETTINGS, FixedIds()).evaluate(  # type: ignore[arg-type]
        ConstraintEvaluationRequest(
            source,
            _state(interpretation.interpretation.expected_output_type),
            interpretation,
            (),
            tuple(item[0] for item in items),
            tuple(item[1] for item in items),
            active_project,
            NOW,
        )
    )


def test_fixture_is_versioned_unique_and_covers_every_required_category() -> None:
    assert DOCUMENT["fixture_version"] == VERSION == "task-0007-deterministic-v1"
    identifiers = [case["id"] for case in CASES]
    assert len(identifiers) == len(set(identifiers))
    assert {
        "intent",
        "qualifier",
        "same_intent_tie",
        "different_intent_tie",
        "unsupported",
        "permitted_text",
        "proposal",
        "condition",
        "condition_error",
        "override",
        "hard_soft",
        "soft_soft",
        "conflict",
        "assumption",
        "confidence",
        "weighted_confidence",
    } <= {case["category"] for case in CASES}


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["category"] in {"intent", "permitted_text"}],
    ids=lambda case: case["id"],
)
def test_fixture_intent_and_text_exception_cases(case: dict[str, object]) -> None:
    decision = _interpret(case)

    assert decision.interpretation.intent is IntentType(str(case["intent"]))
    assert decision.interpretation.expected_output_type is OutputType(str(case["output"]))
    assert decision.clarification_reason is None


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["category"] == "qualifier"],
    ids=lambda case: case["id"],
)
def test_fixture_qualifier_cases(case: dict[str, object]) -> None:
    decision = _interpret(case)

    assert QualifierKind(str(case["qualifier"])) in {
        item.kind for item in decision.interpretation.qualifiers
    }


def test_fixture_tie_cases_use_exact_canonical_ordering() -> None:
    same_case = next(case for case in CASES if case["category"] == "same_intent_tie")
    different_case = next(
        case for case in CASES if case["category"] == "different_intent_tie"
    )
    template_plan = SETTINGS.intent_rules[3]
    template_debug = SETTINGS.intent_rules[6]
    same_settings = replace(
        SETTINGS,
        intent_rules=(
            replace(template_plan, id="plan-z", phrases=("alpha",), priority=90),
            replace(template_plan, id="plan-a", phrases=("bravo",), priority=90),
            *SETTINGS.intent_rules,
        ),
    )
    different_settings = replace(
        SETTINGS,
        intent_rules=(
            replace(template_plan, id="tie-plan", phrases=("alpha",), priority=90),
            replace(template_debug, id="tie-debug", phrases=("bravo",), priority=90),
            *SETTINGS.intent_rules,
        ),
    )
    source = _message(str(same_case["message"]))
    request = InterpretationRequest(
        DomainId(FIXED["processing_run_id"]), source, _state(), NOW
    )

    same = DeterministicInterpretationEngine(same_settings).interpret(request)  # type: ignore[arg-type]
    different = DeterministicInterpretationEngine(different_settings).interpret(request)  # type: ignore[arg-type]

    assert same.interpretation.intent_rule_id == same_case["expected_rule"]
    assert different.interpretation.intent is IntentType.UNSUPPORTED
    assert different.clarification_reason is ClarificationReason(
        str(different_case["reason"])
    )


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["category"] == "unsupported"],
    ids=lambda case: case["id"],
)
def test_fixture_unsupported_cases_stop(case: dict[str, object]) -> None:
    decision = _interpret(case)

    assert decision.interpretation.intent is IntentType.UNSUPPORTED
    assert decision.clarification_reason is ClarificationReason(str(case["reason"]))


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["category"] == "proposal"],
    ids=lambda case: case["id"],
)
def test_fixture_exact_proposal_cases(case: dict[str, object]) -> None:
    decision = _interpret(case)

    assert decision.proposed_topic_label == case.get("topic")
    assert decision.proposed_task_title == case.get("task")


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["category"] == "confidence"],
    ids=lambda case: case["id"],
)
def test_fixture_confidence_cases(case: dict[str, object]) -> None:
    score = UnitScore(str(case["score"]))

    assert confidence_band(score) is ConfidenceBand(str(case["band"]))
    assert requires_confidence_clarification(score, material=True) is case[
        "material_blocks"
    ]


def test_fixture_weighted_confidence_case() -> None:
    case = next(case for case in CASES if case["category"] == "weighted_confidence")

    assert overall_confidence(
        interpretation=UnitScore(str(case["interpretation"])),
        reference_resolution=UnitScore(str(case["reference"])),
        retrieval=UnitScore(str(case["retrieval"])),
    ) == UnitScore(str(case["score"]))


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["category"] in {"condition", "condition_error"}],
    ids=lambda case: case["id"],
)
def test_fixture_condition_cases(case: dict[str, object]) -> None:
    source = _message(str(case["message"]))
    output = OutputType(str(case.get("output", "TEXT_ANSWER")))
    result = _constrain(source, _manual_interpretation(source, output))

    if case["category"] == "condition_error":
        assert result.clarification_reason is ClarificationReason(str(case["reason"]))
    else:
        conditional = next(
            item
            for item in result.constraints
            if item.constraint_type is ConstraintType.CONDITIONAL
        )
        assert conditional.condition.evaluation is ConditionEvaluation(
            str(case["evaluation"])
        )


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in CASES
        if case["category"]
        in {"override", "hard_soft", "soft_soft", "conflict", "assumption"}
    ],
    ids=lambda case: case["id"],
)
def test_fixture_constraint_resolution_cases(case: dict[str, object]) -> None:
    source = _message("edit text")
    decision = _manual_interpretation(source, OutputType.TEXT_ANSWER)
    category = case["category"]
    if case["id"] == "override-priority":
        first = _eligible(10, ConstraintType.REQUIRED, "MUST_USE:PYTHON", "USE:PYTHON", 1000)
        second = _eligible(11, ConstraintType.FORBIDDEN, "MUST_NOT_USE:PYTHON", "USE:PYTHON", 600, source=ConstraintSourceKind.CORRECTION_MEMORY)
    elif case["id"] == "override-recency":
        first = _eligible(12, ConstraintType.REQUIRED, "MUST_USE:RUST", "USE:RUST", 1000, sequence=1)
        second = _eligible(13, ConstraintType.FORBIDDEN, "MUST_NOT_USE:RUST", "USE:RUST", 1000, sequence=2)
    elif category == "hard_soft":
        first = _eligible(14, ConstraintType.PREFERRED, "PREFER_USE:PYTHON", "USE:PYTHON", 1000)
        second = _eligible(15, ConstraintType.FORBIDDEN, "MUST_NOT_USE:PYTHON", "USE:PYTHON", 400, source=ConstraintSourceKind.RETRIEVED_MEMORY)
    elif category == "soft_soft":
        first = _eligible(16, ConstraintType.PREFERRED, "PREFER_USE:RUST", "USE:RUST", 500, source=ConstraintSourceKind.PREFERENCE_MEMORY)
        second = _eligible(17, ConstraintType.OPTIONAL, "MAY_USE:RUST", "USE:RUST", 500, source=ConstraintSourceKind.PREFERENCE_MEMORY)
    elif case["id"] == "hard-conflict":
        first = _eligible(18, ConstraintType.REQUIRED, "MUST_USE:PYTHON", "USE:PYTHON", 1000)
        second = _eligible(19, ConstraintType.FORBIDDEN, "MUST_NOT_USE:PYTHON", "USE:PYTHON", 1000)
    elif case["id"] == "preserve-conflict":
        first = _eligible(20, ConstraintType.REQUIRED, "MUST_CHANGE:LAYOUT", "CHANGE:LAYOUT", 1000)
        second = _eligible(21, ConstraintType.PRESERVE, "MUST_PRESERVE:LAYOUT", "PRESERVE:LAYOUT", 1000)
    elif case["id"] == "assumed-redundant":
        first = _eligible(22, ConstraintType.REQUIRED, "MUST_USE:PYTHON", "USE:PYTHON", 1000)
        second = _eligible(23, ConstraintType.ASSUMED, "ASSUME_USE:PYTHON", "USE:PYTHON", 0, source=ConstraintSourceKind.ASSUMPTION)
    else:
        first = _eligible(24, ConstraintType.ASSUMED, "ASSUME_USE:RUST", "USE:RUST", 0, source=ConstraintSourceKind.ASSUMPTION)
        second = None
    items = (first,) if second is None else (first, second)
    result = _constrain(source, decision, items)

    if "reason" in case:
        assert result.clarification_reason is ClarificationReason(str(case["reason"]))
    elif "expected_rule" in case:
        active = {
            item.normalized_rule
            for item in result.constraints
            if item.resolution_status is ConstraintResolutionStatus.ACTIVE
        }
        assert case["expected_rule"] in active
    elif "expected_status" in case:
        by_rule = {item.normalized_rule: item for item in result.constraints}
        assert by_rule[second[0].normalized_rule].resolution_status is ConstraintResolutionStatus(
            str(case["expected_status"])
        )
    else:
        assert any(
            item.resolution_status is ConstraintResolutionStatus.OVERRIDDEN
            for item in result.constraints
        )
