"""Typed configuration failures that are safe to present or log."""

from __future__ import annotations

from context_for_ai.domain.ports.errors import (
    ConfigurationError as PortConfigurationError,
)


class ConfigurationError(PortConfigurationError):
    """A configuration failure identified by source file and key, never value."""
