"""Minimal SQLite bootstrap boundary for the schema migration ledger."""

from .migration_ledger import initialize_migration_ledger

__all__ = ["initialize_migration_ledger"]
