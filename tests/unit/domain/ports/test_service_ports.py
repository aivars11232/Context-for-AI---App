"""Contract tests for non-repository inward ports."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import fields
import inspect
from typing import Protocol, get_type_hints

from context_for_ai.domain.lifecycle import ClarificationRequest, ValidationResult
from context_for_ai.domain.ports import (
    CancellationToken,
    ClarificationBuildRequest,
    ClarificationBuilder,
    Clock,
    CompletedGeneration,
    ConfigurationLoader,
    ConfigurationSnapshot,
    ContextRetriever,
    CorrectionController,
    CorrectionDecision,
    GenerationRequest,
    IdGenerator,
    ModelGateway,
    ResponseValidator,
    RetrievalDecision,
    RetrievalRequest,
    TraceEvent,
    TraceLogger,
    TransactionBoundary,
    ValidationRequest,
)
from context_for_ai.domain.value_objects import DomainId


SERVICE_PROTOCOLS = (
    CancellationToken,
    ClarificationBuilder,
    Clock,
    ConfigurationLoader,
    ContextRetriever,
    CorrectionController,
    IdGenerator,
    ModelGateway,
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
