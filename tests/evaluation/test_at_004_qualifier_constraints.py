"""AT-004 through the public TASK-0007 result objects."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from context_for_ai.context_engine import (
    DeterministicConstraintEngine,
    DeterministicInterpretationEngine,
)
from context_for_ai.domain.decisions import ConstraintSourceEvidence
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
MESSAGE_TEXT = "Remove only the blue line and do not change anything else."


def identifier(number: int) -> DomainId:
    return DomainId(f"74000000-0000-4000-8000-{number:012x}")


class FixedIds:
    def __init__(self) -> None:
        self._next = 100

    def new_id(self) -> DomainId:
        result = identifier(self._next)
        self._next += 1
        return result


def state(output: OutputType | None) -> ConversationState:
    return ConversationState(identifier(1), None, None, None, output, (), 4, NOW)


def test_at_004_qualifiers_become_only_the_three_explicit_constraints() -> None:
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
    interpretation = DeterministicInterpretationEngine(settings).interpret(  # type: ignore[arg-type]
        InterpretationRequest(identifier(3), source, state(None), NOW)
    )

    assert interpretation.interpretation.intent is IntentType.EDIT_TEXT
    assert interpretation.interpretation.expected_output_type is OutputType.TEXT_ANSWER
    assert interpretation.interpretation.confidence == UnitScore("1")
    assert interpretation.clarification_reason is None
    selected_evidence = next(
        candidate.evidence
        for candidate in interpretation.intent_candidates
        if candidate.evidence.rule_id
        == interpretation.interpretation.intent_rule_id
    )
    assert (
        selected_evidence.matched_text,
        selected_evidence.normalized_phrase,
        selected_evidence.start_offset,
        selected_evidence.end_offset,
    ) == ("Remove", "remove", 0, 6)
    assert [item.kind for item in interpretation.interpretation.qualifiers] == [
        QualifierKind.ONLY,
        QualifierKind.PROHIBITION,
    ]
    assert [item.matched_text for item in interpretation.interpretation.qualifiers] == [
        "only",
        "do not",
    ]
    assert interpretation.reference_mentions == ()

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

    current = tuple(
        constraint
        for constraint in decision.constraints
        if constraint.source_kind is ConstraintSourceKind.CURRENT_MESSAGE
    )
    assert [
        (
            constraint.constraint_type,
            constraint.normalized_rule,
            constraint.priority,
            constraint.resolution_status,
        )
        for constraint in current
    ] == [
        (
            ConstraintType.REQUIRED,
            "MUST_REMOVE:BLUE_LINE",
            1000,
            ConstraintResolutionStatus.ACTIVE,
        ),
        (
            ConstraintType.PRESERVE,
            "MUST_PRESERVE:UNSPECIFIED_CONTENT",
            1000,
            ConstraintResolutionStatus.ACTIVE,
        ),
        (
            ConstraintType.FORBIDDEN,
            "MUST_NOT_CHANGE:UNSPECIFIED_CONTENT",
            1000,
            ConstraintResolutionStatus.ACTIVE,
        ),
    ]
    evidence_by_id: dict[DomainId, ConstraintSourceEvidence] = {
        item.constraint_id: item for item in decision.evidence
    }
    for constraint in current:
        evidence = evidence_by_id[constraint.id]
        assert evidence.contributing_rule_ids
        assert evidence.source_texts in {("only",), ("do not",)}
        assert evidence.source_message_sequence == 8

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
    assert decision.clarification_reason is None
