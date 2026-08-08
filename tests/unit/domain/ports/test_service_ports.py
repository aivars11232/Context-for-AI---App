"""Contract tests for non-repository inward ports."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
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
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.entities import ConversationState, Entity, Memory, Message
from context_for_ai.domain.enums import (
    EntityType,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MessageRole,
    OutputType,
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
    GenerationRequest,
    IdGenerator,
    InterpretationEngine,
    InterpretationRequest,
    ModelGateway,
    OutputShapeRule,
    PromptRenderer,
    PromptRenderOutcome,
    PromptRenderRequest,
    ResponseValidator,
    RetrievalDecision,
    RetrievalRequest,
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
        ContextPacketBuildRequest,
        PromptRenderRequest,
    ):
        assert is_dataclass(request_type)
        assert request_type.__dataclass_params__.frozen is True
        assert "__slots__" in vars(request_type)


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
