"""TASK-0015 safe startup ordering and failure-matrix integration coverage."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop
from PySide6.QtWidgets import QApplication

import context_for_ai.main as main_module
from context_for_ai.application import (
    RecoveryRequiredResult,
    ShellPreparationFailureKind,
    ShellPreparationFailureResult,
    ShellReadyResult,
)
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.infrastructure.configuration import (
    ConfigurationError,
    load_configuration as real_load_configuration,
)
from context_for_ai.main import (
    StartupError,
    StartupResources,
    bootstrap_application,
    create_qml_engine,
    main,
    prepare_application_shell,
)
from context_for_ai.ui import (
    ShellFacade,
    StartupFailureKind,
    StartupFailureView,
    StartupPresentationMode,
)


def identifier(number: int) -> DomainId:
    return DomainId(f"55000000-0000-4000-8000-{number:012x}")


class TraceSink:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events

    def emit(self, _: object) -> None:
        if self.events is not None:
            self.events.append("trace")


class RecordingPresenter:
    def __init__(self) -> None:
        self.calls: list[tuple[StartupFailureView, StartupPresentationMode]] = []

    def present(
        self,
        failure: StartupFailureView,
        mode: StartupPresentationMode,
    ) -> None:
        self.calls.append((failure, mode))


class FixedKeys:
    def new_key(self) -> DomainId:
        return identifier(90)


class PreparationService:
    def __init__(self, result: object, events: list[str]) -> None:
        self.result = result
        self.events = events
        self.calls = 0

    def execute(self, _: object) -> object:
        self.calls += 1
        self.events.append("prepare")
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class StartupScope:
    def __init__(
        self,
        result: object,
        events: list[str],
        *,
        fail_close: bool = False,
    ) -> None:
        self.prepare_application_shell = PreparationService(result, events)
        self.events = events
        self.fail_close = fail_close
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        self.events.append("close_startup_scope")
        if self.fail_close:
            raise RuntimeError("unsafe close defect /private/database.sqlite3")


class ScopeFactory:
    def __init__(
        self,
        result: object,
        events: list[str],
        *,
        fail_close: bool = False,
    ) -> None:
        self.result = result
        self.events = events
        self.fail_close = fail_close
        self.startup_scopes: list[StartupScope] = []
        self.foreground_calls = 0

    def open_startup_scope(self) -> StartupScope:
        self.events.append("open_startup_scope")
        scope = StartupScope(
            self.result,
            self.events,
            fail_close=self.fail_close,
        )
        self.startup_scopes.append(scope)
        return scope

    def open_foreground_scope(self) -> object:
        self.foreground_calls += 1
        raise AssertionError("Startup failure must not open a foreground scope.")


def startup_resources(
    configuration: object,
    factory: ScopeFactory,
    tmp_path: Path,
) -> StartupResources:
    return StartupResources(
        configuration,  # type: ignore[arg-type]
        TraceSink(),  # type: ignore[arg-type]
        tmp_path / "startup.sqlite3",
        factory,
        FixedKeys(),
    )


def test_offscreen_startup_prepares_one_conversation_then_loads_one_root(
    fixture_application_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    startup = bootstrap_application(
        application_root=fixture_application_root,
        environ={},
    )
    with sqlite3.connect(startup.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone() == (0,)

    preparation = prepare_application_shell(startup.scope_factory)
    assert isinstance(preparation, ShellReadyResult)
    assert preparation.initial_conversation_created is True
    with sqlite3.connect(startup.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM conversation_states WHERE version = 0"
        ).fetchone() == (1,)

    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    facade = ShellFacade(startup.scope_factory, startup.idempotency_keys)
    engine = create_qml_engine(facade)
    facade.apply_preparation(preparation)

    roots = tuple(engine.rootObjects())
    assert len(roots) == 1
    assert roots[0].objectName() == "contextForAiRoot"
    assert facade.route == "CHAT"
    assert facade.state == "IDLE"
    assert facade.submit_enabled is True
    assert facade._controller.active_execution_id is None  # type: ignore[attr-defined]
    facade.request_shutdown()
    for root in roots:
        root.close()
    engine.deleteLater()
    facade.dispose()
    facade.deleteLater()
    application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def test_check_runs_through_composition_without_scope_qt_facade_or_worker(
    fixture_application_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = real_load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    events: list[str] = []

    def load(**_: object) -> object:
        events.append("configuration")
        return loaded

    def logging(*_: object) -> TraceSink:
        events.append("logging")
        return TraceSink(events)

    def migrations(_: Path) -> Path:
        events.append("migrations")
        return tmp_path / "checked.sqlite3"

    class Composition:
        def __init__(self, **_: object) -> None:
            events.append("composition")

        def open_startup_scope(self) -> object:
            raise AssertionError("--check must not open startup scope")

        def open_foreground_scope(self) -> object:
            raise AssertionError("--check must not open foreground scope")

    class KeyFactory:
        def __init__(self) -> None:
            events.append("idempotency_factory")

    class ForbiddenQt:
        @classmethod
        def instance(cls) -> object:
            raise AssertionError("--check must not inspect QApplication")

    monkeypatch.setattr(main_module, "load_configuration", load)
    monkeypatch.setattr(main_module, "bootstrap_logging", logging)
    monkeypatch.setattr(main_module, "apply_migrations", migrations)
    monkeypatch.setattr(main_module, "ProductionShellScopeFactory", Composition)
    monkeypatch.setattr(main_module, "UuidIdempotencyKeyFactory", KeyFactory)
    monkeypatch.setattr(main_module, "QApplication", ForbiddenQt)
    monkeypatch.setattr(
        main_module,
        "ShellFacade",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("--check must not create ShellFacade")
        ),
    )
    presenter = RecordingPresenter()

    result = main(
        ["--check"],
        application_root=fixture_application_root,
        environ={},
        startup_error_presenter=presenter,
    )

    assert result == 0
    assert events[:5] == [
        "configuration",
        "logging",
        "migrations",
        "composition",
        "idempotency_factory",
    ]
    assert "trace" in events
    assert presenter.calls == []


@pytest.mark.parametrize(
    ("failed_stage", "expected_kind"),
    (
        ("configuration", StartupFailureKind.CONFIGURATION),
        ("logging", StartupFailureKind.CONFIGURATION),
        ("migrations", StartupFailureKind.MIGRATION),
        ("composition", StartupFailureKind.COMPOSITION),
    ),
)
def test_bootstrap_stage_failures_stop_in_order_and_are_closed(
    failed_stage: str,
    expected_kind: StartupFailureKind,
    fixture_application_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = real_load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    events: list[str] = []

    def load(**_: object) -> object:
        events.append("configuration")
        if failed_stage == "configuration":
            raise ConfigurationError("models.yaml", "model.name", "safe shape")
        return loaded

    def logging(*_: object) -> TraceSink:
        events.append("logging")
        if failed_stage == "logging":
            raise OSError("unsafe log path /private/log")
        return TraceSink()

    def migrations(_: Path) -> Path:
        events.append("migrations")
        if failed_stage == "migrations":
            raise RuntimeError("unsafe SQL and /private/database.sqlite3")
        return tmp_path / "bootstrap.sqlite3"

    class Composition:
        def __init__(self, **_: object) -> None:
            events.append("composition")
            if failed_stage == "composition":
                raise RuntimeError("unsafe endpoint http://127.0.0.1")

    monkeypatch.setattr(main_module, "load_configuration", load)
    monkeypatch.setattr(main_module, "bootstrap_logging", logging)
    monkeypatch.setattr(main_module, "apply_migrations", migrations)
    monkeypatch.setattr(main_module, "ProductionShellScopeFactory", Composition)

    if failed_stage == "configuration":
        with pytest.raises(ConfigurationError) as captured_configuration:
            bootstrap_application(
                application_root=fixture_application_root,
                environ={},
            )
        assert captured_configuration.value.file_name == "models.yaml"
        assert captured_configuration.value.key == "model.name"
        assert events == ["configuration"]
        return

    with pytest.raises(StartupError) as captured_startup:
        bootstrap_application(
            application_root=fixture_application_root,
            environ={},
        )

    failure = captured_startup.value.failure
    assert failure.failure_kind is expected_kind
    assert events[-1] == failed_stage
    assert not any(
        prohibited in failure.safe_message
        for prohibited in ("/private", "SQL", "127.0.0.1", "safe shape")
    )
    assert (failure.file, failure.key) == (None, None)


@pytest.mark.parametrize(
    ("result", "fail_close", "expected_kind"),
    (
        (
            ShellPreparationFailureResult(
                ShellPreparationFailureKind.RECOVERY_PREFLIGHT_FAILED
            ),
            False,
            StartupFailureKind.RECOVERY_PREFLIGHT,
        ),
        (
            ShellPreparationFailureResult(
                ShellPreparationFailureKind.CONVERSATION_SETUP_FAILED
            ),
            False,
            StartupFailureKind.COMPOSITION,
        ),
        (
            RuntimeError("unsafe preparation defect /private/path"),
            False,
            StartupFailureKind.COMPOSITION,
        ),
        (
            ShellReadyResult(identifier(1), False),
            True,
            StartupFailureKind.COMPOSITION,
        ),
    ),
)
def test_preparation_always_closes_and_projects_only_closed_failure(
    result: object,
    fail_close: bool,
    expected_kind: StartupFailureKind,
) -> None:
    events: list[str] = []
    factory = ScopeFactory(result, events, fail_close=fail_close)

    with pytest.raises(StartupError) as captured:
        prepare_application_shell(factory)

    assert captured.value.failure.failure_kind is expected_kind
    assert events[-1] == "close_startup_scope"
    assert factory.startup_scopes[0].close_calls == 1
    assert factory.foreground_calls == 0


def test_preparation_success_closes_before_returning() -> None:
    events: list[str] = []
    ready = ShellReadyResult(identifier(1), False)
    factory = ScopeFactory(ready, events)

    assert prepare_application_shell(factory) is ready
    assert events == ["open_startup_scope", "prepare", "close_startup_scope"]


@pytest.mark.parametrize(
    ("failure", "arguments", "mode"),
    (
        (
            StartupFailureView(
                StartupFailureKind.CONFIGURATION,
                "app.yaml",
                "app.environment",
            ),
            ["--check"],
            StartupPresentationMode.NON_INTERACTIVE,
        ),
        (
            StartupFailureView(StartupFailureKind.MIGRATION),
            [],
            StartupPresentationMode.INTERACTIVE,
        ),
        (
            StartupFailureView(StartupFailureKind.COMPOSITION),
            [],
            StartupPresentationMode.INTERACTIVE,
        ),
    ),
)
def test_main_presents_bootstrap_failure_exactly_once(
    failure: StartupFailureView,
    arguments: list[str],
    mode: StartupPresentationMode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**_: object) -> StartupResources:
        if failure.failure_kind is StartupFailureKind.CONFIGURATION:
            raise ConfigurationError(
                failure.file or "bootstrap",
                failure.key or "",
                "unsafe internal expected shape",
            )
        raise StartupError(failure)

    monkeypatch.setattr(main_module, "bootstrap_application", fail)
    presenter = RecordingPresenter()

    result = main(arguments, startup_error_presenter=presenter)

    assert result == 2
    assert presenter.calls == [(failure, mode)]


def test_preparation_failure_creates_no_qt_facade_qml_or_worker(
    fixture_application_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = real_load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    events: list[str] = []
    factory = ScopeFactory(
        ShellPreparationFailureResult(
            ShellPreparationFailureKind.RECOVERY_PREFLIGHT_FAILED
        ),
        events,
    )
    resources = startup_resources(loaded, factory, tmp_path)
    monkeypatch.setattr(main_module, "bootstrap_application", lambda **_: resources)

    class ForbiddenQt:
        @classmethod
        def instance(cls) -> object:
            raise AssertionError("Preparation failure must precede QApplication")

    monkeypatch.setattr(main_module, "QApplication", ForbiddenQt)
    monkeypatch.setattr(
        main_module,
        "create_qml_engine",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("Preparation failure must precede QML")
        ),
    )
    presenter = RecordingPresenter()

    result = main([], startup_error_presenter=presenter)

    assert result == 2
    assert presenter.calls[0][0].failure_kind is StartupFailureKind.RECOVERY_PREFLIGHT
    assert len(presenter.calls) == 1
    assert factory.foreground_calls == 0
    assert factory.startup_scopes[0].close_calls == 1


class FakeSignal:
    def __init__(self) -> None:
        self.connections: list[object] = []

    def connect(self, callback: object, *_: object) -> None:
        self.connections.append(callback)


class FakeApplication:
    _instance: FakeApplication | None = None

    def __init__(self, _: object) -> None:
        type(self)._instance = self
        self.events: list[str] = []

    @classmethod
    def instance(cls) -> FakeApplication | None:
        return cls._instance

    def quit(self) -> None:
        self.events.append("quit")

    def exec(self) -> int:
        self.events.append("exec")
        return 0


class FakeFacade:
    instances: list[FakeFacade] = []

    def __init__(self, *_: object) -> None:
        self.shutdownReady = FakeSignal()
        self.applied: list[object] = []
        self.disposed = 0
        type(self).instances.append(self)

    def apply_preparation(self, value: object) -> None:
        self.applied.append(value)

    def dispose(self) -> None:
        self.disposed += 1

    def deleteLater(self) -> None:
        return


def test_qml_failure_disposes_facade_and_never_publishes_recovery(
    fixture_application_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = real_load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    events: list[str] = []
    recovery = RecoveryRequiredResult(identifier(2), identifier(3))
    factory = ScopeFactory(recovery, events)
    resources = startup_resources(loaded, factory, tmp_path)
    monkeypatch.setattr(main_module, "bootstrap_application", lambda **_: resources)
    FakeApplication._instance = None
    FakeFacade.instances.clear()
    monkeypatch.setattr(main_module, "QApplication", FakeApplication)
    monkeypatch.setattr(main_module, "ShellFacade", FakeFacade)
    monkeypatch.setattr(
        main_module,
        "create_qml_engine",
        lambda *_: (_ for _ in ()).throw(
            StartupError(StartupFailureView(StartupFailureKind.QML_LOAD))
        ),
    )
    presenter = RecordingPresenter()

    result = main([], startup_error_presenter=presenter)

    assert result == 2
    assert presenter.calls == [
        (
            StartupFailureView(StartupFailureKind.QML_LOAD),
            StartupPresentationMode.INTERACTIVE,
        )
    ]
    assert FakeFacade.instances[0].applied == []
    assert FakeFacade.instances[0].disposed == 1
    assert factory.foreground_calls == 0
    assert factory.startup_scopes[0].close_calls == 1
