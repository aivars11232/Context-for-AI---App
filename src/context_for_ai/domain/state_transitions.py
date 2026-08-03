"""Pure deterministic transitions for versioned conversation state."""

from __future__ import annotations

from datetime import datetime

from context_for_ai.domain.entities import ConversationState
from context_for_ai.domain.enums import IntentType, OutputType
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.policies import ConfidenceBand, confidence_band
from context_for_ai.domain.value_objects import DomainId, UnitScore


_CONTROL_INTENTS = frozenset({IntentType.CONTINUE, IntentType.CORRECT})
_NON_STATE_OUTPUT_TYPES = frozenset(
    {OutputType.CLARIFICATION, OutputType.CONTROLLED_FAILURE}
)


def initial_conversation_state(
    conversation_id: DomainId,
    *,
    updated_at: datetime,
) -> ConversationState:
    """Return the canonical empty version-zero state for a conversation."""

    return ConversationState(
        conversation_id=conversation_id,
        active_topic_id=None,
        active_task_id=None,
        previous_task_id=None,
        expected_output_type=None,
        topic_stack=(),
        version=0,
        updated_at=updated_at,
    )


def _validate_id_proposal(
    name: str,
    identifier: DomainId | None,
    confidence: UnitScore | None,
) -> None:
    if (identifier is None) != (confidence is None):
        raise LifecycleInvariantError(
            f"{name} ID and confidence must be supplied together."
        )


def _is_high(confidence: UnitScore | None) -> bool:
    return (
        confidence is not None
        and confidence_band(confidence) is ConfidenceBand.HIGH
    )


def _updated_state(
    state: ConversationState,
    *,
    active_topic_id: DomainId | None,
    active_task_id: DomainId | None,
    previous_task_id: DomainId | None,
    expected_output_type: OutputType | None,
    topic_stack: tuple[DomainId, ...],
    updated_at: datetime,
    force: bool = False,
) -> ConversationState:
    prior_values = (
        state.active_topic_id,
        state.active_task_id,
        state.previous_task_id,
        state.expected_output_type,
        state.topic_stack,
    )
    next_values = (
        active_topic_id,
        active_task_id,
        previous_task_id,
        expected_output_type,
        topic_stack,
    )
    if not force and next_values == prior_values:
        return state
    return ConversationState(
        conversation_id=state.conversation_id,
        active_topic_id=active_topic_id,
        active_task_id=active_task_id,
        previous_task_id=previous_task_id,
        expected_output_type=expected_output_type,
        topic_stack=topic_stack,
        version=state.version + 1,
        updated_at=updated_at,
    )


def transition_conversation_state(
    state: ConversationState,
    *,
    topic_id: DomainId | None = None,
    topic_confidence: UnitScore | None = None,
    task_id: DomainId | None = None,
    task_confidence: UnitScore | None = None,
    intent: IntentType | None = None,
    expected_output_type: OutputType | None = None,
    output_confidence: UnitScore | None = None,
    updated_at: datetime,
) -> ConversationState:
    """Apply one prepared, atomic topic/task/output transition."""

    _validate_id_proposal("Topic proposal", topic_id, topic_confidence)
    _validate_id_proposal("Task proposal", task_id, task_confidence)
    if (intent is None) != (output_confidence is None):
        raise LifecycleInvariantError(
            "Output intent and confidence must be supplied together."
        )
    if intent is None and expected_output_type is not None:
        raise LifecycleInvariantError(
            "Expected output type requires a prepared output intent."
        )
    if intent in _CONTROL_INTENTS and (topic_id is not None or task_id is not None):
        raise LifecycleInvariantError(
            "CONTINUE and CORRECT cannot carry topic or task proposals."
        )
    if (
        intent is not None
        and intent not in _CONTROL_INTENTS
        and intent is not IntentType.UNSUPPORTED
        and expected_output_type is None
    ):
        raise LifecycleInvariantError(
            "A prepared non-control intent requires an expected output type."
        )

    active_topic_id = state.active_topic_id
    active_task_id = state.active_task_id
    previous_task_id = state.previous_task_id
    next_output_type = state.expected_output_type
    topic_stack = state.topic_stack

    if topic_id is not None and _is_high(topic_confidence):
        topic_stack = tuple(item for item in topic_stack if item != topic_id)
        topic_stack = (*topic_stack, topic_id)[-10:]
        active_topic_id = topic_id

    if task_id is not None and _is_high(task_confidence) and task_id != active_task_id:
        previous_task_id = active_task_id
        active_task_id = task_id

    if intent is not None and _is_high(output_confidence):
        if intent in _CONTROL_INTENTS:
            next_output_type = state.expected_output_type or OutputType.TEXT_ANSWER
        elif (
            intent is not IntentType.UNSUPPORTED
            and expected_output_type not in _NON_STATE_OUTPUT_TYPES
        ):
            next_output_type = expected_output_type

    return _updated_state(
        state,
        active_topic_id=active_topic_id,
        active_task_id=active_task_id,
        previous_task_id=previous_task_id,
        expected_output_type=next_output_type,
        topic_stack=topic_stack,
        updated_at=updated_at,
    )


def clear_terminal_active_task(
    state: ConversationState,
    *,
    task_id: DomainId,
    updated_at: datetime,
) -> ConversationState:
    """Clear a named active task before its terminal status is persisted."""

    if state.active_task_id != task_id:
        return state
    return _updated_state(
        state,
        active_topic_id=state.active_topic_id,
        active_task_id=None,
        previous_task_id=task_id,
        expected_output_type=state.expected_output_type,
        topic_stack=state.topic_stack,
        updated_at=updated_at,
    )


def touch_conversation_state(
    state: ConversationState,
    *,
    updated_at: datetime,
) -> ConversationState:
    """Increment a state snapshot for an atomic project-association change."""

    return _updated_state(
        state,
        active_topic_id=state.active_topic_id,
        active_task_id=state.active_task_id,
        previous_task_id=state.previous_task_id,
        expected_output_type=state.expected_output_type,
        topic_stack=state.topic_stack,
        updated_at=updated_at,
        force=True,
    )


__all__ = [
    "clear_terminal_active_task",
    "initial_conversation_state",
    "touch_conversation_state",
    "transition_conversation_state",
]
