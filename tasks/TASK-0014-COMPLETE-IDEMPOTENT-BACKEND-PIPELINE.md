# TASK-0014 — Complete Idempotent Backend Pipeline

Status: Specification-ready; implementation blocked by TASK-0013

## Goal

Implement the public `ProcessUserMessage` use case and all documented
transactions, lifecycle transitions, one-shot foreground recovery, global
concurrency, and exhaustive typed outcomes.

## Sources

- `docs/contracts/ProcessUserMessage.md`
- `docs/contracts/Persistence.md`
- `docs/contracts/DomainAndDecisionRules.md`
- `docs/contracts/ContextPacket.md`
- `docs/contracts/ModelGateway.md`
- `docs/contracts/ResponseValidation.md`
- `docs/contracts/ConfigurationAndLogging.md`
- `ARCHITECTURE.md`
- `ACCEPTANCE_TESTS.md` AT-002, AT-012, and AT-015

## Required work

1. Orchestrate acceptance, context, request-start, candidate, and terminal
   transactions in the canonical order.
2. Enforce idempotency, at most one global non-terminal foreground run, state
   compare-and-swap, the public restart-recovery entry, and no uncertain
   model-call retry.
3. Return only the exhaustive public result algebra, including existing, busy,
   clarification, cancellation, exhaustion, configuration, persistence,
   concurrency, and controlled-failure branches; never return an invalid
   candidate as final.
4. Persist the contract-defined context projections, closed request/response
   metadata, validation, correction, safe failures, state, and byte-exact final
   assistant-message lineage.
5. Add public-seam integration tests with the mock provider for all lifecycle
   branches, restart points, duplicate submissions, and persistence failure.

## Boundaries

- No QML/UI work, HTTP service, background queue, or automatic memory mutation.
- Do not use live Ollama in required tests; mock provider behavior is required.
- Do not add retries beyond bounded validation revisions.

## Verification

- Run complete-pipeline integration tests against temporary SQLite storage.
- Demonstrate AT-002 through the public use case, complete AT-012 orchestration,
  and all AT-015 admission, concurrency, cancellation, recovery, lineage, and
  trace assertions; re-run AT-003 through AT-011 through the public use case
  where applicable.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every terminal path is durable, typed, and traceable to the user message.
- Idempotency/recovery/concurrency behavior matches the contracts.
- TASK-0013's pure validator/correction and bounded repository-projection
  ownership remains unchanged; TASK-0014 supplies the complete lifecycle.
- All verification is green.
