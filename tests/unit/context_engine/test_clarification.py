"""Canonical clarification-template tests for TASK-0007."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from context_for_ai.context_engine.clarification import (
    DeterministicClarificationBuilder,
)
from context_for_ai.domain.enums import ClarificationReason
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import ClarificationBuildRequest
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"71000000-0000-4000-8000-{number:012x}")


@pytest.mark.parametrize(
    ("reason", "details", "expected"),
    [
        (
            ClarificationReason.AMBIGUOUS_REFERENCE,
            {"entity_type": "task", "surface_text": "it", "candidate_labels": ["A", "B"]},
            'Which task do you mean by "it"? A, B',
        ),
        (
            ClarificationReason.UNRESOLVED_REFERENCE,
            {"surface_text": "that"},
            'Please clarify what "that" refers to.',
        ),
        (
            ClarificationReason.LOW_CONFIDENCE_INTERPRETATION,
            {"candidate_intents": ["DEBUG", "PLAN"]},
            "Please clarify whether you want: DEBUG, PLAN.",
        ),
        (
            ClarificationReason.HARD_CONSTRAINT_CONFLICT,
            {"rule_a": "MUST_USE:PYTHON", "rule_b": "MUST_NOT_USE:PYTHON"},
            'Which instruction should apply: "MUST_USE:PYTHON" or "MUST_NOT_USE:PYTHON"?',
        ),
        (
            ClarificationReason.UNSUPPORTED_INTENT,
            {},
            "Please clarify the text-only result you want.",
        ),
        (
            ClarificationReason.UNSUPPORTED_CONDITION,
            {},
            "Please restate the condition using the supported output-type or active-project form.",
        ),
        (
            ClarificationReason.MATERIAL_ASSUMPTION,
            {"assumed_rule": "ASSUME_USE:PYTHON"},
            'Please confirm the assumption: "ASSUME_USE:PYTHON".',
        ),
    ],
)
def test_every_reason_builds_exactly_one_canonical_question(
    reason: ClarificationReason,
    details: dict[str, object],
    expected: str,
) -> None:
    result = DeterministicClarificationBuilder().build(
        ClarificationBuildRequest(
            identifier(1),
            identifier(2),
            reason,
            FrozenJsonObject(details),
            NOW,
        )
    )

    assert result.question_text == expected
    assert result.reason is reason
    assert result.details["reason"] == reason.value


def test_missing_template_input_is_rejected() -> None:
    request = ClarificationBuildRequest(
        identifier(1),
        identifier(2),
        ClarificationReason.MATERIAL_ASSUMPTION,
        FrozenJsonObject({}),
        NOW,
    )

    with pytest.raises(LifecycleInvariantError, match="assumed_rule"):
        DeterministicClarificationBuilder().build(request)
