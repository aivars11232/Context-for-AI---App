"""Pure bounded correction planning for one failed candidate."""

from __future__ import annotations

from context_for_ai.domain.decisions import (
    CONTEXT_PACKET_SCHEMA_VERSION,
    CORRECTION_ENVELOPE_SCHEMA_VERSION,
    CORRECTION_INSTRUCTION,
    CorrectionEnvelope,
)
from context_for_ai.domain.enums import (
    ModelRequestPurpose,
    ModelRequestStatus,
    ValidationStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import (
    MatchLocation,
    ValidationEvidence,
    ValidationResult,
    ValidationViolation,
    ValidationViolationEvidence,
)
from context_for_ai.domain.ports.context import (
    CorrectionDecision,
    CorrectionExhausted,
    CorrectionPlanRequest,
)
from context_for_ai.domain.value_objects import FrozenJsonObject


def _canonical_report(report: ValidationResult) -> ValidationResult:
    """Re-run every nested public invariant before planning a correction."""

    try:
        evidence = tuple(
            ValidationEvidence(
                item.ordinal,
                item.check_id,
                item.rule_id,
                item.constraint_id,
                item.severity,
                item.outcome,
                item.normalized_input,
                tuple(
                    MatchLocation(
                        location.source_start,
                        location.source_end,
                        location.sentence_ordinal,
                    )
                    for location in item.matches
                ),
                item.missing_predicate,
                item.violation_code,
                item.warning_code,
                item.explanation,
            )
            for item in report.evidence
        )
        violations = tuple(
            ValidationViolation(
                item.ordinal,
                item.code,
                item.message,
                item.constraint_id,
                ValidationViolationEvidence(
                    item.evidence.check_id,
                    item.evidence.rule_id,
                    item.evidence.evidence_ordinal,
                ),
            )
            for item in report.violations
        )
        canonical = ValidationResult(
            report.id,
            report.model_response_id,
            report.status,
            report.score,
            violations,
            evidence,
            report.created_at,
        )
    except LifecycleInvariantError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise LifecycleInvariantError(
            "Correction planning requires a canonical typed validation report."
        ) from error
    if canonical != report:
        raise LifecycleInvariantError(
            "Correction planning requires a canonical typed validation report."
        )
    return canonical


def _correction_limit(request: CorrectionPlanRequest) -> int:
    packet = request.packet
    payload = packet.packet_json
    if (
        packet.schema_version != CONTEXT_PACKET_SCHEMA_VERSION
        or payload.get("schema_version") != CONTEXT_PACKET_SCHEMA_VERSION
    ):
        raise LifecycleInvariantError(
            "Correction planning requires an mvp-context-packet-v2 packet."
        )
    policy = payload.get("response_policy")
    if not isinstance(policy, FrozenJsonObject):
        raise LifecycleInvariantError(
            "Correction planning requires an immutable response policy."
        )
    correction_limit = policy.get("correction_limit")
    generation_limit = policy.get("model_generation_limit")
    absolute_cap = policy.get("absolute_model_generation_cap")
    if (
        not isinstance(correction_limit, int)
        or isinstance(correction_limit, bool)
        or correction_limit not in (0, 1, 2)
        or not isinstance(generation_limit, int)
        or isinstance(generation_limit, bool)
        or generation_limit != correction_limit + 1
        or absolute_cap != 3
        or isinstance(absolute_cap, bool)
    ):
        raise LifecycleInvariantError(
            "Correction planning requires canonical packet generation limits."
        )
    return correction_limit


class DeterministicCorrectionController:
    """Return the next immutable envelope or exact bounded exhaustion value."""

    def plan(self, request: CorrectionPlanRequest) -> CorrectionDecision:
        if not isinstance(request, CorrectionPlanRequest):
            raise LifecycleInvariantError(
                "Correction planning requires a typed CorrectionPlanRequest."
            )
        packet = request.packet
        failed = request.failed_candidate
        report = _canonical_report(request.validation_result)
        correction_limit = _correction_limit(request)

        if (
            packet.id != failed.context_packet_id
            or packet.processing_run_id != failed.processing_run_id
        ):
            raise LifecycleInvariantError(
                "Correction packet and failed-candidate lineage must agree."
            )
        if report.model_response_id != failed.model_response_id:
            raise LifecycleInvariantError(
                "Correction report must name the immediately failed response."
            )
        if report.status is not ValidationStatus.FAILED or not report.violations:
            raise LifecycleInvariantError(
                "Correction planning requires a failed validation report."
            )

        expected_purpose = (
            ModelRequestPurpose.INITIAL
            if failed.attempt_number == 0
            else ModelRequestPurpose.REVISION
        )
        if failed.request_purpose is not expected_purpose:
            raise LifecycleInvariantError(
                "Failed request purpose must match its persisted attempt number."
            )
        if failed.request_status is not ModelRequestStatus.SUCCEEDED:
            raise LifecycleInvariantError(
                "Only a succeeded model request can enter correction planning."
            )
        if failed.assistant_message_id is not None:
            raise LifecycleInvariantError(
                "A failed candidate cannot already link an assistant message."
            )
        if failed.attempt_number > correction_limit or failed.attempt_number > 2:
            raise LifecycleInvariantError(
                "Failed request attempt exceeds the packet correction bound."
            )

        if failed.attempt_number < correction_limit:
            return CorrectionEnvelope(
                CORRECTION_ENVELOPE_SCHEMA_VERSION,
                packet.id,
                failed.model_response_id,
                failed.attempt_number + 1,
                CORRECTION_INSTRUCTION,
                report.violations,
            )
        return CorrectionExhausted(
            failed.processing_run_id,
            failed.context_packet_id,
            failed.model_request_id,
            failed.model_response_id,
            report.id,
            failed.attempt_number,
            correction_limit,
        )


__all__ = ["DeterministicCorrectionController"]
