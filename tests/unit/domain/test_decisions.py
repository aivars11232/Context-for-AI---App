"""Tests for immutable context-decision records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from context_for_ai.domain.decisions import (
    CONDITION_GRAMMAR_VERSION,
    CONTEXT_PACKET_SCHEMA_VERSION,
    PROMPT_POLICY_VERSION,
    Condition,
    Constraint,
    ConstraintConflictGroup,
    ConstraintDecision,
    ConstraintSourceEvidence,
    ContextPacket,
    IntentCandidate,
    InterpretationDecision,
    MatchedRuleEvidence,
    QualifierMatch,
    ReferenceCandidateEvidence,
    ReferenceDecision,
    ReferenceMention,
    ReferenceOutcome,
    RequestInterpretation,
    ResponsePolicy,
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.enums import (
    ConditionEvaluation,
    ConditionKind,
    ClarificationReason,
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    EntityType,
    IntentType,
    OutputType,
    QualifierKind,
    ReferenceRankReason,
    ReferenceStatus,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
SELECTED_REASONS = (
    "project_match=0",
    "topic_match=1",
    "keyword_jaccard=0.5",
    "recency=1",
    "importance=0.5",
    "scope_match=1",
    "correction_match=0",
)


def identifier(number: int) -> DomainId:
    return DomainId(f"10000000-0000-4000-8000-{number:012d}")


def valid_packet_json(*, action_markers: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": CONTEXT_PACKET_SCHEMA_VERSION,
        "trace": {
            "processing_run_id": str(identifier(1)),
            "conversation_id": str(identifier(3)),
            "user_message_id": str(identifier(2)),
            "state_version": 4,
            "configuration_fingerprint": "configuration-fingerprint",
        },
        "request": {
            "original_text": "Explain the result.",
            "intent": "EXPLAIN",
            "intent_rule_id": "intent-explain",
            "expected_output_type": "TEXT_EXPLANATION",
            "qualifiers": (),
            "confidence": Decimal("0.9"),
        },
        "active_state": {
            "project_id": None,
            "topic_id": None,
            "task_id": None,
            "previous_task_id": None,
            "topic_stack": (),
        },
        "validation_context": {
            "rule_set_version": "validation-v1",
            "active_topic": None,
            "output_shape_rule": {
                "id": "shape-explanation",
                "output_type": "TEXT_EXPLANATION",
                "shape": "NON_EMPTY_TEXT",
            },
            "preserve_change_verb_list_id": "preserve-verbs-v1",
            "preserve_change_verbs": ("change",),
            "action_markers": action_markers or ["TOOL_CALL:"],
        },
        "references": (),
        "constraints": (),
        "retrieval": (),
        "confidence": {
            "interpretation": Decimal("0.9"),
            "references": None,
            "retrieval": None,
            "overall": Decimal("0.9"),
        },
        "response_policy": {
            "output_type": "TEXT_EXPLANATION",
            "validate_before_display": True,
            "text_only": True,
            "no_actions": True,
            "streaming": False,
            "correction_limit": 2,
            "model_generation_limit": 3,
            "absolute_model_generation_cap": 3,
        },
        "rendering": {
            "prompt_policy_version": PROMPT_POLICY_VERSION,
            "token_estimator": "conservative_utf8_v1",
            "token_budget": 1000,
            "mandatory_estimated_tokens": 200,
            "estimated_prompt_tokens": 200,
            "included_sections": (),
            "omitted_sections": (),
        },
    }


def active_project_evidence(
    *,
    rank: int = 1,
    entity_id: DomainId | None = None,
) -> ReferenceCandidateEvidence:
    return ReferenceCandidateEvidence(
        rank,
        entity_id or identifier(4),
        EntityType.PROJECT,
        "Context for AI",
        "context for ai",
        UnitScore("0.90"),
        ReferenceRankReason.ACTIVE_STATE,
        None,
        None,
        None,
        None,
        True,
    )


def no_candidate_evidence() -> ReferenceCandidateEvidence:
    return ReferenceCandidateEvidence(
        1,
        None,
        None,
        None,
        None,
        UnitScore("0.00"),
        ReferenceRankReason.NO_CANDIDATE,
        None,
        None,
        None,
        None,
        None,
    )


def exact_name_evidence(
    *,
    rank: int,
    entity_id: DomainId,
    entity_type: EntityType,
    display_name: str,
    message_id: DomainId,
) -> ReferenceCandidateEvidence:
    return ReferenceCandidateEvidence(
        rank,
        entity_id,
        entity_type,
        display_name,
        display_name.casefold(),
        UnitScore("1.00"),
        ReferenceRankReason.EXACT_NAME,
        identifier(20 + rank),
        message_id,
        4,
        None,
        True,
    )


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


def test_task_0007_interpretation_evidence_preserves_offsets_and_captures() -> None:
    evidence = MatchedRuleEvidence(
        "intent.edit.remove",
        "Remove",
        "remove",
        0,
        6,
        80,
    )
    qualifier = QualifierMatch(
        QualifierKind.ONLY,
        "qualifier.only",
        "only",
        "only",
        7,
        11,
        FrozenJsonObject({"target": "remove blue line"}),
    )
    interpretation = RequestInterpretation(
        identifier(1),
        identifier(2),
        IntentType.EDIT_TEXT,
        OutputType.TEXT_ANSWER,
        evidence.rule_id,
        (qualifier,),
        UnitScore("1"),
        "selected intent.edit.remove",
        NOW,
    )
    decision = InterpretationDecision(
        interpretation,
        "mvp-context-rules-v2",
        (IntentCandidate(IntentType.EDIT_TEXT, OutputType.TEXT_ANSWER, evidence),),
        None,
        None,
        (ReferenceMention(0, "same as before", "same as before", "prior", 12, 26),),
        ClarificationReason.LOW_CONFIDENCE_INTERPRETATION,
        FrozenJsonObject({"candidate_intents": ["EDIT_TEXT"]}),
    )

    assert qualifier.captures["target"] == "remove blue line"
    assert decision.intent_candidates[0].evidence.matched_text == "Remove"
    assert not hasattr(decision.reference_mentions[0], "resolved_entity_id")
    with pytest.raises(FrozenInstanceError):
        decision.rule_set_version = "changed"  # type: ignore[misc]


def test_task_0007_constraint_decision_requires_complete_evidence() -> None:
    constraint = Constraint(
        identifier(10),
        identifier(1),
        identifier(2),
        0,
        ConstraintType.FORBIDDEN,
        None,
        ConstraintScope.CURRENT_RESPONSE,
        "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
        1000,
        ConstraintSourceKind.DERIVED_OUTPUT_POLICY,
        "text-only policy",
        UnitScore("1"),
        ConstraintResolutionStatus.ACTIVE,
        None,
        None,
        NOW,
    )
    evidence = ConstraintSourceEvidence(
        constraint.id,
        "EXECUTE:IMAGE_OR_ACTION",
        ("policy.text-only",),
        ("text-only policy",),
        None,
        NOW,
        ("1000", "HARD", NOW.isoformat()),
    )
    policy = ResponsePolicy(OutputType.TEXT_ANSWER, "mvp-context-rules-v2")
    decision = ConstraintDecision(
        (constraint,),
        (evidence,),
        (),
        policy,
        None,
        None,
    )

    assert decision.response_policy.text_only is True
    assert decision.response_policy.actions_allowed is False
    with pytest.raises(LifecycleInvariantError, match="one evidence"):
        ConstraintDecision((constraint,), (), (), policy, None, None)

    second = Constraint(
        identifier(11),
        identifier(1),
        identifier(2),
        1,
        ConstraintType.REQUIRED,
        None,
        ConstraintScope.CURRENT_RESPONSE,
        "MUST_EXECUTE:IMAGE_OR_ACTION",
        1000,
        ConstraintSourceKind.CURRENT_MESSAGE,
        "execute image action",
        UnitScore("1"),
        ConstraintResolutionStatus.CONFLICTING,
        "hard-conflict-example",
        None,
        NOW,
    )
    with pytest.raises(LifecycleInvariantError, match="decision constraints"):
        ConstraintDecision(
            (constraint,),
            (evidence,),
            (ConstraintConflictGroup("group", "EXECUTE:IMAGE_OR_ACTION", (constraint.id, second.id)),),
            policy,
            ClarificationReason.HARD_CONSTRAINT_CONFLICT,
            FrozenJsonObject({"rule_a": constraint.normalized_rule, "rule_b": second.normalized_rule}),
        )


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
        (active_project_evidence(),),  # type: ignore[arg-type]
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
            (active_project_evidence(),),  # type: ignore[arg-type]
            NOW,
        )

    with pytest.raises(LifecycleInvariantError, match="non-empty typed"):
        ReferenceOutcome(
            identifier(3),
            identifier(1),
            identifier(2),
            0,
            "it",
            ReferenceStatus.UNRESOLVED,
            None,
            None,
            UnitScore("0.00"),
            (),
            NOW,
        )


def test_reference_candidate_evidence_has_exact_json_round_trip() -> None:
    evidence = exact_name_evidence(
        rank=1,
        entity_id=identifier(4),
        entity_type=EntityType.PROJECT,
        display_name="Context for AI",
        message_id=identifier(2),
    )

    stored = evidence.to_json_object()

    assert set(stored) == {
        "rank",
        "entity_id",
        "entity_type",
        "display_name",
        "normalized_name",
        "score",
        "rank_reason",
        "entity_source_message_id",
        "evidence_message_id",
        "evidence_message_sequence",
        "prior_mention_ordinal",
        "is_active",
    }
    assert stored["score"] == 1.0
    assert stored["rank_reason"] == "EXACT_NAME"
    assert ReferenceCandidateEvidence.from_json_object(stored) == evidence
    with pytest.raises(FrozenInstanceError):
        evidence.rank = 2  # type: ignore[misc]
    with pytest.raises(LifecycleInvariantError, match="canonical keys"):
        ReferenceCandidateEvidence.from_json_object(
            FrozenJsonObject({**dict(stored), "unexpected": True})
        )


def test_reference_candidate_evidence_rejects_noncanonical_reason_fields() -> None:
    with pytest.raises(LifecycleInvariantError, match="null candidate fields"):
        ReferenceCandidateEvidence(
            1,
            identifier(4),
            None,
            None,
            None,
            UnitScore("0.00"),
            ReferenceRankReason.NO_CANDIDATE,
            None,
            None,
            None,
            None,
            None,
        )
    with pytest.raises(LifecycleInvariantError, match="Tracked evidence"):
        ReferenceCandidateEvidence(
            1,
            identifier(4),
            EntityType.PROJECT,
            "Context for AI",
            "context for ai",
            UnitScore("0.80"),
            ReferenceRankReason.RECENT_TRACKED,
            None,
            None,
            None,
            None,
            True,
        )


def test_reference_outcome_and_decision_enforce_tie_and_blocking_contract() -> None:
    message_id = identifier(2)
    evidence = (
        exact_name_evidence(
            rank=1,
            entity_id=identifier(4),
            entity_type=EntityType.NAMED_ITEM,
            display_name="App",
            message_id=message_id,
        ),
        exact_name_evidence(
            rank=2,
            entity_id=identifier(5),
            entity_type=EntityType.PROJECT,
            display_name="App",
            message_id=message_id,
        ),
    )
    outcome = ReferenceOutcome(
        identifier(3),
        identifier(1),
        message_id,
        0,
        "the app",
        ReferenceStatus.AMBIGUOUS,
        None,
        None,
        UnitScore("1.00"),
        evidence,
        NOW,
    )
    details = FrozenJsonObject(
        {"mention_ordinal": 0, "surface_text": "the app", "entity_type": "entity"}
    )
    decision = ReferenceDecision(
        (outcome,),
        ClarificationReason.AMBIGUOUS_REFERENCE,
        details,
        True,
    )

    assert decision.outcomes == (outcome,)
    assert decision.blocks_generation is True
    with pytest.raises(LifecycleInvariantError, match="blocking flag"):
        ReferenceDecision(
            (outcome,),
            ClarificationReason.AMBIGUOUS_REFERENCE,
            details,
            False,
        )
    with pytest.raises(LifecycleInvariantError, match="canonical presentation"):
        ReferenceOutcome(
            identifier(6),
            identifier(1),
            message_id,
            0,
            "the app",
            ReferenceStatus.AMBIGUOUS,
            None,
            None,
            UnitScore("1.00"),
            (
                exact_name_evidence(
                    rank=1,
                    entity_id=identifier(5),
                    entity_type=EntityType.PROJECT,
                    display_name="App",
                    message_id=message_id,
                ),
                exact_name_evidence(
                    rank=2,
                    entity_id=identifier(4),
                    entity_type=EntityType.NAMED_ITEM,
                    display_name="App",
                    message_id=message_id,
                ),
            ),
            NOW,
        )


def test_declaration_target_is_non_blocking_not_applicable() -> None:
    message_id = identifier(2)
    declaration = ReferenceCandidateEvidence(
        1,
        None,
        None,
        None,
        None,
        UnitScore("0.00"),
        ReferenceRankReason.DECLARATION_TARGET,
        None,
        None,
        None,
        None,
        None,
    )
    outcome = ReferenceOutcome(
        identifier(3),
        identifier(1),
        message_id,
        0,
        "this",
        ReferenceStatus.NOT_APPLICABLE,
        None,
        message_id,
        UnitScore("1.00"),
        (declaration,),
        NOW,
    )

    assert ReferenceDecision((outcome,), None, None, False).blocks_generation is False
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
            UnitScore("0.00"),
            (no_candidate_evidence(),),  # type: ignore[arg-type]
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
    action_markers = ["TOOL_CALL:"]
    packet_source = valid_packet_json(action_markers=action_markers)
    packet = ContextPacket(
        identifier(7),
        identifier(1),
        identifier(2),
        packet_source,  # type: ignore[arg-type]
        CONTEXT_PACKET_SCHEMA_VERSION,
        PROMPT_POLICY_VERSION,
        "configuration-fingerprint",
        NOW,
    )
    selected = RetrievalResult(
        identifier(8),
        packet.id,
        identifier(9),
        0,
        UnitScore("0.72"),
        SELECTED_REASONS,
        NOW,
    )
    excluded = RetrievalExclusion(
        identifier(10),
        packet.id,
        identifier(11),
        RetrievalExclusionReason.SCORE_BELOW_THRESHOLD,
        UnitScore("0.20"),
        FrozenJsonObject({"minimum_relevance_score": "0.5"}),
        NOW,
    )
    action_markers.append("ACTION_EXECUTED:")

    validation_context = packet.packet_json["validation_context"]
    assert isinstance(validation_context, FrozenJsonObject)
    assert validation_context["action_markers"] == ("TOOL_CALL:",)
    assert selected.reasons == SELECTED_REASONS
    assert excluded.details["minimum_relevance_score"] == "0.5"


def test_context_packet_rejects_v1_and_outer_payload_mismatch() -> None:
    packet_json = valid_packet_json()
    packet_json["schema_version"] = "mvp-context-packet-v1"
    with pytest.raises(LifecycleInvariantError, match="v2"):
        ContextPacket(
            identifier(7),
            identifier(1),
            identifier(2),
            packet_json,  # type: ignore[arg-type]
            CONTEXT_PACKET_SCHEMA_VERSION,
            PROMPT_POLICY_VERSION,
            "configuration-fingerprint",
            NOW,
        )


def test_context_packet_revalidates_nested_confidence_semantics() -> None:
    packet_json = valid_packet_json()
    confidence = packet_json["confidence"]
    assert isinstance(confidence, dict)
    confidence["overall"] = Decimal("0.8")

    with pytest.raises(LifecycleInvariantError, match="normalized weighted mean"):
        ContextPacket(
            identifier(7),
            identifier(1),
            identifier(2),
            packet_json,  # type: ignore[arg-type]
            CONTEXT_PACKET_SCHEMA_VERSION,
            PROMPT_POLICY_VERSION,
            "configuration-fingerprint",
            NOW,
        )


def test_context_packet_revalidates_fixed_response_policy_scalars() -> None:
    packet_json = valid_packet_json()
    response_policy = packet_json["response_policy"]
    assert isinstance(response_policy, dict)
    response_policy["streaming"] = 0

    with pytest.raises(LifecycleInvariantError, match="fixed booleans"):
        ContextPacket(
            identifier(7),
            identifier(1),
            identifier(2),
            packet_json,  # type: ignore[arg-type]
            CONTEXT_PACKET_SCHEMA_VERSION,
            PROMPT_POLICY_VERSION,
            "configuration-fingerprint",
            NOW,
        )


def test_context_packet_revalidates_rendering_estimate_relationships() -> None:
    packet_json = valid_packet_json()
    rendering = packet_json["rendering"]
    assert isinstance(rendering, dict)
    rendering["mandatory_estimated_tokens"] = 201

    with pytest.raises(LifecycleInvariantError, match="fit its budget"):
        ContextPacket(
            identifier(7),
            identifier(1),
            identifier(2),
            packet_json,  # type: ignore[arg-type]
            CONTEXT_PACKET_SCHEMA_VERSION,
            PROMPT_POLICY_VERSION,
            "configuration-fingerprint",
            NOW,
        )


def test_context_packet_revalidates_normalized_validation_tokens() -> None:
    packet_json = valid_packet_json()
    validation_context = packet_json["validation_context"]
    assert isinstance(validation_context, dict)
    validation_context["preserve_change_verbs"] = (" Change ",)

    with pytest.raises(LifecycleInvariantError, match="normalized tokens"):
        ContextPacket(
            identifier(7),
            identifier(1),
            identifier(2),
            packet_json,  # type: ignore[arg-type]
            CONTEXT_PACKET_SCHEMA_VERSION,
            PROMPT_POLICY_VERSION,
            "configuration-fingerprint",
            NOW,
        )


def test_context_packet_revalidates_topic_word_normalization() -> None:
    packet_json = valid_packet_json()
    active_state = packet_json["active_state"]
    validation_context = packet_json["validation_context"]
    assert isinstance(active_state, dict)
    assert isinstance(validation_context, dict)
    active_state["topic_id"] = str(identifier(20))
    validation_context["active_topic"] = {
        "topic_id": str(identifier(20)),
        "terms": ("topic!",),
    }

    with pytest.raises(LifecycleInvariantError, match="normalized tokens"):
        ContextPacket(
            identifier(7),
            identifier(1),
            identifier(2),
            packet_json,  # type: ignore[arg-type]
            CONTEXT_PACKET_SCHEMA_VERSION,
            PROMPT_POLICY_VERSION,
            "configuration-fingerprint",
            NOW,
        )


def test_context_packet_revalidates_rendered_section_presence() -> None:
    packet_json = valid_packet_json()
    rendering = packet_json["rendering"]
    assert isinstance(rendering, dict)
    rendering["included_sections"] = ("REFERENCES",)

    with pytest.raises(LifecycleInvariantError, match="exactly match"):
        ContextPacket(
            identifier(7),
            identifier(1),
            identifier(2),
            packet_json,  # type: ignore[arg-type]
            CONTEXT_PACKET_SCHEMA_VERSION,
            PROMPT_POLICY_VERSION,
            "configuration-fingerprint",
            NOW,
        )


@pytest.mark.parametrize(
    "reasons",
    [
        SELECTED_REASONS[:-1],
        (SELECTED_REASONS[1], SELECTED_REASONS[0], *SELECTED_REASONS[2:]),
        ("project_match=1.0", *SELECTED_REASONS[1:]),
        ("project_match=2", *SELECTED_REASONS[1:]),
        ("project=1", *SELECTED_REASONS[1:]),
    ],
)
def test_retrieval_result_rejects_noncanonical_factor_reasons(
    reasons: tuple[str, ...],
) -> None:
    with pytest.raises(LifecycleInvariantError, match="seven|factor|canonical"):
        RetrievalResult(
            identifier(8),
            identifier(7),
            identifier(9),
            0,
            UnitScore("0.72"),
            reasons,
            NOW,
        )


def test_retrieval_exclusions_accept_all_exact_reason_shapes() -> None:
    cases = (
        (
            RetrievalExclusionReason.SCOPE_MISMATCH,
            None,
            {
                "scope": "CONVERSATION",
                "request_conversation_id": str(identifier(1)),
                "request_project_id": None,
                "memory_conversation_id": str(identifier(2)),
                "memory_project_id": None,
            },
        ),
        (
            RetrievalExclusionReason.DELETED,
            None,
            {"stored_status": "DELETED", "deleted_at": "2026-08-02T10:00:00Z"},
        ),
        (
            RetrievalExclusionReason.EXPIRED,
            None,
            {
                "stored_status": "ACTIVE",
                "expires_at": "2026-08-01T10:00:00Z",
                "evaluated_at": "2026-08-02T10:00:00Z",
            },
        ),
        (
            RetrievalExclusionReason.SCORE_BELOW_THRESHOLD,
            UnitScore("0.2"),
            {"minimum_relevance_score": "0.5"},
        ),
        (
            RetrievalExclusionReason.DUPLICATE_CONTENT,
            UnitScore("0.7"),
            {"retained_memory_id": str(identifier(3))},
        ),
        (
            RetrievalExclusionReason.LIMIT_EXCEEDED,
            UnitScore("0.6"),
            {"result_limit": 1, "pre_limit_rank": 1},
        ),
    )

    exclusions = tuple(
        RetrievalExclusion(
            identifier(20 + index),
            identifier(7),
            identifier(40 + index),
            reason,
            score,
            FrozenJsonObject(details),
            NOW,
        )
        for index, (reason, score, details) in enumerate(cases)
    )

    assert tuple(exclusion.exclusion_reason for exclusion in exclusions) == tuple(
        reason for reason, _, _ in cases
    )


@pytest.mark.parametrize(
    ("reason", "score", "details", "message"),
    [
        (
            RetrievalExclusionReason.DELETED,
            UnitScore("0.2"),
            {"stored_status": "DELETED", "deleted_at": "2026-08-02T10:00:00Z"},
            "nullability",
        ),
        (
            RetrievalExclusionReason.EXPIRED,
            None,
            {
                "stored_status": "ACTIVE",
                "expires_at": "2026-08-03T10:00:00Z",
                "evaluated_at": "2026-08-02T10:00:00Z",
            },
            "at or before",
        ),
        (
            RetrievalExclusionReason.SCORE_BELOW_THRESHOLD,
            UnitScore("0.2"),
            {"minimum_relevance_score": "0.50"},
            "canonical",
        ),
        (
            RetrievalExclusionReason.LIMIT_EXCEEDED,
            UnitScore("0.6"),
            {"result_limit": 2, "pre_limit_rank": 1},
            "at or beyond",
        ),
        (
            RetrievalExclusionReason.DUPLICATE_CONTENT,
            UnitScore("0.6"),
            {
                "retained_memory_id": str(identifier(9)),
                "normalized_content": "forbidden",
            },
            "exactly the canonical keys",
        ),
    ],
)
def test_retrieval_exclusion_rejects_noncanonical_evidence(
    reason: RetrievalExclusionReason,
    score: UnitScore | None,
    details: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(LifecycleInvariantError, match=message):
        RetrievalExclusion(
            identifier(10),
            identifier(7),
            identifier(9),
            reason,
            score,
            FrozenJsonObject(details),
            NOW,
        )


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
