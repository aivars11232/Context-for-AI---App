"""SQLite integration coverage for pre-QML shell preparation."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from context_for_ai.application import (
    PrepareApplicationShellRequest,
    RecoveryRequiredResult,
    ShellPreparationFailureKind,
    ShellPreparationFailureResult,
    ShellReadyResult,
)
from context_for_ai.application.prepare_application_shell import (
    PrepareApplicationShellService,
)
from context_for_ai.domain.entities import Conversation, ConversationState, Message, Project
from context_for_ai.domain.enums import MessageRole, ProcessingRunStatus, ProjectStatus
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.infrastructure.database import (
    SQLiteConversationRepository,
    SQLiteConversationStateRepository,
    SQLiteMessageRepository,
    SQLiteProcessingRunRepository,
    SQLiteProjectRepository,
    SQLiteSettingsRepository,
    SQLiteTransactionBoundary,
    apply_migrations,
    connect_database,
)


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"52000000-0000-4000-8000-{number:012x}")


def initial_state(conversation_id: DomainId) -> ConversationState:
    return ConversationState(conversation_id, None, None, None, None, (), 0, NOW)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FixedIds:
    def __init__(self, value: DomainId) -> None:
        self._value = value

    def new_id(self) -> DomainId:
        return self._value


class FailingStateRepository:
    def __init__(self, delegate: SQLiteConversationStateRepository) -> None:
        self._delegate = delegate

    def get(self, conversation_id: DomainId) -> ConversationState | None:
        return self._delegate.get(conversation_id)

    def add(self, state: ConversationState) -> None:
        raise PersistenceError("Injected state write failure.")


def prepare_service(
    connection: sqlite3.Connection,
    *,
    new_id: DomainId = identifier(999),
    states: SQLiteConversationStateRepository | FailingStateRepository | None = None,
) -> PrepareApplicationShellService:
    return PrepareApplicationShellService(
        projects=SQLiteProjectRepository(connection),
        conversations=SQLiteConversationRepository(connection),
        conversation_states=states or SQLiteConversationStateRepository(connection),
        processing_runs=SQLiteProcessingRunRepository(connection),
        settings=SQLiteSettingsRepository(connection),
        transactions=SQLiteTransactionBoundary(connection),
        clock=FixedClock(),
        id_generator=FixedIds(new_id),
    )


def open_database(tmp_path: Path, name: str) -> sqlite3.Connection:
    return connect_database(apply_migrations(tmp_path / name))


def test_first_run_creates_only_atomic_default_conversation_and_state(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path, "shell-first-run.sqlite3")
    try:
        result = prepare_service(connection).execute(PrepareApplicationShellRequest())

        assert result == ShellReadyResult(identifier(999), True)
        assert SQLiteConversationRepository(connection).get(identifier(999)) == Conversation(
            identifier(999), None, None, NOW, NOW
        )
        assert SQLiteConversationStateRepository(connection).get(
            identifier(999)
        ) == initial_state(identifier(999))
        assert SQLiteSettingsRepository(connection).get(
            "ui.last_selected_conversation_id"
        ) is None
        for table in (
            "projects",
            "topics",
            "tasks",
            "messages",
            "processing_runs",
            "memories",
            "entity_registry",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        connection.close()


def test_preference_then_stale_fallback_selects_latest_with_uuid_tie_break(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path, "shell-selection.sqlite3")
    projects = SQLiteProjectRepository(connection)
    conversations = SQLiteConversationRepository(connection)
    states = SQLiteConversationStateRepository(connection)
    settings = SQLiteSettingsRepository(connection)
    transactions = SQLiteTransactionBoundary(connection)
    project = Project(identifier(1), "Active", None, ProjectStatus.ACTIVE, NOW, NOW)
    preferred = Conversation(identifier(20), None, "Preferred", NOW, NOW)
    tie_winner = Conversation(
        identifier(21),
        project.id,
        "Tie winner",
        NOW,
        NOW + timedelta(minutes=1),
    )
    tie_loser = Conversation(
        identifier(22),
        None,
        "Tie loser",
        NOW,
        NOW + timedelta(minutes=1),
    )
    try:
        with transactions.transaction():
            projects.add(project)
            for record in (preferred, tie_winner, tie_loser):
                conversations.add(record)
                states.add(initial_state(record.id))
            settings.set(
                key="ui.last_selected_conversation_id",
                value=str(preferred.id),
                updated_at=NOW,
            )

        service = prepare_service(connection)
        assert service.execute(PrepareApplicationShellRequest()) == ShellReadyResult(
            preferred.id,
            False,
        )

        settings.set(
            key="ui.last_selected_conversation_id",
            value=str(identifier(404)),
            updated_at=NOW,
        )
        assert service.execute(PrepareApplicationShellRequest()) == ShellReadyResult(
            tie_winner.id,
            False,
        )
    finally:
        connection.close()


def test_recovery_preflight_wins_without_conversation_or_setting_mutation(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path, "shell-recovery.sqlite3")
    conversations = SQLiteConversationRepository(connection)
    states = SQLiteConversationStateRepository(connection)
    messages = SQLiteMessageRepository(connection)
    runs = SQLiteProcessingRunRepository(connection)
    transactions = SQLiteTransactionBoundary(connection)
    conversation = Conversation(identifier(30), None, None, NOW, NOW)
    message = Message(identifier(31), conversation.id, MessageRole.USER, "pending", NOW, 0)
    run = ProcessingRun(
        identifier(32),
        conversation.id,
        message.id,
        str(identifier(33)),
        ProcessingRunStatus.PERSISTED,
        0,
        "fixture",
        NOW,
        None,
    )
    try:
        with transactions.transaction():
            conversations.add(conversation)
            states.add(initial_state(conversation.id))
            messages.add(message)
            runs.add(run)

        result = prepare_service(connection).execute(PrepareApplicationShellRequest())

        assert result == RecoveryRequiredResult(run.id, conversation.id)
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
        assert SQLiteSettingsRepository(connection).get(
            "ui.last_selected_conversation_id"
        ) is None
    finally:
        connection.close()


def test_real_transaction_rolls_back_first_write_when_state_write_fails(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path, "shell-rollback.sqlite3")
    states = SQLiteConversationStateRepository(connection)
    try:
        result = prepare_service(
            connection,
            states=FailingStateRepository(states),
        ).execute(PrepareApplicationShellRequest())

        assert result == ShellPreparationFailureResult(
            ShellPreparationFailureKind.CONVERSATION_SETUP_FAILED
        )
        assert connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM conversation_states"
        ).fetchone()[0] == 0
    finally:
        connection.close()
