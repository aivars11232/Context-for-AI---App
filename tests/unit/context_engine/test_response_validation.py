"""Focused public-behavior tests for deterministic response validation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from context_for_ai.context_engine.prompt_rendering import _plan_initial
from context_for_ai.context_engine.response_validation import (
    DeterministicResponseValidator,
)
from context_for_ai.domain.decisions import (
    CONTEXT_PACKET_SCHEMA_VERSION,
    HISTORICAL_PROMPT_POLICY_VERSION,
    PROMPT_POLICY_VERSION,
    ContextPacket,
)
from context_for_ai.domain.enums import (
    ValidationCheckId,
    ValidationOutcome,
    ValidationStatus,
    ValidationViolationCode,
    ValidationWarningCode,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import (
    ContextBudgetExceeded,
    ValidationRequest,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"60000000-0000-4000-8000-{number:012d}")


def constraint(
    number: int,
    ordinal: int,
    constraint_type: str,
    predicate: str,
    *,
    priority: int | None = None,
    status: str = "ACTIVE",
    underlying_type: str | None = None,
    condition_evaluation: str | None = None,
    winner_number: int | None = None,
) -> FrozenJsonObject:
    assumption = constraint_type == "ASSUMED"
    actual_priority = 0 if assumption else (1000 - ordinal if priority is None else priority)
    condition = (
        None
        if condition_evaluation is None
        else {
            "grammar_version": "mvp-condition-v1",
            "kind": "OUTPUT_TYPE_EQUALS",
            "expected_value": "TEXT_EXPLANATION",
            "evaluation": condition_evaluation,
        }
    )
    winner_id = None if winner_number is None else str(identifier(winner_number))
    return FrozenJsonObject(
        {
            "ordinal": ordinal,
            "id": str(identifier(number)),
            "type": constraint_type,
            "underlying_type": underlying_type,
            "scope": "CURRENT_RESPONSE",
            "normalized_rule": predicate,
            "priority": actual_priority,
            "source_kind": "ASSUMPTION" if assumption else "CURRENT_MESSAGE",
            "source_evidence": {
                "constraint_id": str(identifier(number)),
                "target_key": f"target:{number}",
                "contributing_rule_ids": (f"rule-{number}",),
                "source_texts": (f"source {number}",),
                "source_message_id": None if assumption else str(identifier(2)),
                "source_memory_id": None,
                "source_state": None,
                "source_message_sequence": None if assumption else 1,
                "source_created_at": "2026-08-09T12:00:00Z",
                "comparison_tuple": (f"comparison-{number}",),
                "winner_constraint_id": winner_id,
                "related_constraint_ids": () if winner_id is None else (winner_id,),
            },
            "confidence": Decimal("1"),
            "status": status,
            "conflict_group_id": None,
            "condition": condition,
        }
    )


def packet(
    *,
    constraints: tuple[FrozenJsonObject, ...] = (),
    topic_terms: tuple[str, ...] | None = None,
    output_type: str = "TEXT_EXPLANATION",
    output_shape: str = "NON_EMPTY_TEXT",
    action_markers: tuple[str, ...] = ("TOOL_CALL:",),
    preserve_verbs: tuple[str, ...] = ("change",),
    correction_limit: int = 2,
    prompt_policy_version: str = PROMPT_POLICY_VERSION,
) -> ContextPacket:
    active_topic = (
        None
        if topic_terms is None
        else {
            "topic_id": str(identifier(11)),
            "terms": topic_terms,
        }
    )
    values: dict[str, object] = {
        "schema_version": CONTEXT_PACKET_SCHEMA_VERSION,
        "trace": {
            "processing_run_id": str(identifier(1)),
            "conversation_id": str(identifier(3)),
            "user_message_id": str(identifier(2)),
            "state_version": 2,
            "configuration_fingerprint": "configuration-fingerprint",
        },
        "request": {
            "original_text": "Validate the candidate.",
            "intent": "EXPLAIN",
            "intent_rule_id": "intent-explain",
            "expected_output_type": output_type,
            "qualifiers": (),
            "confidence": Decimal("0.9"),
        },
        "active_state": {
            "project_id": None,
            "topic_id": None if active_topic is None else str(identifier(11)),
            "task_id": None,
            "previous_task_id": None,
            "topic_stack": (),
        },
        "validation_context": {
            "rule_set_version": "validation-v1",
            "active_topic": active_topic,
            "output_shape_rule": {
                "id": f"shape-{output_shape.casefold()}",
                "output_type": output_type,
                "shape": output_shape,
            },
            "preserve_change_verb_list_id": "preserve-v1",
            "preserve_change_verbs": preserve_verbs,
            "action_markers": action_markers,
        },
        "references": (),
        "constraints": constraints,
        "retrieval": (),
        "confidence": {
            "interpretation": Decimal("0.9"),
            "references": None,
            "retrieval": None,
            "overall": Decimal("0.9"),
        },
        "response_policy": {
            "output_type": output_type,
            "validate_before_display": True,
            "text_only": True,
            "no_actions": True,
            "streaming": False,
            "correction_limit": correction_limit,
            "model_generation_limit": correction_limit + 1,
            "absolute_model_generation_cap": 3,
        },
        "rendering": {
            "prompt_policy_version": prompt_policy_version,
            "token_estimator": "conservative_utf8_v1",
            "token_budget": 10000,
            "mandatory_estimated_tokens": 0,
            "estimated_prompt_tokens": 0,
            "included_sections": (),
            "omitted_sections": (),
        },
    }
    plan = _plan_initial(
        context_packet_id=identifier(10),
        packet_json=FrozenJsonObject(values),
        effective_budget=10000,
    )
    assert not isinstance(plan, ContextBudgetExceeded)
    values["rendering"] = plan.metadata.to_json_object()
    return ContextPacket(
        identifier(10),
        identifier(1),
        identifier(2),
        FrozenJsonObject(values),
        CONTEXT_PACKET_SCHEMA_VERSION,
        prompt_policy_version,
        "configuration-fingerprint",
        NOW,
    )


def validate(packet_value: ContextPacket, candidate: str):
    return DeterministicResponseValidator().validate(
        ValidationRequest(
            packet_value,
            identifier(20),
            identifier(21),
            candidate,
            NOW,
        )
    )


def test_fixed_checks_and_required_predicate_pass_with_exact_source_locations() -> None:
    packet_value = packet(
        topic_terms=("café",),
        constraints=(constraint(30, 0, "REQUIRED", "MUST_USE:PYTHON"),),
    )

    first = validate(packet_value, "CAFE\u0301. Use Python.")
    second = validate(packet_value, "CAFE\u0301. Use Python.")

    assert first == second
    assert first.status is ValidationStatus.PASSED
    assert first.score.value == Decimal("1.00")
    assert tuple(item.check_id for item in first.evidence) == (
        ValidationCheckId.TOPIC,
        ValidationCheckId.OUTPUT_SHAPE,
        ValidationCheckId.ACTION_MARKER,
        ValidationCheckId.REQUIRED_CONSTRAINT,
        ValidationCheckId.REPETITION,
    )
    topic, _, _, required, _ = first.evidence
    assert topic.matches[0].source_start == 0
    assert topic.matches[0].source_end == 5
    assert topic.matches[0].sentence_ordinal == 0
    assert tuple(
        "CAFE\u0301. Use Python."[match.source_start : match.source_end]
        for match in required.matches
    ) == ("Use", "Python")
    assert required.normalized_input["candidate_token_count"] == 3
    assert required.normalized_input["sentence_count"] == 2


def test_all_constraint_categories_use_canonical_order_and_outcomes() -> None:
    constraints = (
        constraint(30, 0, "REQUIRED", "MUST_USE:PYTHON"),
        constraint(31, 1, "FORBIDDEN", "MUST_NOT_DELETE:FILE"),
        constraint(32, 2, "PRESERVE", "MUST_PRESERVE:HEADER"),
        constraint(
            33,
            3,
            "CONDITIONAL",
            "MUST_INCLUDE:SUMMARY",
            underlying_type="REQUIRED",
            condition_evaluation="TRUE",
        ),
        constraint(34, 4, "PREFERRED", "PREFER_ADD:EXAMPLE"),
        constraint(35, 5, "OPTIONAL", "MAY_USE:RUST"),
        constraint(
            36,
            6,
            "ASSUMED",
            "ASSUME_USE:GO",
            status="OVERRIDDEN",
            winner_number=30,
        ),
    )

    result = validate(
        packet(constraints=constraints),
        "Use Python and Rust. Delete file. Change header.",
    )

    assert tuple(item.check_id for item in result.evidence) == tuple(ValidationCheckId)
    by_check = {item.check_id: item for item in result.evidence}
    assert by_check[ValidationCheckId.REQUIRED_CONSTRAINT].outcome is ValidationOutcome.PASSED
    assert by_check[ValidationCheckId.FORBIDDEN_CONSTRAINT].outcome is ValidationOutcome.FAILED
    assert by_check[ValidationCheckId.PRESERVE_CONSTRAINT].outcome is ValidationOutcome.FAILED
    assert by_check[ValidationCheckId.CONDITIONAL_CONSTRAINT].outcome is ValidationOutcome.FAILED
    assert by_check[ValidationCheckId.PREFERRED_CONSTRAINT].warning_code is (
        ValidationWarningCode.PREFERRED_CONSTRAINT_UNSATISFIED
    )
    assert by_check[ValidationCheckId.OPTIONAL_CONSTRAINT].outcome is ValidationOutcome.PASSED
    assert by_check[ValidationCheckId.ASSUMED_CONSTRAINT].warning_code is (
        ValidationWarningCode.ASSUMED_CONSTRAINT_NON_BINDING
    )
    assert tuple(violation.code for violation in result.violations) == (
        ValidationViolationCode.FORBIDDEN_ACTION,
        ValidationViolationCode.PRESERVATION_VIOLATION,
        ValidationViolationCode.CONDITIONAL_VIOLATION,
    )
    assert result.score.value == Decimal("0.10")


def test_inactive_and_overridden_nonassumption_constraints_are_not_applicable() -> None:
    constraints = (
        constraint(30, 0, "REQUIRED", "MUST_USE:PYTHON"),
        constraint(
            31,
            1,
            "CONDITIONAL",
            "MUST_NOT_DELETE:FILE",
            status="INACTIVE",
            underlying_type="FORBIDDEN",
            condition_evaluation="FALSE",
        ),
        constraint(
            32,
            2,
            "PREFERRED",
            "PREFER_USE:RUST",
            status="OVERRIDDEN",
            winner_number=30,
        ),
    )

    result = validate(packet(constraints=constraints), "Use Python. Delete file.")

    conditional = next(
        item
        for item in result.evidence
        if item.check_id is ValidationCheckId.CONDITIONAL_CONSTRAINT
    )
    preferred = next(
        item
        for item in result.evidence
        if item.check_id is ValidationCheckId.PREFERRED_CONSTRAINT
    )
    assert conditional.outcome is ValidationOutcome.NOT_APPLICABLE
    assert preferred.outcome is ValidationOutcome.NOT_APPLICABLE
    assert not result.violations


def test_action_marker_and_derived_forbidden_rule_fail_independently() -> None:
    marker = "TOOL_\nCALL:"
    result = validate(
        packet(
            action_markers=(marker,),
            constraints=(
                constraint(
                    30,
                    0,
                    "FORBIDDEN",
                    "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
                ),
            ),
        ),
        "Text TOOL_\nCALL: remains.",
    )

    assert tuple(violation.code for violation in result.violations) == (
        ValidationViolationCode.OUTPUT_TYPE_MISMATCH,
        ValidationViolationCode.FORBIDDEN_ACTION,
    )
    action = result.evidence[2]
    forbidden = result.evidence[3]
    assert action.matches == forbidden.matches
    assert action.matches[0].sentence_ordinal is None
    assert result.score.value == Decimal("0.55")


def test_literal_matching_retains_overlaps_but_deduplicates_mapped_locations() -> None:
    result = validate(
        packet(action_markers=("aa",)),
        "aaaa text",
    )

    assert tuple(
        (match.source_start, match.source_end)
        for match in result.evidence[2].matches
    ) == ((0, 2), (1, 3), (2, 4))


def test_positive_predicates_never_match_across_sentence_boundaries() -> None:
    result = validate(
        packet(
            constraints=(constraint(30, 0, "REQUIRED", "MUST_USE:PYTHON"),)
        ),
        "Use. Python.",
    )

    required = result.evidence[3]
    assert required.outcome is ValidationOutcome.FAILED
    assert required.matches == ()
    assert required.missing_predicate == "MUST_USE:PYTHON"


@pytest.mark.parametrize(
    ("predicate", "candidate", "expected"),
    (
        ("MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI", "Answer context for AI.", True),
        ("MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI", "Answer the context for AI.", False),
        ("MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME", "1. First step", True),
        ("MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME", "1. First\n2. Second", False),
    ),
)
def test_reserved_required_predicates_have_exact_semantics(
    predicate: str,
    candidate: str,
    expected: bool,
) -> None:
    result = validate(
        packet(constraints=(constraint(30, 0, "REQUIRED", predicate),)),
        candidate,
    )

    required = result.evidence[3]
    assert (required.outcome is ValidationOutcome.PASSED) is expected
    if predicate.startswith("MUST_PRESENT:"):
        assert required.matches == ()


@pytest.mark.parametrize(
    ("candidate", "expected"),
    (
        ("ANSWER_CONTEXT_FOR_AI_SMOKE_OK", False),
        ("answer context for ai smoke ok", True),
        (
            "ANSWER_CONTEXT_FOR_AI_SMOKE_OK. Answer context for AI smoke ok.",
            True,
        ),
    ),
)
def test_must_exactly_smoke_sentinel_preserves_existing_token_semantics(
    candidate: str,
    expected: bool,
) -> None:
    result = validate(
        packet(
            constraints=(
                constraint(
                    30,
                    0,
                    "REQUIRED",
                    "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",
                ),
            )
        ),
        candidate,
    )

    required = result.evidence[3]
    assert (required.outcome is ValidationOutcome.PASSED) is expected


@pytest.mark.parametrize(
    ("shape", "candidate", "passes"),
    (
        ("NON_EMPTY_TEXT", "# Heading", True),
        ("NON_EMPTY_TEXT", " \t\nTOOL_CALL:", False),
        ("NUMBERED_LIST", "1. One\n2. Two", True),
        ("NUMBERED_LIST", "01. One", False),
        ("FENCED_CODE", "```python\nprint('x')\n```", True),
        ("FENCED_CODE", "before\n```\nx\n```", False),
        ("COMPARISON_LIST", "- Alpha: one\n* Beta: two", True),
        ("COMPARISON_LIST", "- A!: one\n* a: two", False),
        ("COMPARISON_LIST", "-\tAlpha: one\n* Beta: two", False),
    ),
)
def test_output_shapes_follow_exact_structural_predicates(
    shape: str,
    candidate: str,
    passes: bool,
) -> None:
    result = validate(packet(output_shape=shape), candidate)

    shape_evidence = result.evidence[1]
    assert (shape_evidence.outcome is ValidationOutcome.PASSED) is passes
    assert shape_evidence.matches == ()


def test_repetition_groups_equal_sentences_and_excludes_exact_source_prefixes() -> None:
    source = (
        "Repeat me.\nrepeat me!\n# repeat me.\n> repeat me.\n"
        "Other.\nother?"
    )
    result = validate(packet(), source)

    repetition = tuple(
        item
        for item in result.evidence
        if item.check_id is ValidationCheckId.REPETITION
    )
    assert len(repetition) == 2
    assert all(item.warning_code is ValidationWarningCode.UNNECESSARY_REPETITION for item in repetition)
    assert tuple(
        tuple(source[match.source_start : match.source_end] for match in item.matches)
        for item in repetition
    ) == (("Repeat me.", "repeat me!"), ("Other.", "other?"))
    assert result.status is ValidationStatus.PASSED
    assert result.score.value == Decimal("0.90")


@pytest.mark.parametrize(
    ("constraint_type", "predicate", "underlying_type"),
    (
        ("REQUIRED", "MUST_NOT_DELETE:FILE", None),
        ("FORBIDDEN", "MUST_DELETE:FILE", None),
        ("PRESERVE", "MUST_NOT_CHANGE:FILE:preserve-v1", None),
        ("PREFERRED", "PREFER_use:PYTHON", None),
        ("OPTIONAL", "MAY_USE:", None),
        ("CONDITIONAL", "MAY_USE:PYTHON", "REQUIRED"),
    ),
)
def test_malformed_or_type_mismatched_predicates_are_invalid_input(
    constraint_type: str,
    predicate: str,
    underlying_type: str | None,
) -> None:
    condition_evaluation = "TRUE" if constraint_type == "CONDITIONAL" else None
    packet_value = packet(
        constraints=(
            constraint(
                30,
                0,
                constraint_type,
                predicate,
                underlying_type=underlying_type,
                condition_evaluation=condition_evaluation,
            ),
        ),
        prompt_policy_version=HISTORICAL_PROMPT_POLICY_VERSION,
    )

    with pytest.raises(LifecycleInvariantError, match="predicate|production"):
        validate(packet_value, "Candidate text.")
