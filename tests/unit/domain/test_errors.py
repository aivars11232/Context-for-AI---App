"""Tests for typed domain error behavior."""

from context_for_ai.domain.enums import TaskStatus
from context_for_ai.domain.errors import (
    BusyError,
    DomainError,
    DomainValidationError,
    InvalidDomainIdError,
    InvalidStateTransitionError,
    InvalidTimestampError,
    LifecycleInvariantError,
    ScoreOutOfRangeError,
)


def test_domain_errors_have_typed_failure_categories() -> None:
    validation_errors = (
        DomainValidationError,
        InvalidDomainIdError,
        InvalidTimestampError,
        LifecycleInvariantError,
        ScoreOutOfRangeError,
    )

    assert all(issubclass(error_type, DomainError) for error_type in validation_errors)
    assert issubclass(BusyError, DomainError)
    assert not issubclass(BusyError, DomainValidationError)


def test_invalid_transition_error_preserves_lifecycle_and_states() -> None:
    error = InvalidStateTransitionError(
        "task",
        TaskStatus.COMPLETED,
        TaskStatus.IN_PROGRESS,
    )

    assert error.lifecycle == "task"
    assert error.current is TaskStatus.COMPLETED
    assert error.target is TaskStatus.IN_PROGRESS
    assert str(error) == "Invalid task transition: COMPLETED -> IN_PROGRESS."
