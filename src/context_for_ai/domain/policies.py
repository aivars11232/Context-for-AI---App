"""Deterministic structural policies for canonical domain lifecycles."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import IntEnum, StrEnum, unique

from context_for_ai.domain.entities import (
    ConversationState,
    ConversationTask,
    Memory,
    MemoryRevision,
    MemorySource,
)
from context_for_ai.domain.enums import (
    MemoryRevisionOperation,
    MemoryEffectiveStatus,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    ModelRequestStatus,
    ProcessingRunStatus,
    ProjectStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import (
    DomainError,
    InvalidStateTransitionError,
    LifecycleInvariantError,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    canonical_decimal_string,
    ensure_utc,
    format_utc_timestamp,
    parse_utc_timestamp,
)


@unique
class PriorityBand(IntEnum):
    """Canonical numeric authority bands without later-task source selection."""

    ASSUMED = 0
    RETRIEVED_MEMORY = 400
    GLOBAL_PREFERENCE = 500
    CORRECTION_MEMORY = 600
    TASK_OR_OUTPUT_POLICY = 800
    TRUE_CONDITIONAL = 900
    CURRENT_HARD = 1000


@unique
class ConfidenceBand(StrEnum):
    """Named confidence outcomes from the canonical unrounded thresholds."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


TERMINAL_TASK_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.CANCELLED})
TERMINAL_PROCESSING_RUN_STATUSES = frozenset(
    {
        ProcessingRunStatus.SUCCEEDED,
        ProcessingRunStatus.NEEDS_CLARIFICATION,
        ProcessingRunStatus.CONTROLLED_FAILURE,
        ProcessingRunStatus.FAILED,
        ProcessingRunStatus.CANCELLED,
    }
)
NON_TERMINAL_PROCESSING_RUN_STATUSES = frozenset(ProcessingRunStatus).difference(
    TERMINAL_PROCESSING_RUN_STATUSES
)
TERMINAL_MODEL_REQUEST_STATUSES = frozenset(
    {
        ModelRequestStatus.SUCCEEDED,
        ModelRequestStatus.TIMED_OUT,
        ModelRequestStatus.CANCELLED,
        ModelRequestStatus.FAILED,
    }
)
MEMORY_REVISION_SCHEMA_VERSION = "memory-revision-v1"

_MEMORY_REVISION_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "source_id",
        "memory_type",
        "scope",
        "conversation_id",
        "project_id",
        "status",
        "keywords",
        "topic_terms",
        "importance",
        "confidence",
        "expires_at",
        "memory_created_at",
        "updated_at",
        "deleted_at",
    }
)


_PROJECT_TRANSITIONS = {
    ProjectStatus.ACTIVE: frozenset({ProjectStatus.ARCHIVED}),
    ProjectStatus.ARCHIVED: frozenset(),
}

_TASK_TRANSITIONS = {
    TaskStatus.OPEN: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset({TaskStatus.OPEN}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.OPEN}),
}

_PROCESSING_RUN_TRANSITIONS = {
    ProcessingRunStatus.PERSISTED: frozenset(
        {
            ProcessingRunStatus.CONTEXT_READY,
            ProcessingRunStatus.NEEDS_CLARIFICATION,
            ProcessingRunStatus.CONTROLLED_FAILURE,
            ProcessingRunStatus.FAILED,
        }
    ),
    ProcessingRunStatus.CONTEXT_READY: frozenset(
        {
            ProcessingRunStatus.GENERATING,
            ProcessingRunStatus.FAILED,
            ProcessingRunStatus.CANCELLED,
        }
    ),
    ProcessingRunStatus.GENERATING: frozenset(
        {
            ProcessingRunStatus.SUCCEEDED,
            ProcessingRunStatus.REVISING,
            ProcessingRunStatus.CONTROLLED_FAILURE,
            ProcessingRunStatus.FAILED,
            ProcessingRunStatus.CANCELLED,
        }
    ),
    ProcessingRunStatus.REVISING: frozenset(
        {
            ProcessingRunStatus.SUCCEEDED,
            ProcessingRunStatus.REVISING,
            ProcessingRunStatus.CONTROLLED_FAILURE,
            ProcessingRunStatus.FAILED,
            ProcessingRunStatus.CANCELLED,
        }
    ),
    **{status: frozenset() for status in TERMINAL_PROCESSING_RUN_STATUSES},
}

_MODEL_REQUEST_TRANSITIONS = {
    ModelRequestStatus.PENDING: frozenset({ModelRequestStatus.IN_FLIGHT}),
    ModelRequestStatus.IN_FLIGHT: TERMINAL_MODEL_REQUEST_STATUSES,
    **{status: frozenset() for status in TERMINAL_MODEL_REQUEST_STATUSES},
}


def require_priority_band(value: int) -> PriorityBand:
    """Return the named canonical band or reject an invented numeric priority."""

    if not isinstance(value, int) or isinstance(value, bool):
        raise LifecycleInvariantError("Constraint priority must be an integer band.")
    try:
        return PriorityBand(value)
    except ValueError as error:
        raise LifecycleInvariantError(f"Unknown canonical priority band: {value}.") from error


def confidence_band(score: UnitScore) -> ConfidenceBand:
    """Classify an unrounded unit score using the canonical confidence thresholds."""

    if score.value >= UnitScore("0.80").value:
        return ConfidenceBand.HIGH
    if score.value >= UnitScore("0.50").value:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def overall_confidence(
    *,
    interpretation: UnitScore,
    reference_resolution: UnitScore | None = None,
    retrieval: UnitScore | None = None,
) -> UnitScore:
    """Return the exact normalized weighted mean of applicable confidence factors."""

    factors = ((interpretation, Decimal("0.50")),)
    optional_factors = (
        (reference_resolution, Decimal("0.30")),
        (retrieval, Decimal("0.20")),
    )
    applicable = factors + tuple(
        (score, weight) for score, weight in optional_factors if score is not None
    )
    total_weight = sum((weight for _, weight in applicable), Decimal(0))
    weighted_score = sum(
        (score.value * weight for score, weight in applicable),
        Decimal(0),
    )
    return UnitScore(weighted_score / total_weight)


def requires_confidence_clarification(
    score: UnitScore,
    *,
    material: bool,
) -> bool:
    """Return whether an unrounded confidence result blocks a material decision."""

    if not isinstance(material, bool):
        raise LifecycleInvariantError("Confidence materiality must be boolean.")
    return material and confidence_band(score) is not ConfidenceBand.HIGH


def is_terminal_task(status: TaskStatus) -> bool:
    """Return whether a conversation-task status is terminal."""

    return status in TERMINAL_TASK_STATUSES


def is_terminal_processing_run(status: ProcessingRunStatus) -> bool:
    """Return whether a processing run has reached its sole terminal state."""

    return status in TERMINAL_PROCESSING_RUN_STATUSES


def is_terminal_model_request(status: ModelRequestStatus) -> bool:
    """Return whether a model transport request can no longer transition."""

    return status in TERMINAL_MODEL_REQUEST_STATUSES


def _require_transition(
    lifecycle: str,
    current: StrEnum,
    target: StrEnum,
    transitions: dict[StrEnum, frozenset[StrEnum]],
) -> None:
    if target not in transitions[current]:
        raise InvalidStateTransitionError(lifecycle, current, target)


def require_project_transition(
    current: ProjectStatus,
    target: ProjectStatus,
    *,
    has_non_terminal_run: bool = False,
) -> None:
    """Require the explicit archive transition and its active-run guard."""

    _require_transition("project", current, target, _PROJECT_TRANSITIONS)
    if has_non_terminal_run:
        raise LifecycleInvariantError(
            "An active project cannot be archived while a processing run is non-terminal."
        )


def require_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    """Require an explicit canonical conversation-task transition."""

    _require_transition("task", current, target, _TASK_TRANSITIONS)


def require_processing_run_transition(
    current: ProcessingRunStatus,
    target: ProcessingRunStatus,
    *,
    recovery: bool = False,
) -> None:
    """Require a canonical run transition, including recovery-to-failed only."""

    if recovery:
        if (
            current not in NON_TERMINAL_PROCESSING_RUN_STATUSES
            or target is not ProcessingRunStatus.FAILED
        ):
            raise InvalidStateTransitionError("processing run recovery", current, target)
        return
    _require_transition("processing run", current, target, _PROCESSING_RUN_TRANSITIONS)


def require_model_request_transition(
    current: ModelRequestStatus,
    target: ModelRequestStatus,
) -> None:
    """Require the one-way canonical model transport lifecycle."""

    _require_transition("model request", current, target, _MODEL_REQUEST_TRANSITIONS)


def require_active_task_consistency(
    state: ConversationState,
    active_task: ConversationTask | None,
) -> None:
    """Require an active state to reference one matching non-terminal task."""

    if state.active_task_id is None:
        if active_task is not None:
            raise LifecycleInvariantError(
                "An active task record was supplied for a state with no active_task_id."
            )
        return
    if active_task is None or active_task.id != state.active_task_id:
        raise LifecycleInvariantError("State active_task_id requires its matching task.")
    if active_task.conversation_id != state.conversation_id:
        raise LifecycleInvariantError("Active task must belong to the state conversation.")
    if is_terminal_task(active_task.status):
        raise LifecycleInvariantError("An active task cannot be terminal.")


def require_memory_provenance(
    memory: Memory,
    sources: tuple[MemorySource, ...],
) -> None:
    """Require one or more provenance records owned by the memory."""

    frozen_sources = tuple(sources)
    if not frozen_sources:
        raise LifecycleInvariantError("Memory requires at least one provenance source.")
    if any(source.memory_id != memory.id for source in frozen_sources):
        raise LifecycleInvariantError("Every provenance source must belong to the memory.")


def memory_revision_metadata(memory: Memory, source_id: DomainId) -> FrozenJsonObject:
    """Return the exact canonical snapshot metadata for one memory revision."""

    return FrozenJsonObject(
        {
            "schema_version": MEMORY_REVISION_SCHEMA_VERSION,
            "source_id": str(source_id),
            "memory_type": memory.memory_type.value,
            "scope": memory.scope.value,
            "conversation_id": (
                None if memory.conversation_id is None else str(memory.conversation_id)
            ),
            "project_id": None if memory.project_id is None else str(memory.project_id),
            "status": memory.status.value,
            "keywords": memory.keywords,
            "topic_terms": memory.topic_terms,
            "importance": canonical_decimal_string(memory.importance.value),
            "confidence": canonical_decimal_string(memory.confidence.value),
            "expires_at": (
                None
                if memory.expires_at is None
                else format_utc_timestamp(memory.expires_at)
            ),
            "memory_created_at": format_utc_timestamp(memory.created_at),
            "updated_at": format_utc_timestamp(memory.updated_at),
            "deleted_at": (
                None
                if memory.deleted_at is None
                else format_utc_timestamp(memory.deleted_at)
            ),
        }
    )


def _metadata_text(metadata: FrozenJsonObject, key: str) -> str:
    value = metadata[key]
    if not isinstance(value, str):
        raise LifecycleInvariantError(f"Memory revision metadata {key!r} must be text.")
    return value


def _metadata_optional_id(metadata: FrozenJsonObject, key: str) -> DomainId | None:
    value = metadata[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise LifecycleInvariantError(
            f"Memory revision metadata {key!r} must be a UUID string or null."
        )
    return DomainId(value)


def _metadata_optional_time(metadata: FrozenJsonObject, key: str) -> datetime | None:
    value = metadata[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise LifecycleInvariantError(
            f"Memory revision metadata {key!r} must be a UTC string or null."
        )
    return parse_utc_timestamp(value)


def _metadata_text_tuple(metadata: FrozenJsonObject, key: str) -> tuple[str, ...]:
    value = metadata[key]
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise LifecycleInvariantError(
            f"Memory revision metadata {key!r} must be an ordered string array."
        )
    return value


def _memory_revision_snapshot(revision: MemoryRevision) -> Memory:
    metadata = revision.metadata
    if set(metadata) != _MEMORY_REVISION_METADATA_KEYS:
        raise LifecycleInvariantError(
            "Memory revision metadata must contain exactly the memory-revision-v1 keys."
        )
    if metadata["schema_version"] != MEMORY_REVISION_SCHEMA_VERSION:
        raise LifecycleInvariantError(
            "Memory revision metadata requires schema_version memory-revision-v1."
        )
    try:
        importance_text = _metadata_text(metadata, "importance")
        confidence_text = _metadata_text(metadata, "confidence")
        importance_decimal = Decimal(importance_text)
        confidence_decimal = Decimal(confidence_text)
        if canonical_decimal_string(importance_decimal) != importance_text:
            raise LifecycleInvariantError(
                "Memory revision importance must be a canonical decimal string."
            )
        if canonical_decimal_string(confidence_decimal) != confidence_text:
            raise LifecycleInvariantError(
                "Memory revision confidence must be a canonical decimal string."
            )
        return Memory(
            revision.memory_id,
            _metadata_optional_id(metadata, "conversation_id"),
            _metadata_optional_id(metadata, "project_id"),
            MemoryType(_metadata_text(metadata, "memory_type")),
            MemoryScope(_metadata_text(metadata, "scope")),
            MemoryStatus(_metadata_text(metadata, "status")),
            revision.content_snapshot,
            _metadata_text_tuple(metadata, "keywords"),
            _metadata_text_tuple(metadata, "topic_terms"),
            UnitScore(importance_decimal),
            UnitScore(confidence_decimal),
            _metadata_optional_time(metadata, "expires_at"),
            parse_utc_timestamp(_metadata_text(metadata, "memory_created_at")),
            parse_utc_timestamp(_metadata_text(metadata, "updated_at")),
            _metadata_optional_time(metadata, "deleted_at"),
        )
    except LifecycleInvariantError:
        raise
    except (DomainError, InvalidOperation, KeyError, TypeError, ValueError) as error:
        raise LifecycleInvariantError("Memory revision metadata is invalid.") from error


def require_memory_history(
    memory: Memory,
    sources: tuple[MemorySource, ...],
    revisions: tuple[MemoryRevision, ...],
) -> None:
    """Require complete ordered manual provenance and immutable revision history."""

    frozen_sources = tuple(sources)
    frozen_revisions = tuple(revisions)
    require_memory_provenance(memory, frozen_sources)
    if not frozen_revisions:
        raise LifecycleInvariantError("Memory requires at least one immutable revision.")
    if len(frozen_sources) != len(frozen_revisions):
        raise LifecycleInvariantError(
            "Memory requires exactly one provenance source per revision."
        )
    if len({source.id for source in frozen_sources}) != len(frozen_sources):
        raise LifecycleInvariantError("Memory provenance source IDs must be distinct.")
    if len({revision.id for revision in frozen_revisions}) != len(frozen_revisions):
        raise LifecycleInvariantError("Memory revision IDs must be distinct.")
    if frozen_sources != tuple(
        sorted(frozen_sources, key=lambda source: (source.created_at, str(source.id)))
    ):
        raise LifecycleInvariantError(
            "Memory provenance sources must be ordered by creation time and UUID."
        )
    if tuple(revision.revision_number for revision in frozen_revisions) != tuple(
        range(1, len(frozen_revisions) + 1)
    ):
        raise LifecycleInvariantError(
            "Memory revisions must have consecutive ordered numbers starting at 1."
        )

    sources_by_id = {str(source.id): source for source in frozen_sources}
    used_source_ids: set[str] = set()
    immutable_identity: tuple[object, ...] | None = None
    final_snapshot: Memory | None = None
    previous_snapshot: Memory | None = None
    soft_deleted = False

    for revision in frozen_revisions:
        if revision.memory_id != memory.id:
            raise LifecycleInvariantError(
                "Every memory revision must belong to the aggregate memory."
            )
        try:
            source_id = _metadata_text(revision.metadata, "source_id")
            source = sources_by_id[source_id]
        except KeyError as error:
            raise LifecycleInvariantError(
                "Every memory revision must reference its matching provenance source."
            ) from error
        if source_id in used_source_ids:
            raise LifecycleInvariantError(
                "Each memory revision must reference a distinct provenance source."
            )
        used_source_ids.add(source_id)
        if source.memory_id != memory.id:
            raise LifecycleInvariantError(
                "Every provenance source must belong to the aggregate memory."
            )
        if source.source_message_id is not None:
            raise LifecycleInvariantError(
                "Manual memory sources require null source_message_id."
            )

        snapshot = _memory_revision_snapshot(revision)
        if revision.metadata != memory_revision_metadata(snapshot, source.id):
            raise LifecycleInvariantError(
                "Memory revision metadata is not in canonical memory-revision-v1 form."
            )
        if not (
            source.created_at == revision.created_at == snapshot.updated_at
        ):
            raise LifecycleInvariantError(
                "Memory source, revision, and snapshot must share one operation time."
            )

        identity = (
            snapshot.memory_type,
            snapshot.scope,
            snapshot.conversation_id,
            snapshot.project_id,
            snapshot.created_at,
        )
        if immutable_identity is None:
            immutable_identity = identity
        elif identity != immutable_identity:
            raise LifecycleInvariantError(
                "Memory type, scope, owners, and creation time are immutable."
            )
        if (
            previous_snapshot is not None
            and snapshot.updated_at < previous_snapshot.updated_at
        ):
            raise LifecycleInvariantError(
                "Memory revision operation times cannot move backward."
            )

        if soft_deleted:
            raise LifecycleInvariantError("No memory revision may follow SOFT_DELETE.")
        if revision.revision_number == 1:
            if (
                revision.operation is not MemoryRevisionOperation.CREATE
                or source.source_kind is not MemorySourceKind.MANUAL_ENTRY
                or snapshot.status is not MemoryStatus.ACTIVE
                or snapshot.created_at != snapshot.updated_at
            ):
                raise LifecycleInvariantError(
                    "Revision 1 must be one ACTIVE CREATE with a MANUAL_ENTRY source."
                )
        elif revision.operation is MemoryRevisionOperation.EDIT:
            if (
                source.source_kind is not MemorySourceKind.USER_EDIT
                or snapshot.status is not MemoryStatus.ACTIVE
            ):
                raise LifecycleInvariantError(
                    "EDIT requires an ACTIVE snapshot and USER_EDIT source."
                )
        elif revision.operation is MemoryRevisionOperation.SOFT_DELETE:
            if (
                source.source_kind is not MemorySourceKind.USER_EDIT
                or snapshot.status is not MemoryStatus.DELETED
                or snapshot.deleted_at != snapshot.updated_at
            ):
                raise LifecycleInvariantError(
                    "SOFT_DELETE requires a DELETED snapshot and USER_EDIT source."
                )
            if previous_snapshot is None or (
                snapshot.content,
                snapshot.keywords,
                snapshot.topic_terms,
                snapshot.importance,
                snapshot.confidence,
                snapshot.expires_at,
            ) != (
                previous_snapshot.content,
                previous_snapshot.keywords,
                previous_snapshot.topic_terms,
                previous_snapshot.importance,
                previous_snapshot.confidence,
                previous_snapshot.expires_at,
            ):
                raise LifecycleInvariantError(
                    "SOFT_DELETE must preserve the preceding memory content and scores."
                )
            soft_deleted = True
        else:
            raise LifecycleInvariantError(
                "Only CREATE may be revision 1; later revisions are EDIT or SOFT_DELETE."
            )
        final_snapshot = snapshot
        previous_snapshot = snapshot

    if len(used_source_ids) != len(frozen_sources):
        raise LifecycleInvariantError("Every memory source must be linked by one revision.")
    if final_snapshot != memory:
        raise LifecycleInvariantError(
            "The final memory revision must reconstruct the current memory."
        )


def memory_effective_status(memory: Memory, at: datetime) -> MemoryEffectiveStatus:
    """Compute retrieval-visible status without mutating the stored memory."""

    current_time = ensure_utc(at)
    if memory.status is MemoryStatus.DELETED:
        return MemoryEffectiveStatus.DELETED
    if memory.expires_at is not None and memory.expires_at <= current_time:
        return MemoryEffectiveStatus.EXPIRED
    return MemoryEffectiveStatus.ACTIVE
