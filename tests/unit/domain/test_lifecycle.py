"""Tests for immutable processing and model lifecycle records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

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
    ValidationStatus,
    ValidationViolationCode,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
    CorrectionAttempt,
    ModelRequest,
    ModelResponse,
    ProcessingRun,
    SafeFailure,
    ValidationResult,
    ValidationViolation,
    ValidationViolationEvidence,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"20000000-0000-4000-8000-{number:012d}")


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
    validation = ValidationResult(
        identifier(7),
        response_id,
        ValidationStatus.FAILED,
        UnitScore("0.40"),
        (FrozenJsonObject({"code": "MISSING_REQUIRED"}),),
        (FrozenJsonObject({"constraint_id": str(identifier(8))}),),
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
        "required-rule",
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
                "rule_id": "required-rule",
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
