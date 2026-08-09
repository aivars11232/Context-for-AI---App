"""AT-002, AT-012, and cross-cutting TASK-0014 acceptance evidence."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from context_for_ai.application import (
    CancellationCheckpoint,
    CancelledResult,
    ConfigurationFailureResult,
    ControlledFailureResult,
    PersistenceFailureResult,
    ProcessUserMessageService,
    SucceededResult,
    ValidationExhaustedResult,
)
from context_for_ai.bootstrap import DeterministicComponents
from context_for_ai.domain.decisions import TOKEN_ESTIMATOR_VERSION
from context_for_ai.domain.enums import (
    ContextBudgetPhase,
    FailureCode,
    MessageRole,
    ModelRequestStatus,
    PipelineStage,
    ProcessingRunStatus,
)
from context_for_ai.domain.ports.context import (
    ContextBudgetExceeded,
    PromptRenderRequest,
    PromptRenderResult,
)
from context_for_ai.domain.ports.errors import ConfigurationError, PersistenceError
from context_for_ai.domain.ports.model_gateway import (
    GenerationFailure,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
)
from context_for_ai.domain.entities import Message
from context_for_ai.domain.value_objects import FrozenJsonObject
from tests.integration.test_process_user_message import (
    Token,
    composition,
    request,
)
from tests.integration.test_recover_processing_run import (
    _PAUSED,
    pause_method,
    recover,
    restore_method,
    unwrap,
)


class CancelOnObservation:
    def __init__(self, observation: int) -> None:
        self.observation = observation
        self.calls = 0

    def is_cancelled(self) -> bool:
        self.calls += 1
        return self.calls >= self.observation


class RaisingTraceLogger:
    def emit(self, _: object) -> None:
        raise OSError("injected trace sink failure")


class InvalidConfigurationLoader:
    def load(self) -> object:
        raise ConfigurationError("model.yaml", "model.name", "non-empty text")


class CorrectionOverflowRenderer:
    def __init__(self, base: object) -> None:
        self.base = base

    def render(
        self,
        render_request: PromptRenderRequest,
    ) -> PromptRenderResult | ContextBudgetExceeded:
        if render_request.correction_envelope is None:
            return self.base.render(render_request)  # type: ignore[attr-defined,no-any-return]
        return ContextBudgetExceeded(
            render_request.packet.id,
            FailureCode.CONTEXT_BUDGET_EXCEEDED,
            ContextBudgetPhase.CORRECTION,
            TOKEN_ESTIMATOR_VERSION,
            101,
            100,
        )


class FailingMessages:
    def __init__(self, base: object) -> None:
        self.base = base

    def __getattr__(self, name: str) -> object:
        return getattr(self.base, name)

    def add(self, _: object) -> None:
        raise PersistenceError("injected acceptance write failure")


class FailingRequestWrites:
    def __init__(self, base: object, *, fail_terminalization: bool) -> None:
        self.base = base
        self.fail_terminalization = fail_terminalization
        self.request_failures = 0
        self.terminal_failures = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self.base, name)

    def add_request(self, _: object) -> None:
        self.request_failures += 1
        raise PersistenceError("injected request write failure")

    def add_failure(self, failure: object) -> None:
        if self.fail_terminalization:
            self.terminal_failures += 1
            raise PersistenceError("injected terminal write failure")
        self.base.add_failure(failure)  # type: ignore[attr-defined]


class FailOnceRepositoryMethod:
    def __init__(
        self,
        base: object,
        method_name: str,
        *,
        predicate: object | None = None,
    ) -> None:
        self.base = base
        self.method_name = method_name
        self.predicate = predicate
        self.failures = 0

    def __getattr__(self, name: str) -> object:
        target = getattr(self.base, name)
        if name != self.method_name:
            return target

        def invoke(*args: object, **kwargs: object) -> object:
            should_fail = self.failures == 0 and (
                self.predicate is None
                or self.predicate(*args, **kwargs)  # type: ignore[operator]
            )
            if should_fail:
                self.failures += 1
                raise PersistenceError(
                    f"injected {self.method_name} transaction-group failure"
                )
            return target(*args, **kwargs)

        return invoke


def service(
    value: SimpleNamespace,
    *,
    repositories: object | None = None,
    system: object | None = None,
    deterministic: DeterministicComponents | None = None,
) -> ProcessUserMessageService:
    return ProcessUserMessageService(
        repositories=(value.repositories if repositories is None else repositories),  # type: ignore[arg-type]
        system=value.system if system is None else system,  # type: ignore[arg-type]
        deterministic=(
            value.deterministic if deterministic is None else deterministic
        ),
        context_packet_stage=value.stage,
    )


@pytest.mark.parametrize(
    "correction_limit",
    [0, 1, 2],
)
def test_at012_revision_bound_is_exact_for_every_configured_limit(
    composition: SimpleNamespace,
    correction_limit: int,
) -> None:
    composition.loader.snapshot = replace(
        composition.configuration,
        validation=replace(
            composition.configuration.validation,
            max_revisions=correction_limit,
        ),
    )
    composition.gateway.text = "IMAGE_RESULT: forbidden"

    result = composition.service.execute(request(composition), Token())

    assert isinstance(result, ValidationExhaustedResult)
    requests = composition.repositories.model_calls.list_requests_for_run(
        result.processing_run_id
    )
    corrections = composition.repositories.model_calls.list_corrections_for_run(
        result.processing_run_id
    )
    assert len(composition.gateway.requests) == correction_limit + 1
    assert [item.attempt_number for item in requests] == list(
        range(correction_limit + 1)
    )
    assert [item.attempt_number for item in corrections] == list(
        range(1, correction_limit + 1)
    )
    assert all(item.status is ModelRequestStatus.SUCCEEDED for item in requests)


@pytest.mark.parametrize(
    "gateway_failure",
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
def test_gateway_failures_have_exact_atomic_public_and_durable_mapping(
    composition: SimpleNamespace,
    gateway_failure: GenerationFailure,
) -> None:
    calls = 0
    original_generate = composition.gateway.generate

    def fail(*_: object) -> GenerationFailure:
        nonlocal calls
        calls += 1
        return gateway_failure

    composition.gateway.generate = fail
    try:
        result = composition.service.execute(request(composition), Token())
    finally:
        composition.gateway.generate = original_generate

    assert calls == 1
    if isinstance(gateway_failure, ModelCancelledFailure):
        assert isinstance(result, CancelledResult)
        assert result.checkpoint is CancellationCheckpoint.GATEWAY
    else:
        assert isinstance(result, ControlledFailureResult)
        assert result.error.code is gateway_failure.failure_code
    stored_run = composition.repositories.processing_runs.get(
        result.processing_run_id
    )
    stored_requests = composition.repositories.model_calls.list_requests_for_run(
        result.processing_run_id
    )
    failures = composition.repositories.model_calls.list_failures_for_run(
        result.processing_run_id
    )
    assert stored_run is not None
    assert stored_run.status is gateway_failure.processing_run_status
    assert stored_requests[-1].status is gateway_failure.model_request_status
    assert failures == (result.safe_failure,)
    assert result.safe_failure.stage is PipelineStage.TRANSPORT
    assert result.safe_failure.details == FrozenJsonObject(
        {
            "attempt_number": 0,
            "context_packet_id": str(result.context_packet_id),
            "diagnostic_code": gateway_failure.diagnostic_code,
            "model_request_id": str(stored_requests[-1].id),
        }
    )


@pytest.mark.parametrize(
    ("cancel_on", "checkpoint"),
    [
        (2, CancellationCheckpoint.AFTER_ACCEPTANCE),
        (3, CancellationCheckpoint.CONTEXT_CONSTRUCTION),
    ],
)
def test_accepted_context_cancellation_has_one_durable_failure(
    composition: SimpleNamespace,
    cancel_on: int,
    checkpoint: CancellationCheckpoint,
) -> None:
    result = composition.service.execute(
        request(composition),
        CancelOnObservation(cancel_on),  # type: ignore[arg-type]
    )

    assert isinstance(result, CancelledResult)
    assert result.checkpoint is checkpoint
    assert result.cancellation_code is FailureCode.CANCELLED_BY_USER
    assert result.processing_status is ProcessingRunStatus.CANCELLED
    assert result.context_packet_id is None
    assert composition.gateway.requests == []
    assert composition.repositories.model_calls.list_failures_for_run(
        result.processing_run_id
    ) == (result.safe_failure,)


def test_recovery_context_ready_cancellation_creates_no_request(
    composition: SimpleNamespace,
) -> None:
    original = pause_method(composition, "_continue_from_packet")
    try:
        assert composition.service.execute(request(composition), Token()) is _PAUSED
    finally:
        restore_method(composition, "_continue_from_packet", original)

    result = unwrap(recover(composition, Token(True)))

    assert isinstance(result, CancelledResult)
    assert result.checkpoint is CancellationCheckpoint.BEFORE_REQUEST_PREPARATION
    assert result.context_packet_id is not None
    assert composition.repositories.model_calls.list_requests_for_run(
        result.processing_run_id
    ) == ()
    assert composition.gateway.requests == []


def test_correction_render_overflow_preserves_failed_candidate_only(
    composition: SimpleNamespace,
) -> None:
    composition.gateway.text = "TOOL_CALL: forbidden"
    deterministic = replace(
        composition.deterministic,
        prompt_renderer=CorrectionOverflowRenderer(
            composition.deterministic.prompt_renderer
        ),
    )

    result = service(composition, deterministic=deterministic).execute(
        request(composition),
        Token(),
    )

    assert isinstance(result, ControlledFailureResult)
    assert result.error.code is FailureCode.CONTEXT_BUDGET_EXCEEDED
    assert result.safe_failure.stage is PipelineStage.CORRECTION
    assert result.safe_failure.safe_message == (
        "The correction context exceeds the configured prompt budget."
    )
    assert len(composition.gateway.requests) == 1
    assert len(
        composition.repositories.model_calls.list_requests_for_run(
            result.processing_run_id
        )
    ) == 1
    assert composition.repositories.model_calls.list_corrections_for_run(
        result.processing_run_id
    ) == ()


def test_closed_request_response_projection_and_exact_bytes(
    composition: SimpleNamespace,
) -> None:
    result = composition.service.execute(request(composition), Token())
    assert isinstance(result, SucceededResult)
    model_request = composition.repositories.model_calls.list_requests_for_run(
        result.processing_run_id
    )[0]
    response = composition.repositories.model_calls.get_response_for_request(
        model_request.id
    )
    assert response is not None

    assert set(model_request.request) == {
        "schema_version",
        "correlation",
        "generation_settings",
        "rendering",
    }
    assert model_request.request["schema_version"] == "mvp-model-request-v1"
    assert set(model_request.request["correlation"]) == {
        "processing_run_id",
        "context_packet_id",
        "model_request_id",
        "attempt_number",
    }
    assert set(response.metadata) == {
        "schema_version",
        "correlation",
        "elapsed_microseconds",
        "token_usage",
        "provider_metadata",
    }
    assert response.metadata["schema_version"] == "mvp-completed-generation-v1"
    assert response.response_text.encode("utf-8") == result.assistant_text.encode(
        "utf-8"
    )
    assert "rendered_prompt" not in model_request.request
    assert "response_text" not in response.metadata


def test_configuration_failure_precedes_all_repository_access(
    composition: SimpleNamespace,
) -> None:
    system = replace(
        composition.system,
        configuration_loader=InvalidConfigurationLoader(),
    )
    before = composition.connection.total_changes

    result = service(composition, system=system).execute(
        request(composition),
        Token(),
    )

    assert isinstance(result, ConfigurationFailureResult)
    assert result.error.file == "model.yaml"
    assert result.error.key == "model.name"
    assert composition.connection.total_changes == before
    assert composition.traces.events == []


def test_trace_adapter_failure_cannot_change_committed_success(
    composition: SimpleNamespace,
) -> None:
    system = replace(composition.system, trace_logger=RaisingTraceLogger())

    result = service(composition, system=system).execute(
        request(composition),
        Token(),
    )

    assert isinstance(result, SucceededResult)
    stored = composition.repositories.processing_runs.get(result.processing_run_id)
    assert stored is not None
    assert stored.status is ProcessingRunStatus.SUCCEEDED


def test_acceptance_write_failure_rolls_back_without_fabricating_a_run(
    composition: SimpleNamespace,
) -> None:
    repositories = replace(
        composition.repositories,
        messages=FailingMessages(composition.repositories.messages),
    )

    result = service(composition, repositories=repositories).execute(
        request(composition),
        Token(),
    )

    assert isinstance(result, PersistenceFailureResult)
    assert result.processing_run_id is None
    assert not result.failure_persisted
    assert composition.repositories.messages.next_sequence_number(
        composition.conversation_id
    ) == 0
    assert composition.repositories.processing_runs.get_non_terminal() is None


@pytest.mark.parametrize("fail_terminalization", [False, True])
def test_request_write_failure_has_one_truthful_best_effort_terminalization(
    composition: SimpleNamespace,
    fail_terminalization: bool,
) -> None:
    failing = FailingRequestWrites(
        composition.repositories.model_calls,
        fail_terminalization=fail_terminalization,
    )
    repositories = replace(composition.repositories, model_calls=failing)

    result = service(composition, repositories=repositories).execute(
        request(composition),
        Token(),
    )

    assert isinstance(result, PersistenceFailureResult)
    assert result.error.failed_stage is PipelineStage.REQUEST
    assert failing.request_failures == 1
    if fail_terminalization:
        assert failing.terminal_failures == 1
        assert not result.failure_persisted
        assert result.processing_status is ProcessingRunStatus.CONTEXT_READY
        assert composition.repositories.processing_runs.get_non_terminal() is not None
    else:
        assert result.failure_persisted
        assert result.processing_status is ProcessingRunStatus.FAILED
        assert result.safe_failure is not None
        assert result.safe_failure.error_code is FailureCode.PERSISTENCE_ERROR
        assert composition.repositories.processing_runs.get_non_terminal() is None


@pytest.mark.parametrize(
    ("failure_group", "failed_stage"),
    [
        ("context", PipelineStage.CONTEXT),
        ("claim", PipelineStage.REQUEST),
        ("candidate", PipelineStage.VALIDATION),
        ("terminal", PipelineStage.TERMINALIZATION),
    ],
)
def test_every_post_acceptance_transaction_group_rolls_back_then_terminalizes_once(
    composition: SimpleNamespace,
    failure_group: str,
    failed_stage: PipelineStage,
) -> None:
    repositories = composition.repositories
    injected: FailOnceRepositoryMethod
    if failure_group == "context":
        injected = FailOnceRepositoryMethod(
            repositories.reference_resolutions,
            "add_all",
        )
        repositories = replace(
            repositories,
            reference_resolutions=injected,
        )
    elif failure_group == "claim":
        injected = FailOnceRepositoryMethod(
            repositories.model_calls,
            "update_request",
        )
        repositories = replace(repositories, model_calls=injected)
    elif failure_group == "candidate":
        injected = FailOnceRepositoryMethod(
            repositories.validations,
            "add",
        )
        repositories = replace(repositories, validations=injected)
    else:
        injected = FailOnceRepositoryMethod(
            repositories.messages,
            "add",
            predicate=lambda message: (
                isinstance(message, Message)
                and message.role is MessageRole.ASSISTANT
            ),
        )
        repositories = replace(repositories, messages=injected)

    result = service(composition, repositories=repositories).execute(
        request(composition),
        Token(),
    )

    assert isinstance(result, PersistenceFailureResult)
    assert result.error.failed_stage is failed_stage
    assert result.failure_persisted
    assert result.processing_status is ProcessingRunStatus.FAILED
    assert result.safe_failure is not None
    assert result.safe_failure.error_code is FailureCode.PERSISTENCE_ERROR
    assert injected.failures == 1
    assert composition.repositories.processing_runs.get_non_terminal() is None

    packet = composition.repositories.context_packets.get_for_run(
        result.processing_run_id
    )
    requests = composition.repositories.model_calls.list_requests_for_run(
        result.processing_run_id
    )
    responses = tuple(
        composition.repositories.model_calls.get_response_for_request(item.id)
        for item in requests
    )
    validations = composition.repositories.validations.list_for_run(
        result.processing_run_id
    )
    if failure_group == "context":
        assert packet is None
        assert requests == ()
    elif failure_group == "claim":
        assert packet is not None
        assert len(requests) == 1
        assert requests[0].status is ModelRequestStatus.PENDING
        assert responses == (None,)
    elif failure_group == "candidate":
        assert packet is not None
        assert len(requests) == 1
        assert requests[0].status is ModelRequestStatus.IN_FLIGHT
        assert responses == (None,)
        assert validations == ()
    else:
        assert packet is not None
        assert len(requests) == 1
        assert responses[0] is not None
        assert responses[0].assistant_message_id is None
        assert len(validations) == 1


def test_revision_request_and_correction_group_rolls_back_together(
    composition: SimpleNamespace,
) -> None:
    composition.gateway.text = "TOOL_CALL: forbidden"
    injected = FailOnceRepositoryMethod(
        composition.repositories.model_calls,
        "add_correction",
    )
    repositories = replace(composition.repositories, model_calls=injected)

    result = service(composition, repositories=repositories).execute(
        request(composition),
        Token(),
    )

    assert isinstance(result, PersistenceFailureResult)
    assert result.error.failed_stage is PipelineStage.CORRECTION
    assert result.failure_persisted
    assert injected.failures == 1
    requests = composition.repositories.model_calls.list_requests_for_run(
        result.processing_run_id
    )
    assert [item.attempt_number for item in requests] == [0]
    assert composition.repositories.model_calls.list_corrections_for_run(
        result.processing_run_id
    ) == ()
    assert len(composition.gateway.requests) == 1


def test_transport_terminal_group_rollback_preserves_in_flight_then_best_effort_fails_run(
    composition: SimpleNamespace,
) -> None:
    original_generate = composition.gateway.generate
    composition.gateway.generate = lambda *_: ProviderUnavailableFailure()
    injected = FailOnceRepositoryMethod(
        composition.repositories.model_calls,
        "add_failure",
    )
    repositories = replace(composition.repositories, model_calls=injected)
    try:
        result = service(composition, repositories=repositories).execute(
            request(composition),
            Token(),
        )
    finally:
        composition.gateway.generate = original_generate

    assert isinstance(result, PersistenceFailureResult)
    assert result.error.failed_stage is PipelineStage.TRANSPORT
    assert result.failure_persisted
    assert result.safe_failure is not None
    assert result.safe_failure.error_code is FailureCode.PERSISTENCE_ERROR
    assert injected.failures == 1
    requests = composition.repositories.model_calls.list_requests_for_run(
        result.processing_run_id
    )
    assert len(requests) == 1
    assert requests[0].status is ModelRequestStatus.IN_FLIGHT
    assert composition.repositories.model_calls.get_response_for_request(
        requests[0].id
    ) is None
