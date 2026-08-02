# TASK-0018 — Local Ollama Smoke Acceptance

Status: Blocked by TASK-0017

## Goal

Run and record the sole opt-in live-model acceptance criterion after all
deterministic and UI acceptance criteria are green.

## Sources

- `ACCEPTANCE_TESTS.md` AT-016
- `docs/contracts/ModelGateway.md`
- `docs/contracts/ConfigurationAndLogging.md`
- `DEFINITION_OF_DONE.md`

## Required work

1. Confirm default unit/integration/evaluation/UI suites are green before live
   execution.
2. Prepare the synthetic AT-016 fixture and explicit loopback configuration with
   `temperature: 0.0`, timeout `60`, and a named installed local model.
3. Run the marked `ollama` acceptance only with
   `CONTEXT_FOR_AI_RUN_OLLAMA=1` and `CONTEXT_FOR_AI__MODEL__NAME` set.
4. Record non-secret model metadata, Ollama version, OS, configuration
   fingerprint, timing, result, and any limitation. Do not log fixture prompt
   or response content in routine logs.
5. Report a missing daemon/model, timeout, token mismatch, or validation failure
   as a failed acceptance result; do not convert it to a silent skip.

## Boundaries

- Do not change application logic merely to make a live model pass.
- Do not add cloud fallback, model routing, streaming, external service, or
  background processing.
- Do not claim MVP completion if any deterministic acceptance test is failing.

## Verification

- Run the full default suite.
- Run AT-016 with explicit opt-in conditions and preserve the required artifact.
- Review trace redaction and final assistant-message lineage.

## Exit criteria

- AT-016 passes with a local configured Ollama model.
- All AT-001 through AT-015 are green in their required environments.
- The completion report meets `DEFINITION_OF_DONE.md`.
