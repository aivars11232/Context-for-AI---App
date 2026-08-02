# TASK-0006 — Versioned Conversation State

Status: Blocked by TASK-0005

## Goal

Implement deterministic, versioned conversation-state transitions with one
source of truth for the active project.

## Sources

- `docs/contracts/DomainAndDecisionRules.md`
- `DATABASE_SCHEMA.md`
- `REQUIREMENTS.md` FR-003 and NFR-008

## Required work

1. Implement state snapshots and transitions for project selection, topic stack,
   active task, previous task, task status, and expected output type.
2. Enforce that `conversations.project_id` is the sole persisted active project.
3. Implement high-confidence topic/task transitions, `CONTINUE`/`CORRECT`
   semantics, ten-item stack behavior, and compare-and-swap versioning.
4. Add deterministic unit and temporary-SQLite integration tests, including
   project switches, topic-stack overflow, version conflict, and concurrent-run
   busy behavior.

## Boundaries

- Do not parse natural language beyond passing prepared interpretation results.
- Do not resolve references, retrieve memory, call a model, or build packets.
- Do not introduce a second active-project field or autonomous task completion.

## Verification

- Run state-transition unit tests and repository integration tests.
- Prove AT-003 state assertions through the public state/use-case seam.
- Run all current tests and syntax/import validation.

## Exit criteria

- State transitions match the canonical rules and are recoverable/versioned.
- No project/state duplicate source of truth exists.
- All verification is green.
