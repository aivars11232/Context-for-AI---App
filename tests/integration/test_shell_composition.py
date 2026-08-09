"""Production shell-composition and SQLite ownership integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import queue
import socket
import sqlite3
import threading
from typing import Any

import pytest

from context_for_ai.application import (
    ContextInspectionEmptyResult,
    InspectContextRequest,
    InspectContextService,
    PrepareApplicationShellRequest,
    ProcessUserMessageService,
    RecoverProcessingRunService,
    ShellReadyResult,
)
from context_for_ai.bootstrap import (
    ProductionShellScopeFactory,
    UuidIdempotencyKeyFactory,
)
from context_for_ai.domain.enums import IntentType, ProviderKind, QualifierKind
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.infrastructure.configuration import load_configuration
from context_for_ai.infrastructure.database import apply_migrations, connect_database


NOW = datetime(2026, 8, 9, 14, 0, tzinfo=UTC)


class TraceSink:
    def emit(self, _: object) -> None:
        return


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FixedIds:
    def __init__(self) -> None:
        self.calls = 0

    def new_id(self) -> DomainId:
        self.calls += 1
        return DomainId(f"53000000-0000-4000-8000-{self.calls:012x}")


class TrackedConnection:
    """Delegate SQLite operations while recording its ownership boundary."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        object.__setattr__(self, "connection", connection)
        object.__setattr__(self, "opened_thread_id", threading.get_ident())
        object.__setattr__(self, "closed_thread_id", None)
        object.__setattr__(self, "close_calls", 0)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)

    def __setattr__(self, name: str, value: object) -> None:
        if name in {
            "connection",
            "opened_thread_id",
            "closed_thread_id",
            "close_calls",
        }:
            object.__setattr__(self, name, value)
            return
        setattr(self.connection, name, value)

    def close(self) -> None:
        self.close_calls += 1
        self.closed_thread_id = threading.get_ident()
        self.connection.close()


class TrackingConnectionFactory:
    def __init__(self) -> None:
        self.connections: list[TrackedConnection] = []

    def __call__(self, path: Path) -> TrackedConnection:
        tracked = TrackedConnection(connect_database(path))
        self.connections.append(tracked)
        return tracked


def production_factory(
    fixture_application_root: Path,
    tmp_path: Path,
    connections: TrackingConnectionFactory,
) -> ProductionShellScopeFactory:
    loaded = load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    database_path = apply_migrations(tmp_path / "shell-composition.sqlite3")
    return ProductionShellScopeFactory(
        configuration=loaded,
        database_path=database_path,
        trace_logger=TraceSink(),
        connection_factory=connections,  # type: ignore[arg-type]
        clock=FixedClock(),
        id_generator=FixedIds(),
    )


def test_factory_converts_configuration_without_sqlite_or_network_contact(
    fixture_application_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    database_path = apply_migrations(tmp_path / "no-contact.sqlite3")
    connection_calls: list[Path] = []

    def forbidden_connection(path: Path) -> sqlite3.Connection:
        connection_calls.append(path)
        raise AssertionError("Factory construction must not open SQLite.")

    def forbidden_network(*_: object, **__: object) -> None:
        raise AssertionError("Factory construction must not contact Ollama.")

    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    factory = ProductionShellScopeFactory(
        configuration=loaded,
        database_path=database_path,
        trace_logger=TraceSink(),
        connection_factory=forbidden_connection,
    )

    snapshot = factory.configuration_snapshot
    assert connection_calls == []
    assert snapshot.configuration_fingerprint == loaded.configuration_fingerprint
    assert snapshot.model.provider is ProviderKind.OLLAMA
    assert snapshot.model == loaded.model
    assert snapshot.context.intent_rules[0].intent is IntentType.ANSWER
    assert snapshot.context.intent_rules[0].output_type is None
    assert snapshot.context.qualifier_rules[0].qualifier is QualifierKind.ONLY
    assert snapshot.logging.include_content is False


def test_fresh_scopes_expose_only_owned_use_cases_and_share_durable_state(
    fixture_application_root: Path,
    tmp_path: Path,
) -> None:
    connections = TrackingConnectionFactory()
    factory = production_factory(fixture_application_root, tmp_path, connections)
    owner_thread_id = threading.get_ident()

    first_scope = factory.open_startup_scope()
    first_result = first_scope.prepare_application_shell.execute(
        PrepareApplicationShellRequest()
    )
    assert isinstance(first_result, ShellReadyResult)
    assert first_result.initial_conversation_created is True
    assert not hasattr(first_scope, "process_user_message")
    first_scope.close()
    first_scope.close()

    second_scope = factory.open_startup_scope()
    second_result = second_scope.prepare_application_shell.execute(
        PrepareApplicationShellRequest()
    )
    assert second_result == ShellReadyResult(first_result.conversation_id, False)
    second_scope.close()

    assert len(connections.connections) == 2
    assert connections.connections[0] is not connections.connections[1]
    assert all(
        connection.opened_thread_id == owner_thread_id
        and connection.closed_thread_id == owner_thread_id
        and connection.close_calls == 1
        for connection in connections.connections
    )


def test_foreground_scope_is_opened_built_and_closed_on_worker_thread(
    fixture_application_root: Path,
    tmp_path: Path,
) -> None:
    connections = TrackingConnectionFactory()
    factory = production_factory(fixture_application_root, tmp_path, connections)
    observations: queue.SimpleQueue[tuple[int, bool, bool, bool]] = queue.SimpleQueue()

    def use_scope() -> None:
        scope = factory.open_foreground_scope()
        observations.put(
            (
                threading.get_ident(),
                isinstance(scope.process_user_message, ProcessUserMessageService),
                isinstance(scope.recover_processing_run, RecoverProcessingRunService),
                hasattr(scope, "prepare_application_shell"),
            )
        )
        scope.close()

    worker = threading.Thread(target=use_scope)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    worker_thread_id, has_process, has_recovery, has_preparation = observations.get()

    assert has_process is True
    assert has_recovery is True
    assert has_preparation is False
    assert worker_thread_id != threading.get_ident()
    assert len(connections.connections) == 1
    assert connections.connections[0].opened_thread_id == worker_thread_id
    assert connections.connections[0].closed_thread_id == worker_thread_id


def test_inspection_scope_opens_queries_and_closes_on_its_worker_thread(
    fixture_application_root: Path,
    tmp_path: Path,
) -> None:
    connections = TrackingConnectionFactory()
    factory = production_factory(fixture_application_root, tmp_path, connections)
    startup = factory.open_startup_scope()
    prepared = startup.prepare_application_shell.execute(
        PrepareApplicationShellRequest()
    )
    assert isinstance(prepared, ShellReadyResult)
    startup.close()
    observations: queue.SimpleQueue[tuple[int, bool, bool, object]] = queue.SimpleQueue()

    def use_scope() -> None:
        scope = factory.open_inspection_scope()
        result = scope.inspect_context.execute(
            InspectContextRequest(prepared.conversation_id)
        )
        observations.put(
            (
                threading.get_ident(),
                isinstance(scope.inspect_context, InspectContextService),
                hasattr(scope, "process_user_message")
                or hasattr(scope, "prepare_application_shell"),
                result,
            )
        )
        scope.close()

    worker = threading.Thread(target=use_scope)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    worker_thread_id, has_inspection, has_other_use_case, result = observations.get()

    assert has_inspection is True
    assert has_other_use_case is False
    assert result == ContextInspectionEmptyResult()
    assert worker_thread_id != threading.get_ident()
    assert len(connections.connections) == 2
    inspection_connection = connections.connections[1]
    assert inspection_connection.opened_thread_id == worker_thread_id
    assert inspection_connection.closed_thread_id == worker_thread_id
    assert inspection_connection.close_calls == 1


def test_scope_rejects_cross_thread_close_then_owner_can_close(
    fixture_application_root: Path,
    tmp_path: Path,
) -> None:
    connections = TrackingConnectionFactory()
    factory = production_factory(fixture_application_root, tmp_path, connections)
    scope = factory.open_startup_scope()
    outcomes: queue.SimpleQueue[BaseException | None] = queue.SimpleQueue()

    def close_from_other_thread() -> None:
        try:
            scope.close()
        except BaseException as error:
            outcomes.put(error)
        else:
            outcomes.put(None)

    worker = threading.Thread(target=close_from_other_thread)
    worker.start()
    worker.join(timeout=5)

    error = outcomes.get()
    assert isinstance(error, RuntimeError)
    assert connections.connections[0].close_calls == 0
    scope.close()
    assert connections.connections[0].closed_thread_id == threading.get_ident()


def test_uuid_idempotency_factory_returns_fresh_domain_ids() -> None:
    factory = UuidIdempotencyKeyFactory()

    first = factory.new_key()
    second = factory.new_key()

    assert isinstance(first, DomainId)
    assert isinstance(second, DomainId)
    assert first != second
