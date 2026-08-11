"""Daemon-free contract tests for the TASK-0018 acceptance harness."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
import yaml

from context_for_ai.application import (
    ProcessUserMessageRequest,
    ShellReadyResult,
    SucceededResult,
)
from context_for_ai.bootstrap import ProductionShellScopeFactory
from context_for_ai.context_engine import (
    DeterministicConstraintEngine,
    DeterministicContextRetriever,
    DeterministicInterpretationEngine,
)
from context_for_ai.context_engine.prompt_rendering import conservative_utf8_estimate
from context_for_ai.domain.entities import ConversationState, Message
from context_for_ai.domain.enums import (
    ConstraintResolutionStatus,
    ConstraintSourceKind,
    ConstraintType,
    IntentType,
    MessageRole,
    OutputType,
    QualifierKind,
    ValidationCheckId,
    ValidationOutcome,
    ValidationSeverity,
    ValidationStatus,
)
from context_for_ai.domain.ports.context import (
    ConstraintEvaluationRequest,
    InterpretationRequest,
    RetrievalRequest,
)
from context_for_ai.domain.ports.model_gateway import (
    CancellationToken,
    CompletedGeneration,
    GenerationOutcome,
    GenerationRequest,
    GenerationSettings,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore, canonical_json
from context_for_ai.infrastructure.configuration import (
    ConfigurationError,
    load_configuration,
)
from context_for_ai.infrastructure.database import (
    SQLiteConstraintRepository,
    SQLiteContextPacketRepository,
    SQLiteValidationRepository,
    apply_migrations,
    connect_database,
)
from context_for_ai.main import prepare_application_shell
import tests.evaluation.test_task_0018_local_ollama_smoke as live_acceptance
import tests.fixtures.at_016_acceptance as at_016
from tests.fixtures.at_016_acceptance import (
    EVIDENCE_TOP_LEVEL_KEYS,
    LIMITATIONS,
    MODEL_BASE_URL_VARIABLE,
    MODEL_NAME_VARIABLE,
    At016Evidence,
    At016EvidenceCollisionError,
    At016EvidenceLifecycleError,
    At016EvidenceValidationError,
    At016EvidenceWriteError,
    At016Failure,
    At016ModelEvidence,
    At016OsEvidence,
    At016Prerequisites,
    At016ProviderEvidence,
    canonical_evidence_bytes,
    evaluate_at_016_gate,
    evidence_filename,
    finalize_evidence,
    model_evidence,
    parse_evidence_bytes,
    project_transport_failure,
    provider_evidence,
    retain_first_failure,
    validate_evidence_document,
    validated_prerequisites,
    write_evidence,
)
from tests.fixtures.ollama_live import OllamaLiveOptIn


REPOSITORY_ROOT = Path(__file__).parents[2]
SOURCE_FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "complete_configuration"
AT_016_FIXTURE = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "at_016_local_ollama_smoke"
)
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
USER_TEXT = "Exactly answer CONTEXT_FOR_AI_SMOKE_OK."


def identifier(number: int) -> DomainId:
    return DomainId(f"68000000-0000-4000-8000-{number:012x}")


class FixedIds:
    def __init__(self, start: int = 100) -> None:
        self._next = start

    def new_id(self) -> DomainId:
        value = identifier(self._next)
        self._next += 1
        return value


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


class TraceSink:
    def emit(self, _: object) -> None:
        pass


class NoCancellation:
    def is_cancelled(self) -> bool:
        return False


class CancelledToken:
    def is_cancelled(self) -> bool:
        return True


class CapturingGateway:
    def __init__(
        self,
        preflight: Callable[[GenerationRequest], None] | None = None,
    ) -> None:
        self.requests: list[GenerationRequest] = []
        self._preflight = preflight

    def generate(
        self,
        request: GenerationRequest,
        cancellation_token: CancellationToken,
    ) -> CompletedGeneration:
        assert cancellation_token.is_cancelled() is False
        self.requests.append(request)
        if self._preflight is not None:
            self._preflight(request)
        return CompletedGeneration(
            "Answer context for AI smoke ok.",
            {"fixture": "at-016-daemon-free"},
            timedelta(microseconds=1),
            None,
        )


class ReturningGateway:
    def __init__(self, outcome: GenerationOutcome) -> None:
        self.outcome = outcome
        self.requests: list[GenerationRequest] = []

    def generate(
        self,
        request: GenerationRequest,
        cancellation_token: CancellationToken,
    ) -> GenerationOutcome:
        self.requests.append(request)
        return self.outcome


def generation_request() -> GenerationRequest:
    return GenerationRequest(
        model_name="local/smoke:latest",
        rendered_prompt="CONTEXT_FOR_AI_PROMPT/mvp-prompt-policy-v2\n@@CFA/END@@\n",
        settings=GenerationSettings(4096, 60, Decimal("0")),
        processing_run_id=identifier(300),
        context_packet_id=identifier(301),
        model_request_id=identifier(302),
        attempt_number=0,
    )


def read_yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_at_016_fixture_is_an_independent_exact_copy_with_closed_deltas() -> None:
    expected_files = {
        "VERSION",
        "config/app.yaml",
        "config/context.yaml",
        "config/logging.yaml",
        "config/memory.yaml",
        "config/models.yaml",
        "config/validation.yaml",
    }
    actual_files = {
        path.relative_to(AT_016_FIXTURE).as_posix()
        for path in AT_016_FIXTURE.rglob("*")
        if path.is_file()
    }

    assert actual_files == expected_files
    assert (AT_016_FIXTURE / "VERSION").read_bytes() == (
        b"at-016-local-ollama-smoke-v1\n"
    )
    assert (SOURCE_FIXTURE / "VERSION").read_bytes() == b"mvp-config-fixture-v2\n"

    for name in (
        "app.yaml",
        "context.yaml",
        "logging.yaml",
        "memory.yaml",
        "models.yaml",
        "validation.yaml",
    ):
        source = read_yaml(SOURCE_FIXTURE / "config" / name)
        expected = deepcopy(source)
        if name == "models.yaml":
            expected["model"]["name"] = "at-016-model-must-be-overridden"  # type: ignore[index]
        if name == "validation.yaml":
            expected["validation"]["max_revisions"] = 0  # type: ignore[index]
        assert read_yaml(AT_016_FIXTURE / "config" / name) == expected

        source_bytes = (SOURCE_FIXTURE / "config" / name).read_bytes()
        expected_bytes = source_bytes
        if name == "models.yaml":
            expected_bytes = source_bytes.replace(
                b"  name: fixture-model\n",
                b"  name: at-016-model-must-be-overridden\n",
            )
        if name == "validation.yaml":
            expected_bytes = source_bytes.replace(
                b"  max_revisions: 2\n",
                b"  max_revisions: 0\n",
            )
        assert (AT_016_FIXTURE / "config" / name).read_bytes() == expected_bytes

    configuration = load_configuration(application_root=AT_016_FIXTURE, environ={})
    assert configuration.model.base_url == "http://127.0.0.1:11434"
    assert configuration.model.name == "at-016-model-must-be-overridden:latest"
    assert configuration.model.context_window_tokens == 4096
    assert configuration.model.request_timeout_seconds == 60
    assert configuration.model.temperature == Decimal("0.0")
    assert configuration.context.maximum_prompt_tokens == 2048
    assert configuration.context.reserved_response_tokens == 512
    assert configuration.validation.max_revisions == 0


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://127.0.0.1:11434",
        "http://localhost:11434",
        "http://192.0.2.1:11434",
    ),
)
def test_at_016_optional_endpoint_uses_normal_configuration_validation(
    endpoint: str,
) -> None:
    with pytest.raises(ConfigurationError) as captured:
        load_configuration(
            application_root=AT_016_FIXTURE,
            environ={"CONTEXT_FOR_AI__MODEL__BASE_URL": endpoint},
        )

    assert captured.value.file_name == "models.yaml"
    assert captured.value.key == "model.base_url"


def test_at_016_message_has_exact_daemon_free_interpretation_and_constraints() -> None:
    configuration = load_configuration(application_root=AT_016_FIXTURE, environ={})
    state = ConversationState(identifier(1), None, None, None, None, (), 0, NOW)
    message = Message(identifier(2), state.conversation_id, MessageRole.USER, USER_TEXT, NOW, 0)
    decision = DeterministicInterpretationEngine(configuration.context).interpret(  # type: ignore[arg-type]
        InterpretationRequest(identifier(3), message, state, NOW)
    )
    interpretation = decision.interpretation

    assert len(decision.intent_candidates) == 1
    assert decision.intent_candidates[0].evidence.rule_id == "answer"
    assert interpretation.intent is IntentType.ANSWER
    assert interpretation.intent_rule_id == "answer"
    assert interpretation.expected_output_type is OutputType.TEXT_ANSWER
    assert interpretation.confidence == UnitScore("1")
    assert len(interpretation.qualifiers) == 1
    qualifier = interpretation.qualifiers[0]
    assert qualifier.kind is QualifierKind.EXACTLY
    assert qualifier.rule_id == "exactly"
    assert dict(qualifier.captures) == {
        "target": "answer context for ai smoke ok",
        "action": "answer",
        "object": "context for ai smoke ok",
    }
    assert decision.reference_mentions == ()
    assert decision.proposed_topic_label is None
    assert decision.proposed_task_title is None
    assert decision.clarification_reason is None

    committed_state = replace(
        state,
        expected_output_type=OutputType.TEXT_ANSWER,
        version=1,
    )
    constraint_decision = DeterministicConstraintEngine(
        configuration.context,  # type: ignore[arg-type]
        FixedIds(),
    ).evaluate(
        ConstraintEvaluationRequest(
            message,
            committed_state,
            decision,
            (),
            (),
            (),
            None,
            NOW,
        )
    )
    assert len(constraint_decision.constraints) == 2
    required, forbidden = constraint_decision.constraints
    assert (
        required.constraint_type,
        required.source_kind,
        required.normalized_rule,
        required.priority,
        required.resolution_status,
    ) == (
        ConstraintType.REQUIRED,
        ConstraintSourceKind.CURRENT_MESSAGE,
        "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",
        1000,
        ConstraintResolutionStatus.ACTIVE,
    )
    assert (
        forbidden.constraint_type,
        forbidden.source_kind,
        forbidden.normalized_rule,
        forbidden.priority,
        forbidden.resolution_status,
    ) == (
        ConstraintType.FORBIDDEN,
        ConstraintSourceKind.DERIVED_OUTPUT_POLICY,
        "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
        1000,
        ConstraintResolutionStatus.ACTIVE,
    )
    assert constraint_decision.conflict_groups == ()
    assert constraint_decision.response_policy.expected_output_type is OutputType.TEXT_ANSWER
    assert constraint_decision.response_policy.text_only is True
    assert constraint_decision.response_policy.actions_allowed is False

    retrieval = DeterministicContextRetriever(FixedIds()).retrieve(
        RetrievalRequest(
            identifier(200),
            identifier(3),
            message.id,
            state.conversation_id,
            None,
            None,
            USER_TEXT,
            (),
            UnitScore(str(configuration.context.minimum_relevance_score)),
            configuration.context.retrieved_memory_limit,
            NOW,
        )
    )
    assert retrieval.selected == ()
    assert retrieval.excluded == ()
    assert retrieval.confidence is None


def test_at_016_daemon_free_pipeline_uses_v2_semantics_and_production_evidence(
    tmp_path: Path,
) -> None:
    configuration = load_configuration(application_root=AT_016_FIXTURE, environ={})
    database_path = apply_migrations(tmp_path / "at-016-daemon-free.sqlite3")
    factory = ProductionShellScopeFactory(
        configuration=configuration,
        database_path=database_path,
        trace_logger=TraceSink(),  # type: ignore[arg-type]
        clock=FixedClock(),
        id_generator=FixedIds(),
    )
    gateway = CapturingGateway(
        lambda request: live_acceptance._assert_pre_provider_database(
            database_path,
            configuration,
            request,
        )
    )
    factory._model_gateway = gateway  # type: ignore[attr-defined]
    preparation = prepare_application_shell(factory)
    assert isinstance(preparation, ShellReadyResult)

    scope = factory.open_foreground_scope()
    try:
        result = scope.process_user_message.execute(
            ProcessUserMessageRequest(
                preparation.conversation_id,
                USER_TEXT,
                identifier(999),
                None,
            ),
            NoCancellation(),
        )
    finally:
        scope.close()

    assert isinstance(result, SucceededResult)
    assert result.assistant_text == "Answer context for AI smoke ok."
    assert "CONTEXT_FOR_AI_SMOKE_OK" not in result.assistant_text
    assert len(gateway.requests) == 1
    prompt = gateway.requests[0].rendered_prompt
    assert prompt.startswith("CONTEXT_FOR_AI_PROMPT/mvp-prompt-policy-v2\n")
    assert conservative_utf8_estimate(prompt) == 1362

    validation_semantics = json.loads(
        prompt.split(
            "@@CFA/VALIDATION_SEMANTICS/TRUSTED_INSTRUCTIONS@@\n",
            1,
        )[1].split("\n", 1)[0]
    )
    assert validation_semantics == {
        "action_markers": {
            "forbidden_literals": [
                "TOOL_CALL:",
                "ACTION_EXECUTED:",
                "IMAGE_RESULT:",
            ],
            "instruction": (
                "Do not include any literal listed in forbidden_literals; matching "
                "uses Unicode NFC and case-folding without punctuation or whitespace "
                "rewriting."
            ),
        },
        "output_shape": {
            "instruction": "Produce at least one non-empty normalized word of text.",
            "rule_id": "text-answer",
            "shape": "NON_EMPTY_TEXT",
        },
        "topic": None,
    }

    trusted_constraints = json.loads(
        prompt.split(
            "@@CFA/CONSTRAINTS/TRUSTED_INSTRUCTIONS@@\n",
            1,
        )[1].split("\n", 1)[0]
    )

    connection = connect_database(database_path)
    try:
        packet = SQLiteContextPacketRepository(connection).get_for_run(
            result.processing_run_id
        )
        constraints = SQLiteConstraintRepository(connection).list_for_run(
            result.processing_run_id
        )
        persisted_validation = SQLiteValidationRepository(connection).get(
            result.latest_validation_result.id
        )
    finally:
        connection.close()

    assert packet is not None
    assert packet.packet.prompt_policy_version == "mvp-prompt-policy-v2"
    assert packet.packet.packet_json["rendering"]["prompt_policy_version"] == (
        "mvp-prompt-policy-v2"
    )
    assert (
        packet.packet.packet_json["rendering"]["mandatory_estimated_tokens"]
        == 1362
    )
    assert packet.packet.packet_json["rendering"]["estimated_prompt_tokens"] == 1362

    required_constraint = next(
        item
        for item in constraints
        if item.constraint_type is ConstraintType.REQUIRED
        and item.normalized_rule
        == "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK"
    )
    required_projection = next(
        item
        for item in trusted_constraints
        if item["normalized_rule"]
        == "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK"
    )
    assert required_projection == {
        "condition": None,
        "id": str(required_constraint.id),
        "normalized_rule": "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",
        "priority": 1000,
        "scope": "CURRENT_RESPONSE",
        "semantic_instruction": (
            'Include the complete consecutive phrase "answer context for ai smoke ok" '
            "in one sentence; do not use a synonym or approximate substitution for "
            "that phrase."
        ),
        "type": "REQUIRED",
        "underlying_type": None,
    }

    validation = result.latest_validation_result
    assert validation.status is ValidationStatus.PASSED
    assert persisted_validation == validation
    required_evidence = tuple(
        item
        for item in validation.evidence
        if item.check_id is ValidationCheckId.REQUIRED_CONSTRAINT
    )
    assert len(required_evidence) == 1
    evidence = required_evidence[0]
    assert evidence.constraint_id == required_constraint.id
    assert evidence.rule_id is None
    assert evidence.severity is ValidationSeverity.INFO
    assert evidence.outcome is ValidationOutcome.PASSED
    assert dict(evidence.normalized_input) == {
        "candidate_token_count": 6,
        "output_shape": None,
        "output_type": None,
        "predicate": "MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK",
        "sentence_count": 1,
        "topic_terms": (),
    }
    assert evidence.missing_predicate is None
    assert evidence.violation_code is None
    assert evidence.warning_code is None
    assert evidence.matches
    assert all(match.sentence_ordinal is not None for match in evidence.matches)
    live_acceptance._assert_required_constraint_evidence(
        json.loads(
            canonical_json(
                tuple(item.to_json_object() for item in validation.evidence)
            )
        ),
        constraint_id=str(required_constraint.id),
    )


def test_live_preflight_estimate_tracks_actual_runtime_timestamp_bytes(
    tmp_path: Path,
) -> None:
    configuration = load_configuration(application_root=AT_016_FIXTURE, environ={})

    def execute_at(observed_at: datetime, database_name: str) -> tuple[str, int]:
        database_path = apply_migrations(tmp_path / database_name)
        factory = ProductionShellScopeFactory(
            configuration=configuration,
            database_path=database_path,
            trace_logger=TraceSink(),  # type: ignore[arg-type]
            clock=FixedClock(observed_at),
            id_generator=FixedIds(),
        )
        gateway = CapturingGateway(
            lambda request: live_acceptance._assert_pre_provider_database(
                database_path,
                configuration,
                request,
            )
        )
        factory._model_gateway = gateway  # type: ignore[attr-defined]
        preparation = prepare_application_shell(factory)
        assert isinstance(preparation, ShellReadyResult)

        scope = factory.open_foreground_scope()
        try:
            result = scope.process_user_message.execute(
                ProcessUserMessageRequest(
                    preparation.conversation_id,
                    USER_TEXT,
                    identifier(999),
                    None,
                ),
                NoCancellation(),
            )
        finally:
            scope.close()

        assert isinstance(result, SucceededResult)
        assert len(gateway.requests) == 1
        prompt = gateway.requests[0].rendered_prompt
        prompt_estimate = conservative_utf8_estimate(prompt)
        connection = connect_database(database_path)
        try:
            packet = SQLiteContextPacketRepository(connection).get_for_run(
                result.processing_run_id
            )
        finally:
            connection.close()
        assert packet is not None
        rendering = packet.packet.packet_json["rendering"]
        assert rendering["mandatory_estimated_tokens"] == prompt_estimate
        assert rendering["estimated_prompt_tokens"] == prompt_estimate
        return prompt, prompt_estimate

    fixed_prompt, fixed_estimate = execute_at(NOW, "fixed-clock.sqlite3")
    runtime_at = NOW.replace(microsecond=123456)
    runtime_prompt, runtime_estimate = execute_at(
        runtime_at,
        "runtime-clock.sqlite3",
    )

    assert runtime_at.isoformat().replace("+00:00", "Z") in runtime_prompt
    assert len(runtime_prompt.encode("utf-8")) > len(fixed_prompt.encode("utf-8"))
    assert runtime_estimate != fixed_estimate


def test_impossible_passed_report_uses_existing_unexpected_result_failure() -> None:
    with pytest.raises(live_acceptance._LiveCheckFailure) as captured:
        live_acceptance._assert_required_constraint_evidence(
            [],
            constraint_id=str(identifier(1)),
        )

    assert captured.value.failure == At016Failure(
        "ACCEPTANCE",
        "UNEXPECTED_RESULT",
    )


def passed_prerequisites() -> At016Prerequisites:
    return validated_prerequisites(
        default_non_live_suite="PASSED",
        at_001_through_at_015="PASSED",
    )


def passed_evidence(
    *,
    recorded_at: str = "2026-08-10T12:34:56.123456Z",
) -> At016Evidence:
    return At016Evidence(
        configuration_fingerprint="a" * 64,
        failure=None,
        gateway_elapsed_microseconds=1_234_567,
        model=At016ModelEvidence("local/smoke:latest", "latest"),
        os=At016OsEvidence("x86_64", "6.18-test", "Linux"),
        prerequisites=passed_prerequisites(),
        provider=At016ProviderEvidence("env", "0.16.2-é"),
        recorded_at_utc=recorded_at,
    )


def failed_evidence() -> At016Evidence:
    return At016Evidence(
        configuration_fingerprint=None,
        failure=At016Failure("CONFIGURATION", "MODEL_NAME_REQUIRED"),
        gateway_elapsed_microseconds=None,
        model=None,
        os=At016OsEvidence("x86_64", "6.18-test", "Linux"),
        prerequisites=passed_prerequisites(),
        provider=None,
        recorded_at_utc="2026-08-10T12:34:56.123456Z",
    )


@pytest.mark.parametrize(
    "environment",
    (
        {},
        {MODEL_NAME_VARIABLE: "installed-model"},
        {MODEL_BASE_URL_VARIABLE: "http://127.0.0.1:11434"},
    ),
)
def test_absent_opt_in_is_the_only_skip_and_starts_no_artifact_lifecycle(
    environment: dict[str, str],
) -> None:
    gate = evaluate_at_016_gate(environment)

    assert gate.opt_in is OllamaLiveOptIn.ABSENT
    assert gate.artifact_lifecycle_started is False
    assert dict(gate.loader_environment) == {}
    assert gate.failure is None


@pytest.mark.parametrize("value", ("", "true", "01", " 1", "0"))
def test_present_non_exact_opt_in_is_invalid_without_artifact_lifecycle(
    value: str,
) -> None:
    gate = evaluate_at_016_gate(
        {
            "CONTEXT_FOR_AI_RUN_OLLAMA": value,
            MODEL_NAME_VARIABLE: "installed-model",
        }
    )

    assert gate.opt_in is OllamaLiveOptIn.INVALID
    assert gate.artifact_lifecycle_started is False
    assert dict(gate.loader_environment) == {}
    assert gate.failure is None


@pytest.mark.parametrize("model_value", (None, ""))
def test_exact_opt_in_starts_lifecycle_and_missing_or_empty_model_is_failed(
    model_value: str | None,
) -> None:
    environment = {"CONTEXT_FOR_AI_RUN_OLLAMA": "1"}
    if model_value is not None:
        environment[MODEL_NAME_VARIABLE] = model_value

    gate = evaluate_at_016_gate(environment)

    assert gate.opt_in is OllamaLiveOptIn.ENABLED
    assert gate.artifact_lifecycle_started is True
    assert gate.failure == At016Failure("CONFIGURATION", "MODEL_NAME_REQUIRED")


def test_exact_opt_in_hands_only_normal_model_overrides_to_configuration() -> None:
    environment = {
        "CONTEXT_FOR_AI_RUN_OLLAMA": "1",
        MODEL_NAME_VARIABLE: "installed-model",
        MODEL_BASE_URL_VARIABLE: "http://127.0.0.1:11555",
        "UNRELATED_VALUE": "must-not-cross",
    }

    gate = evaluate_at_016_gate(environment)

    assert gate.opt_in is OllamaLiveOptIn.ENABLED
    assert gate.artifact_lifecycle_started is True
    assert gate.failure is None
    assert dict(gate.loader_environment) == {
        MODEL_NAME_VARIABLE: "installed-model",
        MODEL_BASE_URL_VARIABLE: "http://127.0.0.1:11555",
    }
    loaded = load_configuration(
        application_root=AT_016_FIXTURE,
        environ=gate.loader_environment,
    )
    assert loaded.model.name == "installed-model:latest"
    assert loaded.model.base_url == "http://127.0.0.1:11555"


def test_whitespace_model_reaches_normal_configuration_failure() -> None:
    gate = evaluate_at_016_gate(
        {
            "CONTEXT_FOR_AI_RUN_OLLAMA": "1",
            MODEL_NAME_VARIABLE: " ",
        }
    )

    assert gate.artifact_lifecycle_started is True
    assert gate.failure is None
    with pytest.raises(ConfigurationError) as captured:
        load_configuration(
            application_root=AT_016_FIXTURE,
            environ=gate.loader_environment,
        )
    assert captured.value.file_name == "environment"
    assert captured.value.key == MODEL_NAME_VARIABLE


@pytest.mark.parametrize(
    "environment",
    ({}, {"CONTEXT_FOR_AI_RUN_OLLAMA": "invalid"}),
)
def test_pre_lifecycle_gate_cannot_create_an_evidence_directory(
    tmp_path: Path,
    environment: dict[str, str],
) -> None:
    output = tmp_path / "evidence"
    gate = evaluate_at_016_gate(environment)

    with pytest.raises(At016EvidenceLifecycleError):
        write_evidence(output, failed_evidence(), gate=gate)

    assert not output.exists()


def test_prerequisites_admit_only_the_two_closed_passed_statuses() -> None:
    assert passed_prerequisites().to_document() == {
        "at_001_through_at_015": "PASSED",
        "default_non_live_suite": "PASSED",
    }
    with pytest.raises(At016EvidenceValidationError):
        validated_prerequisites(
            default_non_live_suite="FAILED",
            at_001_through_at_015="PASSED",
        )


def test_pre_provider_harness_failure_is_not_mapped_to_model_cancelled() -> None:
    recorder = live_acceptance._Recorder()
    delegate = ReturningGateway(ModelCancelledFailure())

    def fail_preflight(_: GenerationRequest) -> None:
        raise live_acceptance._LiveCheckFailure(live_acceptance.LINEAGE_FAILURE)

    observed = live_acceptance._ObservedGateway(
        delegate,
        recorder,
        fail_preflight,
    )

    with pytest.raises(live_acceptance._LiveCheckFailure) as captured:
        observed.generate(generation_request(), NoCancellation())

    assert captured.value.failure == live_acceptance.LINEAGE_FAILURE
    assert recorder.first_failure == live_acceptance.UNEXPECTED_FAILURE
    assert recorder.outcomes == []
    assert delegate.requests == []
    assert live_acceptance._failure_for_result(None, recorder) == (
        live_acceptance.UNEXPECTED_FAILURE
    )


def test_observed_gateway_preserves_real_provider_cancellation() -> None:
    recorder = live_acceptance._Recorder()
    outcome = ModelCancelledFailure()
    delegate = ReturningGateway(outcome)
    observed = live_acceptance._ObservedGateway(
        delegate,
        recorder,
        lambda _: None,
    )
    request = generation_request()

    assert observed.generate(request, CancelledToken()) == outcome
    assert delegate.requests == [request]
    assert recorder.first_failure is None
    assert recorder.outcomes == [outcome]
    assert live_acceptance._failure_for_result(None, recorder) == At016Failure(
        "TRANSPORT",
        "MODEL_CANCELLED",
    )


@pytest.mark.parametrize(
    ("outcome", "code"),
    (
        (ModelCancelledFailure(), "MODEL_CANCELLED"),
        (ModelTimeoutFailure(), "MODEL_TIMEOUT"),
        (ModelNotFoundFailure(), "MODEL_NOT_FOUND"),
        (InvalidProviderResponseFailure(), "INVALID_PROVIDER_RESPONSE"),
        (ProviderUnavailableFailure(), "PROVIDER_UNAVAILABLE"),
    ),
)
def test_gateway_failures_have_exact_safe_transport_projections(
    outcome: object,
    code: str,
) -> None:
    assert project_transport_failure(outcome) == At016Failure("TRANSPORT", code)


def test_unknown_or_mismatched_safe_failure_values_are_rejected() -> None:
    with pytest.raises(At016EvidenceValidationError):
        project_transport_failure(object())
    with pytest.raises(At016EvidenceValidationError):
        At016Failure("TRANSPORT", "STARTUP_FAILED")


def test_first_safe_failure_is_retained() -> None:
    first = At016Failure("TRANSPORT", "MODEL_TIMEOUT")
    later = At016Failure("EVIDENCE", "OS_METADATA_UNAVAILABLE")

    assert retain_first_failure(None, first) is first
    assert retain_first_failure(first, later) is first


def test_model_and_provider_evidence_are_narrow_normalized_projections() -> None:
    assert model_evidence("local/smoke") == At016ModelEvidence(
        "local/smoke:latest",
        "latest",
    )
    metadata = {
        "provider": "ollama",
        "provider_version": "0.16.2",
        "model_identity": "local/smoke:latest",
        "model_tag": "latest",
        "cloud_disable_source": "both",
        "done_reason": "stop",
        "total_duration_ns": 1,
    }
    assert provider_evidence(metadata) == At016ProviderEvidence(
        "both",
        "0.16.2",
    )
    with pytest.raises(At016EvidenceValidationError):
        provider_evidence({**metadata, "cloud_disable_source": "none"})


def test_evidence_has_exact_closed_schema_and_pass_failure_relations() -> None:
    passed = passed_evidence().to_document()
    failed = failed_evidence().to_document()

    assert set(passed) == EVIDENCE_TOP_LEVEL_KEYS
    assert passed["limitations"] == list(LIMITATIONS)
    assert passed["result"] == "PASSED"
    assert passed["failure"] is None
    assert failed["result"] == "FAILED"
    assert failed["failure"] == {
        "code": "MODEL_NAME_REQUIRED",
        "stage": "CONFIGURATION",
    }
    validate_evidence_document(passed)
    validate_evidence_document(failed)

    invalid = dict(passed)
    invalid["gateway_elapsed_microseconds"] = None
    with pytest.raises(At016EvidenceValidationError):
        validate_evidence_document(invalid)


def test_canonical_evidence_bytes_are_sorted_compact_unicode_and_one_lf() -> None:
    evidence = passed_evidence()
    data = canonical_evidence_bytes(evidence)
    text = data.decode("utf-8")

    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    assert "é" in text and "\\u00e9" not in text
    assert ": " not in text and ", " not in text
    assert text.startswith('{"acceptance_id":"AT-016",')
    assert text.endswith('"schema_version":"at-016-evidence-v1"}\n')
    assert parse_evidence_bytes(data) == evidence.to_document()


def test_parser_rejects_duplicates_noncanonical_bytes_and_missing_final_lf() -> None:
    canonical = canonical_evidence_bytes(passed_evidence())
    duplicated = canonical.replace(
        b'{"acceptance_id":"AT-016",',
        b'{"acceptance_id":"AT-016","acceptance_id":"AT-016",',
        1,
    )
    expanded = json.dumps(
        passed_evidence().to_document(),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8") + b"\n"

    with pytest.raises(At016EvidenceValidationError, match="duplicate"):
        parse_evidence_bytes(duplicated)
    with pytest.raises(At016EvidenceValidationError, match="canonical"):
        parse_evidence_bytes(expanded)
    with pytest.raises(At016EvidenceValidationError, match="final LF"):
        parse_evidence_bytes(canonical[:-1])


@pytest.mark.parametrize(
    "private_value",
    (
        USER_TEXT,
        "CONTEXT_FOR_AI_SMOKE_OK",
        "private rendered prompt",
        "private candidate",
        "http://127.0.0.1:11434",
        "/home/operator/private",
        "operator-hostname",
    ),
)
def test_redaction_rejects_runtime_private_or_sensitive_values(
    private_value: str,
) -> None:
    document = passed_evidence().to_document()
    provider = dict(document["provider"])  # type: ignore[arg-type]
    provider["version"] = private_value
    document["provider"] = provider

    with pytest.raises(At016EvidenceValidationError, match="prohibited"):
        validate_evidence_document(
            document,
            prohibited_values=(private_value,),
        )


def test_os_unavailability_selects_only_the_first_safe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(at_016.platform, "system", lambda: "")
    monkeypatch.setattr(at_016.platform, "release", lambda: "release")
    monkeypatch.setattr(at_016.platform, "machine", lambda: "machine")

    selected = finalize_evidence(
        recorded_at=NOW,
        prerequisites=passed_prerequisites(),
    )
    earlier = finalize_evidence(
        recorded_at=NOW,
        prerequisites=passed_prerequisites(),
        failure=At016Failure("STARTUP", "STARTUP_FAILED"),
    )

    assert selected.os is None
    assert selected.failure == At016Failure(
        "EVIDENCE",
        "OS_METADATA_UNAVAILABLE",
    )
    assert earlier.os is None
    assert earlier.failure == At016Failure("STARTUP", "STARTUP_FAILED")


def test_os_observation_error_is_projected_without_retaining_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_system() -> str:
        raise OSError("private platform detail")

    monkeypatch.setattr(at_016.platform, "system", fail_system)

    evidence = finalize_evidence(
        recorded_at=NOW,
        prerequisites=passed_prerequisites(),
    )

    assert evidence.os is None
    assert evidence.failure == At016Failure(
        "EVIDENCE",
        "OS_METADATA_UNAVAILABLE",
    )


def test_timestamp_deterministically_owns_the_evidence_filename() -> None:
    assert evidence_filename("2026-08-08T12:34:56.123456Z") == (
        "at-016-20260808T123456123456Z.json"
    )


def enabled_gate() -> at_016.At016Gate:
    return evaluate_at_016_gate(
        {
            "CONTEXT_FOR_AI_RUN_OLLAMA": "1",
            MODEL_NAME_VARIABLE: "local/smoke:latest",
        }
    )


def test_writer_atomically_publishes_rereads_and_revalidates_one_artifact(
    tmp_path: Path,
) -> None:
    output = tmp_path / "acceptance" / "at-016"
    evidence = passed_evidence()

    artifact = write_evidence(output, evidence, gate=enabled_gate())

    assert artifact.name == "at-016-20260810T123456123456Z.json"
    assert tuple(output.glob("*.json")) == (artifact,)
    assert tuple(output.glob("*.tmp")) == ()
    assert artifact.read_bytes() == canonical_evidence_bytes(evidence)
    assert parse_evidence_bytes(artifact.read_bytes()) == evidence.to_document()


def test_writer_collision_fails_without_overwrite_or_append(tmp_path: Path) -> None:
    output = tmp_path / "acceptance" / "at-016"
    evidence = passed_evidence()
    artifact = write_evidence(output, evidence, gate=enabled_gate())
    original = artifact.read_bytes()

    with pytest.raises(At016EvidenceCollisionError) as captured:
        write_evidence(output, evidence, gate=enabled_gate())

    assert captured.value.code == "EVIDENCE_WRITE_FAILED"
    assert artifact.read_bytes() == original
    assert tuple(output.iterdir()) == (artifact,)


def test_repeated_writer_execution_uses_distinct_timestamp_owned_files(
    tmp_path: Path,
) -> None:
    output = tmp_path / "acceptance" / "at-016"
    first = write_evidence(output, passed_evidence(), gate=enabled_gate())
    second = write_evidence(
        output,
        passed_evidence(recorded_at="2026-08-10T12:34:56.123457Z"),
        gate=enabled_gate(),
    )

    assert first != second
    assert {path.name for path in output.iterdir()} == {first.name, second.name}


def test_writer_failure_has_only_safe_report_code_and_no_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "acceptance" / "at-016"

    def fail_publish(_: Path, __: Path) -> None:
        raise OSError("private injected writer detail")

    monkeypatch.setattr(at_016, "_native_rename_no_replace", fail_publish)

    with pytest.raises(At016EvidenceWriteError) as captured:
        write_evidence(output, passed_evidence(), gate=enabled_gate())

    assert str(captured.value) == "EVIDENCE_WRITE_FAILED"
    assert tuple(output.iterdir()) == ()


def test_writer_wraps_schema_or_redaction_failure_without_creating_artifact(
    tmp_path: Path,
) -> None:
    output = tmp_path / "acceptance" / "at-016"
    evidence = passed_evidence()

    with pytest.raises(At016EvidenceWriteError) as captured:
        write_evidence(
            output,
            evidence,
            gate=enabled_gate(),
            prohibited_values=(evidence.provider.version,),  # type: ignore[union-attr]
        )

    assert str(captured.value) == "EVIDENCE_WRITE_FAILED"
    assert not output.exists()
