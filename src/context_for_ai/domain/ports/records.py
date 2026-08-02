"""Immutable records exchanged across persistence port boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from context_for_ai.domain.decisions import (
    ContextPacket,
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.entities import Memory, MemoryRevision, MemorySource
from context_for_ai.domain.enums import EvaluationProviderMode
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import require_memory_provenance
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
        require_memory_provenance(self.memory, sources)
        if any(revision.memory_id != self.memory.id for revision in revisions):
            raise LifecycleInvariantError(
                "Every memory revision must belong to the aggregate memory."
            )
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "revisions", revisions)


@dataclass(frozen=True, slots=True)
class ContextPacketRecord:
    """One immutable packet with selected and excluded retrieval evidence."""

    packet: ContextPacket
    retrieval_results: tuple[RetrievalResult, ...]
    retrieval_exclusions: tuple[RetrievalExclusion, ...]

    def __post_init__(self) -> None:
        retrieval_results = tuple(self.retrieval_results)
        retrieval_exclusions = tuple(self.retrieval_exclusions)
        if any(
            result.context_packet_id != self.packet.id
            for result in retrieval_results
        ):
            raise LifecycleInvariantError(
                "Every retrieval result must belong to the aggregate packet."
            )
        if any(
            exclusion.context_packet_id != self.packet.id
            for exclusion in retrieval_exclusions
        ):
            raise LifecycleInvariantError(
                "Every retrieval exclusion must belong to the aggregate packet."
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
