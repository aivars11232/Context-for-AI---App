"""AT-011 and bounded TASK-0013 component evidence for AT-012."""

from __future__ import annotations

import ast
from dataclasses import fields, replace
from datetime import datetime
from decimal import Decimal
import inspect
import json
from pathlib import Path

import pytest
import yaml

from context_for_ai.context_engine import (
    DeterministicCorrectionController,
    DeterministicPromptRenderer,
    DeterministicResponseValidator,
)
from context_for_ai.domain.decisions import (
    CONTEXT_PACKET_SCHEMA_VERSION,
    CORRECTION_ENVELOPE_SCHEMA_VERSION,
    CORRECTION_INSTRUCTION,
    HISTORICAL_PROMPT_POLICY_VERSION,
    ContextPacket,
    CorrectionEnvelope,
)
from context_for_ai.domain.enums import (
    FailureCode,
    ModelRequestPurpose,
    ModelRequestStatus,
    PipelineStage,
    ProcessingRunStatus,
    ProviderKind,
    ValidationCheckId,
    ValidationOutcome,
    ValidationStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import (
    CorrectionAttempt,
    ModelRequest,
    ModelResponse,
    SafeFailure,
)
from context_for_ai.domain.ports.context import (
    CorrectionExhausted,
    CorrectionPlanRequest,
    FailedCandidateLineage,
    PromptRenderRequest,
    PromptRenderResult,
    ValidationRequest,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    canonical_json,
)
from context_for_ai.infrastructure.database import apply_migrations, connect_database
from tests.integration.test_sqlite_repositories import (
    add_empty_packet as add_database_packet,
    completed_response_projection,
    identifier as database_id,
    initial_request,
    model_request_projection,
    repositories,
    seed_core,
    stamp,
    validate_response,
)
from tests.unit.context_engine.test_response_validation import (
    constraint,
    identifier,
    packet,
    validate,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "response_validation"
VERSION = (FIXTURE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
DOCUMENT = yaml.safe_load(
    (FIXTURE_ROOT / "cases.yaml").read_text(encoding="utf-8")
)
EVIDENCE_KEYS = {
    "ordinal",
    "check_id",
    "rule_id",
    "constraint_id",
    "severity",
    "outcome",
    "normalized_input",
    "matches",
    "missing_predicate",
    "violation_code",
    "warning_code",
    "explanation",
}
NORMALIZED_INPUT_KEYS = {
    "candidate_token_count",
    "sentence_count",
    "predicate",
    "topic_terms",
    "output_type",
    "output_shape",
}


def fixture_constraints(values: list[dict[str, object]] | None):
    return tuple(
        constraint(
            int(value["number"]),
            int(value["ordinal"]),
            str(value["type"]),
            str(value["predicate"]),
            status=str(value.get("status", "ACTIVE")),
            underlying_type=(
                None
                if value.get("underlying_type") is None
                else str(value["underlying_type"])
            ),
            condition_evaluation=(
                None
                if value.get("condition_evaluation") is None
                else str(value["condition_evaluation"])
            ),
            winner_number=(
                None
                if value.get("winner_number") is None
                else int(value["winner_number"])
            ),
        )
        for value in values or []
    )


def fixture_packet(case: dict[str, object]) -> ContextPacket:
    return packet(
        constraints=fixture_constraints(case.get("constraints")),  # type: ignore[arg-type]
        topic_terms=(
            None
            if "topic_terms" not in case
            else tuple(str(value) for value in case["topic_terms"])  # type: ignore[union-attr]
        ),
        output_type=str(case.get("output_type", "TEXT_EXPLANATION")),
        output_shape=str(case.get("shape", "NON_EMPTY_TEXT")),
    )


def _thaw(value: object) -> object:
    if isinstance(value, FrozenJsonObject):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_thaw(item) for item in value)
    return value


def unsafe_packet(
    original: ContextPacket,
    *,
    payload: dict[str, object] | None = None,
    schema_version: str | None = None,
) -> ContextPacket:
    result = object.__new__(ContextPacket)
    for field in fields(ContextPacket):
        object.__setattr__(result, field.name, getattr(original, field.name))
    if payload is not None:
        object.__setattr__(result, "packet_json", FrozenJsonObject(payload))
    if schema_version is not None:
        object.__setattr__(result, "schema_version", schema_version)
    return result


def failed_report(packet_value: ContextPacket):
    return validate(packet_value, "Unrelated candidate text.")


def failed_lineage(packet_value: ContextPacket, report, attempt: int):
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


def test_at011_versioned_rich_case_has_exact_full_report_and_source_locations() -> None:
    assert VERSION == DOCUMENT["fixture_version"] == (
        "task-0013-response-validation-v1"
    )
    case = DOCUMENT["rich_case"]
    packet_value = fixture_packet(case)
    source = case["candidate"]
    request = ValidationRequest(
        packet_value,
        identifier(20),
        identifier(21),
        source,
        datetime.fromisoformat("2026-08-09T12:00:00+00:00"),
    )
    validator = DeterministicResponseValidator()
    packet_bytes = canonical_json(packet_value.packet_json).encode("utf-8")

    first = validator.validate(request)
    second = validator.validate(request)

    expected = case["expected"]
    assert first == second
    assert first.status.value == expected["status"]
    assert first.score.value == Decimal(expected["score"])
    assert [item.check_id.value for item in first.evidence] == expected["checks"]
    assert [item.outcome.value for item in first.evidence] == expected["outcomes"]
    assert [item.code.value for item in first.violations] == expected["violations"]
    assert [
        item.warning_code.value
        for item in first.evidence
        if item.warning_code is not None
    ] == expected["warnings"]
    assert [item.ordinal for item in first.evidence] == list(
        range(len(first.evidence))
    )
    assert [item.ordinal for item in first.violations] == list(
        range(len(first.violations))
    )
    assert canonical_json(packet_value.packet_json).encode("utf-8") == packet_bytes

    evidence_by_check = {item.check_id.value: item for item in first.evidence}
    for check_name, expected_ranges in expected["match_ranges"].items():
        assert [
            [match.source_start, match.source_end, match.sentence_ordinal]
            for match in evidence_by_check[check_name].matches
        ] == expected_ranges
    assert source[0:5] == "CAFE\u0301"
    assert source[56:66] == "Repeat me."
    assert source[67:77] == "repeat me!"

    for item in first.evidence:
        serialized = item.to_json_object()
        assert set(serialized) == EVIDENCE_KEYS
        assert set(item.normalized_input) == NORMALIZED_INPUT_KEYS
        assert item.normalized_input["candidate_token_count"] == expected[
            "candidate_token_count"
        ]
        assert item.normalized_input["sentence_count"] == expected["sentence_count"]
        assert "candidate" not in serialized
    for violation, item in zip(
        first.violations,
        (
            evidence
            for evidence in first.evidence
            if evidence.outcome is ValidationOutcome.FAILED
        ),
        strict=True,
    ):
        assert violation.evidence.evidence_ordinal == item.ordinal
        assert violation.evidence.check_id is item.check_id
        assert violation.evidence.rule_id == item.rule_id
        assert violation.constraint_id == item.constraint_id


def test_at011_all_output_shapes_empty_content_and_additional_predicates() -> None:
    for case in DOCUMENT["shape_cases"]:
        result = validate(fixture_packet(case), case["candidate"])
        shape = next(
            item
            for item in result.evidence
            if item.check_id is ValidationCheckId.OUTPUT_SHAPE
        )
        assert shape.outcome.value == case["outcome"], case["id"]
        assert result.status.value == case["status"], case["id"]
        assert result.score.value == Decimal(case["score"]), case["id"]
        assert shape.matches == ()

    for case in DOCUMENT["additional_cases"]:
        result = validate(fixture_packet(case), case["candidate"])
        assert result.status.value == case["expected_status"], case["id"]
        assert result.score.value == Decimal(case["expected_score"]), case["id"]
        if "expected_violations" in case:
            assert [item.code.value for item in result.violations] == case[
                "expected_violations"
            ]
        if "conditional_outcome" in case:
            conditional = next(
                item
                for item in result.evidence
                if item.check_id is ValidationCheckId.CONDITIONAL_CONSTRAINT
            )
            assert conditional.outcome.value == case["conditional_outcome"]
        if case["id"] == "marker-and-derived-forbidden":
            action = next(
                item
                for item in result.evidence
                if item.check_id is ValidationCheckId.ACTION_MARKER
            )
            forbidden = next(
                item
                for item in result.evidence
                if item.check_id is ValidationCheckId.FORBIDDEN_CONSTRAINT
            )
            assert action.matches == forbidden.matches
        if case["id"] == "one-ordered-step":
            required = next(
                item
                for item in result.evidence
                if item.check_id is ValidationCheckId.REQUIRED_CONSTRAINT
            )
            assert required.matches == ()


def test_at011_malformed_predicates_and_packet_invariants_produce_no_report() -> None:
    validator = DeterministicResponseValidator()
    for case in DOCUMENT["invalid_predicates"]:
        packet_value = packet(
            constraints=(
                constraint(
                    30,
                    0,
                    case["type"],
                    case["predicate"],
                    underlying_type=case.get("underlying_type"),
                    condition_evaluation=case.get("condition_evaluation"),
                ),
            ),
            prompt_policy_version=HISTORICAL_PROMPT_POLICY_VERSION,
        )
        request = ValidationRequest(
            packet_value,
            identifier(20),
            identifier(21),
            "Candidate text.",
            datetime.fromisoformat("2026-08-09T12:00:00+00:00"),
        )
        with pytest.raises(LifecycleInvariantError, match="predicate|production"):
            validator.validate(request)

    for invariant in DOCUMENT["invalid_packet_invariants"]:
        base = packet(topic_terms=("topic",))
        payload = _thaw(base.packet_json)
        assert isinstance(payload, dict)
        if invariant == "outer-schema":
            malformed = unsafe_packet(base, schema_version="unknown-packet")
        elif invariant == "topic-identity":
            active_state = payload["active_state"]
            assert isinstance(active_state, dict)
            active_state["topic_id"] = str(identifier(99))
            malformed = unsafe_packet(base, payload=payload)
        elif invariant == "output-type-equality":
            response_policy = payload["response_policy"]
            assert isinstance(response_policy, dict)
            response_policy["output_type"] = "TEXT_CODE"
            malformed = unsafe_packet(base, payload=payload)
        elif invariant == "correction-limit":
            response_policy = payload["response_policy"]
            assert isinstance(response_policy, dict)
            response_policy["correction_limit"] = 3
            response_policy["model_generation_limit"] = 4
            malformed = unsafe_packet(base, payload=payload)
        else:
            del payload["validation_context"]
            malformed = unsafe_packet(base, payload=payload)
        request = ValidationRequest(
            malformed,
            identifier(20),
            identifier(21),
            "Candidate text.",
            datetime.fromisoformat("2026-08-09T12:00:00+00:00"),
        )
        with pytest.raises(LifecycleInvariantError):
            validator.validate(request)


def test_component_at012_exact_limits_envelopes_exhaustion_and_renderer_compatibility() -> None:
    controller = DeterministicCorrectionController()
    rendered_one = False
    for case in DOCUMENT["correction_cases"]:
        packet_value = packet(
            correction_limit=case["limit"],
            constraints=(
                constraint(30, 0, "REQUIRED", "MUST_USE:PYTHON"),
                constraint(31, 1, "PREFERRED", "PREFER_ADD:EXAMPLE"),
            ),
        )
        report = failed_report(packet_value)
        assert report.status is ValidationStatus.FAILED
        assert any(item.warning_code is not None for item in report.evidence)
        lineage = failed_lineage(packet_value, report, case["attempt"])
        packet_bytes = canonical_json(packet_value.packet_json).encode("utf-8")

        decision = controller.plan(
            CorrectionPlanRequest(packet_value, lineage, report)
        )

        if case["decision"] == "ENVELOPE":
            assert isinstance(decision, CorrectionEnvelope)
            assert decision.schema_version == CORRECTION_ENVELOPE_SCHEMA_VERSION
            assert decision.context_packet_id == packet_value.id
            assert decision.failed_model_response_id == lineage.model_response_id
            assert decision.attempt_number == case["next_attempt"]
            assert decision.instruction == CORRECTION_INSTRUCTION
            assert decision.violations == report.violations
            assert all(
                set(item.evidence.to_json_object())
                == {"check_id", "rule_id", "evidence_ordinal"}
                for item in decision.violations
            )
            assert not hasattr(decision, "candidate_response")
            assert not hasattr(decision, "evidence")
            if not rendered_one:
                rendered = DeterministicPromptRenderer().render(
                    PromptRenderRequest(packet_value, decision)
                )
                assert isinstance(rendered, PromptRenderResult)
                rendered_one = True
        else:
            assert decision == CorrectionExhausted(
                packet_value.processing_run_id,
                packet_value.id,
                lineage.model_request_id,
                lineage.model_response_id,
                report.id,
                case["attempt"],
                case["limit"],
            )
        assert canonical_json(packet_value.packet_json).encode("utf-8") == packet_bytes
    assert rendered_one


def test_component_at012_invalid_lineage_and_range_never_create_a_decision() -> None:
    controller = DeterministicCorrectionController()
    base_packet = packet(
        constraints=(constraint(30, 0, "REQUIRED", "MUST_USE:PYTHON"),)
    )
    report = failed_report(base_packet)
    base = failed_lineage(base_packet, report, 0)

    for case in DOCUMENT["invalid_lineage_cases"]:
        packet_value = base_packet
        current_report = report
        lineage = base
        if case == "cross-run":
            lineage = replace(lineage, processing_run_id=identifier(90))
        elif case == "cross-packet":
            lineage = replace(lineage, context_packet_id=identifier(91))
        elif case == "cross-response":
            lineage = replace(lineage, model_response_id=identifier(92))
        elif case == "purpose":
            lineage = replace(lineage, request_purpose=ModelRequestPurpose.REVISION)
        elif case == "request-status":
            lineage = replace(lineage, request_status=ModelRequestStatus.FAILED)
        elif case == "assistant-link":
            lineage = replace(lineage, assistant_message_id=identifier(93))
        else:
            packet_value = packet(
                correction_limit=0,
                constraints=(
                    constraint(30, 0, "REQUIRED", "MUST_USE:PYTHON"),
                ),
            )
            current_report = failed_report(packet_value)
            lineage = failed_lineage(packet_value, current_report, 1)
        with pytest.raises(LifecycleInvariantError):
            controller.plan(
                CorrectionPlanRequest(packet_value, lineage, current_report)
            )

    with pytest.raises(LifecycleInvariantError, match="0, 1, or 2"):
        FailedCandidateLineage(
            base.processing_run_id,
            base.context_packet_id,
            base.model_request_id,
            base.model_response_id,
            3,
            ModelRequestPurpose.REVISION,
            ModelRequestStatus.SUCCEEDED,
            None,
        )


def test_component_at012_typed_persistence_is_exact_adjacent_and_atomic(
    tmp_path: Path,
) -> None:
    connection = connect_database(
        apply_migrations(tmp_path / "task-0013-component.sqlite3")
    )
    try:
        bundle = repositories(connection)
        core = seed_core(bundle)
        packet_record, context_ready = add_database_packet(bundle, core)
        pending = initial_request(core, packet_record.packet)
        generating = replace(context_ready, status=ProcessingRunStatus.GENERATING)
        with bundle.transactions.transaction():
            bundle.runs.update(generating)
            bundle.models.add_request(pending)
        in_flight = replace(
            pending,
            status=ModelRequestStatus.IN_FLIGHT,
            started_at=stamp(20),
        )
        succeeded = replace(
            in_flight,
            status=ModelRequestStatus.SUCCEEDED,
            completed_at=stamp(21),
        )
        bundle.models.update_request(in_flight)
        response_id = database_id(41)
        response = ModelResponse(
            response_id,
            succeeded.id,
            "TOOL_CALL:\nTOOL_CALL:",
            completed_response_projection(succeeded, response_id),
            None,
            stamp(21),
        )
        report = replace(
            validate_response(packet_record.packet, response),
            created_at=response.created_at,
        )
        assert report.status is ValidationStatus.FAILED
        assert any(item.warning_code is not None for item in report.evidence)
        with bundle.transactions.transaction():
            bundle.models.update_request(succeeded)
            bundle.models.add_response(response)
            bundle.validations.add(report)
        assert bundle.validations.get(report.id) == report
        stored = connection.execute(
            """
            SELECT violations_json, evidence_json
            FROM validation_results WHERE id = ?
            """,
            (str(report.id),),
        ).fetchone()
        stored_violations = json.loads(stored["violations_json"])
        stored_evidence = json.loads(stored["evidence_json"])
        assert all("warning_code" not in item for item in stored_violations)
        assert any(item["outcome"] == "WARNING" for item in stored_evidence)

        revising = replace(generating, status=ProcessingRunStatus.REVISING)
        bundle.runs.update(revising)
        skipped_id = database_id(49)
        skipped = ModelRequest(
            skipped_id,
            core.run.id,
            packet_record.packet.id,
            ModelRequestPurpose.REVISION,
            2,
            ProviderKind.OLLAMA,
            "fixture-model",
            ModelRequestStatus.PENDING,
            "Skipped revision prompt",
            model_request_projection(
                request_id=skipped_id,
                processing_run_id=core.run.id,
                context_packet_id=packet_record.packet.id,
                attempt_number=2,
                render_kind="CORRECTION",
            ),
            None,
            None,
            None,
            None,
        )
        with pytest.raises(LifecycleInvariantError, match="preceding failed"):
            bundle.models.add_request(skipped)

        revision_id = database_id(44)
        revision = replace(
            skipped,
            id=revision_id,
            attempt_number=1,
            rendered_prompt="Adjacent revision prompt",
            request=model_request_projection(
                request_id=revision_id,
                processing_run_id=core.run.id,
                context_packet_id=packet_record.packet.id,
                attempt_number=1,
                render_kind="CORRECTION",
            ),
        )
        correction = CorrectionAttempt(
            database_id(45),
            core.run.id,
            1,
            response.id,
            revision.id,
            report.violations,
            stamp(23),
        )
        bad = replace(correction, reasons=report.violations[:1])
        with pytest.raises(LifecycleInvariantError, match="exactly equal"):
            with bundle.transactions.transaction():
                bundle.models.add_request(revision)
                bundle.models.add_correction(bad)
        assert bundle.models.get_request(revision.id) is None
        assert bundle.models.list_corrections_for_run(core.run.id) == ()

        with bundle.transactions.transaction():
            bundle.models.add_request(revision)
            bundle.models.add_correction(correction)
        assert bundle.models.get_request(revision.id) == revision
        assert bundle.models.list_corrections_for_run(core.run.id) == (correction,)
    finally:
        connection.close()


def test_component_at012_preconstructed_exhaustion_failure_has_no_correction(
    tmp_path: Path,
) -> None:
    connection = connect_database(
        apply_migrations(tmp_path / "task-0013-exhaustion.sqlite3")
    )
    try:
        bundle = repositories(connection)
        core = seed_core(bundle)
        packet_record, context_ready = add_database_packet(
            bundle,
            core,
            correction_limit=0,
        )
        pending = initial_request(core, packet_record.packet)
        generating = replace(context_ready, status=ProcessingRunStatus.GENERATING)
        with bundle.transactions.transaction():
            bundle.runs.update(generating)
            bundle.models.add_request(pending)
        in_flight = replace(
            pending,
            status=ModelRequestStatus.IN_FLIGHT,
            started_at=stamp(20),
        )
        succeeded = replace(
            in_flight,
            status=ModelRequestStatus.SUCCEEDED,
            completed_at=stamp(21),
        )
        bundle.models.update_request(in_flight)
        response_id = database_id(41)
        response = ModelResponse(
            response_id,
            succeeded.id,
            "TOOL_CALL:",
            completed_response_projection(succeeded, response_id),
            None,
            stamp(21),
        )
        report = replace(
            validate_response(packet_record.packet, response),
            created_at=response.created_at,
        )
        with bundle.transactions.transaction():
            bundle.models.update_request(succeeded)
            bundle.models.add_response(response)
            bundle.validations.add(report)
        exhausted = CorrectionExhausted(
            core.run.id,
            packet_record.packet.id,
            succeeded.id,
            response.id,
            report.id,
            0,
            0,
        )
        failure = SafeFailure(
            database_id(47),
            core.run.id,
            PipelineStage.VALIDATION,
            FailureCode.VALIDATION_EXHAUSTED,
            "The response did not pass validation.",
            FrozenJsonObject(
                {
                    "context_packet_id": str(exhausted.context_packet_id),
                    "failed_model_request_id": str(
                        exhausted.failed_model_request_id
                    ),
                    "failed_model_response_id": str(
                        exhausted.failed_model_response_id
                    ),
                    "validation_result_id": str(exhausted.validation_result_id),
                    "attempt_number": exhausted.attempt_number,
                    "correction_limit": exhausted.correction_limit,
                }
            ),
            True,
            stamp(23),
        )
        terminal = replace(
            generating,
            status=ProcessingRunStatus.CONTROLLED_FAILURE,
            completed_at=stamp(23),
        )
        with bundle.transactions.transaction():
            bundle.models.add_failure(failure)
            bundle.runs.update(terminal)

        assert bundle.models.list_failures_for_run(core.run.id) == (failure,)
        assert bundle.models.list_corrections_for_run(core.run.id) == ()
        assert bundle.models.get_response(response.id).assistant_message_id is None
    finally:
        connection.close()


def test_task0013_components_have_no_gateway_network_or_application_dependency() -> None:
    modules = (
        inspect.getmodule(DeterministicResponseValidator),
        inspect.getmodule(DeterministicCorrectionController),
    )
    for module in modules:
        assert module is not None and module.__file__ is not None
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            name.startswith("context_for_ai.application")
            or "gateway" in name
            or name in {"socket", "http", "urllib", "requests"}
            for name in imported
        )
    assert tuple(inspect.signature(DeterministicResponseValidator).parameters) == ()
    assert tuple(inspect.signature(DeterministicCorrectionController).parameters) == ()
