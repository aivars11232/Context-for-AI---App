"""AT-010 component acceptance for the deterministic buffered model gateway."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest
import yaml

from context_for_ai.bootstrap import SystemPorts
from context_for_ai.domain.enums import (
    FailureCode,
    ModelRequestStatus,
    ProcessingRunStatus,
)
from context_for_ai.domain.ports import (
    CompletedGeneration,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "mock_model_provider"


def invoke_in_worker(
    gateway: Any,
    request: Any,
    token: Any,
) -> tuple[Thread, Event, dict[str, Any]]:
    """Invoke one synchronous gateway call with deterministic completion evidence."""

    completed = Event()
    observation: dict[str, Any] = {}

    def invoke() -> None:
        try:
            observation["outcome"] = gateway.generate(request, token)
        except BaseException as error:  # test thread must return its failure to pytest
            observation["error"] = error
        finally:
            completed.set()

    worker = Thread(target=invoke, name="task-0011-held-gateway")
    worker.start()
    return worker, completed, observation


def test_at010_fixture_version_and_test_composition_are_exact(
    mock_gateway_composition: Any,
) -> None:
    version = (FIXTURE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    document = yaml.safe_load(
        (FIXTURE_ROOT / "cases.yaml").read_text(encoding="utf-8")
    )
    composition = mock_gateway_composition(step_indices=(0,))

    assert version == document["schema_version"] == "mock-model-provider-v1"
    assert isinstance(composition.system_ports, SystemPorts)
    assert composition.system_ports.model_gateway is composition.gateway
    assert composition.call_snapshot == ()
    assert composition.expected_request.rendered_prompt.encode("utf-8") == (
        document["request"]["rendered_prompt"].encode("utf-8")
    )
    assert composition.expected_request.context_packet_id == DomainId(
        document["request"]["correlation"]["context_packet_id"]
    )
    assert composition.expected_request.processing_run_id == DomainId(
        document["request"]["correlation"]["processing_run_id"]
    )
    assert composition.expected_request.model_request_id == DomainId(
        document["request"]["correlation"]["model_request_id"]
    )
    assert composition.expected_request.attempt_number == 0
    assert composition.expected_request.settings.context_window_tokens == 4096
    assert composition.expected_request.settings.request_timeout_seconds == 60


def test_at010_ordered_script_returns_complete_success_and_all_failures(
    mock_gateway_composition: Any,
) -> None:
    composition = mock_gateway_composition(step_indices=(0, 1, 2, 3, 4))
    expected_outcomes = (
        composition.expected_success,
        ProviderUnavailableFailure(),
        ModelNotFoundFailure(),
        ModelTimeoutFailure(),
        InvalidProviderResponseFailure(),
    )

    observed_outcomes = tuple(
        composition.gateway.generate(
            composition.expected_request,
            composition.new_cancellation_token(),
        )
        for _ in expected_outcomes
    )

    assert observed_outcomes == expected_outcomes
    assert isinstance(observed_outcomes[0], CompletedGeneration)
    assert observed_outcomes[0].response_text == (
        "Complete synthetic response.\nSecond line: café 😀"
    )
    assert observed_outcomes[0].provider_metadata == FrozenJsonObject(
        {
            "finish_reason": "stop",
            "fixture": {
                "labels": ["complete", "synthetic"],
                "schema_version": "mock-model-provider-v1",
            },
        }
    )
    for failure in observed_outcomes[1:]:
        assert not hasattr(failure, "response_text")
        assert not hasattr(failure, "partial_text")

    records = composition.call_snapshot
    assert tuple(record.ordinal for record in records) == tuple(range(5))
    assert tuple(record.script_step_index for record in records) == tuple(range(5))
    assert tuple(record.request for record in records) == (
        composition.expected_request,
    ) * 5
    assert tuple(record.outcome for record in records) == expected_outcomes


def test_at010_failure_mappings_are_canonical_and_fixture_independent(
    mock_gateway_composition: Any,
) -> None:
    composition = mock_gateway_composition(step_indices=(1, 2, 3, 4))
    expected = (
        (
            "PROVIDER_UNAVAILABLE",
            "The local model provider is unavailable.",
            ModelRequestStatus.FAILED,
            ProcessingRunStatus.FAILED,
            FailureCode.PROVIDER_UNAVAILABLE,
        ),
        (
            "MODEL_NOT_FOUND",
            "The configured local model is unavailable.",
            ModelRequestStatus.FAILED,
            ProcessingRunStatus.FAILED,
            FailureCode.MODEL_NOT_FOUND,
        ),
        (
            "MODEL_TIMEOUT",
            "The local model request timed out.",
            ModelRequestStatus.TIMED_OUT,
            ProcessingRunStatus.FAILED,
            FailureCode.MODEL_TIMEOUT,
        ),
        (
            "INVALID_PROVIDER_RESPONSE",
            "The local model provider returned an invalid response.",
            ModelRequestStatus.FAILED,
            ProcessingRunStatus.FAILED,
            FailureCode.INVALID_PROVIDER_RESPONSE,
        ),
    )

    for mapping in expected:
        failure = composition.gateway.generate(
            composition.expected_request,
            composition.new_cancellation_token(),
        )
        assert (
            failure.diagnostic_code,
            failure.safe_message,
            failure.model_request_status,
            failure.processing_run_status,
            failure.failure_code,
        ) == mapping

    fixture_text = (FIXTURE_ROOT / "cases.yaml").read_text(encoding="utf-8")
    assert "safe_message" not in fixture_text
    assert "diagnostic_code" not in fixture_text


def test_at010_mismatch_and_exhaustion_do_not_select_or_repeat_outcomes(
    mock_gateway_composition: Any,
) -> None:
    composition = mock_gateway_composition(step_indices=(0,))
    mismatched = replace(
        composition.expected_request,
        model_request_id=DomainId("30000000-0000-4000-8000-000000000099"),
    )

    with pytest.raises(AssertionError, match="did not match"):
        composition.gateway.generate(
            mismatched,
            composition.new_cancellation_token(),
        )
    assert composition.call_snapshot == ()

    outcome = composition.gateway.generate(
        composition.expected_request,
        composition.new_cancellation_token(),
    )
    assert outcome == composition.expected_success
    assert len(composition.call_snapshot) == 1

    with pytest.raises(AssertionError, match="exhausted"):
        composition.gateway.generate(
            composition.expected_request,
            composition.new_cancellation_token(),
        )
    assert len(composition.call_snapshot) == 1


def test_at010_malformed_script_is_a_fixture_error_not_gateway_outcome(
    mock_gateway_composition: Any,
) -> None:
    with pytest.raises(AssertionError, match="schema_version"):
        mock_gateway_composition(
            step_indices=(0,),
            schema_version="unknown-mock-schema",
        )
    with pytest.raises(AssertionError, match="step indices"):
        mock_gateway_composition(step_indices=(99,))


def test_at010_fresh_equal_scripts_are_value_deterministic(
    mock_gateway_composition: Any,
) -> None:
    first = mock_gateway_composition(step_indices=(0, 1, 0))
    second = mock_gateway_composition(step_indices=(0, 1, 0))

    first_outcomes = tuple(
        first.gateway.generate(first.expected_request, first.new_cancellation_token())
        for _ in range(3)
    )
    second_outcomes = tuple(
        second.gateway.generate(second.expected_request, second.new_cancellation_token())
        for _ in range(3)
    )

    assert first_outcomes == second_outcomes
    assert first.call_snapshot == second.call_snapshot


def test_at010_pre_call_cancellation_records_no_step_and_consumes_none(
    mock_gateway_composition: Any,
) -> None:
    composition = mock_gateway_composition(step_indices=(0,))
    cancelled = composition.new_cancellation_token(cancelled=True)

    outcome = composition.gateway.generate(
        composition.expected_request,
        cancelled,
    )

    assert outcome == ModelCancelledFailure()
    assert outcome.model_request_status is ModelRequestStatus.CANCELLED
    assert outcome.processing_run_status is ProcessingRunStatus.CANCELLED
    assert outcome.failure_code is FailureCode.MODEL_CANCELLED
    assert composition.call_snapshot[0].script_step_index is None

    next_outcome = composition.gateway.generate(
        composition.expected_request,
        composition.new_cancellation_token(),
    )
    assert next_outcome == composition.expected_success
    assert tuple(record.script_step_index for record in composition.call_snapshot) == (
        None,
        0,
    )


def test_at010_held_success_exposes_no_result_or_text_before_release(
    mock_gateway_composition: Any,
) -> None:
    composition = mock_gateway_composition(step_indices=(5,))
    worker, completed, observation = invoke_in_worker(
        composition.gateway,
        composition.expected_request,
        composition.new_cancellation_token(),
    )

    try:
        composition.checkpoint_controller.wait_until_held(0, 2.0)
        assert not completed.is_set()
        assert observation == {}
        assert composition.call_snapshot == ()
        assert not hasattr(composition.gateway, "stream")
        assert not hasattr(composition.gateway, "partial")
        assert not hasattr(composition.gateway, "content_callback")
    finally:
        composition.checkpoint_controller.release(0)

    assert completed.wait(2.0)
    worker.join(2.0)
    assert not worker.is_alive()
    assert "error" not in observation
    assert observation["outcome"] == composition.expected_success
    records = composition.call_snapshot
    assert len(records) == 1
    assert records[0].ordinal == 0
    assert records[0].script_step_index == 0
    assert records[0].request is composition.expected_request
    assert records[0].outcome == composition.expected_success


def test_at010_held_cancellation_consumes_step_and_wins_at_resume(
    mock_gateway_composition: Any,
) -> None:
    composition = mock_gateway_composition(step_indices=(5, 3))
    token = composition.new_cancellation_token()
    worker, completed, observation = invoke_in_worker(
        composition.gateway,
        composition.expected_request,
        token,
    )

    try:
        composition.checkpoint_controller.wait_until_held(0, 2.0)
        token.cancel()
    finally:
        composition.checkpoint_controller.release(0)

    assert completed.wait(2.0)
    worker.join(2.0)
    assert not worker.is_alive()
    assert "error" not in observation
    assert observation["outcome"] == ModelCancelledFailure()
    assert composition.call_snapshot[0].script_step_index == 0

    next_outcome = composition.gateway.generate(
        composition.expected_request,
        composition.new_cancellation_token(),
    )
    assert next_outcome == ModelTimeoutFailure()
    assert tuple(record.script_step_index for record in composition.call_snapshot) == (
        0,
        1,
    )


def test_at010_call_observations_are_immutable_and_retain_no_token(
    mock_gateway_composition: Any,
) -> None:
    composition = mock_gateway_composition(step_indices=(1,))
    token = composition.new_cancellation_token()
    outcome = composition.gateway.generate(composition.expected_request, token)
    snapshot = composition.call_snapshot
    record = snapshot[0]

    assert isinstance(snapshot, tuple)
    assert outcome == ProviderUnavailableFailure()
    assert {field.name for field in fields(record)} == {
        "ordinal",
        "script_step_index",
        "request",
        "outcome",
    }
    assert all(getattr(record, field.name) is not token for field in fields(record))
    with pytest.raises(FrozenInstanceError):
        record.ordinal = 99  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot[0] = record  # type: ignore[index]
