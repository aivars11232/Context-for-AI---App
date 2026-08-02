"""SQLite connection and canonical schema-migration infrastructure."""

from .connection import connect_database
from .migration_ledger import initialize_migration_ledger
from .migrations import (
    MIGRATIONS,
    Migration,
    MigrationApplicationError,
    MigrationChecksumError,
    MigrationError,
    MigrationOrderError,
    apply_migrations,
)

__all__ = [
    "MIGRATIONS",
    "Migration",
    "MigrationApplicationError",
    "MigrationChecksumError",
    "MigrationError",
    "MigrationOrderError",
    "apply_migrations",
    "connect_database",
    "initialize_migration_ledger",
]
