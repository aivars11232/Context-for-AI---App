# TASK-0004 — Canonical SQLite Migrations

Status: Blocked by TASK-0003

## Goal

Implement numbered, transactional SQLite migrations for the single canonical
schema without introducing repository behavior.

## Sources

- `DATABASE_SCHEMA.md`
- `docs/contracts/Persistence.md`
- `REQUIREMENTS.md` NFR-005

## Required work

1. Create migration ledger support with version and checksum validation.
2. Implement the complete canonical MVP schema, including
   `reference_resolutions`, entity registry, processing lifecycle, memory
   sources/revisions, model lineage, correction, failures, and evaluations.
3. Enable foreign keys on every connection and add documented checks, unique
   constraints, indexes, and restrictive deletion behavior.
4. Add migration integration tests for empty initialization, upgrade from the
   immediately previous version, failed migration rollback, and reserved-word
   safety.

## Boundaries

- Do not implement repositories, context rules, UI, or Ollama transport.
- Do not add a `references` table, users table, vector table, file table, or
  external database.
- Do not create destructive downgrade automation.

## Verification

- Run isolated SQLite migration integration tests against temporary databases.
- Inspect foreign-key enforcement, schema checks, indexes, and migration ledger.
- Run all current tests and syntax/import validation.

## Exit criteria

- A fresh database exactly matches `DATABASE_SCHEMA.md`.
- Migration failure leaves the prior schema/version intact.
- All verification is green.
