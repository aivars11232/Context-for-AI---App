# TASK-0008 — Entity Registry and Reference Resolution

Status: Specification reconciled; awaiting implementation approval

## Goal

Implement deterministic entity registration and reference outcomes with clear
ambiguity handling and provenance.

## Sources

- `DATABASE_SCHEMA.md`
- `docs/contracts/DomainAndDecisionRules.md`
- `docs/contracts/ContextEngine.md`
- `ACCEPTANCE_TESTS.md` AT-006 and AT-007

## Required work

1. Register project/topic/task owners and explicit named items with exactly one
   durable entity row, canonical source-message/null-UI provenance, synchronized
   lifecycle, and atomic owner/entity creation.
2. Implement the TASK-0008 reference-form extractor. It consumes immutable
   TASK-0007 `ReferenceMention` seed evidence, adds only the canonical finite
   forms and exact scoped registry names, and emits final source-ordered
   contiguous mention ordinals without changing TASK-0007 intent/qualifiers.
3. Implement the pure `ReferenceResolver` request/decision contract and the
   canonical exact-name, active-state, recent-tracked, source-message, stale,
   tie, evidence-order, status, confidence, and source-lineage rules.
4. Persist one `RESOLVED`, `AMBIGUOUS`, `UNRESOLVED`, or `NOT_APPLICABLE`
   outcome for every final mention, including the exact non-empty candidate
   evidence JSON. Persist no synthetic row when there is no mention.
5. Return the material-reference blocking clarification reason/details and add
   deterministic exact, stale, tied, missing, declaration-target
   `NOT_APPLICABLE`, and unsupported-file cases.

## Boundaries

- TASK-0007 remains the owner of deterministic intent/qualifier interpretation;
  TASK-0008 treats its mentions as immutable seed evidence.
- Do not ingest, scan, index, or resolve project files.
- Do not use a model, embeddings, semantic search, or automatic named-entity
  extraction beyond explicit deterministic registration.
- Do not update memory or call a provider.
- Do not construct packets, orchestrate the full message pipeline, persist a
  clarification, terminalize a processing run, inspect/create a model request,
  or implement/present UI. TASK-0008 returns a blocking decision for those
  later integrations.

## Verification

- Run mention extraction, registration, reference-resolution, evidence, and
  persistence unit/integration/evaluation tests.
- Demonstrate AT-006 and the TASK-0008 component-owned part of AT-007 against an
  isolated SQLite entity registry.
- Verify atomic rollback, source lineage, lifecycle synchronization, and no
  model/provider dependency at the component boundary.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every persisted resolution has valid entity/source lineage or explicit
  unresolved evidence.
- Every final mention has exactly one persisted status/evidence row and no
  unsupported/inferred phrase creates an entity or outcome.
- A material ambiguity/unresolved result returns the canonical single blocking
  decision before provider use; later orchestration enforcement is not part of
  this task.
- D-001 and the TASK-0008 portion of D-014 remain reconciled across the task,
  canonical contracts, schema semantics, and AT-006/AT-007 ownership.
- All verification is green.
