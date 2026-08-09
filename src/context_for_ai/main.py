"""Safe executable orchestration for the responsive packaged QML shell."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
import sys
from typing import ContextManager

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from context_for_ai.application import (
    IdempotencyKeyFactory,
    PrepareApplicationShellRequest,
    RecoveryRequiredResult,
    ShellApplicationScopeFactory,
    ShellPreparationFailureResult,
    ShellReadyResult,
)
from context_for_ai.bootstrap import (
    ProductionShellScopeFactory,
    UuidIdempotencyKeyFactory,
)
from context_for_ai.domain.enums import PipelineStage
from context_for_ai.domain.ports.system import TraceEvent
from context_for_ai.infrastructure.configuration import (
    ApplicationConfiguration,
    ConfigurationError,
    load_configuration,
)
from context_for_ai.infrastructure.database import apply_migrations
from context_for_ai.infrastructure.logging import TraceLogger, bootstrap_logging
from context_for_ai.ui import (
    NativeStartupErrorPresenter,
    ShellFacade,
    StartupErrorPresenter,
    StartupFailureKind,
    StartupFailureView,
    StartupPresentationMode,
    startup_failure_for_preparation,
)


class StartupError(RuntimeError):
    """Carry only one closed pre-shell failure between startup stages."""

    def __init__(self, failure: StartupFailureView) -> None:
        self.failure = failure
        super().__init__(failure.code)


@dataclass(frozen=True, slots=True)
class StartupResources:
    configuration: ApplicationConfiguration
    trace_logger: TraceLogger
    database_path: Path
    scope_factory: ShellApplicationScopeFactory
    idempotency_keys: IdempotencyKeyFactory


def _raise_startup(failure: StartupFailureView) -> None:
    raise StartupError(failure) from None


def bootstrap_application(
    *,
    application_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> StartupResources:
    """Run configuration, logging, migration, and no-I/O composition in order."""

    try:
        configuration = load_configuration(
            application_root=application_root,
            environ=environ,
        )
    except ConfigurationError:
        raise
    except Exception:
        _raise_startup(StartupFailureView(StartupFailureKind.CONFIGURATION))

    try:
        trace_logger = bootstrap_logging(
            configuration.logging,
            configuration.configuration_fingerprint,
        )
    except Exception:
        _raise_startup(StartupFailureView(StartupFailureKind.CONFIGURATION))

    try:
        database_path = apply_migrations(
            configuration.app.data_directory
            / "database"
            / "context_for_ai.sqlite3"
        )
    except Exception:
        _raise_startup(StartupFailureView(StartupFailureKind.MIGRATION))

    try:
        scope_factory = ProductionShellScopeFactory(
            configuration=configuration,
            database_path=database_path,
            trace_logger=trace_logger,
        )
        idempotency_keys = UuidIdempotencyKeyFactory()
    except Exception:
        _raise_startup(StartupFailureView(StartupFailureKind.COMPOSITION))

    try:
        trace_logger.emit(
            TraceEvent(
                timestamp=datetime.now(UTC),
                level="INFO",
                event_name="startup_initialized",
                stage=PipelineStage.ACCEPTANCE,
                configuration_fingerprint=(
                    configuration.configuration_fingerprint
                ),
            )
        )
    except Exception:
        pass
    return StartupResources(
        configuration,
        trace_logger,
        database_path,
        scope_factory,
        idempotency_keys,
    )


def prepare_application_shell(
    scope_factory: ShellApplicationScopeFactory,
) -> ShellReadyResult | RecoveryRequiredResult:
    """Open, invoke, and close the sole synchronous pre-QML startup scope."""

    scope = None
    result: object | None = None
    failed = False
    try:
        scope = scope_factory.open_startup_scope()
        result = scope.prepare_application_shell.execute(
            PrepareApplicationShellRequest()
        )
    except Exception:
        failed = True
    finally:
        if scope is not None:
            try:
                scope.close()
            except Exception:
                failed = True

    if failed:
        _raise_startup(StartupFailureView(StartupFailureKind.COMPOSITION))
    if isinstance(result, ShellPreparationFailureResult):
        _raise_startup(startup_failure_for_preparation(result))
    if not isinstance(result, (ShellReadyResult, RecoveryRequiredResult)):
        _raise_startup(StartupFailureView(StartupFailureKind.COMPOSITION))
    return result


def _qml_resource_context(
    qml_directory: Path | None,
) -> ContextManager[Path]:
    if qml_directory is not None:
        return nullcontext(Path(qml_directory))
    packaged_directory = resources.files("context_for_ai.ui").joinpath("qml")
    return resources.as_file(packaged_directory)


def _dispose_qml_engine(engine: QQmlApplicationEngine) -> None:
    for root in tuple(engine.rootObjects()):
        close = getattr(root, "close", None)
        if callable(close):
            close()
        root.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def create_qml_engine(
    facade: ShellFacade,
    *,
    qml_directory: Path | None = None,
) -> QQmlApplicationEngine:
    """Load one packaged root with raw Qt/QML diagnostics suppressed."""

    engine = QQmlApplicationEngine()
    engine.setOutputWarningsToStandardError(False)
    engine.rootContext().setContextProperty("shellFacade", facade)
    warning_counts: list[int] = []
    engine.warnings.connect(lambda warnings: warning_counts.append(len(warnings)))
    previous_handler = qInstallMessageHandler(lambda *_: None)
    try:
        with _qml_resource_context(qml_directory) as qml_root:
            engine.load(QUrl.fromLocalFile(str(qml_root / "Main.qml")))
    except Exception:
        _dispose_qml_engine(engine)
        raise StartupError(StartupFailureView(StartupFailureKind.QML_LOAD)) from None
    finally:
        qInstallMessageHandler(previous_handler)

    roots = tuple(engine.rootObjects())
    if len(roots) != 1 or roots[0].objectName() != "contextForAiRoot":
        _dispose_qml_engine(engine)
        raise StartupError(StartupFailureView(StartupFailureKind.QML_LOAD)) from None
    return engine


def _present_once(
    presenter: StartupErrorPresenter,
    failure: StartupFailureView,
    mode: StartupPresentationMode,
) -> None:
    try:
        presenter.present(failure, mode)
    except Exception:
        return


def _dispose_shell(
    facade: ShellFacade | None,
    engine: QQmlApplicationEngine | None,
) -> None:
    if engine is not None:
        _dispose_qml_engine(engine)
    if facade is not None:
        facade.dispose()
        facade.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def main(
    arguments: Sequence[str] | None = None,
    *,
    application_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    startup_error_presenter: StartupErrorPresenter | None = None,
) -> int:
    """Run safe validation mode or the one-window responsive desktop shell."""

    parser = argparse.ArgumentParser(prog="context-for-ai")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration, migrations, and composition without Qt",
    )
    options = parser.parse_args(arguments)
    mode = (
        StartupPresentationMode.NON_INTERACTIVE
        if options.check
        else StartupPresentationMode.INTERACTIVE
    )
    presenter = startup_error_presenter or NativeStartupErrorPresenter()

    try:
        startup = bootstrap_application(
            application_root=application_root,
            environ=environ,
        )
    except ConfigurationError as error:
        failure = StartupFailureView(
            StartupFailureKind.CONFIGURATION,
            error.file_name,
            error.key or None,
        )
        _present_once(presenter, failure, mode)
        return 2
    except StartupError as error:
        _present_once(presenter, error.failure, mode)
        return 2
    if options.check:
        return 0

    try:
        preparation = prepare_application_shell(startup.scope_factory)
    except StartupError as error:
        _present_once(presenter, error.failure, mode)
        return 2

    facade: ShellFacade | None = None
    engine: QQmlApplicationEngine | None = None
    try:
        application = QApplication.instance() or QApplication([sys.argv[0]])
        if not isinstance(application, QApplication):
            _raise_startup(StartupFailureView(StartupFailureKind.COMPOSITION))
        facade = ShellFacade(startup.scope_factory, startup.idempotency_keys)
        facade.shutdownReady.connect(
            application.quit,
            Qt.ConnectionType.QueuedConnection,
        )
        engine = create_qml_engine(facade)
        facade.apply_preparation(preparation)
    except StartupError as error:
        _dispose_shell(facade, engine)
        _present_once(presenter, error.failure, mode)
        return 2
    except Exception:
        _dispose_shell(facade, engine)
        failure = StartupFailureView(StartupFailureKind.COMPOSITION)
        _present_once(presenter, failure, mode)
        return 2

    exit_code = application.exec()
    _dispose_shell(facade, engine)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
