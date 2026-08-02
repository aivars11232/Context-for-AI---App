# TASK-0009 — Manual Memory Lifecycle and Deterministic Retrieval

Status: Blocked by TASK-0008

## Goal

Implement explicit-user-operation memory lifecycle behavior and deterministic
keyword retrieval without autonomous mutation.

## Sources

- `docs/contracts/DomainAndDecisionRules.md`
- `DATABASE_SCHEMA.md`
- `REQUIREMENTS.md` FR-009, FR-014, and FR-016
- `ACCEPTANCE_TESTS.md` AT-008 and AT-014

## Required work

1. Implement explicit create, edit, inspect, and soft-delete use cases with
   required source records and immutable revisions.
2. Implement expiry-as-exclusion, scope eligibility, exact duplicate handling
   during retrieval only, and no automatic merge/rewrite/deletion behavior.
3. Implement the canonical normalization, scoring formula, threshold,
   deterministic tie-breaking, rank/reason persistence, and injected clock.
4. Add unit/integration/evaluation tests for provenance, revisions, scopes,
   expiry, duplicates, cross-project exclusion, score calculation, and deletion.

## Boundaries

- Do not create extraction, summary, cleanup, embedding, or background workers.
- Do not automatically create/merge/rewrite/delete memory after messages.
- Do not build packets or call providers.

## Verification

- Run memory unit, evaluation, and temporary-SQLite integration tests.
- Demonstrate AT-008 and AT-014 observable assertions.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every memory has inspectable provenance and revision history.
- Retrieval exactly follows the canonical deterministic rules.
- All verification is green.
