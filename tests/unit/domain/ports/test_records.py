"""Persistence-boundary aggregate invariant tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from context_for_ai.domain.decisions import (
    CONTEXT_PACKET_SCHEMA_VERSION,
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
from context_for_ai.domain.policies import memory_revision_metadata
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


def packet() -> ContextPacket:
    return ContextPacket(
        identifier(10),
        identifier(11),
        identifier(12),
        FrozenJsonObject({}),
        CONTEXT_PACKET_SCHEMA_VERSION,
        "prompt-policy-v1",
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
    record = ContextPacketRecord(
        packet(),
        [
            selected(evidence_id=20, memory_id=30, rank=0, score="0.9"),
            selected(evidence_id=21, memory_id=31, rank=1, score="0.8"),
        ],
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
