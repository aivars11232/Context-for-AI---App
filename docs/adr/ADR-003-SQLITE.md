# ADR-003 — SQLite Persistence

Status: Accepted

Decision: Use SQLite as the only MVP database.

Consequences: Local-first deployment and simple backup. Enable foreign keys, use explicit migrations, and preserve existing data. External databases are excluded from MVP.
