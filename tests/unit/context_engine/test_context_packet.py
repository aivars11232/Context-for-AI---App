"""Focused public-behavior tests for pure TASK-0010 packet construction."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from context_for_ai.context_engine.context_packet import DeterministicContextPacketBuilder
from context_for_ai.domain.decisions import (
    Constraint,
    ConstraintDecision,
    ConstraintPacketLineage,
    ConstraintSourceEvidence,
    InterpretationDecision,
    ReferenceCandidateEvidence,
    ReferenceOutcome,
    RequestInterpretation,
    ResponsePolicy,
)
from context_for_ai.domain.entities import ConversationState, Memory, Message, Topic
from context_for_ai.domain.enums import (
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    ContextBudgetPhase,
    EntityType,
    IntentType,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MessageRole,
    OutputType,
    ProcessingRunStatus,
    ReferenceRankReason,
    ReferenceStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.configuration import (
    OutputShapeRule,
    ValidationConfigurationSnapshot,
)
from context_for_ai.domain.ports.context import (
    ContextBudgetExceeded,
    ContextPacketBuildRequest,
    ContextPacketBuildSuccess,
    RetrievalDecision,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore
from context_for_ai.domain.decisions import RetrievalResult


NOW = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
REASONS = (
    "project_match=0",
    "topic_match=0",
    "keyword_jaccard=0.5",
    "recency=1",
    "importance=0.5",
    "scope_match=1",
    "correction_match=0",
)


def identifier(number: int) -> DomainId:
    return DomainId(f"60000000-0000-4000-8000-{number:012d}")


def validation_configuration() -> ValidationConfigurationSnapshot:
    output_types = tuple(
        value
        for value in OutputType
        if value not in {OutputType.CLARIFICATION, OutputType.CONTROLLED_FAILURE}
    )
    return ValidationConfigurationSnapshot(
        "configuration-fingerprint",
        2,
        "validation-v1",
        tuple(
            OutputShapeRule(
                f"shape-{value.value.casefold()}",
                value,
                "NON_EMPTY_TEXT",
            )
            for value in output_types
        ),
        "preserve-v1",
        ("change", "remove"),
        ("TOOL_CALL:", "ACTION_EXECUTED:"),
    )


def base_request(
    *,
    references: tuple[ReferenceOutcome, ...] = (),
    constraint_decision: ConstraintDecision | None = None,
    lineage: tuple[ConstraintPacketLineage, ...] = (),
    retrieval_decision: RetrievalDecision | None = None,
    memories: tuple[Memory, ...] = (),
    maximum_prompt_tokens: int = 10000,
    state: ConversationState | None = None,
    active_topic: Topic | None = None,
) -> ContextPacketBuildRequest:
    conversation_id = identifier(3)
    run = ProcessingRun(
        identifier(1),
        conversation_id,
        identifier(2),
        "request-1",
        ProcessingRunStatus.PERSISTED,
        0,
        "configuration-fingerprint",
        NOW,
        None,
    )
    message = Message(
        identifier(2),
        conversation_id,
        MessageRole.USER,
        'Explain "it" safely.',
        NOW,
        1,
    )
    state = state or ConversationState(
        conversation_id,
        None,
        None,
        None,
        OutputType.TEXT_EXPLANATION,
        (),
        4,
        NOW,
    )
    interpretation = InterpretationDecision(
        RequestInterpretation(
            run.id,
            message.id,
            IntentType.EXPLAIN,
            OutputType.TEXT_EXPLANATION,
            "intent-explain",
            (),
            UnitScore("0.9"),
            "matched explain",
            NOW,
        ),
        "context-rules-v1",
        (),
        None,
        None,
        (),
        None,
        None,
    )
    decision = constraint_decision or ConstraintDecision(
        (),
        (),
        (),
        ResponsePolicy(OutputType.TEXT_EXPLANATION, "context-rules-v1"),
        None,
        None,
    )
    retrieval = retrieval_decision or RetrievalDecision((), (), None)
    return ContextPacketBuildRequest(
        identifier(10),
        run,
        message,
        state,
        None,
        active_topic,
        interpretation,
        references,
        decision,
        lineage,
        retrieval,
        memories,
        16384,
        maximum_prompt_tokens,
        512,
        validation_configuration(),
        NOW,
    )


def resolved_reference() -> ReferenceOutcome:
    evidence = ReferenceCandidateEvidence(
        1,
        identifier(21),
        EntityType.PROJECT,
        "Context for AI",
        "context for ai",
        UnitScore("0.90"),
        ReferenceRankReason.ACTIVE_STATE,
        None,
        None,
        None,
        None,
        True,
    )
    return ReferenceOutcome(
        identifier(20),
        identifier(1),
        identifier(2),
        0,
        "it",
        ReferenceStatus.RESOLVED,
        identifier(21),
        None,
        UnitScore("0.90"),
        (evidence,),
        NOW,
    )


def selected_memory() -> tuple[RetrievalDecision, tuple[Memory, ...]]:
    memory = Memory(
        identifier(40),
        None,
        None,
        MemoryType.PROJECT_FACT,
        MemoryScope.GLOBAL,
        MemoryStatus.ACTIVE,
        "The immutable memory snapshot.",
        ("immutable",),
        (),
        UnitScore("0.5"),
        UnitScore("1"),
        None,
        NOW,
        NOW,
        None,
    )
    result = RetrievalResult(
        identifier(41),
        identifier(10),
        memory.id,
        0,
        UnitScore("0.8"),
        REASONS,
        NOW,
    )
    return RetrievalDecision((result,), (), result.score), (memory,)


def test_builder_returns_complete_immutable_v2_packet_and_initial_render() -> None:
    retrieval, memories = selected_memory()
    request = base_request(
        references=(resolved_reference(),),
        retrieval_decision=retrieval,
        memories=memories,
    )
    builder = DeterministicContextPacketBuilder()

    first = builder.build(request)
    second = builder.build(request)

    assert isinstance(first, ContextPacketBuildSuccess)
    assert first == second
    packet = first.record.packet
    assert packet.schema_version == "mvp-context-packet-v2"
    assert packet.packet_json["request"]["original_text"] == request.message.original_text
    reference = packet.packet_json["references"][0]
    assert reference["evidence"][0]["score"] == Decimal("0.9")
    assert isinstance(reference["evidence"][0]["score"], Decimal)
    assert packet.packet_json["retrieval"][0]["content"] == memories[0].content
    assert packet.packet_json["confidence"] == FrozenJsonObject(
        {
            "interpretation": Decimal("0.9"),
            "references": Decimal("0.9"),
            "retrieval": Decimal("0.8"),
            "overall": Decimal("0.88"),
        }
    )
    assert first.initial_render.context_packet_id == packet.id
    assert first.record.retrieval_results == retrieval.selected


def test_builder_persists_normalized_topic_terms_only_in_validation_context() -> None:
    state = ConversationState(
        identifier(3),
        identifier(50),
        None,
        None,
        OutputType.TEXT_EXPLANATION,
        (identifier(50),),
        5,
        NOW,
    )
    topic = Topic(
        identifier(50),
        identifier(3),
        "Café, café tools!",
        "café café tools",
        NOW,
        NOW,
    )
    result = DeterministicContextPacketBuilder().build(
        base_request(state=state, active_topic=topic)
    )

    assert isinstance(result, ContextPacketBuildSuccess)
    validation = result.record.packet.packet_json["validation_context"]
    assert validation["active_topic"]["terms"] == ("café", "tools")
    assert "validation-v1" not in result.initial_render.rendered_prompt


def test_builder_returns_typed_initial_overflow_without_packet_or_prompt() -> None:
    result = DeterministicContextPacketBuilder().build(
        base_request(maximum_prompt_tokens=1)
    )

    assert isinstance(result, ContextBudgetExceeded)
    assert result.phase is ContextBudgetPhase.INITIAL
    assert result.effective_prompt_budget == 1
    assert not hasattr(result, "record")
    assert not hasattr(result, "rendered_prompt")


def test_build_request_rejects_mismatched_retrieval_snapshot_bijection() -> None:
    retrieval, memories = selected_memory()
    with pytest.raises(LifecycleInvariantError, match="bijectively"):
        base_request(retrieval_decision=retrieval, memories=())
    with pytest.raises(LifecycleInvariantError, match="preallocated"):
        foreign = replace(
            retrieval.selected[0],
            context_packet_id=identifier(99),
        )
        base_request(
            retrieval_decision=RetrievalDecision((foreign,), (), foreign.score),
            memories=memories,
        )


def test_builder_rejects_active_assumption_and_incomplete_lineage() -> None:
    assumption = Constraint(
        identifier(70),
        identifier(1),
        identifier(2),
        0,
        ConstraintType.ASSUMED,
        None,
        ConstraintScope.CURRENT_RESPONSE,
        "ASSUME:DETAIL",
        500,
        ConstraintSourceKind.ASSUMPTION,
        "assumed detail",
        UnitScore("0.5"),
        ConstraintResolutionStatus.ACTIVE,
        None,
        None,
        NOW,
    )
    evidence = ConstraintSourceEvidence(
        assumption.id,
        "assumption:detail",
        ("assumption-rule",),
        ("assumed detail",),
        1,
        NOW,
        ("500", "0"),
    )
    decision = ConstraintDecision(
        (assumption,),
        (evidence,),
        (),
        ResponsePolicy(OutputType.TEXT_EXPLANATION, "context-rules-v1"),
        None,
        None,
    )
    companion = ConstraintPacketLineage(
        assumption.id,
        identifier(2),
        None,
        None,
        None,
        (),
    )
    request = base_request(
        constraint_decision=decision,
        lineage=(companion,),
    )
    with pytest.raises(LifecycleInvariantError, match="active assumed"):
        DeterministicContextPacketBuilder().build(request)

    with pytest.raises(LifecycleInvariantError, match="lineage companion"):
        base_request(constraint_decision=decision, lineage=())
