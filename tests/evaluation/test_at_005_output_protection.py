"""TASK-0007-owned portion of AT-005 through public result objects."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from context_for_ai.context_engine import (
    DeterministicConstraintEngine,
    DeterministicInterpretationEngine,
)
from context_for_ai.domain.decisions import ConstraintDecision, InterpretationDecision
from context_for_ai.domain.entities import ConversationState, Message
from context_for_ai.domain.enums import (
    ConstraintResolutionStatus,
    ConstraintSourceKind,
    ConstraintType,
    IntentType,
    MessageRole,
    OutputType,
    QualifierKind,
)
from context_for_ai.domain.ports.context import (
    ConstraintEvaluationRequest,
    InterpretationRequest,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore
from context_for_ai.infrastructure.configuration import load_configuration


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
MESSAGE_TEXT = "Do not generate anything; give me a description."


def identifier(number: int) -> DomainId:
    return DomainId(f"75000000-0000-4000-8000-{number:012x}")


class FixedIds:
    def __init__(self) -> None:
        self._next = 100

    def new_id(self) -> DomainId:
        result = identifier(self._next)
        self._next += 1
        return result


def state(output: OutputType | None) -> ConversationState:
    return ConversationState(identifier(1), None, None, None, output, (), 4, NOW)


def test_at_005_description_remains_text_only_and_action_free() -> None:
    settings = load_configuration(
        application_root=REPOSITORY_ROOT,
        environ={},
    ).context
    source = Message(
        identifier(2),
        identifier(1),
        MessageRole.USER,
        MESSAGE_TEXT,
        NOW,
        8,
    )
    prior_state = state(OutputType.TEXT_PLAN)

    interpretation = DeterministicInterpretationEngine(settings).interpret(  # type: ignore[arg-type]
        InterpretationRequest(identifier(3), source, prior_state, NOW)
    )

    assert isinstance(interpretation, InterpretationDecision)
    assert interpretation.interpretation.intent is IntentType.DESCRIBE
    assert (
        interpretation.interpretation.expected_output_type
        is OutputType.TEXT_DESCRIPTION
    )
    assert interpretation.interpretation.confidence == UnitScore("1")
    assert interpretation.clarification_reason is None
    assert prior_state.expected_output_type is OutputType.TEXT_PLAN
    selected_evidence = next(
        candidate.evidence
        for candidate in interpretation.intent_candidates
        if candidate.evidence.rule_id
        == interpretation.interpretation.intent_rule_id
    )
    assert selected_evidence.matched_text == "give me a description"
    prohibition = next(
        item
        for item in interpretation.interpretation.qualifiers
        if item.kind is QualifierKind.PROHIBITION
    )
    assert prohibition.matched_text == "Do not"
    assert prohibition.normalized_phrase == "do not"
    assert prohibition.captures["action"] == "generate"
    assert prohibition.captures["object"] == "anything"

    decision = DeterministicConstraintEngine(settings, FixedIds()).evaluate(  # type: ignore[arg-type]
        ConstraintEvaluationRequest(
            source,
            state(interpretation.interpretation.expected_output_type),
            interpretation,
            (),
            (),
            (),
            None,
            NOW,
        )
    )

    assert isinstance(decision, ConstraintDecision)
    assert decision.response_policy.expected_output_type is OutputType.TEXT_DESCRIPTION
    assert decision.response_policy.text_only is True
    assert decision.response_policy.actions_allowed is False
    assert decision.clarification_reason is None

    current = tuple(
        constraint
        for constraint in decision.constraints
        if constraint.source_kind is ConstraintSourceKind.CURRENT_MESSAGE
    )
    assert len(current) == 1
    assert current[0].constraint_type is ConstraintType.FORBIDDEN
    assert current[0].normalized_rule == "MUST_NOT_GENERATE:ANYTHING"
    assert current[0].priority == 1000
    current_evidence = next(
        item for item in decision.evidence if item.constraint_id == current[0].id
    )
    assert current_evidence.contributing_rule_ids == (prohibition.rule_id,)
    assert current_evidence.source_texts == ("Do not",)

    derived = tuple(
        constraint
        for constraint in decision.constraints
        if constraint.source_kind is ConstraintSourceKind.DERIVED_OUTPUT_POLICY
    )
    assert len(derived) == 1
    assert derived[0].constraint_type is ConstraintType.FORBIDDEN
    assert derived[0].normalized_rule == "MUST_NOT_EXECUTE:IMAGE_OR_ACTION"
    assert derived[0].priority == 1000
    assert derived[0].resolution_status is ConstraintResolutionStatus.ACTIVE
    derived_evidence = next(
        item for item in decision.evidence if item.constraint_id == derived[0].id
    )
    assert derived_evidence.contributing_rule_ids == ("policy.text-only",)
    assert derived_evidence.source_message_sequence is None
    assert not hasattr(interpretation, "packet")
    assert not hasattr(decision, "packet")
