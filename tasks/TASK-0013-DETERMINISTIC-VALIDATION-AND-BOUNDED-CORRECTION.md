# TASK-0013 — Deterministic Validation and Bounded Correction

Status: Blocked by TASK-0012

## Goal

Implement deterministic candidate validation and correction control without
weakening packet constraints or exposing invalid output.

## Sources

- `docs/contracts/ResponseValidation.md`
- `docs/contracts/ContextPacket.md`
- `REQUIREMENTS.md` FR-012 and FR-013
- `ACCEPTANCE_TESTS.md` AT-011 and AT-012

## Required work

1. Implement every canonical validation check, typed violation/evidence shape,
   score, warning behavior, and pass/fail rule.
2. Implement correction-envelope construction from immutable packet and failed
   candidate IDs, respecting configured `max_revisions` in `0..2`.
3. Persist validation results, correction attempts, and controlled exhaustion
   through the established ports/repositories.
4. Add deterministic fixtures for pass, each violation type, warnings,
   unchanged hard constraints, attempts `0`/`1`/`2`, and controlled exhaustion.

## Boundaries

- No model call inside the validator and no fact/hallucination oracle.
- No automatic transport retry, constraint weakening, packet mutation, or
  display of an invalid candidate.
- Do not orchestrate the complete pipeline until TASK-0014.

## Verification

- Run validation/correction unit and integration tests with the mock provider.
- Demonstrate AT-011 and AT-012 exactly, including assistant-message absence on
  exhaustion.
- Run all current tests and syntax/import validation.

## Exit criteria

- Three generation attempts are the absolute upper bound when configured at 2.
- Every candidate has deterministic validation evidence.
- All verification is green.
