# TASK-0008 — Entity Registry and Reference Resolution

Status: Blocked by TASK-0007

## Goal

Implement deterministic entity registration and reference outcomes with clear
ambiguity handling and provenance.

## Sources

- `DATABASE_SCHEMA.md`
- `docs/contracts/DomainAndDecisionRules.md`
- `docs/contracts/ContextEngine.md`
- `ACCEPTANCE_TESTS.md` AT-006 and AT-007

## Required work

1. Register projects, topics, tasks, and explicit named items in the entity
   registry with durable IDs and source-message evidence.
2. Implement mention extraction for MVP-supported pronouns/phrases and the
   canonical candidate ranking/confidence rules.
3. Persist `RESOLVED`, `AMBIGUOUS`, `UNRESOLVED`, and `NOT_APPLICABLE` results,
   including candidate evidence and source message IDs.
4. Implement the material-reference clarification result and tests for exact,
   stale, tied, missing, and unsupported file-reference cases.

## Boundaries

- Do not ingest, scan, index, or resolve project files.
- Do not use a model, embeddings, semantic search, or automatic named-entity
  extraction beyond explicit deterministic registration.
- Do not update memory or call a provider.

## Verification

- Run reference-resolution unit/evaluation tests.
- Demonstrate AT-006 and AT-007 against an isolated SQLite entity registry.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every persisted resolution has valid entity/source lineage or explicit
  unresolved evidence.
- Ambiguity blocks material model generation.
- All verification is green.
