from datetime import UTC, datetime, timedelta

import pytest

from context_for_ai.domain.entities import ConversationState
from context_for_ai.domain.enums import IntentType, OutputType
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.state_transitions import (
    clear_terminal_active_task,
    initial_conversation_state,
    touch_conversation_state,
    transition_conversation_state,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
HIGH = UnitScore("0.80")
MEDIUM = UnitScore("0.79")


def identifier(number: int) -> DomainId:
    return DomainId(f"20000000-0000-4000-8000-{number:012x}")


def state(
    *,
    active_topic_id: DomainId | None = None,
    active_task_id: DomainId | None = None,
    previous_task_id: DomainId | None = None,
    expected_output_type: OutputType | None = None,
    topic_stack: tuple[DomainId, ...] = (),
    version: int = 0,
) -> ConversationState:
    return ConversationState(
        identifier(1),
        active_topic_id,
        active_task_id,
        previous_task_id,
        expected_output_type,
        topic_stack,
        version,
        NOW,
    )


def test_initial_state_is_the_exact_version_zero_snapshot() -> None:
    result = initial_conversation_state(identifier(1), updated_at=NOW)

    assert result == state()


def test_combined_high_confidence_transition_increments_exactly_once() -> None:
    topic_id = identifier(2)
    task_id = identifier(3)

    result = transition_conversation_state(
        state(),
        topic_id=topic_id,
        topic_confidence=HIGH,
        task_id=task_id,
        task_confidence=HIGH,
        intent=IntentType.PLAN,
        expected_output_type=OutputType.TEXT_PLAN,
        output_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert result.active_topic_id == topic_id
    assert result.topic_stack == (topic_id,)
    assert result.active_task_id == task_id
    assert result.previous_task_id is None
    assert result.expected_output_type is OutputType.TEXT_PLAN
    assert result.version == 1


def test_lower_confidence_proposals_retain_every_prior_value() -> None:
    prior = state(
        active_topic_id=identifier(2),
        active_task_id=identifier(3),
        previous_task_id=identifier(4),
        expected_output_type=OutputType.TEXT_CODE,
        topic_stack=(identifier(2),),
        version=7,
    )

    result = transition_conversation_state(
        prior,
        topic_id=identifier(5),
        topic_confidence=MEDIUM,
        task_id=identifier(6),
        task_confidence=MEDIUM,
        intent=IntentType.ANSWER,
        expected_output_type=OutputType.TEXT_ANSWER,
        output_confidence=MEDIUM,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert result is prior


def test_topic_stack_moves_repeats_to_top_and_drops_oldest_on_overflow() -> None:
    original_stack = tuple(identifier(number) for number in range(10, 20))
    prior = state(
        active_topic_id=original_stack[-1],
        topic_stack=original_stack,
        version=3,
    )

    overflowed = transition_conversation_state(
        prior,
        topic_id=identifier(20),
        topic_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=1),
    )
    moved = transition_conversation_state(
        overflowed,
        topic_id=identifier(15),
        topic_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=2),
    )
    repeated = transition_conversation_state(
        moved,
        topic_id=identifier(15),
        topic_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=3),
    )

    assert overflowed.topic_stack == tuple(identifier(number) for number in range(11, 21))
    assert len(overflowed.topic_stack) == 10
    assert moved.topic_stack == (
        *tuple(identifier(number) for number in range(11, 15)),
        *tuple(identifier(number) for number in range(16, 21)),
        identifier(15),
    )
    assert moved.active_topic_id == identifier(15)
    assert moved.version == 5
    assert repeated is moved


def test_selecting_a_new_task_tracks_previous_and_reselection_is_a_noop() -> None:
    prior = state(active_task_id=identifier(2), version=4)

    selected = transition_conversation_state(
        prior,
        task_id=identifier(3),
        task_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=1),
    )
    repeated = transition_conversation_state(
        selected,
        task_id=identifier(3),
        task_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=2),
    )

    assert selected.active_task_id == identifier(3)
    assert selected.previous_task_id == identifier(2)
    assert selected.version == 5
    assert repeated is selected


@pytest.mark.parametrize("intent", [IntentType.CONTINUE, IntentType.CORRECT])
def test_control_intents_preserve_task_and_existing_output(intent: IntentType) -> None:
    prior = state(
        active_task_id=identifier(2),
        previous_task_id=identifier(3),
        expected_output_type=OutputType.TEXT_PLAN,
        version=2,
    )

    result = transition_conversation_state(
        prior,
        intent=intent,
        expected_output_type=OutputType.TEXT_ANSWER,
        output_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert result is prior


@pytest.mark.parametrize("intent", [IntentType.CONTINUE, IntentType.CORRECT])
def test_unscoped_control_intents_default_output_to_text_answer(
    intent: IntentType,
) -> None:
    result = transition_conversation_state(
        state(),
        intent=intent,
        expected_output_type=OutputType.TEXT_PLAN,
        output_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert result.expected_output_type is OutputType.TEXT_ANSWER
    assert result.version == 1


def test_control_intents_reject_topic_or_task_proposals() -> None:
    with pytest.raises(LifecycleInvariantError, match="cannot carry"):
        transition_conversation_state(
            state(),
            task_id=identifier(2),
            task_confidence=HIGH,
            intent=IntentType.CONTINUE,
            output_confidence=HIGH,
            updated_at=NOW,
        )


@pytest.mark.parametrize(
    ("intent", "output_type"),
    [
        (IntentType.UNSUPPORTED, OutputType.CLARIFICATION),
        (IntentType.ANSWER, OutputType.CLARIFICATION),
        (IntentType.ANSWER, OutputType.CONTROLLED_FAILURE),
    ],
)
def test_unsupported_and_terminal_outputs_do_not_change_state(
    intent: IntentType,
    output_type: OutputType,
) -> None:
    prior = state(expected_output_type=OutputType.TEXT_PLAN)

    result = transition_conversation_state(
        prior,
        intent=intent,
        expected_output_type=output_type,
        output_confidence=HIGH,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert result is prior


def test_terminal_active_task_is_cleared_once_and_nonactive_task_is_noop() -> None:
    prior = state(active_task_id=identifier(2), previous_task_id=identifier(3), version=8)

    cleared = clear_terminal_active_task(
        prior,
        task_id=identifier(2),
        updated_at=NOW + timedelta(seconds=1),
    )
    unchanged = clear_terminal_active_task(
        cleared,
        task_id=identifier(4),
        updated_at=NOW + timedelta(seconds=2),
    )

    assert cleared.active_task_id is None
    assert cleared.previous_task_id == identifier(2)
    assert cleared.version == 9
    assert unchanged is cleared


def test_project_association_touch_preserves_fields_and_increments_once() -> None:
    prior = state(
        active_topic_id=identifier(2),
        active_task_id=identifier(3),
        expected_output_type=OutputType.TEXT_CODE,
        topic_stack=(identifier(2),),
        version=5,
    )

    result = touch_conversation_state(
        prior,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert result.version == 6
    assert result.active_topic_id == prior.active_topic_id
    assert result.active_task_id == prior.active_task_id
    assert result.expected_output_type == prior.expected_output_type
    assert result.topic_stack == prior.topic_stack


def test_incomplete_prepared_values_are_rejected() -> None:
    with pytest.raises(LifecycleInvariantError, match="supplied together"):
        transition_conversation_state(
            state(),
            topic_id=identifier(2),
            updated_at=NOW,
        )
    with pytest.raises(LifecycleInvariantError, match="requires an expected output"):
        transition_conversation_state(
            state(),
            intent=IntentType.PLAN,
            output_confidence=HIGH,
            updated_at=NOW,
        )
