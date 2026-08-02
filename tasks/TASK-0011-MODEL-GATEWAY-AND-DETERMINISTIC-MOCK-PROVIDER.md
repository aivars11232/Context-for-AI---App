# TASK-0011 — Model Gateway and Deterministic Mock Provider

Status: Blocked by TASK-0010

## Goal

Implement the inward-facing buffered generation port and deterministic mock
provider needed for all non-live pipeline tests.

## Sources

- `docs/contracts/ModelGateway.md`
- `ARCHITECTURE.md`
- `ACCEPTANCE_TESTS.md` AT-010

## Required work

1. Implement typed gateway request/completed/failure results, cancellation
   token support, trace IDs, and safe error mapping.
2. Implement `MockModelProvider` fixture behavior for complete success,
   timeout, cancellation, unavailable model, and invalid response outcomes.
3. Implement composition-root wiring boundaries and static import checks proving
   application/domain code has no Ollama implementation import.
4. Add deterministic gateway contract tests and full buffering assertions.

## Boundaries

- Do not implement the Ollama transport until TASK-0012.
- Do not stream partial text, retry transport, route/fallback models, call tools,
  use cloud providers, or show provider output in QML.
- Do not validate response content here.

## Verification

- Run gateway contract/unit tests with the mock provider.
- Demonstrate AT-010 import, buffering, persistence-input, and trace behavior.
- Run all current tests and syntax/import validation.

## Exit criteria

- Mock generation is deterministic and complete-output-only.
- Provider implementation remains outward of the gateway port.
- All verification is green.
