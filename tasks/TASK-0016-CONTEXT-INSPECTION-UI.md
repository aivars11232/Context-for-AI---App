# TASK-0016 — Context Inspection UI

Status: Blocked by TASK-0015

## Goal

Implement the required context-inspection view using persisted, observable data
from application use cases.

## Sources

- `REQUIREMENTS.md` FR-015
- `MVP_SCOPE.md`
- `ACCEPTANCE_TESTS.md` AT-013
- `ARCHITECTURE.md`

## Required work

1. Implement a context-inspection page/panel showing active project/topic/task,
   intent, expected output type, qualifier evidence, reference outcomes and
   sources, constraints/conflicts, retrieved memories with scores/reasons,
   confidence, validation, correction count, and controlled failure status.
2. Load the view through application inspection use cases, not direct database
   access from QML.
3. Add empty/loading/error/clarification states without exposing raw prompts or
   invalid candidate responses.
4. Add offscreen UI tests for all AT-013 fields and accessibility-friendly
   labels/state updates.

## Boundaries

- Do not add file context, embeddings, vector search, provider configuration,
  automatic memory edits, or direct SQL/model calls in UI.
- Do not turn inspection into a local HTTP API.

## Verification

- Run focused context-inspection UI tests with a deterministic mock pipeline.
- Demonstrate every AT-013 assertion.
- Run all current tests and application-startup validation.

## Exit criteria

- The user can inspect every required context decision and safe final status.
- Inspection remains responsive and uses only application-facing data.
- All verification is green.
