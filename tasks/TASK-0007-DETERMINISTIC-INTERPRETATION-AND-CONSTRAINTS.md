# TASK-0007 — Deterministic Interpretation and Constraints

Status: Ready after bounded TASK-0007 specification reconciliation

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
   matched-evidence recording, including validated unsupported-request rules
   and source-preserving offsets.
2. Implement every listed qualifier mapping, including `only`, `do not`,
   `without changing`, `instead of`, `same as before`, and modals.
3. Implement confidence bands, `ASSUMED` treatment, ambiguity/clarification
   behavior, priority bands, overridden evidence, and hard-conflict stopping.
4. Add deterministic unit/evaluation fixtures for all qualifier mappings,
   multi-intent ties, unsupported actions, conflicts, and confidence bands.

## Reconciled TASK-0007 contract

- Normalize with Unicode NFC, Unicode case-folding, collapsed whitespace,
  Unicode word boundaries, and original half-open source offsets.
- Preserve rule IDs, exact source text, normalized phrases, offsets, and
  normalized qualifier captures in public evidence.
- An explicit requested text description is `DESCRIBE`/`TEXT_DESCRIPTION`; an
  explicit request to write a text prompt is `EDIT_TEXT`/`TEXT_ANSWER`. Neither
  exception executes the described image generation or external action.
- Return immutable `InterpretationDecision`, `ConstraintDecision`, and
  `ResponsePolicy` objects through inward `InterpretationEngine` and
  `ConstraintEngine` protocols.
- Emit the fixed `MUST_NOT_EXECUTE:IMAGE_OR_ACTION` derived policy for every
  accepted text result.
- Apply only the canonical lexical conflict rules and clarification precedence
  defined by `DomainAndDecisionRules.md`.
- Emit `same as before` only as an unresolved ordered `ReferenceMention` for
  TASK-0008. Do not search, rank, resolve, persist, or clarify references here.

## Boundaries

- No model-assisted interpretation, embeddings, cloud call, or natural-language
  fallback.
- Do not resolve entity mentions beyond emitting references for TASK-0008.
- Do not persist directly, call repositories, construct a context packet,
  terminalize a processing run, or call UI/provider code.

## Verification

- Run interpretation/constraint unit and evaluation suites.
- Demonstrate AT-004 and AT-005 through public result objects.
- AT-005 verification is limited to TASK-0007-owned interpretation, response
  policy, and constraint results; packet construction remains later work.
- Run all current tests and syntax/import validation.

## Exit criteria

- Every canonical qualifier and constraint type, including `ASSUMED`, has a
  deterministic behavior and observable evidence.
- Material ambiguity and hard conflicts stop before provider use.
- D-002, D-003, and TASK-0007's portion of D-014 are recorded as reconciled.
- All verification is green.
