"""Public-behavior tests for deterministic TASK-0007 interpretation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from context_for_ai.context_engine.interpretation import (
    DeterministicInterpretationEngine,
)
from context_for_ai.domain.entities import ConversationState, Message
from context_for_ai.domain.enums import (
    ClarificationReason,
    IntentType,
    MessageRole,
    OutputType,
    QualifierKind,
)
from context_for_ai.domain.ports.context import InterpretationRequest
from context_for_ai.domain.value_objects import DomainId, UnitScore
from context_for_ai.infrastructure.configuration import load_configuration


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"70000000-0000-4000-8000-{number:012x}")


def state(expected_output: OutputType | None = None) -> ConversationState:
    return ConversationState(identifier(1), None, None, None, expected_output, (), 4, NOW)


def request(text: str, prior_output: OutputType | None = None) -> InterpretationRequest:
    message = Message(identifier(2), identifier(1), MessageRole.USER, text, NOW, 8)
    return InterpretationRequest(identifier(3), message, state(prior_output), NOW)


def engine(fixture_application_root: Path) -> DeterministicInterpretationEngine:
    settings = load_configuration(
        application_root=fixture_application_root,
        environ={},
    ).context
    return DeterministicInterpretationEngine(settings)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "intent", "output"),
    [
        ("answer", IntentType.ANSWER, OutputType.TEXT_ANSWER),
        ("explain", IntentType.EXPLAIN, OutputType.TEXT_EXPLANATION),
        ("describe", IntentType.DESCRIBE, OutputType.TEXT_DESCRIPTION),
        ("plan", IntentType.PLAN, OutputType.TEXT_PLAN),
        ("analyze", IntentType.ANALYZE, OutputType.TEXT_ANALYSIS),
        ("research", IntentType.RESEARCH, OutputType.TEXT_ANALYSIS),
        ("debug", IntentType.DEBUG, OutputType.TEXT_ANALYSIS),
        ("edit text", IntentType.EDIT_TEXT, OutputType.TEXT_ANSWER),
    ],
)
def test_every_non_control_intent_has_its_canonical_output(
    fixture_application_root: Path,
    text: str,
    intent: IntentType,
    output: OutputType,
) -> None:
    decision = engine(fixture_application_root).interpret(request(text))

    assert decision.interpretation.intent is intent
    assert decision.interpretation.expected_output_type is output
    assert decision.interpretation.confidence == UnitScore("1")
    assert decision.clarification_reason is None


@pytest.mark.parametrize("text", ["continue", "correct"])
def test_control_intents_inherit_or_default_output(
    fixture_application_root: Path,
    text: str,
) -> None:
    interpreter = engine(fixture_application_root)

    retained = interpreter.interpret(request(text, OutputType.TEXT_PLAN))
    defaulted = interpreter.interpret(request(text))

    assert retained.interpretation.expected_output_type is OutputType.TEXT_PLAN
    assert defaulted.interpretation.expected_output_type is OutputType.TEXT_ANSWER


def test_configured_output_override_is_used(fixture_application_root: Path) -> None:
    settings = load_configuration(
        application_root=fixture_application_root,
        environ={},
    ).context
    answer = replace(settings.intent_rules[0], output_type="TEXT_COMPARISON")
    configured = replace(settings, intent_rules=(answer, *settings.intent_rules[1:]))

    decision = DeterministicInterpretationEngine(configured).interpret(request("answer"))  # type: ignore[arg-type]

    assert decision.interpretation.expected_output_type is OutputType.TEXT_COMPARISON


def test_source_evidence_preserves_exact_text_and_offsets(
    fixture_application_root: Path,
) -> None:
    decision = engine(fixture_application_root).interpret(
        request("  REMOVE   only the blue line")
    )
    evidence = decision.intent_candidates[0].evidence
    qualifier = decision.interpretation.qualifiers[0]

    assert evidence.matched_text == "REMOVE"
    assert (evidence.start_offset, evidence.end_offset) == (2, 8)
    assert qualifier.matched_text == "only"
    assert qualifier.captures["target"] == "remove blue line"


def test_same_intent_tie_uses_lexicographically_smaller_rule_id(
    fixture_application_root: Path,
) -> None:
    settings = load_configuration(
        application_root=fixture_application_root,
        environ={},
    ).context
    template = settings.intent_rules[3]
    rules = (
        replace(template, id="plan-z", phrases=("alpha",), priority=90),
        replace(template, id="plan-a", phrases=("bravo",), priority=90),
        *settings.intent_rules,
    )
    decision = DeterministicInterpretationEngine(
        replace(settings, intent_rules=rules)
    ).interpret(request("alpha bravo"))  # type: ignore[arg-type]

    assert decision.interpretation.intent is IntentType.PLAN
    assert decision.interpretation.intent_rule_id == "plan-a"


def test_different_intent_tie_is_unsupported_with_candidates(
    fixture_application_root: Path,
) -> None:
    settings = load_configuration(
        application_root=fixture_application_root,
        environ={},
    ).context
    plan = replace(
        settings.intent_rules[3], id="tie-plan", phrases=("alpha",), priority=90
    )
    debug = replace(
        settings.intent_rules[6], id="tie-debug", phrases=("bravo",), priority=90
    )
    decision = DeterministicInterpretationEngine(
        replace(settings, intent_rules=(plan, debug, *settings.intent_rules))
    ).interpret(request("alpha bravo"))  # type: ignore[arg-type]

    assert decision.interpretation.intent is IntentType.UNSUPPORTED
    assert decision.interpretation.expected_output_type is OutputType.CLARIFICATION
    assert decision.interpretation.confidence == UnitScore("0")
    assert decision.clarification_reason is ClarificationReason.LOW_CONFIDENCE_INTERPRETATION
    assert decision.clarification_details["candidate_intents"] == ("DEBUG", "PLAN")


def test_no_match_and_direct_image_or_action_requests_are_unsupported(
    fixture_application_root: Path,
) -> None:
    interpreter = engine(fixture_application_root)

    no_match = interpreter.interpret(request("unconfigured wording"))
    image = interpreter.interpret(request("generate an image"))
    action = interpreter.interpret(request("send an email"))

    assert no_match.clarification_reason is ClarificationReason.UNSUPPORTED_INTENT
    assert image.clarification_details["unsupported_categories"] == (
        "IMAGE_GENERATION",
    )
    assert action.clarification_details["unsupported_categories"] == (
        "EXTERNAL_ACTION",
    )


def test_explicit_description_and_text_prompt_are_permitted_text_results(
    fixture_application_root: Path,
) -> None:
    interpreter = engine(fixture_application_root)

    description = interpreter.interpret(request("describe how to generate an image"))
    prompt = interpreter.interpret(request("write a text prompt to generate an image"))

    assert description.interpretation.intent is IntentType.DESCRIBE
    assert description.interpretation.expected_output_type is OutputType.TEXT_DESCRIPTION
    assert description.clarification_reason is None
    assert prompt.interpretation.intent is IntentType.EDIT_TEXT
    assert prompt.interpretation.expected_output_type is OutputType.TEXT_ANSWER
    assert prompt.clarification_reason is None


@pytest.mark.parametrize(
    ("text", "expected_topic", "expected_task"),
    [
        ("topic: Launch", "launch", None),
        ("switch topic to Release", "release", None),
        ("task: Ship it", None, "ship it"),
        ("new task: Verify", None, "verify"),
        ("topic:", None, None),
    ],
)
def test_topic_and_task_proposals_use_only_exact_grammar(
    fixture_application_root: Path,
    text: str,
    expected_topic: str | None,
    expected_task: str | None,
) -> None:
    decision = engine(fixture_application_root).interpret(request(text))

    assert decision.proposed_topic_label == expected_topic
    assert decision.proposed_task_title == expected_task


@pytest.mark.parametrize(
    ("text", "kind", "capture_key", "capture_value"),
    [
        ("remove only the blue line", QualifierKind.ONLY, "target", "remove blue line"),
        ("edit text use exactly three words", QualifierKind.EXACTLY, "target", "use three words"),
        ("edit text use roughly three words", QualifierKind.APPROXIMATE, "target", "use three words"),
        ("edit text could use python", QualifierKind.APPROXIMATE, "target", "use python"),
        ("edit text might use python", QualifierKind.APPROXIMATE, "target", "use python"),
        ("describe; do not change layout", QualifierKind.PROHIBITION, "target", "change layout"),
        ("edit text without changing layout", QualifierKind.PRESERVATION, "object", "layout"),
        ("use rust instead of python; edit text", QualifierKind.SUBSTITUTION, "replacement", "rust"),
        ("continue same as before", QualifierKind.PRIOR_REFERENCE, "reference", "same as before"),
        ("plan one at a time", QualifierKind.SEQUENTIAL, "structure", "one ordered step at a time"),
    ],
)
def test_every_canonical_qualifier_has_deterministic_captures(
    fixture_application_root: Path,
    text: str,
    kind: QualifierKind,
    capture_key: str,
    capture_value: str,
) -> None:
    decision = engine(fixture_application_root).interpret(request(text))
    match = next(item for item in decision.interpretation.qualifiers if item.kind is kind)

    assert match.captures[capture_key] == capture_value
    if kind is QualifierKind.PRIOR_REFERENCE:
        assert len(decision.reference_mentions) == 1
        assert not hasattr(decision.reference_mentions[0], "status")


def test_missing_qualifier_operand_is_low_confidence_clarification(
    fixture_application_root: Path,
) -> None:
    decision = engine(fixture_application_root).interpret(
        request("instead of python; edit text")
    )

    assert decision.interpretation.intent is IntentType.EDIT_TEXT
    assert decision.interpretation.expected_output_type is OutputType.CLARIFICATION
    assert decision.interpretation.confidence == UnitScore("0.49")
    assert decision.clarification_reason is ClarificationReason.LOW_CONFIDENCE_INTERPRETATION
