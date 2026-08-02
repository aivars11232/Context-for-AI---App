# TASK-0007 — Deterministic Interpretation and Constraints

Status: Blocked by TASK-0006

## Goal

Implement the canonical rule-based interpretation, qualifier normalization,
confidence, constraint priority, and conflict behavior.

## Sources

- `docs/contracts/DomainAndDecisionRules.md`
- `docs/contracts/ContextEngine.md`
- `REQUIREMENTS.md` FR-004 through FR-008
- `ACCEPTANCE_TESTS.md` AT-004 and AT-005

## Required work

1. Implement the versioned phrase table, canonical intent/output taxonomy, and
   matched-evidence recording.
2. Implement every listed qualifier mapping, including `only`, `do not`,
   `without changing`, `instead of`, `same as before`, and modals.
3. Implement confidence bands, `ASSUMED` treatment, ambiguity/clarification
   behavior, priority bands, overridden evidence, and hard-conflict stopping.
4. Add deterministic unit/evaluation fixtures for all qualifier mappings,
   multi-intent ties, unsupported actions, conflicts, and confidence bands.

## Boundaries

- No model-assisted interpretation, embeddings, cloud call, or natural-language
  fallback.
- Do not resolve entity mentions beyond emitting references for TASK-0008.
- Do not persist directly or call UI/provider code.

## Verification

- Run interpretation/constraint unit and evaluation suites.
- Demonstrate AT-004 and AT-005 through public result objects.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every canonical qualifier and constraint type, including `ASSUMED`, has a
  deterministic behavior and observable evidence.
- Material ambiguity and hard conflicts stop before provider use.
- All verification is green.
