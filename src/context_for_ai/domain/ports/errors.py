"""Typed failures exposed by inward infrastructure-facing ports."""

from context_for_ai.domain.errors import DomainError


class PortError(DomainError):
    """Base class for a failure reported through an inward port."""


class ConfigurationError(PortError):
    """The complete local configuration could not be loaded or validated."""


class PersistenceError(PortError):
    """A mandatory persistence operation could not complete safely."""


class ConcurrencyConflictError(PersistenceError):
    """A versioned write still conflicted after its one allowed reload."""
