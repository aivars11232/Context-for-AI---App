"""Immutable records exchanged across persistence port boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from context_for_ai.domain.decisions import (
    ContextPacket,
    RetrievalExclusion,
    RetrievalResult,
    require_retrieval_evidence,
)
from context_for_ai.domain.entities import Memory, MemoryRevision, MemorySource
from context_for_ai.domain.enums import EvaluationProviderMode
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import require_memory_history
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    FrozenJsonValue,
    ensure_utc,
    freeze_json,
)


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _normalize_time(instance: object, field_name: str) -> datetime:
    value = ensure_utc(getattr(instance, field_name))
    object.__setattr__(instance, field_name, value)
    return value


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One memory with all durable provenance and immutable revisions."""

    memory: Memory
    sources: tuple[MemorySource, ...]
    revisions: tuple[MemoryRevision, ...]

    def __post_init__(self) -> None:
        sources = tuple(self.sources)
        revisions = tuple(self.revisions)
        require_memory_history(self.memory, sources, revisions)
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "revisions", revisions)


@dataclass(frozen=True, slots=True)
class ContextPacketRecord:
    """One immutable packet with selected and excluded retrieval evidence."""

    packet: ContextPacket
    retrieval_results: tuple[RetrievalResult, ...]
    retrieval_exclusions: tuple[RetrievalExclusion, ...]

    def __post_init__(self) -> None:
        retrieval_results, retrieval_exclusions = require_retrieval_evidence(
            self.retrieval_results,
            self.retrieval_exclusions,
            context_packet_id=self.packet.id,
        )

        payload_retrieval = self.packet.packet_json["retrieval"]
        if not isinstance(payload_retrieval, tuple):
            raise LifecycleInvariantError(
                "Context packet retrieval payload must be an immutable array."
            )
        if len(payload_retrieval) != len(retrieval_results):
            raise LifecycleInvariantError(
                "Context packet selected snapshots must bijectively match retrieval results."
            )
        for snapshot, result in zip(payload_retrieval, retrieval_results, strict=True):
            if not isinstance(snapshot, FrozenJsonObject) or (
                snapshot["memory_id"] != str(result.memory_id)
                or snapshot["rank"] != result.rank
                or snapshot["score"] != result.score.value
                or snapshot["reasons"] != result.reasons
            ):
                raise LifecycleInvariantError(
                    "Context packet selected snapshot must match its retrieval result."
                )
        confidence = self.packet.packet_json["confidence"]
        if not isinstance(confidence, FrozenJsonObject):
            raise LifecycleInvariantError("Context packet confidence must be an object.")
        expected_retrieval_confidence = (
            None if not retrieval_results else retrieval_results[0].score.value
        )
        if confidence["retrieval"] != expected_retrieval_confidence:
            raise LifecycleInvariantError(
                "Context packet retrieval confidence must match the upstream decision."
            )

        object.__setattr__(self, "retrieval_results", retrieval_results)
        object.__setattr__(self, "retrieval_exclusions", retrieval_exclusions)


@dataclass(frozen=True, slots=True)
class Setting:
    """One validated, non-secret presentation setting value."""

    key: str
    value: FrozenJsonValue
    updated_at: datetime

    def __post_init__(self) -> None:
        _required_text("Setting.key", self.key)
        object.__setattr__(self, "value", freeze_json(self.value))
        _normalize_time(self, "updated_at")


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """Opaque persisted evaluation case pending its later-task JSON contract."""

    id: DomainId
    name: str
    category: str
    case: FrozenJsonObject
    enabled: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _required_text("EvaluationCase.name", self.name)
        _required_text("EvaluationCase.category", self.category)
        if not isinstance(self.enabled, bool):
            raise LifecycleInvariantError("EvaluationCase.enabled must be boolean.")
        if not isinstance(self.case, FrozenJsonObject):
            object.__setattr__(self, "case", FrozenJsonObject(self.case))
        created_at = _normalize_time(self, "created_at")
        updated_at = _normalize_time(self, "updated_at")
        if updated_at < created_at:
            raise LifecycleInvariantError(
                "EvaluationCase.updated_at cannot precede created_at."
            )


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """Opaque persisted evaluation outcome pending its later-task JSON contract."""

    id: DomainId
    evaluation_case_id: DomainId
    fixture_version: str
    provider_mode: EvaluationProviderMode
    result: FrozenJsonObject
    passed: bool
    created_at: datetime

    def __post_init__(self) -> None:
        _required_text("EvaluationRun.fixture_version", self.fixture_version)
        if not isinstance(self.passed, bool):
            raise LifecycleInvariantError("EvaluationRun.passed must be boolean.")
        if not isinstance(self.result, FrozenJsonObject):
            object.__setattr__(self, "result", FrozenJsonObject(self.result))
        _normalize_time(self, "created_at")
