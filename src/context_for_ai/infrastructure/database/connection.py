"""Create application-owned SQLite connections with required safety settings."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from context_for_ai.domain.ports.errors import PersistenceError


def connect_database(database_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement enabled.

    The database parent directory is created for local first-run startup. A
    typed persistence failure is raised when the connection cannot be opened or
    SQLite refuses to enable the required foreign-key setting.
    """

    resolved_path = Path(database_path).resolve()
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(resolved_path)
        connection.execute("PRAGMA foreign_keys = ON")
        foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()
    except (OSError, sqlite3.Error) as error:
        raise PersistenceError("SQLite connection initialization failed.") from error

    if foreign_keys_enabled != (1,):
        connection.close()
        raise PersistenceError("SQLite foreign-key enforcement could not be enabled.")
    return connection
