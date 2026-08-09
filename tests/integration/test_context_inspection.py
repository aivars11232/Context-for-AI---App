"""Isolated SQLite coverage for the TASK-0016 inspection read boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from context_for_ai.application import (
    ContextInspectionEmptyResult,
    ContextInspectionLoadFailureResult,
    ContextInspectionReadyResult,
    InspectContextRequest,
    InspectContextService,
    InspectionCheckpoint,
)
from context_for_ai.domain.entities import Conversation, ConversationState, Message
from context_for_ai.domain.enums import (
    FailureCode,
    MessageRole,
    PipelineStage,
    ProcessingRunStatus,
)
from context_for_ai.domain.lifecycle import ProcessingRun, SafeFailure
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.value_objects import DomainId, format_utc_timestamp
from context_for_ai.infrastructure.database import (
    SQLiteClarificationRepository,
    SQLiteConstraintRepository,
    SQLiteContextPacketRepository,
    SQLiteConversationRepository,
    SQLiteConversationStateRepository,
    SQLiteInspectionSnapshotBoundary,
    SQLiteMessageRepository,
    SQLiteModelCallRepository,
    SQLiteProcessingRunRepository,
    SQLiteProjectRepository,
    SQLiteReferenceResolutionRepository,
    SQLiteTaskRepository,
    SQLiteTopicRepository,
    SQLiteTransactionBoundary,
    SQLiteValidationRepository,
    apply_migrations,
    connect_database,
)


NOW = datetime(2026, 8, 9, 11, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"92000000-0000-4000-8000-{number:012d}")


@dataclass(frozen=True, slots=True)
class Core:
    conversation: Conversation
    state: ConversationState


def repositories(connection: sqlite3.Connection) -> SimpleNamespace:
    return SimpleNamespace(
        projects=SQLiteProjectRepository(connection),
        conversations=SQLiteConversationRepository(connection),
        topics=SQLiteTopicRepository(connection),
        tasks=SQLiteTaskRepository(connection),
        conversation_states=SQLiteConversationStateRepository(connection),
        messages=SQLiteMessageRepository(connection),
        processing_runs=SQLiteProcessingRunRepository(connection),
        context_packets=SQLiteContextPacketRepository(connection),
        reference_resolutions=SQLiteReferenceResolutionRepository(connection),
        constraints=SQLiteConstraintRepository(connection),
        model_calls=SQLiteModelCallRepository(connection),
        validations=SQLiteValidationRepository(connection),
        clarifications=SQLiteClarificationRepository(connection),
    )


def seed_conversation(connection: sqlite3.Connection, number: int = 1) -> Core:
    conversation = Conversation(identifier(number), None, None, NOW, NOW)
    state = ConversationState(
        conversation.id,
        None,
        None,
        None,
        None,
        (),
        0,
        NOW,
    )
    boundary = SQLiteTransactionBoundary(connection)
    with boundary.transaction():
        SQLiteConversationRepository(connection).add(conversation)
        SQLiteConversationStateRepository(connection).add(state)
    return Core(conversation, state)


def add_run(
    connection: sqlite3.Connection,
    core: Core,
    *,
    number: int,
    sequence: int,
) -> tuple[Message, ProcessingRun]:
    source = Message(
        identifier(number),
        core.conversation.id,
        MessageRole.USER,
        f"request-{sequence}",
        NOW + timedelta(seconds=sequence),
        sequence,
    )
    run = ProcessingRun(
        identifier(number + 100),
        core.conversation.id,
        source.id,
        str(identifier(number + 200)),
        ProcessingRunStatus.PERSISTED,
        0,
        "configuration-fingerprint",
        NOW + timedelta(minutes=sequence),
        None,
    )
    boundary = SQLiteTransactionBoundary(connection)
    with boundary.transaction():
        SQLiteMessageRepository(connection).add(source)
        SQLiteProcessingRunRepository(connection).add(run)
    return source, run


def terminalize_cancelled(
    connection: sqlite3.Connection,
    run: ProcessingRun,
    *,
    number: int,
) -> ProcessingRun:
    completed_at = run.started_at + timedelta(seconds=1)
    terminal = replace(
        run,
        status=ProcessingRunStatus.CANCELLED,
        completed_at=completed_at,
    )
    failure = SafeFailure(
        identifier(number),
        run.id,
        PipelineStage.CONTEXT,
        FailureCode.CANCELLED_BY_USER,
        "The request was cancelled.",
        {},
        True,
        completed_at,
    )
    with SQLiteTransactionBoundary(connection).transaction():
        SQLiteModelCallRepository(connection).add_failure(failure)
        SQLiteProcessingRunRepository(connection).update(terminal)
    return terminal


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return apply_migrations(tmp_path / "context-inspection.sqlite3")


def test_deferred_query_only_snapshot_is_stable_and_restores_connection(
    database_path: Path,
) -> None:
    writer = connect_database(database_path)
    reader = connect_database(database_path)
    try:
        core = seed_conversation(writer)
        _, first = add_run(writer, core, number=10, sequence=1)
        first = terminalize_cancelled(writer, first, number=310)
        runs = SQLiteProcessingRunRepository(reader)
        snapshots = SQLiteInspectionSnapshotBoundary(reader)
        statements: list[str] = []
        reader.set_trace_callback(statements.append)

        with snapshots.snapshot():
            assert runs.list_for_conversation(core.conversation.id) == (first,)
            _, second = add_run(writer, core, number=20, sequence=2)
            assert runs.list_for_conversation(core.conversation.id) == (first,)
            with pytest.raises(PersistenceError, match="ambient transaction"):
                runs.add(second)

        assert runs.list_for_conversation(core.conversation.id) == (first, second)
        assert reader.in_transaction is False
        assert reader.execute("PRAGMA query_only").fetchone()[0] == 0
        normalized = tuple(statement.strip().upper() for statement in statements)
        assert "BEGIN" in normalized
        assert all("BEGIN IMMEDIATE" not in statement for statement in normalized)
    finally:
        reader.close()
        writer.close()


def test_inspect_context_uses_real_repositories_and_latest_user_sequence(
    database_path: Path,
) -> None:
    writer = connect_database(database_path)
    reader = connect_database(database_path)
    try:
        core = seed_conversation(writer)
        _, first = add_run(writer, core, number=10, sequence=2)
        terminalize_cancelled(writer, first, number=310)
        add_run(writer, core, number=20, sequence=7)
        service = InspectContextService(
            repositories=repositories(reader),
            snapshots=SQLiteInspectionSnapshotBoundary(reader),
        )

        result = service.execute(InspectContextRequest(core.conversation.id))

        assert isinstance(result, ContextInspectionReadyResult)
        assert result.view.target.user_message_sequence == 7
        assert result.view.target.request_label == "Request 7"
        assert result.view.target.checkpoint is InspectionCheckpoint.ACCEPTED
        assert reader.in_transaction is False
        assert reader.execute("PRAGMA query_only").fetchone()[0] == 0
    finally:
        reader.close()
        writer.close()


def test_empty_and_corrupt_non_user_lineage_are_distinct_results(
    database_path: Path,
) -> None:
    connection = connect_database(database_path)
    try:
        core = seed_conversation(connection)
        service = InspectContextService(
            repositories=repositories(connection),
            snapshots=SQLiteInspectionSnapshotBoundary(connection),
        )
        assert service.execute(InspectContextRequest(core.conversation.id)) == (
            ContextInspectionEmptyResult()
        )

        assistant = Message(
            identifier(50),
            core.conversation.id,
            MessageRole.ASSISTANT,
            "not a valid run source",
            NOW + timedelta(seconds=1),
            1,
        )
        SQLiteMessageRepository(connection).add(assistant)
        connection.execute(
            """
            INSERT INTO processing_runs (
                id, conversation_id, user_message_id, idempotency_key, status,
                state_version_at_start, configuration_fingerprint,
                started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(identifier(51)),
                str(core.conversation.id),
                str(assistant.id),
                str(identifier(52)),
                ProcessingRunStatus.PERSISTED.value,
                0,
                "configuration-fingerprint",
                format_utc_timestamp(NOW + timedelta(minutes=1)),
                None,
            ),
        )
        connection.commit()

        assert service.execute(InspectContextRequest(core.conversation.id)) == (
            ContextInspectionLoadFailureResult()
        )
    finally:
        connection.close()


def test_malformed_packet_json_returns_closed_load_failure_and_restores_snapshot(
    database_path: Path,
) -> None:
    connection = connect_database(database_path)
    try:
        core = seed_conversation(connection)
        source, accepted = add_run(connection, core, number=60, sequence=3)
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            """
            INSERT INTO context_packets (
                id, processing_run_id, message_id, packet_json, schema_version,
                prompt_policy_version, configuration_fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(identifier(61)),
                str(accepted.id),
                str(source.id),
                "{malformed-json",
                "context-packet-v1",
                "prompt-policy-v1",
                accepted.configuration_fingerprint,
                format_utc_timestamp(NOW + timedelta(seconds=30)),
            ),
        )
        connection.execute(
            "UPDATE processing_runs SET status = ? WHERE id = ?",
            (ProcessingRunStatus.CONTEXT_READY.value, str(accepted.id)),
        )
        connection.commit()
        connection.execute("PRAGMA ignore_check_constraints = OFF")
        service = InspectContextService(
            repositories=repositories(connection),
            snapshots=SQLiteInspectionSnapshotBoundary(connection),
        )

        result = service.execute(InspectContextRequest(core.conversation.id))

        assert result == ContextInspectionLoadFailureResult()
        assert connection.in_transaction is False
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 0
    finally:
        connection.close()
