"""Shared isolated, deterministic test composition and data fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import os
import shutil
from typing import Any, cast

import pytest
import yaml

from context_for_ai.bootstrap import SystemPorts
from context_for_ai.domain.ports import (
    Clock,
    CompletedGeneration,
    ConfigurationLoader,
    GenerationOutcome,
    GenerationRequest,
    GenerationSettings,
    IdGenerator,
    InvalidProviderResponseFailure,
    ModelGateway,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
    TokenUsage,
    TraceLogger,
    TransactionBoundary,
)
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.infrastructure.ollama.provider import OllamaModelProvider
from tests.fixtures.model_gateway import (
    DeterministicCancellationToken,
    MockCallRecord,
    MockCheckpoint,
    MockCheckpointController,
    MockGenerationStep,
    MockModelFixtureError,
    MockModelProvider,
    MockModelScript,
)
from tests.fixtures.ollama_transport import (
    ControlledCancellationToken,
    ControlledMonotonicClock,
    ScriptedExchange,
    ScriptedOllamaTransport,
    successful_script,
)
from tests.fixtures.ollama_live import (
    OllamaLiveOptIn,
    classify_ollama_live_opt_in,
    load_live_ollama_case,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "complete_configuration"
MOCK_GATEWAY_FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "mock_model_provider"
)
OLLAMA_ADAPTER_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "ollama_adapter"


@dataclass(frozen=True, slots=True)
class MockGatewayTestComposition:
    """One fresh test composition exposing inward and content-free observer seams."""

    system_ports: SystemPorts
    expected_request: GenerationRequest
    expected_success: CompletedGeneration
    _provider: MockModelProvider

    @property
    def gateway(self) -> ModelGateway:
        return self.system_ports.model_gateway

    @property
    def checkpoint_controller(self) -> MockCheckpointController:
        return self._provider.checkpoint_controller

    @property
    def call_snapshot(self) -> tuple[MockCallRecord, ...]:
        return self._provider.call_snapshot

    @staticmethod
    def new_cancellation_token(
        *,
        cancelled: bool = False,
    ) -> DeterministicCancellationToken:
        return DeterministicCancellationToken(cancelled=cancelled)


class MockGatewayCompositionFactory:
    """Construct the test adapter only at this outer test-composition boundary."""

    def __init__(self, document: dict[str, Any], fixture_version: str) -> None:
        self._document = document
        self._fixture_version = fixture_version

    def __call__(
        self,
        *,
        step_indices: tuple[int, ...] | None = None,
        schema_version: str | None = None,
    ) -> MockGatewayTestComposition:
        request = self._build_request()
        success = self._build_success()
        step_documents = tuple(self._document["steps"])
        selected_indices = (
            tuple(range(len(step_documents)))
            if step_indices is None
            else tuple(step_indices)
        )
        if any(
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < len(step_documents)
            for index in selected_indices
        ):
            raise MockModelFixtureError(
                "Mock gateway fixture step indices must name existing steps."
            )
        steps = tuple(
            self._build_step(step_documents[index], request, success)
            for index in selected_indices
        )
        script = MockModelScript(
            self._fixture_version if schema_version is None else schema_version,
            steps,
        )
        provider = MockModelProvider(script)
        unused_port = object()
        system_ports = SystemPorts(
            model_gateway=provider,
            clock=cast(Clock, unused_port),
            id_generator=cast(IdGenerator, unused_port),
            configuration_loader=cast(ConfigurationLoader, unused_port),
            trace_logger=cast(TraceLogger, unused_port),
            transactions=cast(TransactionBoundary, unused_port),
        )
        return MockGatewayTestComposition(
            system_ports,
            request,
            success,
            provider,
        )

    def _build_request(self) -> GenerationRequest:
        request = self._document["request"]
        settings = request["settings"]
        correlation = request["correlation"]
        return GenerationRequest(
            model_name=request["model_name"],
            rendered_prompt=request["rendered_prompt"],
            settings=GenerationSettings(
                settings["context_window_tokens"],
                settings["request_timeout_seconds"],
                Decimal(settings["temperature_decimal"]),
            ),
            processing_run_id=DomainId(correlation["processing_run_id"]),
            context_packet_id=DomainId(correlation["context_packet_id"]),
            model_request_id=DomainId(correlation["model_request_id"]),
            attempt_number=correlation["attempt_number"],
        )

    def _build_success(self) -> CompletedGeneration:
        success = self._document["success"]
        usage = success["token_usage"]
        return CompletedGeneration(
            response_text=success["response_text"],
            provider_metadata=success["provider_metadata"],
            elapsed=timedelta(microseconds=success["elapsed_microseconds"]),
            token_usage=(
                None
                if usage is None
                else TokenUsage(
                    usage["prompt_tokens"],
                    usage["generated_tokens"],
                    usage["total_tokens"],
                )
            ),
        )

    @staticmethod
    def _build_step(
        document: dict[str, Any],
        request: GenerationRequest,
        success: CompletedGeneration,
    ) -> MockGenerationStep:
        outcomes: dict[str, GenerationOutcome] = {
            "COMPLETED": success,
            "PROVIDER_UNAVAILABLE": ProviderUnavailableFailure(),
            "MODEL_NOT_FOUND": ModelNotFoundFailure(),
            "MODEL_TIMEOUT": ModelTimeoutFailure(),
            "INVALID_PROVIDER_RESPONSE": InvalidProviderResponseFailure(),
        }
        try:
            checkpoint = MockCheckpoint(document["checkpoint"])
            outcome = outcomes[document["terminal_outcome"]]
        except (KeyError, ValueError) as error:
            raise MockModelFixtureError(
                "Mock gateway fixture contains an unknown checkpoint or outcome."
            ) from error
        return MockGenerationStep(request, checkpoint, outcome)


@dataclass(frozen=True, slots=True)
class OllamaAdapterTestComposition:
    """One daemon-free construction of the real adapter and controlled transport."""

    system_ports: SystemPorts
    expected_request: GenerationRequest
    transport: ScriptedOllamaTransport
    clock: ControlledMonotonicClock

    @property
    def gateway(self) -> ModelGateway:
        return self.system_ports.model_gateway

    @staticmethod
    def new_cancellation_token(
        *,
        cancelled: bool = False,
    ) -> ControlledCancellationToken:
        return ControlledCancellationToken(cancelled=cancelled)


class OllamaAdapterCompositionFactory:
    """Own the sole daemon-free test construction boundary for the real adapter."""

    def __init__(self, document: dict[str, Any], fixture_version: str) -> None:
        self._document = document
        self.fixture_version = fixture_version

    @property
    def expected_request(self) -> GenerationRequest:
        return self._build_request()

    def successful_steps(
        self,
        request: GenerationRequest | None = None,
    ) -> tuple[ScriptedExchange, ...]:
        selected_request = self._build_request() if request is None else request
        return successful_script(self._document, selected_request)

    def __call__(
        self,
        *,
        steps: tuple[ScriptedExchange, ...] | None = None,
        request: GenerationRequest | None = None,
        clock: ControlledMonotonicClock | None = None,
    ) -> OllamaAdapterTestComposition:
        selected_request = self._build_request() if request is None else request
        selected_clock = ControlledMonotonicClock() if clock is None else clock
        selected_steps = (
            successful_script(self._document, selected_request)
            if steps is None
            else tuple(steps)
        )
        transport = ScriptedOllamaTransport(selected_steps, selected_clock)
        provider = OllamaModelProvider(
            self._document["endpoint"],
            self._document["model"],
            transport=transport,
            monotonic=selected_clock,
        )
        unused_port = object()
        system_ports = SystemPorts(
            model_gateway=provider,
            clock=cast(Clock, unused_port),
            id_generator=cast(IdGenerator, unused_port),
            configuration_loader=cast(ConfigurationLoader, unused_port),
            trace_logger=cast(TraceLogger, unused_port),
            transactions=cast(TransactionBoundary, unused_port),
        )
        return OllamaAdapterTestComposition(
            system_ports,
            selected_request,
            transport,
            selected_clock,
        )

    def _build_request(self) -> GenerationRequest:
        request = self._document["request"]
        settings = request["settings"]
        correlation = request["correlation"]
        return GenerationRequest(
            model_name=request["model_name"],
            rendered_prompt=request["rendered_prompt"],
            settings=GenerationSettings(
                settings["context_window_tokens"],
                settings["request_timeout_seconds"],
                Decimal(settings["temperature_decimal"]),
            ),
            processing_run_id=DomainId(correlation["processing_run_id"]),
            context_packet_id=DomainId(correlation["context_packet_id"]),
            model_request_id=DomainId(correlation["model_request_id"]),
            attempt_number=correlation["attempt_number"],
        )


@dataclass(frozen=True, slots=True)
class LiveOllamaAdapterComposition:
    """One optional live adapter call surface constructed after explicit opt-in."""

    gateway: ModelGateway
    request: GenerationRequest

    @staticmethod
    def new_cancellation_token() -> ControlledCancellationToken:
        return ControlledCancellationToken()


@pytest.fixture
def fixture_application_root(tmp_path: Path) -> Path:
    """Return a private application root containing the versioned YAML fixture."""

    application_root = tmp_path / "application-root"
    shutil.copytree(FIXTURE_ROOT, application_root)
    return application_root


@pytest.fixture
def mock_gateway_composition() -> MockGatewayCompositionFactory:
    """Return the sole fresh-construction boundary for deterministic mock gateways."""

    fixture_version = (
        MOCK_GATEWAY_FIXTURE_ROOT / "VERSION"
    ).read_text(encoding="utf-8").strip()
    document = yaml.safe_load(
        (MOCK_GATEWAY_FIXTURE_ROOT / "cases.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(document, dict):
        raise MockModelFixtureError("Mock gateway fixture document must be an object.")
    if document.get("schema_version") != fixture_version:
        raise MockModelFixtureError(
            "Mock gateway fixture VERSION and schema_version must match."
        )
    return MockGatewayCompositionFactory(document, fixture_version)


@pytest.fixture
def ollama_adapter_composition() -> OllamaAdapterCompositionFactory:
    """Return the designated daemon-free composition for the concrete adapter."""

    fixture_version = (
        OLLAMA_ADAPTER_FIXTURE_ROOT / "VERSION"
    ).read_text(encoding="utf-8").strip()
    document = yaml.safe_load(
        (OLLAMA_ADAPTER_FIXTURE_ROOT / "cases.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(document, dict):
        raise AssertionError("Ollama adapter fixture document must be an object.")
    if document.get("schema_version") != fixture_version:
        raise AssertionError(
            "Ollama adapter fixture VERSION and schema_version must match."
        )
    return OllamaAdapterCompositionFactory(document, fixture_version)


@pytest.fixture
def live_ollama_adapter(tmp_path: Path) -> LiveOllamaAdapterComposition:
    """Construct a normally configured live adapter only after exact opt-in."""

    opt_in = classify_ollama_live_opt_in(os.environ)
    if opt_in is OllamaLiveOptIn.ABSENT:
        pytest.skip("CONTEXT_FOR_AI_RUN_OLLAMA is absent; live Ollama was not run.")
    if opt_in is OllamaLiveOptIn.INVALID:
        pytest.fail("CONTEXT_FOR_AI_RUN_OLLAMA must be exactly 1 when present.")

    application_root = tmp_path / "ollama-live-application"
    shutil.copytree(FIXTURE_ROOT, application_root)
    live_case = load_live_ollama_case(application_root, os.environ)
    provider = OllamaModelProvider(live_case.base_url, live_case.model_name)
    return LiveOllamaAdapterComposition(provider, live_case.request)


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
