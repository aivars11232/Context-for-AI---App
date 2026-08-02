"""Bootstrap the migration ledger first established in TASK-0001."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.infrastructure.database.connection import connect_database


def initialize_migration_ledger(database_path: Path) -> Path:
    """Create an empty database ledger without applying any canonical migration."""

    resolved_path = Path(database_path).resolve()
    try:
        with connect_database(resolved_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
    except sqlite3.Error as error:
        raise PersistenceError("SQLite migration-ledger initialization failed.") from error
    return resolved_path
