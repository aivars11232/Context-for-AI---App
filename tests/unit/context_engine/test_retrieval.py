"""Focused tests for pure deterministic TASK-0009 retrieval."""

from __future__ import annotations

from decimal import Context, Decimal, localcontext
from datetime import datetime, timedelta, timezone
from itertools import permutations

import pytest

from context_for_ai.context_engine.normalization import normalize_words
from context_for_ai.context_engine.retrieval import (
    DeterministicContextRetriever,
    normalize_retrieval_content,
)
from context_for_ai.domain.entities import Memory
from context_for_ai.domain.enums import (
    MemoryScope,
    MemoryStatus,
    MemoryType,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import RetrievalDecision, RetrievalRequest
from context_for_ai.domain.value_objects import DomainId, UnitScore


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
CONVERSATION_ID = DomainId("70000000-0000-4000-8000-000000000100")
PROJECT_ID = DomainId("70000000-0000-4000-8000-000000000200")
OTHER_CONVERSATION_ID = DomainId("70000000-0000-4000-8000-000000000101")
OTHER_PROJECT_ID = DomainId("70000000-0000-4000-8000-000000000201")


def identifier(number: int) -> DomainId:
    return DomainId(f"70000000-0000-4000-8000-{number:012d}")


class SequenceIds:
    def __init__(self, start: int = 900) -> None:
        self.next_number = start
        self.calls: list[DomainId] = []

    def new_id(self) -> DomainId:
        value = identifier(self.next_number)
        self.next_number += 1
        self.calls.append(value)
        return value


def memory(
    number: int,
    *,
    scope: MemoryScope = MemoryScope.GLOBAL,
    conversation_id: DomainId | None = None,
    project_id: DomainId | None = None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    memory_type: MemoryType = MemoryType.PROJECT_FACT,
    content: str | None = None,
    keywords: tuple[str, ...] = (),
    topic_terms: tuple[str, ...] = (),
    importance: str = "0",
    expires_at: datetime | None = None,
    updated_at: datetime = NOW,
) -> Memory:
    if scope is MemoryScope.CONVERSATION and conversation_id is None:
        conversation_id = CONVERSATION_ID
    if scope is MemoryScope.PROJECT and project_id is None:
        project_id = PROJECT_ID
    if scope is MemoryScope.GLOBAL:
        conversation_id = None
        project_id = None
    return Memory(
        identifier(number),
        conversation_id,
        project_id,
        memory_type,
        scope,
        status,
        content if content is not None else f"Memory {number}",
        keywords,
        topic_terms,
        UnitScore(importance),
        UnitScore("1"),
        expires_at,
        NOW - timedelta(days=365),
        updated_at,
        updated_at if status is MemoryStatus.DELETED else None,
    )


def request(
    candidates: tuple[Memory, ...],
    *,
    request_text: str = "",
    active_topic_label: str | None = None,
    project_id: DomainId | None = PROJECT_ID,
    threshold: str = "0",
    limit: int = 20,
    evaluated_at: datetime = NOW,
) -> RetrievalRequest:
    return RetrievalRequest(
        identifier(800),
        identifier(801),
        identifier(802),
        CONVERSATION_ID,
        project_id,
        active_topic_label,
        request_text,
        candidates,
        UnitScore(threshold),
        limit,
        evaluated_at,
    )


def retrieve(
    candidates: tuple[Memory, ...],
    *,
    ids: SequenceIds | None = None,
    **request_values: object,
) -> RetrievalDecision:
    generator = ids or SequenceIds()
    return DeterministicContextRetriever(generator).retrieve(
        request(candidates, **request_values)  # type: ignore[arg-type]
    )


def test_retrieval_normalization_deletes_punctuation_but_preserves_symbols() -> None:
    value = "  CAFE\u0301\tFoo-bar, baz…qux  C++\u2003price€  "

    assert normalize_retrieval_content(value) == "café foobar bazqux c++ price€"
    assert normalize_retrieval_content(value) == normalize_words(value)
    assert normalize_retrieval_content("---…") == ""
    with pytest.raises(LifecycleInvariantError, match="requires text"):
        normalize_retrieval_content(3)  # type: ignore[arg-type]


def test_exact_decimal_score_and_all_seven_factor_reasons_ignore_ambient_context() -> None:
    candidate = memory(
        1,
        scope=MemoryScope.PROJECT,
        conversation_id=OTHER_CONVERSATION_ID,
        memory_type=MemoryType.CORRECTION_RULE,
        content="Use SQLite safely",
        keywords=("SQLite transactions",),
        topic_terms=("Persistence",),
        importance="0.8000",
    )

    with localcontext(Context(prec=3)):
        decision = retrieve(
            (candidate,),
            request_text="SQLite safe",
            active_topic_label="Persistence",
            threshold="0.8",
            limit=1,
        )

    result = decision.selected[0]
    assert result.score.value == Decimal("0.8366666666666666666666666667")
    assert result.reasons == (
        "project_match=1",
        "topic_match=1",
        "keyword_jaccard=0.3333333333333333333333333333",
        "recency=1",
        "importance=0.8",
        "scope_match=0.8",
        "correction_match=1",
    )
    assert result.rank == 0
    assert result.created_at == NOW
    assert decision.confidence == result.score


def test_threshold_is_inclusive_and_recency_has_exact_edges() -> None:
    exact_ninety = memory(
        1,
        content="exact ninety",
        updated_at=NOW - timedelta(days=90),
    )
    just_inside = memory(
        2,
        content="just inside",
        updated_at=NOW - timedelta(days=90) + timedelta(microseconds=1),
    )
    after_ninety = memory(
        3,
        content="after ninety",
        updated_at=NOW - timedelta(days=91),
    )
    future = memory(
        4,
        content="future",
        updated_at=NOW + timedelta(days=1),
    )

    inclusive = retrieve(
        (exact_ninety,),
        threshold="0.030",
        limit=1,
    )
    assert inclusive.selected[0].score == UnitScore("0.03")

    decision = retrieve(
        (after_ninety, future, exact_ninety, just_inside),
        threshold="0",
        limit=4,
    )
    by_memory_id = {result.memory_id: result for result in decision.selected}
    assert by_memory_id[exact_ninety.id].reasons[3] == "recency=0"
    assert by_memory_id[after_ninety.id].reasons[3] == "recency=0"
    assert by_memory_id[future.id].reasons[3] == "recency=1"
    inside_recency = Decimal(
        by_memory_id[just_inside.id].reasons[3].removeprefix("recency=")
    )
    assert Decimal("0") < inside_recency < Decimal("1")


def test_scope_eligibility_ignores_the_irrelevant_owner_identifier() -> None:
    conversation_memory = memory(
        1,
        scope=MemoryScope.CONVERSATION,
        project_id=OTHER_PROJECT_ID,
        content="conversation",
    )
    project_memory = memory(
        2,
        scope=MemoryScope.PROJECT,
        conversation_id=OTHER_CONVERSATION_ID,
        content="project",
    )
    global_memory = memory(3, content="global")

    decision = retrieve(
        (global_memory, project_memory, conversation_memory),
        threshold="0",
        limit=3,
    )

    assert {result.memory_id for result in decision.selected} == {
        conversation_memory.id,
        project_memory.id,
        global_memory.id,
    }
    reasons = {result.memory_id: result.reasons for result in decision.selected}
    assert reasons[conversation_memory.id][0] == "project_match=0"
    assert reasons[project_memory.id][0] == "project_match=1"
    no_project = retrieve(
        (project_memory,),
        project_id=None,
        threshold="0",
    )
    assert no_project.excluded[0].exclusion_reason is RetrievalExclusionReason.SCOPE_MISMATCH


def test_every_primary_exclusion_has_exact_precedence_score_and_details() -> None:
    retained = memory(
        1,
        content="Same-memory",
        keywords=("alpha",),
        importance="1",
    )
    duplicate = memory(
        2,
        content="samememory",
        keywords=("alpha",),
    )
    limited = memory(
        3,
        content="different",
        keywords=("alpha",),
        importance="0.5",
    )
    below = memory(
        4,
        content="below",
        updated_at=NOW - timedelta(days=100),
    )
    scope_mismatch = memory(
        5,
        scope=MemoryScope.CONVERSATION,
        conversation_id=OTHER_CONVERSATION_ID,
        status=MemoryStatus.DELETED,
        content="scope first",
        expires_at=NOW - timedelta(days=1),
    )
    deleted = memory(
        6,
        status=MemoryStatus.DELETED,
        content="deleted before expiry",
        expires_at=NOW - timedelta(days=1),
    )
    expired = memory(
        7,
        content="expired",
        expires_at=NOW,
    )
    ids = SequenceIds()

    decision = retrieve(
        (
            expired,
            duplicate,
            scope_mismatch,
            retained,
            below,
            deleted,
            limited,
        ),
        ids=ids,
        request_text="alpha",
        threshold="0.1",
        limit=1,
    )

    assert tuple(result.memory_id for result in decision.selected) == (retained.id,)
    assert tuple(exclusion.memory_id for exclusion in decision.excluded) == (
        duplicate.id,
        limited.id,
        below.id,
        scope_mismatch.id,
        deleted.id,
        expired.id,
    )
    by_memory_id = {
        exclusion.memory_id: exclusion for exclusion in decision.excluded
    }
    assert by_memory_id[scope_mismatch.id].exclusion_reason is (
        RetrievalExclusionReason.SCOPE_MISMATCH
    )
    assert by_memory_id[scope_mismatch.id].computed_score is None
    assert set(by_memory_id[scope_mismatch.id].details) == {
        "scope",
        "request_conversation_id",
        "request_project_id",
        "memory_conversation_id",
        "memory_project_id",
    }
    assert by_memory_id[deleted.id].exclusion_reason is RetrievalExclusionReason.DELETED
    assert by_memory_id[deleted.id].computed_score is None
    assert set(by_memory_id[deleted.id].details) == {"stored_status", "deleted_at"}
    assert by_memory_id[expired.id].exclusion_reason is RetrievalExclusionReason.EXPIRED
    assert by_memory_id[expired.id].computed_score is None
    assert set(by_memory_id[expired.id].details) == {
        "stored_status",
        "expires_at",
        "evaluated_at",
    }
    assert by_memory_id[below.id].exclusion_reason is (
        RetrievalExclusionReason.SCORE_BELOW_THRESHOLD
    )
    assert by_memory_id[below.id].computed_score == UnitScore("0.03")
    assert dict(by_memory_id[below.id].details) == {
        "minimum_relevance_score": "0.1"
    }
    assert by_memory_id[duplicate.id].exclusion_reason is (
        RetrievalExclusionReason.DUPLICATE_CONTENT
    )
    assert dict(by_memory_id[duplicate.id].details) == {
        "retained_memory_id": str(retained.id)
    }
    assert by_memory_id[limited.id].exclusion_reason is (
        RetrievalExclusionReason.LIMIT_EXCEEDED
    )
    assert dict(by_memory_id[limited.id].details) == {
        "result_limit": 1,
        "pre_limit_rank": 1,
    }
    assert all(
        not {"content", "normalized_content"} & set(exclusion.details)
        for exclusion in decision.excluded
    )
    assert ids.calls == [identifier(number) for number in range(900, 907)]
    assert decision.selected[0].id == identifier(900)
    assert tuple(exclusion.id for exclusion in decision.excluded) == tuple(
        identifier(number) for number in range(901, 907)
    )
    assert all(
        evidence.context_packet_id == identifier(800)
        and evidence.created_at == NOW
        for evidence in (*decision.selected, *decision.excluded)
    )


def test_zero_limit_runs_after_duplicate_collapse() -> None:
    retained = memory(
        1,
        content="Equal!",
        keywords=("alpha",),
        importance="1",
    )
    duplicate = memory(
        2,
        content="equal",
        keywords=("alpha",),
        importance="1",
    )
    other = memory(3, content="other", keywords=("alpha",))

    decision = retrieve(
        (other, duplicate, retained),
        request_text="alpha",
        threshold="0",
        limit=0,
    )

    assert decision.selected == ()
    assert decision.confidence is None
    by_memory_id = {
        exclusion.memory_id: exclusion for exclusion in decision.excluded
    }
    assert by_memory_id[retained.id].exclusion_reason is (
        RetrievalExclusionReason.LIMIT_EXCEEDED
    )
    assert by_memory_id[retained.id].details["pre_limit_rank"] == 0
    assert by_memory_id[duplicate.id].exclusion_reason is (
        RetrievalExclusionReason.DUPLICATE_CONTENT
    )
    assert by_memory_id[duplicate.id].details["retained_memory_id"] == str(retained.id)
    assert by_memory_id[other.id].exclusion_reason is (
        RetrievalExclusionReason.LIMIT_EXCEEDED
    )
    assert by_memory_id[other.id].details["pre_limit_rank"] == 1


def test_candidate_order_permutations_produce_identical_decisions_and_ids() -> None:
    candidates = (
        memory(1, content="selected", keywords=("alpha",), importance="1"),
        memory(2, content="below", updated_at=NOW - timedelta(days=100)),
        memory(
            3,
            scope=MemoryScope.CONVERSATION,
            conversation_id=OTHER_CONVERSATION_ID,
            content="wrong scope",
        ),
        memory(4, content="also selected", keywords=("alpha",), importance="0.5"),
    )
    expected = retrieve(
        candidates,
        request_text="alpha",
        threshold="0.1",
        limit=2,
    )

    for candidate_order in permutations(candidates):
        assert retrieve(
            candidate_order,
            request_text="alpha",
            threshold="0.1",
            limit=2,
        ) == expected


def test_canonical_tie_breakers_use_importance_then_time_then_uuid() -> None:
    higher_importance_global = memory(
        1,
        content="global",
        importance="0.7",
    )
    lower_importance_conversation = memory(
        2,
        scope=MemoryScope.CONVERSATION,
        content="conversation",
        importance="0.5",
    )
    importance_tie = retrieve(
        (lower_importance_conversation, higher_importance_global),
        threshold="0",
        limit=2,
    )
    assert tuple(item.score for item in importance_tie.selected) == (
        UnitScore("0.2"),
        UnitScore("0.2"),
    )
    assert tuple(item.memory_id for item in importance_tie.selected) == (
        higher_importance_global.id,
        lower_importance_conversation.id,
    )

    older = memory(
        3,
        content="older",
        importance="0.5",
        updated_at=NOW - timedelta(days=120),
    )
    newer = memory(
        4,
        content="newer",
        importance="0.5",
        updated_at=NOW - timedelta(days=100),
    )
    same_time_larger_uuid = memory(
        6,
        content="larger UUID",
        importance="0.5",
        updated_at=NOW - timedelta(days=100),
    )
    same_time_smaller_uuid = memory(
        5,
        content="smaller UUID",
        importance="0.5",
        updated_at=NOW - timedelta(days=100),
    )
    time_uuid_tie = retrieve(
        (same_time_larger_uuid, older, same_time_smaller_uuid, newer),
        threshold="0",
        limit=4,
    )
    assert tuple(item.memory_id for item in time_uuid_tie.selected) == (
        newer.id,
        same_time_smaller_uuid.id,
        same_time_larger_uuid.id,
        older.id,
    )
