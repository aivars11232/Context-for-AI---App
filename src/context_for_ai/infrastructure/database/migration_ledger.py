"""Bootstrap the only SQLite structure permitted in TASK-0001."""

from __future__ import annotations

from pathlib import Path
import sqlite3


def initialize_migration_ledger(database_path: Path) -> Path:
    """Create an empty database ledger without applying any canonical migration."""

    resolved_path = Path(database_path).resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(resolved_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
    return resolved_path
