"""SQLite recovery-matrix acceptance coverage for TASK-0014."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from context_for_ai.application import (
    CancelledResult,
    ControlledFailureResult,
    NoRecoveryRequiredResult,
    RecoverProcessingRunRequest,
    RecoverProcessingRunService,
    RecoveryCompletedResult,
    SucceededResult,
    ValidationExhaustedResult,
)
from context_for_ai.domain.enums import (
    FailureCode,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    ProcessingRunStatus,
)
from context_for_ai.domain.lifecycle import ModelRequest
from context_for_ai.domain.ports.model_gateway import (
    GenerationFailure,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject
from tests.integration.test_process_user_message import (
    Token,
    composition,
    request,
)


_PAUSED = object()


def recovery_service(value: SimpleNamespace) -> RecoverProcessingRunService:
    return RecoverProcessingRunService(
        repositories=value.repositories,
        system=value.system,
        deterministic=value.deterministic,
        context_packet_stage=value.stage,
    )


def pause_method(value: SimpleNamespace, name: str) -> object:
    original = getattr(value.service, name)
    setattr(value.service, name, lambda **_: _PAUSED)
    return original


def restore_method(value: SimpleNamespace, name: str, original: object) -> None:
    setattr(value.service, name, original)


def admit_only(value: SimpleNamespace) -> object:
    return value.service._admit(  # type: ignore[attr-defined]
        request(value),
        Token(),
        value.configuration,
    )


def recover(
    value: SimpleNamespace,
    token: Token | None = None,
) -> object:
    return recovery_service(value).execute(
        RecoverProcessingRunRequest(),
        Token() if token is None else token,
    )


def unwrap(result: object) -> object:
    assert isinstance(result, RecoveryCompletedResult)
    return result.outcome


def trace_names(value: SimpleNamespace) -> list[str]:
    return [event.event_name for event in value.traces.events]


def test_no_active_run_is_read_only_and_emits_no_trace(
    composition: SimpleNamespace,
) -> None:
    result = recover(composition)

    assert isinstance(result, NoRecoveryRequiredResult)
    assert composition.gateway.requests == []
    assert composition.traces.events == []


def test_persisted_run_recomputes_context_once_and_completes(
    composition: SimpleNamespace,
) -> None:
    admitted = admit_only(composition)
    assert getattr(admitted, "run").status is ProcessingRunStatus.PERSISTED

    outcome = unwrap(recover(composition))

    assert isinstance(outcome, SucceededResult)
    assert len(composition.gateway.requests) == 1
    assert trace_names(composition)[0:2] == [
        "recovery_started",
        "recovery_resumed",
    ]
    assert trace_names(composition)[-2:] == [
        "run_succeeded",
        "recovery_completed",
    ]
    before = tuple(composition.traces.events)
    assert isinstance(recover(composition), NoRecoveryRequiredResult)
    assert tuple(composition.traces.events) == before


def test_context_ready_run_rerenders_then_prepares_and_claims(
    composition: SimpleNamespace,
) -> None:
    original = pause_method(composition, "_continue_from_packet")
    try:
        assert composition.service.execute(request(composition), Token()) is _PAUSED
    finally:
        restore_method(composition, "_continue_from_packet", original)
    active = composition.repositories.processing_runs.get_non_terminal()
    assert active is not None
    assert active.status is ProcessingRunStatus.CONTEXT_READY
    composition.traces.events.clear()

    outcome = unwrap(recover(composition))

    assert isinstance(outcome, SucceededResult)
    assert len(composition.gateway.requests) == 1
    assert trace_names(composition)[0:2] == [
        "recovery_started",
        "recovery_resumed",
    ]


def test_pending_request_is_claimed_once_and_enters_gateway(
    composition: SimpleNamespace,
) -> None:
    original = pause_method(composition, "_claim_and_generate")
    try:
        assert composition.service.execute(request(composition), Token()) is _PAUSED
    finally:
        restore_method(composition, "_claim_and_generate", original)
    active = composition.repositories.processing_runs.get_non_terminal()
    assert active is not None
    stored = composition.repositories.model_calls.list_requests_for_run(active.id)
    assert len(stored) == 1
    assert stored[0].status is ModelRequestStatus.PENDING
    composition.traces.events.clear()

    outcome = unwrap(recover(composition))

    assert isinstance(outcome, SucceededResult)
    assert len(composition.gateway.requests) == 1
    assert composition.gateway.requests[0].model_request_id == stored[0].id


def test_in_flight_request_is_failed_without_uncertain_retry(
    composition: SimpleNamespace,
) -> None:
    calls = 0
    original_generate = composition.gateway.generate

    def crash(*_: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError("simulated process interruption")

    composition.gateway.generate = crash
    try:
        with pytest.raises(RuntimeError, match="simulated process interruption"):
            composition.service.execute(request(composition), Token())
    finally:
        composition.gateway.generate = original_generate
    active = composition.repositories.processing_runs.get_non_terminal()
    assert active is not None
    stored = composition.repositories.model_calls.list_requests_for_run(active.id)
    assert stored[-1].status is ModelRequestStatus.IN_FLIGHT
    composition.traces.events.clear()

    outcome = unwrap(recover(composition))

    assert isinstance(outcome, ControlledFailureResult)
    assert outcome.error.code is FailureCode.PROCESS_RESTARTED
    assert calls == 1
    recovered_request = composition.repositories.model_calls.get_request(stored[-1].id)
    assert recovered_request is not None
    assert recovered_request.status is ModelRequestStatus.FAILED
    assert recovered_request.error_code == FailureCode.PROCESS_RESTARTED.value
    assert trace_names(composition) == [
        "recovery_started",
        "run_failed",
        "recovery_completed",
    ]


def test_passing_candidate_reuses_durable_candidate_and_only_terminalizes(
    composition: SimpleNamespace,
) -> None:
    original = pause_method(composition, "_commit_success")
    try:
        assert composition.service.execute(request(composition), Token()) is _PAUSED
    finally:
        restore_method(composition, "_commit_success", original)
    active = composition.repositories.processing_runs.get_non_terminal()
    assert active is not None
    model_requests = composition.repositories.model_calls.list_requests_for_run(
        active.id
    )
    response = composition.repositories.model_calls.get_response_for_request(
        model_requests[-1].id
    )
    assert response is not None
    assert response.assistant_message_id is None
    gateway_count = len(composition.gateway.requests)
    composition.traces.events.clear()

    outcome = unwrap(recover(composition))

    assert isinstance(outcome, SucceededResult)
    assert len(composition.gateway.requests) == gateway_count
    assert outcome.latest_validation_result.model_response_id == response.id
    assert trace_names(composition) == [
        "recovery_started",
        "recovery_resumed",
        "run_succeeded",
        "recovery_completed",
    ]


def test_failed_candidate_below_limit_reconstructs_adjacent_corrections(
    composition: SimpleNamespace,
) -> None:
    composition.gateway.text = "TOOL_CALL: forbidden"
    original = pause_method(composition, "_continue_failed_candidate")
    try:
        assert composition.service.execute(request(composition), Token()) is _PAUSED
    finally:
        restore_method(composition, "_continue_failed_candidate", original)
    active = composition.repositories.processing_runs.get_non_terminal()
    assert active is not None
    assert len(composition.repositories.model_calls.list_requests_for_run(active.id)) == 1
    composition.traces.events.clear()

    outcome = unwrap(recover(composition))

    assert isinstance(outcome, ValidationExhaustedResult)
    requests = composition.repositories.model_calls.list_requests_for_run(active.id)
    corrections = composition.repositories.model_calls.list_corrections_for_run(
        active.id
    )
    assert [item.attempt_number for item in requests] == [0, 1, 2]
    assert [item.attempt_number for item in corrections] == [1, 2]
    assert len(composition.gateway.requests) == 3


def test_failed_candidate_at_limit_persists_exhaustion_without_gateway(
    composition: SimpleNamespace,
) -> None:
    composition.gateway.text = "ACTION_EXECUTED: forbidden"
    original = pause_method(composition, "_exhaust_validation")
    try:
        assert composition.service.execute(request(composition), Token()) is _PAUSED
    finally:
        restore_method(composition, "_exhaust_validation", original)
    gateway_count = len(composition.gateway.requests)
    assert gateway_count == 3
    composition.traces.events.clear()

    outcome = unwrap(recover(composition, Token(True)))

    assert isinstance(outcome, ValidationExhaustedResult)
    assert len(composition.gateway.requests) == gateway_count
    assert trace_names(composition) == [
        "recovery_started",
        "recovery_resumed",
        "run_failed",
        "recovery_completed",
    ]


@pytest.mark.parametrize(
    "failure_outcome",
    [
        ProviderUnavailableFailure(),
        ModelNotFoundFailure(),
        ModelTimeoutFailure(),
        ModelCancelledFailure(),
        InvalidProviderResponseFailure(),
    ],
    ids=[
        "provider-unavailable",
        "model-not-found",
        "timeout",
        "cancelled",
        "invalid-response",
    ],
)
def test_terminal_request_is_projected_without_another_provider_call(
    composition: SimpleNamespace,
    failure_outcome: GenerationFailure,
) -> None:
    calls = 0
    original_generate = composition.gateway.generate
    original_commit = composition.service._commit_gateway_failure

    def return_failure(*_: object) -> GenerationFailure:
        nonlocal calls
        calls += 1
        return failure_outcome

    def persist_request_only(**values: object) -> object:
        model_request = cast(ModelRequest, values["request"])
        terminal_time = composition.clock.now()
        stored = replace(
            model_request,
            status=failure_outcome.model_request_status,
            completed_at=terminal_time,
            error_code=failure_outcome.diagnostic_code,
            safe_error_message=failure_outcome.safe_message,
        )
        with composition.transactions.transaction():
            composition.repositories.model_calls.update_request(stored)
        return _PAUSED

    composition.gateway.generate = return_failure
    composition.service._commit_gateway_failure = persist_request_only
    try:
        assert composition.service.execute(request(composition), Token()) is _PAUSED
    finally:
        composition.gateway.generate = original_generate
        composition.service._commit_gateway_failure = original_commit
    composition.traces.events.clear()

    outcome = unwrap(recover(composition))

    assert calls == 1
    if isinstance(failure_outcome, ModelCancelledFailure):
        assert isinstance(outcome, CancelledResult)
        assert outcome.cancellation_code is FailureCode.MODEL_CANCELLED
    else:
        assert isinstance(outcome, ControlledFailureResult)
        assert outcome.error.code is failure_outcome.failure_code
    assert trace_names(composition)[0:2] == [
        "recovery_started",
        "recovery_resumed",
    ]
    assert trace_names(composition)[-2:] == [
        "run_failed",
        "recovery_completed",
    ]


def test_fingerprint_mismatch_precedes_resumption_and_preserves_artifacts(
    composition: SimpleNamespace,
) -> None:
    admitted = admit_only(composition)
    run = getattr(admitted, "run")
    composition.loader.snapshot = replace(
        composition.configuration,
        configuration_fingerprint="changed-configuration-fingerprint",
    )

    outcome = unwrap(recover(composition))

    assert isinstance(outcome, ControlledFailureResult)
    assert outcome.error.code is FailureCode.CONFIGURATION_CHANGED
    assert outcome.safe_failure.details == FrozenJsonObject(
        {
            "stored_configuration_fingerprint": run.configuration_fingerprint,
            "current_configuration_fingerprint": (
                "changed-configuration-fingerprint"
            ),
            "prior_run_status": ProcessingRunStatus.PERSISTED.value,
        }
    )
    assert composition.gateway.requests == []
    assert trace_names(composition) == [
        "recovery_started",
        "run_failed",
        "recovery_completed",
    ]


@pytest.mark.parametrize(
    ("corrupt", "expected_reason"),
    [
        ("missing-packet", "MISSING_REQUIRED_PACKET"),
        ("packet-status", "PACKET_STATUS_MISMATCH"),
        ("message-status", "STATUS_ARTIFACT_MISMATCH"),
    ],
)
def test_impossible_state_uses_first_closed_reason_without_resuming(
    composition: SimpleNamespace,
    corrupt: str,
    expected_reason: str,
) -> None:
    if corrupt in {"missing-packet", "packet-status"}:
        original = pause_method(composition, "_continue_from_packet")
        try:
            assert composition.service.execute(request(composition), Token()) is _PAUSED
        finally:
            restore_method(composition, "_continue_from_packet", original)
        active = composition.repositories.processing_runs.get_non_terminal()
        assert active is not None
        if corrupt == "missing-packet":
            composition.connection.execute(
                "DELETE FROM context_packets WHERE processing_run_id = ?",
                (str(active.id),),
            )
        else:
            composition.connection.execute(
                "UPDATE processing_runs SET status = 'PERSISTED' WHERE id = ?",
                (str(active.id),),
            )
    else:
        admitted = admit_only(composition)
        active = getattr(admitted, "run")
        composition.connection.execute(
            "UPDATE messages SET role = ? WHERE id = ?",
            (MessageRole.ASSISTANT.value, str(active.user_message_id)),
        )
    composition.connection.commit()
    composition.traces.events.clear()

    outcome = unwrap(recover(composition))

    assert isinstance(outcome, ControlledFailureResult)
    assert outcome.error.code is FailureCode.PERSISTENCE_ERROR
    assert outcome.safe_failure.details["recovery_reason"] == expected_reason
    assert composition.gateway.requests == []
    assert trace_names(composition) == [
        "recovery_started",
        "run_failed",
        "recovery_completed",
    ]


def test_impossible_state_classifier_covers_all_closed_reasons_in_precedence_order(
    composition: SimpleNamespace,
) -> None:
    original = pause_method(composition, "_commit_success")
    try:
        assert composition.service.execute(request(composition), Token()) is _PAUSED
    finally:
        restore_method(composition, "_commit_success", original)
    classifier = recovery_service(composition)
    snapshot = classifier._load_snapshot()  # type: ignore[attr-defined]
    assert snapshot is not None
    model_request = snapshot.requests[0]
    response = snapshot.responses[0]
    validation = snapshot.validations[0]
    assert response is not None
    assert validation is not None
    alternate_id = DomainId("93000000-0000-4000-8000-000000000001")

    missing_packet = replace(
        snapshot,
        run=replace(snapshot.run, status=ProcessingRunStatus.CONTEXT_READY),
        packet=None,
        requests=(),
        responses=(),
        validations=(),
        listed_validations=(),
        assistant_messages=(),
        corrections=(),
    )
    packet_status = replace(
        snapshot,
        run=replace(snapshot.run, status=ProcessingRunStatus.PERSISTED),
    )
    duplicate = replace(model_request, id=alternate_id)
    duplicate_attempt = replace(
        snapshot,
        requests=(model_request, duplicate),
        responses=(response, None),
        validations=(validation, None),
        assistant_messages=(None, None),
    )
    request_packet = replace(
        snapshot,
        requests=(replace(model_request, context_packet_id=alternate_id),),
    )
    response_request = replace(
        snapshot,
        responses=(replace(response, model_request_id=alternate_id),),
    )
    validation_response = replace(
        snapshot,
        validations=(replace(validation, model_response_id=alternate_id),),
        listed_validations=(replace(validation, model_response_id=alternate_id),),
    )
    assistant_validation = replace(
        snapshot,
        responses=(replace(response, assistant_message_id=alternate_id),),
    )
    correction_lineage = replace(
        snapshot,
        requests=(
            replace(
                model_request,
                purpose=ModelRequestPurpose.REVISION,
                attempt_number=1,
            ),
        ),
    )
    status_artifact = replace(snapshot, state=None)

    cases = (
        (missing_packet, "MISSING_REQUIRED_PACKET"),
        (packet_status, "PACKET_STATUS_MISMATCH"),
        (duplicate_attempt, "DUPLICATE_REQUEST_ATTEMPT"),
        (request_packet, "REQUEST_PACKET_MISMATCH"),
        (response_request, "RESPONSE_REQUEST_MISMATCH"),
        (validation_response, "VALIDATION_RESPONSE_MISMATCH"),
        (assistant_validation, "ASSISTANT_VALIDATION_MISMATCH"),
        (correction_lineage, "CORRECTION_LINEAGE_MISMATCH"),
        (status_artifact, "STATUS_ARTIFACT_MISMATCH"),
    )
    for mutated, expected_reason in cases:
        issue = classifier._classify_impossible(mutated)  # type: ignore[attr-defined]
        assert issue is not None
        assert issue.reason == expected_reason

    combined = replace(
        duplicate_attempt,
        requests=(
            replace(model_request, context_packet_id=alternate_id),
            duplicate,
        ),
    )
    issue = classifier._classify_impossible(combined)  # type: ignore[attr-defined]
    assert issue is not None
    assert issue.reason == "DUPLICATE_REQUEST_ATTEMPT"
