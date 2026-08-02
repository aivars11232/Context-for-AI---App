"""SQLite integration coverage limited to the TASK-0001 migration ledger."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from context_for_ai.infrastructure.database import initialize_migration_ledger


def test_empty_database_initializes_only_the_migration_ledger(tmp_path: Path) -> None:
    database_path = initialize_migration_ledger(tmp_path / "database" / "context.sqlite3")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }
        ledger_rows = connection.execute("SELECT * FROM schema_migrations").fetchall()

    assert tables == {"schema_migrations"}
    assert ledger_rows == []
