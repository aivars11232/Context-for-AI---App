"""Pure bounded-correction controller tests for TASK-0013."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from context_for_ai.context_engine.correction import (
    DeterministicCorrectionController,
)
from context_for_ai.context_engine.prompt_rendering import (
    DeterministicPromptRenderer,
)
from context_for_ai.domain.decisions import (
    CORRECTION_ENVELOPE_SCHEMA_VERSION,
    CORRECTION_INSTRUCTION,
    CorrectionEnvelope,
)
from context_for_ai.domain.enums import (
    ModelRequestPurpose,
    ModelRequestStatus,
    PromptRenderKind,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import (
    CorrectionExhausted,
    CorrectionPlanRequest,
    FailedCandidateLineage,
    PromptRenderRequest,
    PromptRenderResult,
)
from context_for_ai.domain.value_objects import UnitScore
from tests.unit.context_engine.test_response_validation import (
    constraint,
    identifier,
    packet,
    validate,
)


def failed_report(packet_value):
    return validate(packet_value, "Unrelated candidate text.")


def lineage(packet_value, report, attempt: int) -> FailedCandidateLineage:
    return FailedCandidateLineage(
        packet_value.processing_run_id,
        packet_value.id,
        identifier(40 + attempt),
        report.model_response_id,
        attempt,
        (
            ModelRequestPurpose.INITIAL
            if attempt == 0
            else ModelRequestPurpose.REVISION
        ),
        ModelRequestStatus.SUCCEEDED,
        None,
    )


def correction_packet(*, correction_limit: int = 2):
    return packet(
        correction_limit=correction_limit,
        constraints=(
            constraint(30, 0, "REQUIRED", "MUST_USE:PYTHON"),
            constraint(31, 1, "PREFERRED", "PREFER_ADD:EXAMPLE"),
        ),
    )


@pytest.mark.parametrize(
    ("limit", "attempt", "expected_attempt"),
    (
        (0, 0, None),
        (1, 0, 1),
        (1, 1, None),
        (2, 0, 1),
        (2, 1, 2),
        (2, 2, None),
    ),
)
def test_exact_correction_limit_attempt_algebra(
    limit: int,
    attempt: int,
    expected_attempt: int | None,
) -> None:
    packet_value = correction_packet(correction_limit=limit)
    report = failed_report(packet_value)

    decision = DeterministicCorrectionController().plan(
        CorrectionPlanRequest(
            packet_value,
            lineage(packet_value, report, attempt),
            report,
        )
    )

    if expected_attempt is not None:
        assert isinstance(decision, CorrectionEnvelope)
        assert decision.schema_version == CORRECTION_ENVELOPE_SCHEMA_VERSION
        assert decision.context_packet_id == packet_value.id
        assert decision.failed_model_response_id == report.model_response_id
        assert decision.attempt_number == expected_attempt
        assert decision.instruction == CORRECTION_INSTRUCTION
        assert decision.violations == report.violations
        assert tuple(field.name for field in fields(decision)) == (
            "schema_version",
            "context_packet_id",
            "failed_model_response_id",
            "attempt_number",
            "instruction",
            "violations",
        )
    else:
        assert isinstance(decision, CorrectionExhausted)
        assert decision == CorrectionExhausted(
            packet_value.processing_run_id,
            packet_value.id,
            identifier(40 + attempt),
            report.model_response_id,
            report.id,
            attempt,
            limit,
        )


def test_warnings_and_full_evidence_never_enter_the_correction_envelope() -> None:
    packet_value = correction_packet()
    report = failed_report(packet_value)
    assert any(item.warning_code is not None for item in report.evidence)

    decision = DeterministicCorrectionController().plan(
        CorrectionPlanRequest(packet_value, lineage(packet_value, report, 0), report)
    )

    assert isinstance(decision, CorrectionEnvelope)
    assert len(decision.violations) == 1
    assert not hasattr(decision, "evidence")
    assert not hasattr(decision, "candidate_response")


def test_existing_prompt_renderer_accepts_the_planned_envelope() -> None:
    packet_value = correction_packet()
    report = failed_report(packet_value)
    decision = DeterministicCorrectionController().plan(
        CorrectionPlanRequest(packet_value, lineage(packet_value, report, 0), report)
    )
    assert isinstance(decision, CorrectionEnvelope)

    rendered = DeterministicPromptRenderer().render(
        PromptRenderRequest(packet_value, decision)
    )

    assert isinstance(rendered, PromptRenderResult)
    assert rendered.render_kind is PromptRenderKind.CORRECTION
    assert str(report.model_response_id) in rendered.rendered_prompt


def test_passed_report_is_not_correction_eligible() -> None:
    packet_value = correction_packet()
    report = validate(packet_value, "Use Python and add an example.")

    with pytest.raises(LifecycleInvariantError, match="failed validation report"):
        DeterministicCorrectionController().plan(
            CorrectionPlanRequest(packet_value, lineage(packet_value, report, 0), report)
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"processing_run_id": identifier(90)}, "packet.*lineage"),
        ({"context_packet_id": identifier(91)}, "packet.*lineage"),
        ({"model_response_id": identifier(92)}, "failed response"),
        ({"request_purpose": ModelRequestPurpose.REVISION}, "purpose"),
        ({"request_status": ModelRequestStatus.FAILED}, "succeeded"),
        ({"assistant_message_id": identifier(93)}, "assistant message"),
    ),
)
def test_cross_lineage_and_request_state_mismatches_are_rejected(
    changes: dict[str, object],
    message: str,
) -> None:
    packet_value = correction_packet()
    report = failed_report(packet_value)
    failed = replace(lineage(packet_value, report, 0), **changes)

    with pytest.raises(LifecycleInvariantError, match=message):
        DeterministicCorrectionController().plan(
            CorrectionPlanRequest(packet_value, failed, report)
        )


def test_attempt_cannot_exceed_the_packet_limit() -> None:
    packet_value = correction_packet(correction_limit=0)
    report = failed_report(packet_value)

    with pytest.raises(LifecycleInvariantError, match="correction bound"):
        DeterministicCorrectionController().plan(
            CorrectionPlanRequest(packet_value, lineage(packet_value, report, 1), report)
        )


def test_controller_revalidates_typed_report_integrity() -> None:
    packet_value = correction_packet()
    report = failed_report(packet_value)
    object.__setattr__(report, "score", UnitScore("1.00"))

    with pytest.raises(LifecycleInvariantError, match="canonical exact score"):
        DeterministicCorrectionController().plan(
            CorrectionPlanRequest(packet_value, lineage(packet_value, report, 0), report)
        )

