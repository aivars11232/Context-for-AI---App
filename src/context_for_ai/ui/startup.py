"""Closed safe projection and non-QML presentation for startup failures."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum, unique
from pathlib import PurePath
import sys
from typing import Protocol, TextIO

from PySide6.QtWidgets import QApplication, QMessageBox

from context_for_ai.application import (
    ShellPreparationFailureKind,
    ShellPreparationFailureResult,
)


@unique
class StartupFailureKind(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    MIGRATION = "MIGRATION"
    COMPOSITION = "COMPOSITION"
    QML_LOAD = "QML_LOAD"
    RECOVERY_PREFLIGHT = "RECOVERY_PREFLIGHT"


@unique
class StartupPresentationMode(StrEnum):
    INTERACTIVE = "INTERACTIVE"
    NON_INTERACTIVE = "NON_INTERACTIVE"


_STARTUP_FAILURE_VALUES: dict[StartupFailureKind, tuple[str, str]] = {
    StartupFailureKind.CONFIGURATION: (
        "CONFIGURATION_INVALID",
        "The application configuration is invalid.",
    ),
    StartupFailureKind.MIGRATION: (
        "MIGRATION_FAILED",
        "The local database could not be prepared safely.",
    ),
    StartupFailureKind.COMPOSITION: (
        "APPLICATION_STARTUP_FAILED",
        "The application could not be started safely.",
    ),
    StartupFailureKind.QML_LOAD: (
        "QML_LOAD_FAILED",
        "The application window could not be opened.",
    ),
    StartupFailureKind.RECOVERY_PREFLIGHT: (
        "RECOVERY_PREFLIGHT_FAILED",
        "Previous processing state could not be inspected safely.",
    ),
}


def _safe_location_field(name: str, value: str | None) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(character in value for character in "\r\n\0")
    ):
        raise ValueError(f"Startup failure {name} must be safe non-empty text.")


@dataclass(frozen=True, slots=True)
class StartupFailureView:
    """One content-free startup failure safe for stderr or a native modal."""

    failure_kind: StartupFailureKind
    file: str | None = None
    key: str | None = None
    code: str = field(init=False)
    safe_message: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.failure_kind, StartupFailureKind):
            raise ValueError("Startup failure kind must be closed.")
        _safe_location_field("file", self.file)
        _safe_location_field("key", self.key)
        if self.failure_kind is StartupFailureKind.CONFIGURATION:
            if self.key is not None and self.file is None:
                raise ValueError("Configuration startup key requires its file name.")
            if self.file is not None and (
                PurePath(self.file).name != self.file or "\\" in self.file
            ):
                raise ValueError("Configuration startup file must not be a path.")
        elif self.file is not None or self.key is not None:
            raise ValueError(
                "Only configuration startup failure may expose file or key."
            )
        code, message = _STARTUP_FAILURE_VALUES[self.failure_kind]
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "safe_message", message)


class StartupErrorPresenter(Protocol):
    def present(
        self,
        failure: StartupFailureView,
        mode: StartupPresentationMode,
    ) -> None: ...


def safe_stderr_record(failure: StartupFailureView) -> str:
    """Render one single-line record containing only allowlisted fields."""

    location = ""
    if failure.file is not None:
        location = f" [{failure.file}"
        if failure.key is not None:
            location += f":{failure.key}"
        location += "]"
    return (
        f"Context for AI startup error ({failure.code}): "
        f"{failure.safe_message}{location}"
    )


def startup_failure_for_preparation(
    result: ShellPreparationFailureResult,
) -> StartupFailureView:
    """Project the two preparation failures into the pre-shell startup algebra."""

    if not isinstance(result, ShellPreparationFailureResult):
        raise TypeError("A shell preparation failure result is required.")
    if (
        result.failure_kind
        is ShellPreparationFailureKind.RECOVERY_PREFLIGHT_FAILED
    ):
        return StartupFailureView(StartupFailureKind.RECOVERY_PREFLIGHT)
    return StartupFailureView(StartupFailureKind.COMPOSITION)


type StartupModal = Callable[[StartupFailureView], None]


class NativeStartupErrorPresenter:
    """Always write safe stderr; add one native Qt modal for interactive launch."""

    def __init__(
        self,
        *,
        stderr: TextIO | None = None,
        modal: StartupModal | None = None,
    ) -> None:
        self._stderr = stderr
        self._modal = self._show_modal if modal is None else modal

    def present(
        self,
        failure: StartupFailureView,
        mode: StartupPresentationMode,
    ) -> None:
        if not isinstance(failure, StartupFailureView) or not isinstance(
            mode,
            StartupPresentationMode,
        ):
            raise TypeError("Startup presenter requires closed presentation values.")
        stream = sys.stderr if self._stderr is None else self._stderr
        print(safe_stderr_record(failure), file=stream)
        if mode is StartupPresentationMode.INTERACTIVE:
            try:
                self._modal(failure)
            except BaseException:
                return

    @staticmethod
    def _show_modal(failure: StartupFailureView) -> None:
        application = QApplication.instance()
        owns_application = application is None
        if application is None:
            application = QApplication([sys.argv[0]])
        if not isinstance(application, QApplication):
            return
        message = failure.safe_message
        if failure.file is not None:
            location = failure.file
            if failure.key is not None:
                location += f": {failure.key}"
            message += f"\n\nConfiguration: {location}"
        QMessageBox.critical(
            None,
            "Context for AI — Startup Error",
            message,
        )
        if owns_application:
            application.quit()


__all__ = [
    "NativeStartupErrorPresenter",
    "StartupErrorPresenter",
    "StartupFailureKind",
    "StartupFailureView",
    "StartupPresentationMode",
    "safe_stderr_record",
    "startup_failure_for_preparation",
]
