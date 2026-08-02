# TASK-0017 — Manual Memory, Project, Validation, and Settings UI

Status: Blocked by TASK-0016

## Goal

Expose the remaining explicitly scoped MVP user operations through safe
application use cases.

## Sources

- `MVP_SCOPE.md`
- `REQUIREMENTS.md` FR-014 through FR-018
- `docs/contracts/ConfigurationAndLogging.md`
- `ACCEPTANCE_TESTS.md` AT-014

## Required work

1. Implement memory inspection, explicit create/edit/soft-delete confirmation,
   provenance/source display, revision history, expiry state, and duplicate
   guidance without an automatic merge button.
2. Implement project selection and archiving presentation through application
   use cases; archive never deletes conversations or memories.
3. Implement validation/correction history and safe failure inspection without
   displaying invalid candidate text as final output.
4. Implement non-secret settings inspection/editing only where settings are
   permitted; YAML model/storage/logging constraints remain read-only source
   configuration and must show their origin/fingerprint.
5. Add offscreen UI/use-case tests for memory lifecycle, archive safety,
   validation history, and settings boundaries.

## Boundaries

- No automatic memory extraction/merge/rewrite/cleanup, user deletion of raw
  messages, provider routing, cloud settings, file indexing, or workers.
- Do not allow UI settings to override validated YAML model/security/logging
  configuration.

## Verification

- Run manual-memory lifecycle integration/UI tests and project/archive tests.
- Demonstrate AT-014 and re-run relevant AT-013 inspection assertions.
- Run all current tests and application-startup validation.

## Exit criteria

- All mutable memory behavior is explicit, auditable, and reversible by history.
- Project/validation/settings screens cannot breach MVP safety/configuration
  boundaries.
- All verification is green.
