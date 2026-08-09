"""Tests for immutable processing and model lifecycle records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext

import pytest

from context_for_ai.domain.enums import (
    ClarificationReason,
    FailureCode,
    ModelRequestPurpose,
    ModelRequestStatus,
    PipelineStage,
    ProcessingRunStatus,
    ProviderKind,
    ValidationCheckId,
    ValidationOutcome,
    ValidationSeverity,
    ValidationStatus,
    ValidationViolationCode,
    ValidationWarningCode,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
    CorrectionAttempt,
    MatchLocation,
    ModelRequest,
    ModelResponse,
    ProcessingRun,
    SafeFailure,
    ValidationResult,
    ValidationEvidence,
    ValidationViolation,
    ValidationViolationEvidence,
    calculate_validation_score,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"20000000-0000-4000-8000-{number:012d}")


def normalized_input(
    *,
    predicate: str | None = None,
    topic_terms: tuple[str, ...] = (),
    output_type: str | None = None,
    output_shape: str | None = None,
) -> FrozenJsonObject:
    return FrozenJsonObject(
        {
            "candidate_token_count": 2,
            "sentence_count": 1,
            "predicate": predicate,
            "topic_terms": topic_terms,
            "output_type": output_type,
            "output_shape": output_shape,
        }
    )


def passing_fixed_evidence() -> tuple[ValidationEvidence, ...]:
    return (
        ValidationEvidence(
            0,
            ValidationCheckId.TOPIC,
            None,
            None,
            ValidationSeverity.INFO,
            ValidationOutcome.PASSED,
            normalized_input(topic_terms=("topic",)),
            (MatchLocation(0, 5, 0),),
            None,
            None,
            None,
            "The deterministic predicate passed.",
        ),
        ValidationEvidence(
            1,
            ValidationCheckId.OUTPUT_SHAPE,
            "shape-text-answer",
            None,
            ValidationSeverity.INFO,
            ValidationOutcome.PASSED,
            normalized_input(
                output_type="TEXT_ANSWER",
                output_shape="NON_EMPTY_TEXT",
            ),
            (),
            None,
            None,
            None,
            "The deterministic predicate passed.",
        ),
        ValidationEvidence(
            2,
            ValidationCheckId.ACTION_MARKER,
            None,
            None,
            ValidationSeverity.INFO,
            ValidationOutcome.PASSED,
            normalized_input(),
            (),
            None,
            None,
            None,
            "The deterministic predicate passed.",
        ),
    )


def repetition_pass(ordinal: int) -> ValidationEvidence:
    return ValidationEvidence(
        ordinal,
        ValidationCheckId.REPETITION,
        None,
        None,
        ValidationSeverity.INFO,
        ValidationOutcome.PASSED,
        normalized_input(),
        (),
        None,
        None,
        None,
        "The deterministic predicate passed.",
    )


def test_processing_run_is_an_immutable_lifecycle_record() -> None:
    run = ProcessingRun(
        identifier(1),
        identifier(2),
        identifier(3),
        "request-1",
        ProcessingRunStatus.PERSISTED,
        0,
        "configuration-fingerprint",
        NOW,
        None,
    )

    assert run.state_version_at_start == 0
    with pytest.raises(FrozenInstanceError):
        run.status = ProcessingRunStatus.FAILED  # type: ignore[misc]


def test_model_request_and_response_freeze_transport_payloads() -> None:
    request_source = {"options": {"temperature": 0}}
    request = ModelRequest(
        identifier(4),
        identifier(1),
        identifier(5),
        ModelRequestPurpose.INITIAL,
        0,
        ProviderKind.OLLAMA,
        "configured-model",
        ModelRequestStatus.PENDING,
        "rendered prompt",
        request_source,  # type: ignore[arg-type]
        None,
        None,
        None,
        None,
    )
    response = ModelResponse(
        identifier(6),
        request.id,
        "Complete buffered response",
        FrozenJsonObject({"duration_ms": 12}),
        None,
        NOW,
    )
    request_source["options"] = {}

    assert request.request["options"] == FrozenJsonObject({"temperature": 0})
    assert response.assistant_message_id is None
    with pytest.raises(LifecycleInvariantError, match="cannot exceed 2"):
        ModelRequest(
            identifier(4),
            identifier(1),
            identifier(5),
            ModelRequestPurpose.REVISION,
            3,
            ProviderKind.OLLAMA,
            "configured-model",
            ModelRequestStatus.PENDING,
            "rendered prompt",
            FrozenJsonObject({}),
            None,
            None,
            None,
            None,
        )


def test_validation_and_correction_records_preserve_typed_evidence() -> None:
    response_id = identifier(6)
    required_evidence = ValidationEvidence(
        3,
        ValidationCheckId.REQUIRED_CONSTRAINT,
        None,
        identifier(8),
        ValidationSeverity.ERROR,
        ValidationOutcome.FAILED,
        normalized_input(predicate="MUST_UPDATE:README"),
        (),
        "MUST_UPDATE:README",
        ValidationViolationCode.MISSING_REQUIREMENT,
        None,
        "The deterministic predicate failed.",
    )
    evidence = (*passing_fixed_evidence(), required_evidence, repetition_pass(4))
    violation = ValidationViolation(
        0,
        ValidationViolationCode.MISSING_REQUIREMENT,
        "The response does not satisfy a required constraint.",
        identifier(8),
        ValidationViolationEvidence(
            ValidationCheckId.REQUIRED_CONSTRAINT,
            None,
            3,
        ),
    )
    validation = ValidationResult(
        identifier(7),
        response_id,
        ValidationStatus.FAILED,
        UnitScore("0.70"),
        (violation,),
        evidence,
        NOW,
    )
    correction = CorrectionAttempt(
        identifier(9),
        identifier(1),
        1,
        response_id,
        identifier(10),
        validation.violations,
        NOW,
    )

    assert correction.reasons == validation.violations
    with pytest.raises(LifecycleInvariantError, match="must be 1 or 2"):
        CorrectionAttempt(
            identifier(9),
            identifier(1),
            0,
            response_id,
            identifier(10),
            validation.violations,
            NOW,
        )
    with pytest.raises(LifecycleInvariantError, match="cannot be empty"):
        CorrectionAttempt(
            identifier(9),
            identifier(1),
            1,
            response_id,
            identifier(10),
            (),
            NOW,
        )


def test_validation_violation_is_closed_immutable_correction_evidence() -> None:
    evidence = ValidationViolationEvidence(
        ValidationCheckId.REQUIRED_CONSTRAINT,
        None,
        3,
    )
    violation = ValidationViolation(
        0,
        ValidationViolationCode.MISSING_REQUIREMENT,
        "The response does not satisfy a required constraint.",
        identifier(8),
        evidence,
    )

    assert violation.to_json_object() == FrozenJsonObject(
        {
            "ordinal": 0,
            "code": "MISSING_REQUIREMENT",
            "message": "The response does not satisfy a required constraint.",
            "constraint_id": str(identifier(8)),
            "evidence": {
                "check_id": "REQUIRED_CONSTRAINT",
                "rule_id": None,
                "evidence_ordinal": 3,
            },
        }
    )
    with pytest.raises(LifecycleInvariantError, match="canonical code message"):
        ValidationViolation(
            0,
            ValidationViolationCode.MISSING_REQUIREMENT,
            "wrong",
            identifier(8),
            evidence,
        )


def test_validation_evidence_has_exact_closed_json_shape() -> None:
    evidence = passing_fixed_evidence()[0]

    assert evidence.to_json_object() == FrozenJsonObject(
        {
            "ordinal": 0,
            "check_id": "TOPIC",
            "rule_id": None,
            "constraint_id": None,
            "severity": "INFO",
            "outcome": "PASSED",
            "normalized_input": {
                "candidate_token_count": 2,
                "sentence_count": 1,
                "predicate": None,
                "topic_terms": ("topic",),
                "output_type": None,
                "output_shape": None,
            },
            "matches": (
                {
                    "source_start": 0,
                    "source_end": 5,
                    "sentence_ordinal": 0,
                },
            ),
            "missing_predicate": None,
            "violation_code": None,
            "warning_code": None,
            "explanation": "The deterministic predicate passed.",
        }
    )


def test_validation_evidence_rejects_noncanonical_combinations() -> None:
    values = {
        "ordinal": 0,
        "check_id": ValidationCheckId.TOPIC,
        "rule_id": None,
        "constraint_id": None,
        "severity": ValidationSeverity.ERROR,
        "outcome": ValidationOutcome.PASSED,
        "normalized_input": normalized_input(topic_terms=("topic",)),
        "matches": (),
        "missing_predicate": None,
        "violation_code": None,
        "warning_code": None,
        "explanation": "The deterministic predicate passed.",
    }
    with pytest.raises(LifecycleInvariantError, match="informational"):
        ValidationEvidence(**values)  # type: ignore[arg-type]

    values["severity"] = ValidationSeverity.INFO
    values["normalized_input"] = FrozenJsonObject(
        {**dict(normalized_input(topic_terms=("topic",))), "candidate_excerpt": "no"}
    )
    with pytest.raises(LifecycleInvariantError, match="exact canonical fields"):
        ValidationEvidence(**values)  # type: ignore[arg-type]


def test_literal_marker_constraint_may_record_an_uncontained_location() -> None:
    marker_evidence = ValidationEvidence(
        0,
        ValidationCheckId.FORBIDDEN_CONSTRAINT,
        None,
        identifier(20),
        ValidationSeverity.ERROR,
        ValidationOutcome.FAILED,
        normalized_input(predicate="MUST_NOT_EXECUTE:IMAGE_OR_ACTION"),
        (MatchLocation(0, 3, None),),
        None,
        ValidationViolationCode.FORBIDDEN_ACTION,
        None,
        "The deterministic predicate failed.",
    )

    assert marker_evidence.matches[0].sentence_ordinal is None
    with pytest.raises(LifecycleInvariantError, match="literal action-marker"):
        ValidationEvidence(
            0,
            ValidationCheckId.FORBIDDEN_CONSTRAINT,
            None,
            identifier(20),
            ValidationSeverity.ERROR,
            ValidationOutcome.FAILED,
            normalized_input(predicate="MUST_NOT_DELETE:FILE"),
            (MatchLocation(0, 3, None),),
            None,
            ValidationViolationCode.FORBIDDEN_ACTION,
            None,
            "The deterministic predicate failed.",
        )


def test_conditional_rule_id_exists_exactly_for_preservation_predicates() -> None:
    values = {
        "ordinal": 0,
        "check_id": ValidationCheckId.CONDITIONAL_CONSTRAINT,
        "rule_id": None,
        "constraint_id": identifier(20),
        "severity": ValidationSeverity.INFO,
        "outcome": ValidationOutcome.NOT_APPLICABLE,
        "normalized_input": normalized_input(predicate="MUST_PRESERVE:HEADER"),
        "matches": (),
        "missing_predicate": None,
        "violation_code": None,
        "warning_code": None,
        "explanation": "The check is not applicable to this packet.",
    }
    with pytest.raises(LifecycleInvariantError, match="require a rule ID"):
        ValidationEvidence(**values)  # type: ignore[arg-type]

    values["rule_id"] = "preserve-v1"
    values["normalized_input"] = normalized_input(predicate="MUST_USE:PYTHON")
    with pytest.raises(LifecycleInvariantError, match="null rule ID"):
        ValidationEvidence(**values)  # type: ignore[arg-type]


def test_validation_result_enforces_status_score_order_and_linkage() -> None:
    evidence = (*passing_fixed_evidence(), repetition_pass(3))
    result = ValidationResult(
        identifier(7),
        identifier(6),
        ValidationStatus.PASSED,
        UnitScore("1.00"),
        (),
        evidence,
        NOW,
    )
    assert result.status is ValidationStatus.PASSED

    with pytest.raises(LifecycleInvariantError, match="PASSED or FAILED"):
        ValidationResult(
            result.id,
            result.model_response_id,
            ValidationStatus.NOT_RUN,
            result.score,
            result.violations,
            result.evidence,
            result.created_at,
        )
    with pytest.raises(LifecycleInvariantError, match="canonical exact score"):
        ValidationResult(
            result.id,
            result.model_response_id,
            result.status,
            UnitScore("0.95"),
            result.violations,
            result.evidence,
            result.created_at,
        )


def test_validation_score_ignores_ambient_context_and_soft_warnings() -> None:
    preferred = ValidationEvidence(
        3,
        ValidationCheckId.PREFERRED_CONSTRAINT,
        None,
        identifier(20),
        ValidationSeverity.WARNING,
        ValidationOutcome.WARNING,
        normalized_input(predicate="PREFER_ADD:EXAMPLE"),
        (),
        "PREFER_ADD:EXAMPLE",
        None,
        ValidationWarningCode.PREFERRED_CONSTRAINT_UNSATISFIED,
        "A non-failing deterministic warning was recorded.",
    )
    repeated = ValidationEvidence(
        4,
        ValidationCheckId.REPETITION,
        None,
        None,
        ValidationSeverity.WARNING,
        ValidationOutcome.WARNING,
        normalized_input(),
        (MatchLocation(0, 5, 0), MatchLocation(7, 12, 1)),
        None,
        None,
        ValidationWarningCode.UNNECESSARY_REPETITION,
        "A non-failing deterministic warning was recorded.",
    )
    evidence = (*passing_fixed_evidence(), preferred, repeated)

    with localcontext(Context(prec=1)):
        score = calculate_validation_score((), evidence)

    assert score.value == Decimal("0.95")


def test_clarification_and_safe_failure_are_distinct_typed_results() -> None:
    clarification = ClarificationRequest(
        identifier(11),
        identifier(1),
        ClarificationReason.UNRESOLVED_REFERENCE,
        'Please clarify what "it" refers to.',
        FrozenJsonObject({"surface_text": "it"}),
        NOW,
    )
    failure = SafeFailure(
        identifier(12),
        identifier(1),
        PipelineStage.TRANSPORT,
        FailureCode.MODEL_TIMEOUT,
        "The local model request timed out.",
        FrozenJsonObject({"attempt_number": 0}),
        True,
        NOW,
    )

    assert clarification.reason is ClarificationReason.UNRESOLVED_REFERENCE
    assert failure.error_code is FailureCode.MODEL_TIMEOUT
    assert failure.is_terminal is True
