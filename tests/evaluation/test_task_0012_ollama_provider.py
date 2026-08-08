"""AT-010 TASK-0012 component acceptance for the real buffered adapter."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
import json
from threading import Event, Thread
from typing import Any

import pytest

from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports import (
    CompletedGeneration,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
    TokenUsage,
)
from context_for_ai.domain.value_objects import FrozenJsonObject
from tests.fixtures.ollama_transport import (
    ControlledMonotonicClock,
    ScriptedEffect,
    json_body,
)


def _invoke_in_worker(
    gateway: Any,
    request: Any,
    token: Any,
) -> tuple[Thread, Event, dict[str, Any]]:
    completed = Event()
    observation: dict[str, Any] = {}

    def invoke() -> None:
        try:
            observation["outcome"] = gateway.generate(request, token)
        except BaseException as error:
            observation["error"] = error
        finally:
            completed.set()

    worker = Thread(target=invoke, name="task-0012-held-adapter")
    worker.start()
    return worker, completed, observation


def _finish_worker(
    worker: Thread,
    completed: Event,
    observation: dict[str, Any],
) -> Any:
    assert completed.wait(2.0)
    worker.join(2.0)
    assert not worker.is_alive()
    assert "error" not in observation
    return observation["outcome"]


def test_at010_task0012_fixture_and_construction_are_daemon_free(
    ollama_adapter_composition: Any,
) -> None:
    composition = ollama_adapter_composition()

    assert ollama_adapter_composition.fixture_version == "ollama-adapter-v1"
    assert composition.system_ports.model_gateway is composition.gateway
    assert composition.transport.call_snapshot == ()
    assert composition.transport.active_indices == ()
    assert composition.expected_request.rendered_prompt == (
        "  Exact prompt: café 😀\nKeep leading and trailing space.  "
    )
    assert composition.expected_request.settings.temperature == Decimal(
        "0.1250000000000000000000000001"
    )


def test_at010_task0012_success_uses_exact_order_and_uncached_checks(
    ollama_adapter_composition: Any,
) -> None:
    request = ollama_adapter_composition.expected_request
    steps = ollama_adapter_composition.successful_steps(request)
    composition = ollama_adapter_composition(
        request=request,
        steps=steps + steps,
    )

    first = composition.gateway.generate(
        request, composition.new_cancellation_token()
    )
    second = composition.gateway.generate(
        request, composition.new_cancellation_token()
    )

    assert isinstance(first, CompletedGeneration)
    assert second == first
    assert tuple(
        (record.request.method, record.request.path)
        for record in composition.transport.call_snapshot
    ) == (
        ("GET", "/api/version"),
        ("GET", "/api/status"),
        ("POST", "/api/show"),
        ("POST", "/api/generate"),
    ) * 2
    assert composition.transport.closed_indices == tuple(range(8))
    assert composition.transport.active_indices == ()


def test_at010_task0012_exact_wire_prompt_metadata_tokens_and_elapsed(
    ollama_adapter_composition: Any,
) -> None:
    composition = ollama_adapter_composition()
    request_before = composition.expected_request

    outcome = composition.gateway.generate(
        composition.expected_request,
        composition.new_cancellation_token(),
    )

    assert isinstance(outcome, CompletedGeneration)
    assert outcome.response_text == (
        "  Complete local answer.\nSecond line: café 😀  "
    )
    assert outcome.provider_metadata == FrozenJsonObject(
        {
            "provider": "ollama",
            "provider_version": "0.16.2",
            "model_identity": "fixture-model:latest",
            "model_tag": "latest",
            "cloud_disable_source": "both",
            "done_reason": "stop",
            "total_duration_ns": 1_000_000_000,
            "load_duration_ns": 100_000_000,
            "prompt_eval_duration_ns": 300_000_000,
            "eval_duration_ns": 600_000_000,
        }
    )
    assert outcome.token_usage == TokenUsage(23, 9, 32)
    assert outcome.elapsed == timedelta(seconds=1)
    assert composition.expected_request == request_before

    show = json.loads(composition.transport.call_snapshot[2].request.body)
    generate = json.loads(
        composition.transport.call_snapshot[3].request.body,
        parse_float=Decimal,
    )
    assert show == {"model": "fixture-model:latest", "verbose": False}
    assert generate == {
        "model": "fixture-model:latest",
        "prompt": composition.expected_request.rendered_prompt,
        "stream": False,
        "raw": True,
        "think": False,
        "truncate": False,
        "shift": False,
        "options": {
            "num_ctx": 8192,
            "temperature": Decimal("0.1250000000000000000000000001"),
        },
    }


@pytest.mark.parametrize(
    ("stage", "replacement", "expected_type", "expected_calls"),
    (
        (0, {"body_fragments": (b"{}",)}, ProviderUnavailableFailure, 1),
        (0, {"status": 503}, ProviderUnavailableFailure, 1),
        (
            1,
            {"body_fragments": (json_body({"cloud": {"disabled": False, "source": "env"}}),)},
            ProviderUnavailableFailure,
            2,
        ),
        (1, {"status": 404}, ProviderUnavailableFailure, 2),
        (2, {"status": 404}, ModelNotFoundFailure, 3),
        (
            2,
            {"body_fragments": (json_body({"remote_model": "remote/model"}),)},
            ModelNotFoundFailure,
            3,
        ),
        (2, {"body_fragments": (json_body({"remote_host": False}),)}, ProviderUnavailableFailure, 3),
        (3, {"status": 404}, ModelNotFoundFailure, 4),
        (3, {"status": 500}, ProviderUnavailableFailure, 4),
        (3, {"media_type": "text/plain"}, InvalidProviderResponseFailure, 4),
        (3, {"body_fragments": (b'{"model":"fixture-model","response":"partial"',)}, InvalidProviderResponseFailure, 4),
        (
            3,
            {"body_fragments": (json_body({"model": "fixture-model", "response": "secret", "done": False}),)},
            InvalidProviderResponseFailure,
            4,
        ),
    ),
)
def test_at010_task0012_stage_failure_matrix_stops_without_retry(
    ollama_adapter_composition: Any,
    stage: int,
    replacement: dict[str, object],
    expected_type: type[object],
    expected_calls: int,
) -> None:
    request = ollama_adapter_composition.expected_request
    steps = list(ollama_adapter_composition.successful_steps(request))
    steps[stage] = replace(steps[stage], **replacement)
    composition = ollama_adapter_composition(request=request, steps=tuple(steps))

    outcome = composition.gateway.generate(
        request, composition.new_cancellation_token()
    )

    assert isinstance(outcome, expected_type)
    assert len(composition.transport.call_snapshot) == expected_calls
    assert composition.transport.closed_indices == tuple(range(expected_calls))
    assert not hasattr(outcome, "response_text")
    assert not hasattr(outcome, "partial_text")


@pytest.mark.parametrize("stage", range(4))
@pytest.mark.parametrize("status", (408, 504))
def test_at010_task0012_http_timeout_status_wins_at_every_stage(
    ollama_adapter_composition: Any,
    stage: int,
    status: int,
) -> None:
    request = ollama_adapter_composition.expected_request
    steps = list(ollama_adapter_composition.successful_steps(request))
    steps[stage] = replace(steps[stage], status=status)
    composition = ollama_adapter_composition(request=request, steps=tuple(steps))

    outcome = composition.gateway.generate(
        request, composition.new_cancellation_token()
    )

    assert outcome == ModelTimeoutFailure()
    assert len(composition.transport.call_snapshot) == stage + 1


@pytest.mark.parametrize(
    ("stage", "failure_status", "expected"),
    (
        (0, None, ProviderUnavailableFailure()),
        (1, 200, ProviderUnavailableFailure()),
        (2, 200, ProviderUnavailableFailure()),
        (3, None, ProviderUnavailableFailure()),
        (3, 200, InvalidProviderResponseFailure()),
    ),
)
def test_at010_task0012_transport_failures_are_content_free_and_stage_specific(
    ollama_adapter_composition: Any,
    stage: int,
    failure_status: int | None,
    expected: object,
) -> None:
    request = ollama_adapter_composition.expected_request
    steps = list(ollama_adapter_composition.successful_steps(request))
    steps[stage] = replace(
        steps[stage],
        effect=ScriptedEffect.FAILURE,
        failure_status=failure_status,
    )
    composition = ollama_adapter_composition(request=request, steps=tuple(steps))

    outcome = composition.gateway.generate(
        request, composition.new_cancellation_token()
    )

    assert outcome == expected
    assert {field.name for field in fields(outcome)} == {
        "diagnostic_code",
        "safe_message",
        "model_request_status",
        "processing_run_status",
        "failure_code",
    }
    assert "fixture-model" not in repr(outcome)
    assert "private" not in outcome.safe_message.casefold()


def test_at010_task0012_precancel_and_model_mismatch_start_no_exchange(
    ollama_adapter_composition: Any,
) -> None:
    pre_cancelled = ollama_adapter_composition()
    assert pre_cancelled.gateway.generate(
        pre_cancelled.expected_request,
        pre_cancelled.new_cancellation_token(cancelled=True),
    ) == ModelCancelledFailure()
    assert pre_cancelled.transport.call_snapshot == ()

    mismatched = ollama_adapter_composition()
    wrong_request = replace(
        mismatched.expected_request,
        model_name="another-model",
    )
    with pytest.raises(LifecycleInvariantError, match="bound provider model"):
        mismatched.gateway.generate(
            wrong_request,
            mismatched.new_cancellation_token(),
        )
    assert mismatched.transport.call_snapshot == ()


def test_at010_task0012_held_fragment_exposes_nothing_until_complete(
    ollama_adapter_composition: Any,
) -> None:
    request = ollama_adapter_composition.expected_request
    steps = list(ollama_adapter_composition.successful_steps(request))
    complete_body = b"".join(steps[3].body_fragments)
    split_at = complete_body.index(b"Complete local") + 8
    steps[3] = replace(
        steps[3],
        body_fragments=(complete_body[:split_at], complete_body[split_at:]),
        hold_after_fragments=1,
    )
    composition = ollama_adapter_composition(request=request, steps=tuple(steps))
    worker, completed, observation = _invoke_in_worker(
        composition.gateway,
        request,
        composition.new_cancellation_token(),
    )

    try:
        composition.transport.wait_until_held(3)
        assert not completed.is_set()
        assert observation == {}
        assert composition.transport.active_indices == (3,)
        assert composition.transport.closed_indices == (0, 1, 2)
        assert not hasattr(composition.gateway, "stream")
        assert not hasattr(composition.gateway, "partial")
    finally:
        composition.transport.release(3)

    outcome = _finish_worker(worker, completed, observation)
    assert isinstance(outcome, CompletedGeneration)
    assert outcome.response_text == (
        "  Complete local answer.\nSecond line: café 😀  "
    )
    assert composition.transport.closed_indices == (0, 1, 2, 3)


def test_at010_task0012_held_cancellation_discards_all_content_and_closes(
    ollama_adapter_composition: Any,
) -> None:
    request = ollama_adapter_composition.expected_request
    steps = list(ollama_adapter_composition.successful_steps(request))
    complete_body = b"".join(steps[3].body_fragments)
    steps[3] = replace(
        steps[3],
        body_fragments=(complete_body[:20], complete_body[20:]),
        hold_after_fragments=1,
    )
    composition = ollama_adapter_composition(request=request, steps=tuple(steps))
    token = composition.new_cancellation_token()
    worker, completed, observation = _invoke_in_worker(
        composition.gateway, request, token
    )

    composition.transport.wait_until_held(3)
    token.cancel()

    outcome = _finish_worker(worker, completed, observation)
    assert outcome == ModelCancelledFailure()
    assert not hasattr(outcome, "response_text")
    assert composition.transport.aborted_indices == (3,)
    assert composition.transport.closed_indices == (0, 1, 2, 3)
    assert composition.transport.active_indices == ()


def test_at010_task0012_cancellation_wins_over_simultaneous_deadline_and_body(
    ollama_adapter_composition: Any,
) -> None:
    request = ollama_adapter_composition.expected_request
    clock = ControlledMonotonicClock()
    steps = list(ollama_adapter_composition.successful_steps(request))
    invalid_body = json_body(
        {"model": "wrong-model", "response": "must-discard", "done": True}
    )
    steps[3] = replace(
        steps[3],
        body_fragments=(invalid_body[:10], invalid_body[10:]),
        hold_after_fragments=1,
    )
    composition = ollama_adapter_composition(
        request=request,
        steps=tuple(steps),
        clock=clock,
    )
    token = composition.new_cancellation_token()
    worker, completed, observation = _invoke_in_worker(
        composition.gateway, request, token
    )

    composition.transport.wait_until_held(3)
    clock.advance(request.settings.request_timeout_seconds)
    token.cancel()
    composition.transport.release(3)

    assert _finish_worker(worker, completed, observation) == ModelCancelledFailure()


def test_at010_task0012_cancellation_wins_at_the_final_publication_edge(
    ollama_adapter_composition: Any,
) -> None:
    composition = ollama_adapter_composition()

    class CancelAtFinalPublication:
        checks_after_generation = 0

        def is_cancelled(self) -> bool:
            if composition.transport.closed_indices == (0, 1, 2, 3):
                self.checks_after_generation += 1
            return self.checks_after_generation >= 6

    token = CancelAtFinalPublication()

    outcome = composition.gateway.generate(composition.expected_request, token)

    assert outcome == ModelCancelledFailure()
    assert token.checks_after_generation == 6
    assert composition.transport.closed_indices == (0, 1, 2, 3)


def test_at010_task0012_one_absolute_deadline_is_shared_and_stops_later_stages(
    ollama_adapter_composition: Any,
) -> None:
    base_request = ollama_adapter_composition.expected_request
    request = replace(
        base_request,
        settings=replace(base_request.settings, request_timeout_seconds=10),
    )
    steps = list(ollama_adapter_composition.successful_steps(request))
    steps[0] = replace(steps[0], advance_seconds=3)
    steps[1] = replace(steps[1], advance_seconds=3)
    steps[2] = replace(steps[2], advance_seconds=4)
    composition = ollama_adapter_composition(request=request, steps=tuple(steps))

    outcome = composition.gateway.generate(
        request, composition.new_cancellation_token()
    )

    assert outcome == ModelTimeoutFailure()
    assert tuple(
        record.deadline for record in composition.transport.call_snapshot
    ) == (110.0, 110.0, 110.0)
    assert tuple(
        record.request.path for record in composition.transport.call_snapshot
    ) == ("/api/version", "/api/status", "/api/show")
    assert composition.transport.aborted_indices == (2,)
    assert composition.transport.closed_indices == (0, 1, 2)
