# TASK-0001 — Repository Foundation

Status: Ready

## Goal
Create the minimal executable and testable repository foundation. Do not
implement domain entities, SQLite tables, context behavior, Ollama integration,
or QML screens beyond the minimum startup boundary.

## Required work

1. Create `pyproject.toml` for Python 3.12+ as the sole dependency-management
   source. Do not create `requirements.txt`.
2. Create the package root `src/context_for_ai/`.
3. Create `tests/unit/`, `tests/integration/`, `tests/evaluation/`, and `tests/fixtures/`.
4. Add configuration loading and validation for the six YAML files under
   `config/` exactly as specified in
   `docs/contracts/ConfigurationAndLogging.md`, including bootstrap `.env`,
   configuration-directory resolution, scalar process overrides, type coercion,
   environment agreement, and complete rule-coverage validation.
5. Add logging bootstrap without secret-bearing output.
6. Add a minimal `main.py` entry point that validates configuration and either
   exits cleanly in a check mode or launches a minimal non-feature QML startup
   boundary needed for AT-001.
7. Add tests for package import; valid complete configuration loading; default
   and explicit configuration-directory resolution; `.env`/process-environment
   precedence; valid scalar override coercion; invalid key/range/rule-coverage
   or override fixtures; typed configuration failure; logging redaction/bootstrap;
   migration-ledger bootstrap; and minimal offscreen QML startup.
8. Verify or update `.gitignore` and `.env.example` without secrets, including
   local database/log/cache exclusions and documented bootstrap variables.

## Constraints

- One file at a time.
- No application feature implementation.
- No database schema implementation, except the AT-001 migration-ledger
  bootstrap: it may create/open an empty SQLite database and initialize only
  `schema_migrations`. It must not add a numbered canonical migration, domain
  table, foreign key, repository, or persistence feature; those begin in
  `TASK-0004`.
- No Ollama call.
- No future task work.
- Do not change architectural documents unless a verified conflict exists.
- No FastAPI, HTTP API, streaming, workers, embeddings, vector store, file
  indexing, cloud provider, or model routing.

## Verification

Run the exact project-supported equivalents of:

- package/import validation
- `pytest`
- application startup or configuration bootstrap check

## Exit criteria

- Package imports successfully.
- A complete valid six-file configuration loads using documented precedence.
- Invalid configuration fails with a typed, clear, redacted error naming the
  file/key.
- An empty database can initialize the migration ledger without creating the
  canonical MVP schema.
- Logging initializes.
- All tests pass.
- No later-stage functionality exists.
