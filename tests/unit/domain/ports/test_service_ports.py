"""Contract tests for non-repository inward ports."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
from typing import Protocol, get_args, get_type_hints

import pytest

import context_for_ai.domain.ports as public_ports
from context_for_ai.domain.lifecycle import ClarificationRequest, ValidationResult
from context_for_ai.domain.decisions import (
    ConstraintDecision,
    CorrectionEnvelope,
    InterpretationDecision,
    ReferenceCandidateEvidence,
    ReferenceDecision,
    ReferenceMention,
    ReferenceOutcome,
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.entities import ConversationState, Entity, Memory, Message
from context_for_ai.domain.enums import (
    EntityType,
    FailureCode,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    OutputType,
    ProcessingRunStatus,
    ReferenceRankReason,
    ReferenceStatus,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports import (
    CancellationToken,
    ClarificationBuildRequest,
    ClarificationBuilder,
    Clock,
    CompletedGeneration,
    ConfigurationLoader,
    ConfigurationSnapshot,
    ContextPacketBuilder,
    ContextPacketBuildRequest,
    ContextPacketBuildResult,
    ConstraintEngine,
    ConstraintEvaluationRequest,
    ContextRetriever,
    CorrectionController,
    CorrectionDecision,
    CorrectionExhausted,
    CorrectionPlanRequest,
    FailedCandidateLineage,
    GenerationFailure,
    GenerationOutcome,
    GenerationRequest,
    GenerationSettings,
    IdGenerator,
    InterpretationEngine,
    InterpretationRequest,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelGateway,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    OutputShapeRule,
    PromptRenderer,
    PromptRenderOutcome,
    PromptRenderRequest,
    ProviderUnavailableFailure,
    ResponseValidator,
    RetrievalDecision,
    RetrievalRequest,
    TokenUsage,
    TraceEvent,
    TraceLogger,
    TransactionBoundary,
    ValidationConfigurationSnapshot,
    ValidationRequest,
)
from context_for_ai.domain.ports.context import (
    ReferenceMentionExtractionRequest,
    ReferenceMentionExtractor,
    ReferenceResolutionRequest,
    ReferenceResolver,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
SELECTED_REASONS = (
    "project_match=0",
    "topic_match=0",
    "keyword_jaccard=0.5",
    "recency=1",
    "importance=0.5",
    "scope_match=0.6",
    "correction_match=0",
)


def identifier(number: int) -> DomainId:
    return DomainId(f"20000000-0000-4000-8000-{number:012d}")


SERVICE_PROTOCOLS = (
    CancellationToken,
    ClarificationBuilder,
    Clock,
    ConfigurationLoader,
    ConstraintEngine,
    ContextRetriever,
    ContextPacketBuilder,
    CorrectionController,
    IdGenerator,
    InterpretationEngine,
    ModelGateway,
    PromptRenderer,
    ReferenceMentionExtractor,
    ReferenceResolver,
    ResponseValidator,
    TraceLogger,
    TransactionBoundary,
)


def test_all_service_contracts_are_structural_protocols() -> None:
    for service in SERVICE_PROTOCOLS:
        assert issubclass(service, Protocol)
        assert service._is_protocol is True


def test_model_gateway_accepts_cancellation_and_returns_exhaustive_outcome() -> None:
    hints = get_type_hints(ModelGateway.generate)

    assert hints == {
        "request": GenerationRequest,
        "cancellation_token": CancellationToken,
        "return": GenerationOutcome,
    }
    assert get_args(GenerationFailure.__value__) == (
        ProviderUnavailableFailure,
        ModelNotFoundFailure,
        ModelTimeoutFailure,
        ModelCancelledFailure,
        InvalidProviderResponseFailure,
    )
    assert get_args(GenerationOutcome.__value__) == (
        CompletedGeneration,
        GenerationFailure,
    )
    assert not hasattr(ModelGateway, "stream")
    assert not hasattr(ModelGateway, "retry")
    assert not hasattr(ModelGateway, "partial")


@pytest.mark.parametrize(
    ("context_window_tokens", "request_timeout_seconds", "temperature"),
    (
        (1024, 1, Decimal("0")),
        (4096, 60, Decimal("0.125")),
        (32768, 300, Decimal("2")),
    ),
)
def test_generation_settings_accept_exact_authoritative_boundaries(
    context_window_tokens: int,
    request_timeout_seconds: int,
    temperature: Decimal,
) -> None:
    settings = GenerationSettings(
        context_window_tokens,
        request_timeout_seconds,
        temperature,
    )

    assert settings.context_window_tokens == context_window_tokens
    assert settings.request_timeout_seconds == request_timeout_seconds
    assert settings.temperature == temperature


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("context_window_tokens", 1023),
        ("context_window_tokens", True),
        ("context_window_tokens", 1024.0),
        ("request_timeout_seconds", 0),
        ("request_timeout_seconds", 301),
        ("request_timeout_seconds", False),
        ("request_timeout_seconds", 1.0),
        ("temperature", 0),
        ("temperature", 0.0),
        ("temperature", Decimal("NaN")),
        ("temperature", Decimal("Infinity")),
        ("temperature", Decimal("-0.001")),
        ("temperature", Decimal("2.001")),
    ),
)
def test_generation_settings_reject_invalid_types_and_ranges(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "context_window_tokens": 4096,
        "request_timeout_seconds": 60,
        "temperature": Decimal("0"),
    }
    values[field_name] = invalid_value

    with pytest.raises(LifecycleInvariantError):
        GenerationSettings(**values)  # type: ignore[arg-type]


def generation_request(*, attempt_number: int = 0) -> GenerationRequest:
    return GenerationRequest(
        model_name="fixture-model",
        rendered_prompt=" \nExact Unicode: café 😀\r\n ",
        settings=GenerationSettings(4096, 60, Decimal("0")),
        processing_run_id=identifier(801),
        context_packet_id=identifier(802),
        model_request_id=identifier(803),
        attempt_number=attempt_number,
    )


def test_generation_request_preserves_exact_prompt_and_correlation_values() -> None:
    request = generation_request(attempt_number=2)

    assert request.rendered_prompt.encode("utf-8") == (
        " \nExact Unicode: café 😀\r\n ".encode("utf-8")
    )
    assert request.processing_run_id == identifier(801)
    assert request.context_packet_id == identifier(802)
    assert request.model_request_id == identifier(803)
    assert request.attempt_number == 2


@pytest.mark.parametrize("attempt_number", (False, True, -1, 3, 1.0, "1"))
def test_generation_request_rejects_noncanonical_attempts(
    attempt_number: object,
) -> None:
    with pytest.raises(LifecycleInvariantError, match="attempt_number"):
        generation_request(attempt_number=attempt_number)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("model_name", " "),
        ("rendered_prompt", ""),
        ("settings", object()),
        ("processing_run_id", "not-a-domain-id"),
        ("context_packet_id", "not-a-domain-id"),
        ("model_request_id", "not-a-domain-id"),
    ),
)
def test_generation_request_rejects_invalid_public_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    request = generation_request()
    values = {field.name: getattr(request, field.name) for field in fields(request)}
    values[field_name] = invalid_value

    with pytest.raises(LifecycleInvariantError):
        GenerationRequest(**values)  # type: ignore[arg-type]


def test_completed_generation_freezes_exact_metadata_duration_and_token_usage() -> None:
    token_usage = TokenUsage(11, 7, 18)
    completed = CompletedGeneration(
        response_text=" complete response \n",
        provider_metadata={"nested": {"safe": ["value", 1]}},
        elapsed=timedelta(microseconds=123456),
        token_usage=token_usage,
    )

    assert completed.response_text == " complete response \n"
    assert completed.provider_metadata == FrozenJsonObject(
        {"nested": {"safe": ["value", 1]}}
    )
    assert completed.elapsed == timedelta(microseconds=123456)
    assert completed.token_usage is token_usage


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("response_text", ""),
        ("response_text", " \n\t"),
        ("provider_metadata", None),
        ("provider_metadata", []),
        ("elapsed", timedelta(microseconds=-1)),
        ("elapsed", 0),
        ("token_usage", object()),
    ),
)
def test_completed_generation_rejects_incomplete_or_invalid_values(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {
        "response_text": "complete",
        "provider_metadata": FrozenJsonObject({}),
        "elapsed": timedelta(0),
        "token_usage": None,
    }
    values[field_name] = invalid_value

    with pytest.raises(LifecycleInvariantError):
        CompletedGeneration(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    (
        (-1, None, None),
        (True, None, None),
        (None, -1, None),
        (None, None, False),
        (None, None, 1.0),
    ),
)
def test_token_usage_rejects_noncanonical_counts(
    values: tuple[object, object, object],
) -> None:
    with pytest.raises(LifecycleInvariantError):
        TokenUsage(*values)  # type: ignore[arg-type]


def test_gateway_failure_values_own_exact_immutable_safe_mappings() -> None:
    expected = (
        (
            ProviderUnavailableFailure,
            "PROVIDER_UNAVAILABLE",
            "The local model provider is unavailable.",
            ModelRequestStatus.FAILED,
            ProcessingRunStatus.FAILED,
            FailureCode.PROVIDER_UNAVAILABLE,
        ),
        (
            ModelNotFoundFailure,
            "MODEL_NOT_FOUND",
            "The configured local model is unavailable.",
            ModelRequestStatus.FAILED,
            ProcessingRunStatus.FAILED,
            FailureCode.MODEL_NOT_FOUND,
        ),
        (
            ModelTimeoutFailure,
            "MODEL_TIMEOUT",
            "The local model request timed out.",
            ModelRequestStatus.TIMED_OUT,
            ProcessingRunStatus.FAILED,
            FailureCode.MODEL_TIMEOUT,
        ),
        (
            ModelCancelledFailure,
            "MODEL_CANCELLED",
            "The local model request was cancelled.",
            ModelRequestStatus.CANCELLED,
            ProcessingRunStatus.CANCELLED,
            FailureCode.MODEL_CANCELLED,
        ),
        (
            InvalidProviderResponseFailure,
            "INVALID_PROVIDER_RESPONSE",
            "The local model provider returned an invalid response.",
            ModelRequestStatus.FAILED,
            ProcessingRunStatus.FAILED,
            FailureCode.INVALID_PROVIDER_RESPONSE,
        ),
    )

    for (
        failure_type,
        diagnostic_code,
        safe_message,
        request_status,
        run_status,
        failure_code,
    ) in expected:
        failure = failure_type()
        assert failure.diagnostic_code == diagnostic_code
        assert failure.safe_message == safe_message
        assert failure.model_request_status is request_status
        assert failure.processing_run_status is run_status
        assert failure.failure_code is failure_code
        assert all(not item.init for item in fields(failure))
        with pytest.raises(FrozenInstanceError):
            failure.safe_message = "provider-controlled"  # type: ignore[misc]
        with pytest.raises(TypeError):
            failure_type("provider-controlled")  # type: ignore[call-arg]


def test_superseded_gateway_exceptions_are_not_public() -> None:
    for name in (
        "ModelGatewayError",
        "ProviderUnavailableError",
        "ModelNotFoundError",
        "ModelTimeoutError",
        "ModelCancelledError",
        "InvalidProviderResponseError",
    ):
        assert not hasattr(public_ports, name)


def test_system_port_signatures_are_provider_independent() -> None:
    assert get_type_hints(Clock.now)["return"].__name__ == "datetime"
    assert get_type_hints(IdGenerator.new_id)["return"] is DomainId
    assert get_type_hints(ConfigurationLoader.load)["return"] is ConfigurationSnapshot
    assert get_type_hints(TransactionBoundary.transaction)["return"] == (
        AbstractContextManager[None]
    )


def test_trace_event_has_identifiers_but_no_raw_content_fields() -> None:
    field_names = {field.name for field in fields(TraceEvent)}
    prohibited = {
        "message_text",
        "original_text",
        "prompt",
        "rendered_prompt",
        "response_text",
        "memory_content",
        "configuration",
    }

    assert prohibited.isdisjoint(field_names)
    assert {
        "processing_run_id",
        "context_packet_id",
        "model_request_id",
        "validation_result_id",
        "clarification_request_id",
    } <= field_names


def test_deterministic_component_ports_have_typed_single_operation_contracts() -> None:
    assert get_type_hints(InterpretationEngine.interpret) == {
        "request": InterpretationRequest,
        "return": InterpretationDecision,
    }
    assert get_type_hints(ConstraintEngine.evaluate) == {
        "request": ConstraintEvaluationRequest,
        "return": ConstraintDecision,
    }
    assert get_type_hints(ReferenceMentionExtractor.extract) == {
        "request": ReferenceMentionExtractionRequest,
        "return": tuple[ReferenceMention, ...],
    }
    assert get_type_hints(ReferenceResolver.resolve) == {
        "request": ReferenceResolutionRequest,
        "return": ReferenceDecision,
    }
    assert get_type_hints(ClarificationBuilder.build) == {
        "request": ClarificationBuildRequest,
        "return": ClarificationRequest,
    }
    assert get_type_hints(ContextRetriever.retrieve) == {
        "request": RetrievalRequest,
        "return": RetrievalDecision,
    }
    assert get_type_hints(ContextPacketBuilder.build) == {
        "request": ContextPacketBuildRequest,
        "return": ContextPacketBuildResult,
    }
    assert get_type_hints(PromptRenderer.render) == {
        "request": PromptRenderRequest,
        "return": PromptRenderOutcome,
    }
    assert get_type_hints(ResponseValidator.validate) == {
        "request": ValidationRequest,
        "return": ValidationResult,
    }
    correction_signature = inspect.signature(CorrectionController.plan)
    correction_hints = get_type_hints(CorrectionController.plan)
    assert tuple(correction_signature.parameters) == ("self", "request")
    assert correction_hints == {
        "request": CorrectionPlanRequest,
        "return": CorrectionDecision,
    }
    assert get_args(CorrectionDecision.__value__) == (
        CorrectionEnvelope,
        CorrectionExhausted,
    )

    for request_type in (
        InterpretationRequest,
        ConstraintEvaluationRequest,
        ReferenceMentionExtractionRequest,
        ReferenceResolutionRequest,
        ContextPacketBuildRequest,
        PromptRenderRequest,
        ValidationRequest,
        FailedCandidateLineage,
        CorrectionPlanRequest,
        CorrectionExhausted,
    ):
        assert is_dataclass(request_type)
        assert request_type.__dataclass_params__.frozen is True
        assert "__slots__" in vars(request_type)


def test_failed_candidate_lineage_and_exhaustion_are_exact_bounded_values() -> None:
    lineage = FailedCandidateLineage(
        identifier(1),
        identifier(2),
        identifier(3),
        identifier(4),
        1,
        ModelRequestPurpose.REVISION,
        ModelRequestStatus.SUCCEEDED,
        None,
    )
    exhausted = CorrectionExhausted(
        lineage.processing_run_id,
        lineage.context_packet_id,
        lineage.model_request_id,
        lineage.model_response_id,
        identifier(5),
        1,
        1,
    )

    assert tuple(field.name for field in fields(FailedCandidateLineage)) == (
        "processing_run_id",
        "context_packet_id",
        "model_request_id",
        "model_response_id",
        "attempt_number",
        "request_purpose",
        "request_status",
        "assistant_message_id",
    )
    assert tuple(field.name for field in fields(CorrectionExhausted)) == (
        "processing_run_id",
        "context_packet_id",
        "failed_model_request_id",
        "failed_model_response_id",
        "validation_result_id",
        "attempt_number",
        "correction_limit",
    )
    assert exhausted.failed_model_response_id == lineage.model_response_id

    with pytest.raises(LifecycleInvariantError, match="must be 0, 1, or 2"):
        FailedCandidateLineage(
            lineage.processing_run_id,
            lineage.context_packet_id,
            lineage.model_request_id,
            lineage.model_response_id,
            3,
            lineage.request_purpose,
            lineage.request_status,
            None,
        )
    with pytest.raises(LifecycleInvariantError, match="must equal"):
        CorrectionExhausted(
            lineage.processing_run_id,
            lineage.context_packet_id,
            lineage.model_request_id,
            lineage.model_response_id,
            identifier(5),
            1,
            2,
        )


def test_provisional_revision_envelope_is_not_public() -> None:
    assert not hasattr(public_ports, "RevisionEnvelope")


def test_validation_configuration_snapshot_requires_complete_model_shapes() -> None:
    model_outputs = tuple(
        output
        for output in OutputType
        if output not in {OutputType.CLARIFICATION, OutputType.CONTROLLED_FAILURE}
    )
    rules = tuple(
        OutputShapeRule(f"shape-{output.value.casefold()}", output, "NON_EMPTY_TEXT")
        for output in model_outputs
    )
    snapshot = ValidationConfigurationSnapshot(
        "configuration-fingerprint",
        2,
        "validation-v1",
        rules,
        "preserve-verbs-v1",
        ("change", "remove"),
        ("TOOL_CALL:",),
    )

    assert snapshot.output_shape_rules == rules
    with pytest.raises(LifecycleInvariantError, match="one rule per model output type"):
        ValidationConfigurationSnapshot(
            "configuration-fingerprint",
            2,
            "validation-v1",
            rules[:-1],
            "preserve-verbs-v1",
            ("change",),
            ("TOOL_CALL:",),
        )

    invalid_shape_rules = (
        OutputShapeRule(
            rules[0].id,
            rules[0].output_type,
            "NOT_A_SHAPE",  # type: ignore[arg-type]
        ),
        *rules[1:],
    )
    with pytest.raises(LifecycleInvariantError, match="shape must be canonical"):
        ValidationConfigurationSnapshot(
            "configuration-fingerprint",
            2,
            "validation-v1",
            invalid_shape_rules,
            "preserve-verbs-v1",
            ("change",),
            ("TOOL_CALL:",),
        )


def test_reference_requests_validate_spans_scope_order_and_prior_linkage() -> None:
    conversation_id = identifier(1)
    entity = Entity(
        identifier(2),
        EntityType.PROJECT,
        identifier(3),
        identifier(3),
        "Context for AI",
        "context for ai",
        None,
        True,
        NOW,
        NOW,
    )
    prior_message = Message(
        identifier(4), conversation_id, MessageRole.USER, "use the app", NOW, 1
    )
    message = Message(
        identifier(5), conversation_id, MessageRole.USER, "fix it", NOW, 2
    )
    state = ConversationState(
        conversation_id, None, None, None, OutputType.TEXT_ANSWER, (), 0, NOW
    )
    mention = ReferenceMention(0, "it", "it", "reference-form:it", 4, 6)
    evidence = ReferenceCandidateEvidence(
        1,
        entity.id,
        EntityType.PROJECT,
        entity.display_name,
        entity.normalized_name,
        UnitScore("0.90"),
        ReferenceRankReason.ACTIVE_STATE,
        None,
        None,
        None,
        None,
        True,
    )
    prior_outcome = ReferenceOutcome(
        identifier(6),
        identifier(7),
        prior_message.id,
        0,
        "the app",
        ReferenceStatus.RESOLVED,
        entity.id,
        None,
        UnitScore("0.90"),
        (evidence,),
        NOW,
    )

    extraction = ReferenceMentionExtractionRequest(message, (mention,), (entity,))
    resolution = ReferenceResolutionRequest(
        identifier(8),
        message,
        (prior_message,),
        state,
        (mention,),
        (entity,),
        (prior_outcome,),
        NOW,
    )

    assert extraction.seed_mentions == (mention,)
    assert resolution.prior_resolved_outcomes == (prior_outcome,)
    with pytest.raises(LifecycleInvariantError, match="exact source slice"):
        ReferenceMentionExtractionRequest(
            message,
            (ReferenceMention(0, "that", "that", "reference-form:that", 4, 6),),
            (entity,),
        )
    with pytest.raises(LifecycleInvariantError, match="precede"):
        ReferenceResolutionRequest(
            identifier(8),
            message,
            (message,),
            state,
            (mention,),
            (entity,),
            (),
            NOW,
        )
    with pytest.raises(LifecycleInvariantError, match="distinct IDs"):
        ReferenceMentionExtractionRequest(message, (mention,), (entity, entity))


def retrieval_memory(number: int) -> Memory:
    return Memory(
        identifier(number),
        None,
        None,
        MemoryType.PROJECT_FACT,
        MemoryScope.GLOBAL,
        MemoryStatus.ACTIVE,
        f"Memory {number}",
        ("memory",),
        (),
        UnitScore("0.5"),
        UnitScore("1"),
        None,
        NOW,
        NOW,
        None,
    )


def retrieval_result(
    *,
    evidence_id: int = 20,
    packet_id: int = 10,
    memory_id: int = 30,
    rank: int = 0,
    score: str = "0.8",
    created_at: datetime = NOW,
) -> RetrievalResult:
    return RetrievalResult(
        identifier(evidence_id),
        identifier(packet_id),
        identifier(memory_id),
        rank,
        UnitScore(score),
        SELECTED_REASONS,
        created_at,
    )


def retrieval_exclusion(
    *,
    evidence_id: int = 21,
    packet_id: int = 10,
    memory_id: int = 31,
    created_at: datetime = NOW,
) -> RetrievalExclusion:
    return RetrievalExclusion(
        identifier(evidence_id),
        identifier(packet_id),
        identifier(memory_id),
        RetrievalExclusionReason.SCORE_BELOW_THRESHOLD,
        UnitScore("0.2"),
        FrozenJsonObject({"minimum_relevance_score": "0.5"}),
        created_at,
    )


def test_retrieval_request_freezes_distinct_considered_memories() -> None:
    candidate = retrieval_memory(40)
    request = RetrievalRequest(
        identifier(10),
        identifier(11),
        identifier(12),
        identifier(13),
        None,
        None,
        "find memory",
        [candidate],  # type: ignore[arg-type]
        UnitScore("0.5"),
        5,
        NOW,
    )

    assert request.candidate_memories == (candidate,)
    with pytest.raises(LifecycleInvariantError, match="distinct IDs"):
        RetrievalRequest(
            identifier(10),
            identifier(11),
            identifier(12),
            identifier(13),
            None,
            None,
            "find memory",
            (candidate, candidate),
            UnitScore("0.5"),
            5,
            NOW,
        )


def test_retrieval_decision_requires_canonical_lineage_order_and_confidence() -> None:
    selected = retrieval_result()
    excluded = retrieval_exclusion()

    decision = RetrievalDecision((selected,), (excluded,), selected.score)

    assert decision.selected == (selected,)
    assert decision.excluded == (excluded,)
    assert decision.confidence == UnitScore("0.8")

    with pytest.raises(LifecycleInvariantError, match="rank order"):
        RetrievalDecision((retrieval_result(rank=1),), (), UnitScore("0.8"))
    with pytest.raises(LifecycleInvariantError, match="packet identity"):
        RetrievalDecision(
            (selected,),
            (retrieval_exclusion(packet_id=99),),
            selected.score,
        )
    with pytest.raises(LifecycleInvariantError, match="common retrieval timestamp"):
        RetrievalDecision(
            (selected,),
            (retrieval_exclusion(created_at=NOW + timedelta(microseconds=1)),),
            selected.score,
        )
    with pytest.raises(LifecycleInvariantError, match="memory UUID order"):
        RetrievalDecision(
            (),
            (
                retrieval_exclusion(evidence_id=22, memory_id=33),
                retrieval_exclusion(evidence_id=23, memory_id=32),
            ),
            None,
        )
    with pytest.raises(LifecycleInvariantError, match="highest selected score"):
        RetrievalDecision((selected,), (excluded,), UnitScore("0.7"))
    with pytest.raises(LifecycleInvariantError, match="highest selected score"):
        RetrievalDecision((), (), UnitScore("0"))
