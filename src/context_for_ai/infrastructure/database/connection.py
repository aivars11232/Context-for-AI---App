"""Create application-owned SQLite connections with required safety settings."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from context_for_ai.domain.ports.errors import PersistenceError


def connect_database(database_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys and WAL enabled.

    The database parent directory is created for local first-run startup. A
    typed persistence failure is raised when the connection cannot be opened or
    SQLite refuses either required safety/concurrency setting.
    """

    resolved_path = Path(database_path).resolve()
    connection: sqlite3.Connection | None = None
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(resolved_path)
        connection.execute("PRAGMA foreign_keys = ON")
        foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
    except (OSError, sqlite3.Error) as error:
        if connection is not None:
            connection.close()
        raise PersistenceError("SQLite connection initialization failed.") from error

    if foreign_keys_enabled != (1,):
        connection.close()
        raise PersistenceError("SQLite foreign-key enforcement could not be enabled.")
    if journal_mode is None or str(journal_mode[0]).casefold() != "wal":
        connection.close()
        raise PersistenceError("SQLite WAL journaling could not be enabled.")
    return connection
