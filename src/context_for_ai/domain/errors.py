"""Typed errors raised by dependency-free domain primitives and policies."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for failures owned by the domain layer."""


class DomainValidationError(DomainError):
    """A domain value violates a canonical representation invariant."""


class InvalidDomainIdError(DomainValidationError):
    """A value is not a canonical UUID domain identifier."""


class InvalidTimestampError(DomainValidationError):
    """A timestamp is not timezone-aware or cannot be normalized to UTC."""


class ScoreOutOfRangeError(DomainValidationError):
    """A score is not finite or lies outside the inclusive unit interval."""


class LifecycleInvariantError(DomainValidationError):
    """An entity or immutable result violates its lifecycle invariants."""


class InvalidStateTransitionError(DomainError):
    """A requested canonical lifecycle transition is not permitted."""

    def __init__(self, lifecycle: str, current: Any, target: Any) -> None:
        self.lifecycle = lifecycle
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid {lifecycle} transition: {current!s} -> {target!s}."
        )


class BusyError(DomainError):
    """A new submission cannot be accepted while a foreground run is active."""
