# Context for AI — Implementation Plan

Implement one numbered task at a time. Do not begin a task until every earlier
task's exit criteria and relevant acceptance criteria pass. The detailed task
files under `tasks/` are mandatory delivery contracts; this plan is their
ordered summary.

## Stage 1 — Repository foundation (`TASK-0001`)

Create the Python packaging, validated six-file YAML bootstrap, logging
bootstrap, minimal QML startup boundary, and isolated test layout. `pyproject.toml`
is the sole dependency-management source of truth; do not add `requirements.txt`.

**Exit:** AT-001 startup/configuration behavior passes with fixtures.

## Stage 2 — Domain and ports (`TASK-0002`, `TASK-0003`)

Implement canonical value objects, enums, entities, typed errors, deterministic
policies, and inward repository/model/clock ports without imports from Qt,
SQLite, or Ollama.

**Exit:** domain/port unit tests pass; import-boundary checks pass.

## Stage 3 — SQLite schema and repositories (`TASK-0004`, `TASK-0005`)

Implement numbered migrations for the canonical schema, all required repository
ports, transaction helpers, state-version checks, idempotency storage, lineage,
and memory revision/provenance persistence.

**Exit:** isolated SQLite migration/repository integration tests pass,
including data-preservation, lifecycle, and FK behavior.

## Stage 4 — Deterministic context intelligence (`TASK-0006`–`TASK-0010`)

Implement state transitions, interpretation/qualifiers/constraints, reference
resolution, memory retrieval, and immutable packet rendering using the
canonical rules only.

**Exit:** AT-003 through AT-009 pass with deterministic fixtures.

## Stage 5 — Controlled model flow (`TASK-0011`–`TASK-0013`)

Implement the mock gateway, bounded foreground provider port, local Ollama
adapter, deterministic validation, and correction controller. No streaming,
routing, fallback, cloud provider, or transport retry is permitted.

**Exit:** AT-010 through AT-012 pass with the mock provider; Ollama adapter has
isolated optional transport tests.

## Stage 6 — Complete mock-provider pipeline (`TASK-0014`)

Implement `ProcessUserMessage` with the documented persistence ordering,
transactions, idempotency, recovery, concurrency handling, safe failures, and
state updates.

**Exit:** AT-002, AT-015, and applicable AT-003–AT-012 assertions pass through
the public use case with the mock provider.

## Stage 7 — Desktop MVP (`TASK-0015`–`TASK-0017`)

Implement the QML shell, bounded foreground request presentation, context
inspection, and explicit manual memory/project/validation/settings views.

**Exit:** AT-013 and AT-014 pass; no UI thread blocking or hidden automatic
memory mutation remains.

## Stage 8 — Local Ollama acceptance (`TASK-0018`)

Run the opt-in, reproducible local-Ollama smoke acceptance against the
configured local model and record non-secret environment/model metadata.

**Exit:** AT-016 passes. A failed or unavailable live environment is reported,
not ignored.
