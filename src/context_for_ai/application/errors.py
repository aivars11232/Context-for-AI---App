"""Typed failures owned by application use-case contracts."""

from context_for_ai.domain.errors import DomainError


class ApplicationError(DomainError):
    """Base class for an application-level use-case failure."""


class ContextConstructionError(ApplicationError):
    """Deterministic context construction could not produce a safe result."""


class ClarificationRequired(ApplicationError):
    """Processing terminated safely with one persisted clarification request."""


class ContextBudgetExceededError(ContextConstructionError):
    """The mandatory context packet cannot fit its configured prompt budget."""


class ValidationExhaustedError(ApplicationError):
    """The bounded configured revision attempts ended without a valid response."""
