"""Deterministic structural policies for canonical domain lifecycles."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import IntEnum, StrEnum, unique

from context_for_ai.domain.entities import (
    ConversationState,
    ConversationTask,
    Memory,
    MemorySource,
)
from context_for_ai.domain.enums import (
    MemoryEffectiveStatus,
    MemoryStatus,
    ModelRequestStatus,
    ProcessingRunStatus,
    ProjectStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import (
    InvalidStateTransitionError,
    LifecycleInvariantError,
)
from context_for_ai.domain.value_objects import UnitScore, ensure_utc


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


def memory_effective_status(memory: Memory, at: datetime) -> MemoryEffectiveStatus:
    """Compute retrieval-visible status without mutating the stored memory."""

    current_time = ensure_utc(at)
    if memory.status is MemoryStatus.DELETED:
        return MemoryEffectiveStatus.DELETED
    if memory.expires_at is not None and memory.expires_at <= current_time:
        return MemoryEffectiveStatus.EXPIRED
    return MemoryEffectiveStatus.ACTIVE
