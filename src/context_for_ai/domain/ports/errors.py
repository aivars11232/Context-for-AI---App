"""Typed failures exposed by inward infrastructure-facing ports."""

from context_for_ai.domain.errors import DomainError
from context_for_ai.domain.lifecycle import ProcessingRun


class PortError(DomainError):
    """Base class for a failure reported through an inward port."""


class ConfigurationError(PortError):
    """The complete local configuration could not be loaded or validated."""

    def __init__(self, file_name: str, key: str, expected: str) -> None:
        self.file_name = file_name
        self.key = key
        self.expected = expected
        self.location = f"{file_name}:{key}" if key else file_name
        super().__init__(
            f"Configuration error at {self.location}: expected {expected}."
        )


class PersistenceError(PortError):
    """A mandatory persistence operation could not complete safely."""


class ConcurrencyConflictError(PersistenceError):
    """A versioned write still conflicted after its one allowed reload."""


class AdmissionRaceError(PersistenceError):
    """A losing admission write captured the conflicting durable run."""

    def __init__(self, conflicting_run: ProcessingRun) -> None:
        if not isinstance(conflicting_run, ProcessingRun):
            raise TypeError("AdmissionRaceError requires a ProcessingRun.")
        self.conflicting_run = conflicting_run
        super().__init__("Foreground processing-run admission lost a durable race.")
