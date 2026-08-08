"""Contract tests for non-repository inward ports."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
import inspect
from typing import Protocol, get_type_hints

import pytest

from context_for_ai.domain.lifecycle import ClarificationRequest, ValidationResult
from context_for_ai.domain.decisions import (
    ConstraintDecision,
    InterpretationDecision,
    ReferenceCandidateEvidence,
    ReferenceDecision,
    ReferenceMention,
    ReferenceOutcome,
)
from context_for_ai.domain.entities import ConversationState, Entity, Message
from context_for_ai.domain.enums import (
    EntityType,
    MessageRole,
    OutputType,
    ReferenceRankReason,
    ReferenceStatus,
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
    ConstraintEngine,
    ConstraintEvaluationRequest,
    ContextRetriever,
    CorrectionController,
    CorrectionDecision,
    GenerationRequest,
    IdGenerator,
    InterpretationEngine,
    InterpretationRequest,
    ModelGateway,
    ResponseValidator,
    RetrievalDecision,
    RetrievalRequest,
    TraceEvent,
    TraceLogger,
    TransactionBoundary,
    ValidationRequest,
)
from context_for_ai.domain.ports.context import (
    ReferenceMentionExtractionRequest,
    ReferenceMentionExtractor,
    ReferenceResolutionRequest,
    ReferenceResolver,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"20000000-0000-4000-8000-{number:012d}")


SERVICE_PROTOCOLS = (
    CancellationToken,
    ClarificationBuilder,
    Clock,
    ConfigurationLoader,
    ConstraintEngine,
    ContextRetriever,
    CorrectionController,
    IdGenerator,
    InterpretationEngine,
    ModelGateway,
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


def test_model_gateway_accepts_cancellation_and_returns_only_buffered_text() -> None:
    hints = get_type_hints(ModelGateway.generate)

    assert hints == {
        "request": GenerationRequest,
        "cancellation_token": CancellationToken,
        "return": CompletedGeneration,
    }
    assert not hasattr(ModelGateway, "stream")
    assert not hasattr(ModelGateway, "retry")


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
    assert get_type_hints(ResponseValidator.validate) == {
        "request": ValidationRequest,
        "return": ValidationResult,
    }
    correction_signature = inspect.signature(CorrectionController.plan)
    correction_hints = get_type_hints(CorrectionController.plan)
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for name, parameter in correction_signature.parameters.items()
        if name != "self"
    )
    assert correction_hints["return"] == CorrectionDecision

    for request_type in (
        InterpretationRequest,
        ConstraintEvaluationRequest,
        ReferenceMentionExtractionRequest,
        ReferenceResolutionRequest,
    ):
        assert is_dataclass(request_type)
        assert request_type.__dataclass_params__.frozen is True
        assert "__slots__" in vars(request_type)


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
