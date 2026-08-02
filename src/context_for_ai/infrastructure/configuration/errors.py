"""Typed configuration failures that are safe to present or log."""

from __future__ import annotations


class ConfigurationError(RuntimeError):
    """A configuration failure identified by source file and key, never value."""

    def __init__(self, file_name: str, key: str, expected: str) -> None:
        self.file_name = file_name
        self.key = key
        self.expected = expected
        self.location = f"{file_name}:{key}" if key else file_name
        super().__init__(f"Configuration error at {self.location}: expected {expected}.")
