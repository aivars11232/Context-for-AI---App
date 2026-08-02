# TASK-0012 — Buffered Local Ollama Provider

Status: Blocked by TASK-0011

## Goal

Implement the sole MVP runtime provider: a buffered local Ollama adapter behind
the established gateway port.

## Sources

- `docs/contracts/ModelGateway.md`
- `docs/contracts/ConfigurationAndLogging.md`
- `MVP_SCOPE.md`

## Required work

1. Implement loopback-only Ollama configuration validation, health check, model
   existence check, request timeout, cancellation, full-output buffering, and
   non-secret metadata capture.
2. Map provider outcomes to the canonical typed failures and request lifecycle
   states without automatic retry.
3. Add isolated optional transport tests marked `ollama`; default tests use the
   mock provider and must not require a daemon.
4. Add tests proving partial output is neither exposed to UI nor persisted as a
   candidate and timeout/cancellation end safely.

## Boundaries

- Only one configured local Ollama model is permitted.
- No FastAPI, cloud URL, API key, provider fallback, model routing, streaming,
  tools, image generation, or background worker.
- Do not implement full pipeline orchestration or correction here.

## Verification

- Run all mock-provider gateway tests.
- Run optional marked transport tests only when a local daemon/model is
  explicitly available; record a skip as environment absence, not a pass.
- Run all current tests and syntax/import validation.

## Exit criteria

- Local transport obeys timeout/cancel/buffer policy and exposes typed outcomes.
- Default test suite remains independent of Ollama.
- All required verification is green.
