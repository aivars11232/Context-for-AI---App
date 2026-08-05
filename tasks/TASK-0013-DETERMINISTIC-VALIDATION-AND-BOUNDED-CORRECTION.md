# TASK-0013 — Deterministic Validation and Bounded Correction

Status: Specification reconciled; implementation blocked until TASK-0012 exit

## Goal

Implement deterministic candidate validation and correction control without
weakening packet constraints or exposing invalid output.

## Sources

- `docs/contracts/ResponseValidation.md`
- `docs/contracts/ContextPacket.md`
- `docs/contracts/DomainAndDecisionRules.md`
- `docs/contracts/Persistence.md`
- `docs/contracts/ProcessUserMessage.md`
- `REQUIREMENTS.md` FR-012 and FR-013
- `ACCEPTANCE_TESTS.md` AT-011 and AT-012

## Required work

1. Implement the pure validator against the immutable
   `mvp-context-packet-v2` validation snapshot, including every canonical check,
   typed violation/evidence shape, exact score, warning behavior, deterministic
   ordering/deduplication, and pass/fail rule.
2. Implement the pure correction controller from the unchanged packet,
   explicit failed-candidate lineage, and failed report. The packet's validated
   `correction_limit` in `0..2` is the sole maximum and the controller returns
   only a typed envelope, typed exhaustion, or invariant error.
3. Implement the established validation/correction repository projections for
   exact reports, atomic adjacent correction request/row evidence, and the
   canonical exhaustion safe-failure value. Keep complete transaction and
   provider lifecycle orchestration outside this task.
4. Add deterministic component fixtures for pass, each violation type,
   warnings, empty candidates, malformed input, unchanged hard constraints,
   attempts `0`/`1`/`2`, invalid lineage, limits `0`/`1`/`2`, and controlled
   exhaustion.

## Boundaries

- No model call inside the validator and no fact/hallucination oracle.
- No automatic transport retry, constraint weakening, packet mutation, or
  display of an invalid candidate.
- No validator/controller repository lookup, hidden configuration, clock, ID
  generation, prompt rendering, or persistence side effect.
- Do not orchestrate the complete pipeline until TASK-0014.

## Acceptance ownership

- TASK-0013 owns all of AT-011 and only the explicitly labeled TASK-0013
  component portion of AT-012: deterministic reports/scores/warnings,
  correction decisions/envelopes, and bounded persistence evidence.
- TASK-0014 owns the complete AT-012 correction lifecycle, provider calls,
  transaction sequencing, final run/assistant state, UI-safe result, and final
  application acceptance.

## Verification

- Demonstrate AT-011 directly without a provider.
- Demonstrate the TASK-0013 component portion of AT-012 with explicit lineage
  and bounded repository fixtures; do not run the complete provider pipeline.
- Run focused validator/controller unit tests, focused repository contract
  tests, all current tests, and syntax/import validation.

## Exit criteria

- Three generation attempts are the absolute upper bound when configured at 2.
- Every received candidate has one exact deterministic validation report;
  warnings and errors have their canonical separate representations.
- Every allowed correction retains the original packet and immediately failed
  response lineage; exhaustion has the canonical safe persistence projection.
- All verification is green.
