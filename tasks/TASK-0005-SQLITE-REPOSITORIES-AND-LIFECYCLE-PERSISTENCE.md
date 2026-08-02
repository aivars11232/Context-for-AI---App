# TASK-0005 — SQLite Repositories and Lifecycle Persistence

Status: Blocked by TASK-0004

## Goal

Implement every canonical repository and durable lifecycle invariant using the
completed SQLite schema.

## Sources

- `DATABASE_SCHEMA.md`
- `docs/contracts/Persistence.md`
- `COMPONENT_CONTRACTS.md`

## Required work

1. Implement all repository ports, including entity/reference, constraints,
   memory source/revision, processing run, packet/retrieval, model lifecycle,
   validation, correction, failure, settings, and evaluation repositories.
2. Implement short transaction helpers, compare-and-swap state updates,
   idempotency lookup/create, and restrictive archive/soft-delete behavior.
3. Persist valid assistant-message/model-response lineage and prevent invalid
   candidates from receiving an assistant-message link.
4. Add isolated repository integration tests for FK behavior, lifecycle states,
   source/revision atomicity, idempotency uniqueness, attempt uniqueness, and
   typed persistence errors.

## Boundaries

- Do not orchestrate `ProcessUserMessage` yet.
- Do not add automatic memory mutation, provider calls, UI, workers, or retries.
- Do not expose SQL rows outside infrastructure.

## Verification

- Run focused temporary-SQLite repository integration tests.
- Run migration plus repository suites together.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every repository in `Persistence.md` has one implementation.
- All lifecycle/integrity invariants have integration coverage.
- All verification is green.
