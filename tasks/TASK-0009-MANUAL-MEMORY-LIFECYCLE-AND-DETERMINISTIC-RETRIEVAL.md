# TASK-0009 — Manual Memory Lifecycle and Deterministic Retrieval

Status: Specification reconciled; awaiting implementation approval

## Goal

Implement explicit-user-operation memory lifecycle behavior and deterministic
keyword retrieval without autonomous mutation.

## Sources

- `docs/contracts/DomainAndDecisionRules.md`
- `DATABASE_SCHEMA.md`
- `REQUIREMENTS.md` FR-009, FR-014, and FR-016
- `ACCEPTANCE_TESTS.md` AT-008 and AT-014

## Required work

1. Implement explicit create, edit, get/inspect, stored-status list, and
   soft-delete use cases. Each successful mutation atomically writes one source
   and one consecutive immutable `memory-revision-v1` snapshot; inspection
   exposes complete provenance/history and computed effective status.
2. Implement stored `ACTIVE`/`DELETED` and computed
   `ACTIVE`/`EXPIRED`/`DELETED` behavior. Expiry is retrieval-time exclusion
   only; deleted records remain inspectable and cannot be edited or restored.
3. Implement conversation, project, and global scope eligibility, including
   cross-conversation and cross-project exclusion evidence.
4. Implement the canonical Unicode normalization, 28-digit decimal scoring,
   inclusive threshold, total tie-breaking, zero-based ranks, ordered reason
   strings, one-primary-exclusion precedence/details, and injected-clock
   behavior from `DomainAndDecisionRules.md`.
5. Collapse exact normalized duplicates only in the retrieval decision, retain
   the canonical first record, and never merge, rewrite, or delete stored
   duplicates automatically.
6. Verify selected/excluded evidence through the existing persistence contract
   with a caller-supplied packet fixture; do not construct a packet.
7. Add unit/integration/evaluation tests for provenance, revision snapshots,
   effective status, scopes, expiry, duplicates, threshold/limit behavior,
   score calculation, tie-breaking, reasons/exclusions, persistence, and
   deletion.

## TASK-0008 dependency boundary

TASK-0008 specification reconciliation is complete at HEAD `8432241`; its
implementation is not part of this task. TASK-0009 consumes no entity-registry,
reference-extractor, resolver, or `ReferenceDecision` runtime output. Its memory
use cases and retriever depend only on the already-established conversation,
project, topic/message, configuration, clock/ID, transaction, memory repository,
and context-packet persistence contracts.

TASK-0009 may therefore proceed independently after its own implementation
approval and does not wait for TASK-0008 implementation completion. It must not
implement, integrate, or claim TASK-0008 behavior; later pipeline composition
remains responsible for ordering both completed components.

## D-013 and D-014 TASK-0009 reconciliation

TASK-0009 owns manual lifecycle use cases, pure deterministic retrieval, atomic
memory source/revision persistence, retrieval evidence persistence assertions,
and the component/use-case portions of AT-008 and AT-014. Memory history is
inspectable only; the MVP has no restore operation.

Pipeline orchestration, context-packet construction, UI/presentation, exact trace events,
and provider interaction are later-task responsibilities. The
TASK-0009 portions of D-013 and D-014 are reconciled by this bounded contract,
the canonical domain/context/schema rules, and the split AT-008/AT-014 passes.

## Boundaries

- Do not create extraction, summarization, cleanup, embedding, semantic/vector
  search, model-based memory decisions, or background workers.
- Do not automatically create, edit, merge, rewrite, expire, restore, or delete
  memory after messages or at any other implicit lifecycle point.
- Do not implement TASK-0008, build context packets, orchestrate the processing
  pipeline, emit trace events, call providers, or implement UI/presentation.

## Verification

- Run memory unit, evaluation, and temporary-SQLite integration tests.
- Demonstrate the TASK-0009 component-owned AT-008 and AT-014 assertions,
  including source/revision and retrieval-result/exclusion persistence.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every memory has inspectable provenance and revision history.
- Retrieval exactly follows the canonical deterministic rules.
- Every considered memory has exactly one selected/excluded outcome, and
  retrieval never mutates a memory.
- D-013 and the TASK-0009 portion of D-014 remain reconciled across this task,
  the canonical contracts, schema semantics, and AT-008/AT-014 ownership.
- All verification is green.
