"""Persistence-boundary aggregate invariant tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from context_for_ai.domain.decisions import (
    CONTEXT_PACKET_SCHEMA_VERSION,
    PROMPT_POLICY_VERSION,
    ContextPacket,
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.entities import Memory, MemoryRevision, MemorySource
from context_for_ai.domain.enums import (
    LocalActor,
    MemoryRevisionOperation,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import memory_revision_metadata, overall_confidence
from context_for_ai.domain.ports.records import ContextPacketRecord, MemoryRecord
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
SELECTED_REASONS = (
    "project_match=0",
    "topic_match=0",
    "keyword_jaccard=0.5",
    "recency=1",
    "importance=0.5",
    "scope_match=1",
    "correction_match=0",
)


def identifier(number: int) -> DomainId:
    return DomainId(f"40000000-0000-4000-8000-{number:012d}")


def memory_record() -> MemoryRecord:
    memory = Memory(
        identifier(1),
        identifier(2),
        None,
        MemoryType.PROJECT_FACT,
        MemoryScope.CONVERSATION,
        MemoryStatus.ACTIVE,
        "Remember this",
        ("remember",),
        ("topic",),
        UnitScore("0.5"),
        UnitScore("1"),
        None,
        NOW,
        NOW,
        None,
    )
    source = MemorySource(
        identifier(3),
        memory.id,
        MemorySourceKind.MANUAL_ENTRY,
        None,
        "Manual creation",
        NOW,
    )
    revision = MemoryRevision(
        identifier(4),
        memory.id,
        1,
        MemoryRevisionOperation.CREATE,
        memory.content,
        memory_revision_metadata(memory, source.id),
        LocalActor.LOCAL_USER,
        NOW,
    )
    return MemoryRecord(memory, [source], [revision])  # type: ignore[arg-type]


def packet(results: tuple[RetrievalResult, ...] = ()) -> ContextPacket:
    retrieval = tuple(
        {
            "memory_id": str(result.memory_id),
            "content": f"Memory {result.memory_id}",
            "score": result.score.value,
            "rank": result.rank,
            "reasons": result.reasons,
            "scope": "GLOBAL",
            "confidence": Decimal("1"),
        }
        for result in results
    )
    return ContextPacket(
        identifier(10),
        identifier(11),
        identifier(12),
        FrozenJsonObject(
            {
                "schema_version": CONTEXT_PACKET_SCHEMA_VERSION,
                "trace": {
                    "processing_run_id": str(identifier(11)),
                    "conversation_id": str(identifier(13)),
                    "user_message_id": str(identifier(12)),
                    "state_version": 0,
                    "configuration_fingerprint": "configuration-fingerprint",
                },
                "request": {
                    "original_text": "Remember this",
                    "intent": "ANSWER",
                    "intent_rule_id": "intent-answer",
                    "expected_output_type": "TEXT_ANSWER",
                    "qualifiers": (),
                    "confidence": Decimal("1"),
                },
                "active_state": {
                    "project_id": None,
                    "topic_id": None,
                    "task_id": None,
                    "previous_task_id": None,
                    "topic_stack": (),
                },
                "validation_context": {
                    "rule_set_version": "validation-v1",
                    "active_topic": None,
                    "output_shape_rule": {
                        "id": "shape-answer",
                        "output_type": "TEXT_ANSWER",
                        "shape": "NON_EMPTY_TEXT",
                    },
                    "preserve_change_verb_list_id": "preserve-v1",
                    "preserve_change_verbs": ("change",),
                    "action_markers": ("TOOL_CALL:",),
                },
                "references": (),
                "constraints": (),
                "retrieval": retrieval,
                "confidence": {
                    "interpretation": Decimal("1"),
                    "references": None,
                    "retrieval": None if not results else results[0].score.value,
                    "overall": overall_confidence(
                        interpretation=UnitScore("1"),
                        retrieval=None if not results else results[0].score,
                    ).value,
                },
                "response_policy": {
                    "output_type": "TEXT_ANSWER",
                    "validate_before_display": True,
                    "text_only": True,
                    "no_actions": True,
                    "streaming": False,
                    "correction_limit": 2,
                    "model_generation_limit": 3,
                    "absolute_model_generation_cap": 3,
                },
                "rendering": {
                    "prompt_policy_version": PROMPT_POLICY_VERSION,
                    "token_estimator": "conservative_utf8_v1",
                    "token_budget": 1000,
                    "mandatory_estimated_tokens": 200,
                    "estimated_prompt_tokens": 200,
                    "included_sections": (() if not results else ("RETRIEVAL",)),
                    "omitted_sections": (),
                },
            }
        ),
        CONTEXT_PACKET_SCHEMA_VERSION,
        PROMPT_POLICY_VERSION,
        "configuration-fingerprint",
        NOW,
    )


def selected(
    *,
    evidence_id: int,
    memory_id: int,
    rank: int,
    score: str,
    context_packet_id: DomainId | None = None,
    created_at: datetime = NOW,
) -> RetrievalResult:
    return RetrievalResult(
        identifier(evidence_id),
        context_packet_id or identifier(10),
        identifier(memory_id),
        rank,
        UnitScore(score),
        SELECTED_REASONS,
        created_at,
    )


def excluded(
    *,
    evidence_id: int,
    memory_id: int,
    context_packet_id: DomainId | None = None,
    created_at: datetime = NOW,
) -> RetrievalExclusion:
    return RetrievalExclusion(
        identifier(evidence_id),
        context_packet_id or identifier(10),
        identifier(memory_id),
        RetrievalExclusionReason.SCORE_BELOW_THRESHOLD,
        UnitScore("0.2"),
        FrozenJsonObject({"minimum_relevance_score": "0.5"}),
        created_at,
    )


def test_memory_record_freezes_and_validates_complete_history() -> None:
    record = memory_record()

    assert isinstance(record.sources, tuple)
    assert isinstance(record.revisions, tuple)
    assert record.revisions[0].metadata["source_id"] == str(record.sources[0].id)


def test_memory_record_rejects_incomplete_history() -> None:
    record = memory_record()

    with pytest.raises(LifecycleInvariantError, match="revision"):
        MemoryRecord(record.memory, record.sources, ())


def test_context_packet_record_accepts_canonical_complete_evidence() -> None:
    results = (
        selected(evidence_id=20, memory_id=30, rank=0, score="0.9"),
        selected(evidence_id=21, memory_id=31, rank=1, score="0.8"),
    )
    record = ContextPacketRecord(
        packet(results),
        results,
        [
            excluded(evidence_id=22, memory_id=32),
            excluded(evidence_id=23, memory_id=33),
        ],
    )

    assert isinstance(record.retrieval_results, tuple)
    assert isinstance(record.retrieval_exclusions, tuple)


@pytest.mark.parametrize(
    "results",
    [
        (
            selected(evidence_id=20, memory_id=30, rank=1, score="0.9"),
        ),
        (
            selected(evidence_id=20, memory_id=30, rank=0, score="0.8"),
            selected(evidence_id=21, memory_id=31, rank=1, score="0.9"),
        ),
    ],
)
def test_context_packet_record_rejects_noncanonical_result_order(
    results: tuple[RetrievalResult, ...],
) -> None:
    with pytest.raises(LifecycleInvariantError, match="rank order|score order"):
        ContextPacketRecord(packet(), results, ())


def test_context_packet_record_rejects_foreign_packet_identity() -> None:
    result = selected(
        evidence_id=20,
        memory_id=30,
        rank=0,
        score="0.9",
        context_packet_id=identifier(99),
    )

    with pytest.raises(LifecycleInvariantError, match="aggregate packet"):
        ContextPacketRecord(packet(), (result,), ())


@pytest.mark.parametrize(
    ("results", "exclusions", "message"),
    [
        (
            (
                selected(evidence_id=20, memory_id=30, rank=0, score="0.9"),
                selected(evidence_id=20, memory_id=31, rank=1, score="0.8"),
            ),
            (),
            "record IDs",
        ),
        (
            (
                selected(evidence_id=20, memory_id=30, rank=0, score="0.9"),
                selected(evidence_id=21, memory_id=30, rank=1, score="0.8"),
            ),
            (),
            "memory IDs",
        ),
        (
            (selected(evidence_id=20, memory_id=30, rank=0, score="0.9"),),
            (excluded(evidence_id=21, memory_id=30),),
            "disjoint",
        ),
        (
            (selected(evidence_id=20, memory_id=30, rank=0, score="0.9"),),
            (excluded(evidence_id=20, memory_id=31),),
            "record IDs must be disjoint",
        ),
    ],
)
def test_context_packet_record_rejects_duplicate_or_overlapping_evidence(
    results: tuple[RetrievalResult, ...],
    exclusions: tuple[RetrievalExclusion, ...],
    message: str,
) -> None:
    with pytest.raises(LifecycleInvariantError, match=message):
        ContextPacketRecord(packet(), results, exclusions)


def test_context_packet_record_rejects_noncanonical_exclusion_order() -> None:
    exclusions = (
        excluded(evidence_id=20, memory_id=32),
        excluded(evidence_id=21, memory_id=31),
    )

    with pytest.raises(LifecycleInvariantError, match="memory UUID order"):
        ContextPacketRecord(packet(), (), exclusions)


def test_context_packet_record_rejects_mixed_retrieval_timestamps() -> None:
    result = selected(evidence_id=20, memory_id=30, rank=0, score="0.9")
    exclusion = excluded(
        evidence_id=21,
        memory_id=31,
        created_at=NOW + timedelta(microseconds=1),
    )

    with pytest.raises(LifecycleInvariantError, match="common retrieval timestamp"):
        ContextPacketRecord(packet(), (result,), (exclusion,))


def test_memory_record_rejects_a_revision_that_disagrees_with_current_state() -> None:
    record = memory_record()
    changed_memory = replace(record.memory, content="Unrecorded change")

    with pytest.raises(LifecycleInvariantError, match="final memory revision"):
        MemoryRecord(changed_memory, record.sources, record.revisions)
