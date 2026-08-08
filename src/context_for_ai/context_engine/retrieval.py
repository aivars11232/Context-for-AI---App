"""Pure deterministic keyword retrieval for TASK-0009."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
import unicodedata

from context_for_ai.domain.decisions import RetrievalExclusion, RetrievalResult
from context_for_ai.domain.entities import Memory
from context_for_ai.domain.enums import (
    MemoryScope,
    MemoryStatus,
    MemoryType,
    RetrievalExclusionReason,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.context import RetrievalDecision, RetrievalRequest
from context_for_ai.domain.ports.system import IdGenerator
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    canonical_decimal_string,
    format_utc_timestamp,
)


_SCORE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_ZERO = Decimal("0")
_ONE = Decimal("1")
_SECONDS_PER_DAY = Decimal("86400")
_MICROSECONDS_PER_SECOND = Decimal("1000000")
_RECENCY_DAYS = Decimal("90")
_FACTOR_NAMES = (
    "project_match",
    "topic_match",
    "keyword_jaccard",
    "recency",
    "importance",
    "scope_match",
    "correction_match",
)
_FACTOR_WEIGHTS = (
    Decimal("0.30"),
    Decimal("0.20"),
    Decimal("0.20"),
    Decimal("0.10"),
    Decimal("0.10"),
    Decimal("0.05"),
    Decimal("0.05"),
)
_SCOPE_FACTORS = {
    MemoryScope.CONVERSATION: Decimal("1.00"),
    MemoryScope.PROJECT: Decimal("0.80"),
    MemoryScope.GLOBAL: Decimal("0.60"),
}


@dataclass(frozen=True, slots=True)
class _ScoredMemory:
    memory: Memory
    normalized_content: str
    factors: tuple[Decimal, ...]
    score: Decimal


@dataclass(frozen=True, slots=True)
class _ExclusionDraft:
    memory: Memory
    reason: RetrievalExclusionReason
    score: Decimal | None
    details: FrozenJsonObject


def _retrieval_tokens(value: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise LifecycleInvariantError("Retrieval normalization requires text.")
    normalized = unicodedata.normalize("NFC", value).casefold()
    without_punctuation = "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("P")
    )
    return tuple(without_punctuation.split())


def normalize_retrieval_content(value: str) -> str:
    """Return canonical punctuation-deleting retrieval content."""

    return " ".join(_retrieval_tokens(value))


def _array_tokens(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(token for value in values for token in _retrieval_tokens(value))


def _scope_eligible(memory: Memory, request: RetrievalRequest) -> bool:
    if memory.scope is MemoryScope.CONVERSATION:
        return memory.conversation_id == request.conversation_id
    if memory.scope is MemoryScope.PROJECT:
        return (
            request.project_id is not None
            and memory.project_id == request.project_id
        )
    return True


def _scope_mismatch_details(
    memory: Memory,
    request: RetrievalRequest,
) -> FrozenJsonObject:
    return FrozenJsonObject(
        {
            "scope": memory.scope.value,
            "request_conversation_id": str(request.conversation_id),
            "request_project_id": (
                None if request.project_id is None else str(request.project_id)
            ),
            "memory_conversation_id": (
                None if memory.conversation_id is None else str(memory.conversation_id)
            ),
            "memory_project_id": (
                None if memory.project_id is None else str(memory.project_id)
            ),
        }
    )


def _elapsed_microseconds(memory: Memory, request: RetrievalRequest) -> int:
    if request.evaluated_at <= memory.updated_at:
        return 0
    elapsed = request.evaluated_at - memory.updated_at
    return (
        (elapsed.days * 86400 + elapsed.seconds) * 1_000_000
        + elapsed.microseconds
    )


def _score_memory(
    memory: Memory,
    request: RetrievalRequest,
    request_tokens: frozenset[str],
    active_topic_tokens: frozenset[str],
) -> _ScoredMemory:
    keyword_tokens = frozenset(_array_tokens(memory.keywords))
    topic_tokens = frozenset(_array_tokens(memory.topic_terms))

    with localcontext(_SCORE_CONTEXT):
        project_match = (
            _ONE
            if memory.scope is MemoryScope.PROJECT
            and request.project_id is not None
            and memory.project_id == request.project_id
            else _ZERO
        )
        topic_match = (
            _ONE
            if active_topic_tokens and active_topic_tokens & topic_tokens
            else _ZERO
        )
        keyword_union = request_tokens | keyword_tokens
        keyword_jaccard = (
            Decimal(len(request_tokens & keyword_tokens))
            / Decimal(len(keyword_union))
            if keyword_union
            else _ZERO
        )
        elapsed_seconds = (
            Decimal(_elapsed_microseconds(memory, request))
            / _MICROSECONDS_PER_SECOND
        )
        age_days = elapsed_seconds / _SECONDS_PER_DAY
        recency = max(_ZERO, _ONE - age_days / _RECENCY_DAYS)
        importance = memory.importance.value
        scope_match = _SCOPE_FACTORS[memory.scope]
        correction_match = (
            _ONE
            if memory.memory_type is MemoryType.CORRECTION_RULE
            and bool(request_tokens & keyword_tokens)
            else _ZERO
        )
        factors = (
            project_match,
            topic_match,
            keyword_jaccard,
            recency,
            importance,
            scope_match,
            correction_match,
        )
        score = _ZERO
        for weight, factor in zip(_FACTOR_WEIGHTS, factors, strict=True):
            score += weight * factor

    return _ScoredMemory(
        memory,
        normalize_retrieval_content(memory.content),
        factors,
        score,
    )


def _canonical_score_order(scored: list[_ScoredMemory]) -> None:
    scored.sort(key=lambda item: str(item.memory.id))
    scored.sort(key=lambda item: item.memory.updated_at, reverse=True)
    scored.sort(key=lambda item: item.memory.importance.value, reverse=True)
    scored.sort(key=lambda item: item.score, reverse=True)


def _selected_reasons(scored: _ScoredMemory) -> tuple[str, ...]:
    return tuple(
        f"{name}={canonical_decimal_string(value)}"
        for name, value in zip(_FACTOR_NAMES, scored.factors, strict=True)
    )


class DeterministicContextRetriever:
    """Partition considered memories without repositories, clocks, or mutation."""

    def __init__(self, id_generator: IdGenerator) -> None:
        self._id_generator = id_generator

    def retrieve(self, request: RetrievalRequest) -> RetrievalDecision:
        request_tokens = frozenset(_retrieval_tokens(request.request_text))
        active_topic_tokens = frozenset(
            ()
            if request.active_topic_label is None
            else _retrieval_tokens(request.active_topic_label)
        )
        exclusions: dict[DomainId, _ExclusionDraft] = {}
        qualifying: list[_ScoredMemory] = []

        for memory in sorted(request.candidate_memories, key=lambda item: str(item.id)):
            if not _scope_eligible(memory, request):
                exclusions[memory.id] = _ExclusionDraft(
                    memory,
                    RetrievalExclusionReason.SCOPE_MISMATCH,
                    None,
                    _scope_mismatch_details(memory, request),
                )
                continue
            if memory.status is MemoryStatus.DELETED:
                if memory.deleted_at is None:
                    raise LifecycleInvariantError(
                        "Deleted retrieval memory requires deleted_at."
                    )
                exclusions[memory.id] = _ExclusionDraft(
                    memory,
                    RetrievalExclusionReason.DELETED,
                    None,
                    FrozenJsonObject(
                        {
                            "stored_status": memory.status.value,
                            "deleted_at": format_utc_timestamp(memory.deleted_at),
                        }
                    ),
                )
                continue
            if (
                memory.expires_at is not None
                and memory.expires_at <= request.evaluated_at
            ):
                exclusions[memory.id] = _ExclusionDraft(
                    memory,
                    RetrievalExclusionReason.EXPIRED,
                    None,
                    FrozenJsonObject(
                        {
                            "stored_status": memory.status.value,
                            "expires_at": format_utc_timestamp(memory.expires_at),
                            "evaluated_at": format_utc_timestamp(
                                request.evaluated_at
                            ),
                        }
                    ),
                )
                continue

            scored = _score_memory(
                memory,
                request,
                request_tokens,
                active_topic_tokens,
            )
            if scored.score < request.minimum_relevance_score.value:
                exclusions[memory.id] = _ExclusionDraft(
                    memory,
                    RetrievalExclusionReason.SCORE_BELOW_THRESHOLD,
                    scored.score,
                    FrozenJsonObject(
                        {
                            "minimum_relevance_score": canonical_decimal_string(
                                request.minimum_relevance_score.value
                            )
                        }
                    ),
                )
            else:
                qualifying.append(scored)

        _canonical_score_order(qualifying)
        retained_by_content: dict[str, _ScoredMemory] = {}
        deduplicated: list[_ScoredMemory] = []
        for scored in qualifying:
            retained = retained_by_content.get(scored.normalized_content)
            if retained is not None:
                exclusions[scored.memory.id] = _ExclusionDraft(
                    scored.memory,
                    RetrievalExclusionReason.DUPLICATE_CONTENT,
                    scored.score,
                    FrozenJsonObject(
                        {"retained_memory_id": str(retained.memory.id)}
                    ),
                )
                continue
            retained_by_content[scored.normalized_content] = scored
            deduplicated.append(scored)

        selected_drafts = deduplicated[: request.result_limit]
        for pre_limit_rank, scored in enumerate(
            deduplicated[request.result_limit :],
            start=request.result_limit,
        ):
            exclusions[scored.memory.id] = _ExclusionDraft(
                scored.memory,
                RetrievalExclusionReason.LIMIT_EXCEEDED,
                scored.score,
                FrozenJsonObject(
                    {
                        "result_limit": request.result_limit,
                        "pre_limit_rank": pre_limit_rank,
                    }
                ),
            )

        selected = tuple(
            RetrievalResult(
                self._id_generator.new_id(),
                request.context_packet_id,
                scored.memory.id,
                rank,
                UnitScore(scored.score),
                _selected_reasons(scored),
                request.evaluated_at,
            )
            for rank, scored in enumerate(selected_drafts)
        )
        excluded = tuple(
            RetrievalExclusion(
                self._id_generator.new_id(),
                request.context_packet_id,
                draft.memory.id,
                draft.reason,
                None if draft.score is None else UnitScore(draft.score),
                draft.details,
                request.evaluated_at,
            )
            for draft in sorted(exclusions.values(), key=lambda item: str(item.memory.id))
        )
        if len(selected) + len(excluded) != len(request.candidate_memories):
            raise LifecycleInvariantError(
                "Retrieval must partition every considered memory exactly once."
            )
        return RetrievalDecision(
            selected,
            excluded,
            selected[0].score if selected else None,
        )


__all__ = ["DeterministicContextRetriever", "normalize_retrieval_content"]
