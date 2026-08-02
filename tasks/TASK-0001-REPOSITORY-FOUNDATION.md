# TASK-0001 — Repository Foundation

Status: Ready

## Goal
Create the minimal executable and testable repository foundation. Do not implement domain entities, SQLite tables, context behavior, Ollama integration, or QML screens beyond the minimum startup boundary.

## Required work

1. Create `pyproject.toml` for Python 3.12+.
2. Create the package root `src/context_for_ai/`.
3. Create `tests/unit/`, `tests/integration/`, `tests/evaluation/`, and `tests/fixtures/`.
4. Add configuration loading for YAML files under `config/`.
5. Add logging bootstrap without secret-bearing output.
6. Add a minimal `main.py` entry point that validates configuration and exits cleanly or launches a minimal non-feature placeholder only where needed for startup verification.
7. Add tests for package import, configuration loading, invalid configuration failure, and logging bootstrap.
8. Add `.gitignore` and `.env.example` without secrets.

## Constraints

- One file at a time.
- No application feature implementation.
- No database schema implementation.
- No Ollama call.
- No future task work.
- Do not change architectural documents unless a verified conflict exists.

## Verification

Run the exact project-supported equivalents of:

- package/import validation
- `pytest`
- application startup or configuration bootstrap check

## Exit criteria

- Package imports successfully.
- Valid configuration loads.
- Invalid configuration fails with a typed clear error.
- Logging initializes.
- All tests pass.
- No later-stage functionality exists.
