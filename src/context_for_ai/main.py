"""Executable composition root for validated local application startup."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from context_for_ai.infrastructure.configuration import (
    ApplicationConfiguration,
    ConfigurationError,
    load_configuration,
)
from context_for_ai.infrastructure.database import MigrationError, apply_migrations
from context_for_ai.infrastructure.logging import TraceLogger, bootstrap_logging


class StartupError(RuntimeError):
    """Raised when the minimal QML startup boundary cannot be created."""


@dataclass(frozen=True, slots=True)
class StartupResources:
    configuration: ApplicationConfiguration
    trace_logger: TraceLogger
    database_path: Path


def bootstrap_application(
    *,
    application_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> StartupResources:
    """Validate local configuration before initializing any QML object."""

    configuration = load_configuration(
        application_root=application_root,
        environ=environ,
    )
    trace_logger = bootstrap_logging(
        configuration.logging,
        configuration.configuration_fingerprint,
    )
    database_path = apply_migrations(
        configuration.app.data_directory / "database" / "context_for_ai.sqlite3"
    )
    trace_logger.event("startup_initialized")
    return StartupResources(configuration, trace_logger, database_path)


def create_qml_engine() -> QQmlApplicationEngine:
    """Create the one non-feature QML root window after successful bootstrap."""

    qml_path = Path(__file__).resolve().parent / "ui" / "qml" / "Main.qml"
    engine = QQmlApplicationEngine()
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        raise StartupError("The QML startup boundary did not create a root window")
    return engine


def main(arguments: Sequence[str] | None = None) -> int:
    """Run configuration checks or the minimal desktop startup boundary."""

    parser = argparse.ArgumentParser(prog="context-for-ai")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and local bootstrap without opening QML",
    )
    options = parser.parse_args(arguments)
    try:
        bootstrap_application()
    except (ConfigurationError, MigrationError) as error:
        print(error, file=sys.stderr)
        return 2
    if options.check:
        return 0

    application = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    engine = create_qml_engine()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
