"""Tests for immutable context-decision records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from context_for_ai.domain.decisions import (
    CONDITION_GRAMMAR_VERSION,
    CONTEXT_PACKET_SCHEMA_VERSION,
    Condition,
    Constraint,
    ContextPacket,
    QualifierMatch,
    ReferenceOutcome,
    RequestInterpretation,
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.enums import (
    ConditionEvaluation,
    ConditionKind,
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    IntentType,
    OutputType,
    QualifierKind,
    ReferenceStatus,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"10000000-0000-4000-8000-{number:012d}")


def test_interpretation_and_qualifiers_are_immutable_value_results() -> None:
    qualifier = QualifierMatch(QualifierKind.ONLY, "qualifier.only", "only")
    first = RequestInterpretation(
        identifier(1),
        identifier(2),
        IntentType.ANSWER,
        OutputType.TEXT_ANSWER,
        "intent.answer",
        (qualifier,),
        UnitScore("0.85"),
        "matched canonical answer phrase",
        NOW,
    )
    second = RequestInterpretation(
        identifier(1),
        identifier(2),
        IntentType.ANSWER,
        OutputType.TEXT_ANSWER,
        "intent.answer",
        (qualifier,),
        UnitScore("0.85"),
        "matched canonical answer phrase",
        NOW,
    )

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.reason = "changed"  # type: ignore[misc]


def test_reference_outcome_enforces_resolved_entity_presence() -> None:
    outcome = ReferenceOutcome(
        identifier(3),
        identifier(1),
        identifier(2),
        0,
        "the app",
        ReferenceStatus.RESOLVED,
        identifier(4),
        None,
        UnitScore("0.90"),
        (FrozenJsonObject({"candidate": "active project"}),),
        NOW,
    )

    assert outcome.resolved_entity_id == identifier(4)
    with pytest.raises(LifecycleInvariantError, match="requires resolved_entity_id"):
        ReferenceOutcome(
            identifier(3),
            identifier(1),
            identifier(2),
            0,
            "it",
            ReferenceStatus.RESOLVED,
            None,
            None,
            UnitScore("0.80"),
            (),
            NOW,
        )
    with pytest.raises(LifecycleInvariantError, match="Only a resolved"):
        ReferenceOutcome(
            identifier(3),
            identifier(1),
            identifier(2),
            0,
            "it",
            ReferenceStatus.UNRESOLVED,
            identifier(4),
            None,
            UnitScore("0.40"),
            (),
            NOW,
        )


def test_conditional_constraint_requires_fixed_grammar_and_hard_underlying_type() -> None:
    condition = Condition(
        CONDITION_GRAMMAR_VERSION,
        ConditionKind.OUTPUT_TYPE_EQUALS,
        OutputType.TEXT_CODE.value,
        ConditionEvaluation.TRUE,
    )
    constraint = Constraint(
        identifier(5),
        identifier(1),
        identifier(2),
        0,
        ConstraintType.CONDITIONAL,
        ConstraintType.REQUIRED,
        ConstraintScope.CURRENT_RESPONSE,
        "MUST_USE:PYTHON",
        900,
        ConstraintSourceKind.CURRENT_MESSAGE,
        "if output type is TEXT_CODE, use Python",
        UnitScore("1"),
        ConstraintResolutionStatus.ACTIVE,
        None,
        condition,
        NOW,
    )

    assert constraint.condition == condition
    with pytest.raises(LifecycleInvariantError, match="hard underlying"):
        Constraint(
            identifier(5),
            identifier(1),
            identifier(2),
            0,
            ConstraintType.CONDITIONAL,
            ConstraintType.PREFERRED,
            ConstraintScope.CURRENT_RESPONSE,
            "PREFER:PYTHON",
            900,
            ConstraintSourceKind.CURRENT_MESSAGE,
            "if output type is TEXT_CODE, prefer Python",
            UnitScore("1"),
            ConstraintResolutionStatus.ACTIVE,
            None,
            condition,
            NOW,
        )
    with pytest.raises(LifecycleInvariantError, match="Only a conditional"):
        Constraint(
            identifier(6),
            identifier(1),
            identifier(2),
            1,
            ConstraintType.REQUIRED,
            ConstraintType.REQUIRED,
            ConstraintScope.CURRENT_RESPONSE,
            "MUST_USE:PYTHON",
            1000,
            ConstraintSourceKind.CURRENT_MESSAGE,
            "use Python",
            UnitScore("1"),
            ConstraintResolutionStatus.ACTIVE,
            None,
            condition,
            NOW,
        )


def test_packet_and_retrieval_records_freeze_nested_evidence() -> None:
    packet_source = {
        "trace": {"processing_run_id": str(identifier(1))},
        "constraints": [{"id": str(identifier(5)), "priority": 1000}],
    }
    packet = ContextPacket(
        identifier(7),
        identifier(1),
        identifier(2),
        packet_source,  # type: ignore[arg-type]
        CONTEXT_PACKET_SCHEMA_VERSION,
        "opaque-policy-version",
        "configuration-fingerprint",
        NOW,
    )
    selected = RetrievalResult(
        identifier(8),
        packet.id,
        identifier(9),
        0,
        UnitScore("0.72"),
        ("project match", "keyword match"),
        NOW,
    )
    excluded = RetrievalExclusion(
        identifier(10),
        packet.id,
        identifier(11),
        RetrievalExclusionReason.SCORE_BELOW_THRESHOLD,
        UnitScore("0.20"),
        FrozenJsonObject({"threshold": 0.5}),
        NOW,
    )
    packet_source["constraints"] = []

    assert packet.packet["constraints"] == (
        FrozenJsonObject({"id": str(identifier(5)), "priority": 1000}),
    )
    assert selected.reasons == ("project match", "keyword match")
    assert excluded.details["threshold"] == 0.5


def test_packet_rejects_noncanonical_schema_version() -> None:
    with pytest.raises(LifecycleInvariantError, match="schema_version"):
        ContextPacket(
            identifier(7),
            identifier(1),
            identifier(2),
            FrozenJsonObject({}),
            "future-version",
            "opaque-policy-version",
            "configuration-fingerprint",
            NOW,
        )
