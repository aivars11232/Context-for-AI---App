# TASK-0014 — Complete Idempotent Backend Pipeline

Status: Blocked by TASK-0013

## Goal

Implement the public `ProcessUserMessage` use case and all documented
transactions, lifecycle transitions, recovery, concurrency, and safe outcomes.

## Sources

- `docs/contracts/ProcessUserMessage.md`
- `docs/contracts/Persistence.md`
- `ARCHITECTURE.md`
- `ACCEPTANCE_TESTS.md` AT-002, AT-012, and AT-015

## Required work

1. Orchestrate acceptance, context, request-start, candidate, and terminal
   transactions in the canonical order.
2. Enforce idempotency, one non-terminal run per conversation, state
   compare-and-swap, restart recovery, and no uncertain model-call retry.
3. Return accepted text, clarification, cancellation, or controlled failure
   through typed use-case results; never return an invalid candidate as final.
4. Persist all decisions, requests, responses, validation, correction, failure,
   state, and final assistant-message lineage.
5. Add public-seam integration tests with the mock provider for all lifecycle
   branches, restart points, duplicate submissions, and persistence failure.

## Boundaries

- No QML/UI work, HTTP service, background queue, or automatic memory mutation.
- Do not use live Ollama in required tests; mock provider behavior is required.
- Do not add retries beyond bounded validation revisions.

## Verification

- Run complete-pipeline integration tests against temporary SQLite storage.
- Demonstrate AT-002, AT-012, and AT-015; re-run AT-003 through AT-011 through
  the public use case where applicable.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every terminal path is durable, typed, and traceable to the user message.
- Idempotency/recovery/concurrency behavior matches the contracts.
- All verification is green.
