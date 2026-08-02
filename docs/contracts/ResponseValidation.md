# Response Validation and Correction Contract

## ResponseValidator

Input: one immutable context packet and one complete buffered candidate response.
Output: `PASSED` or `FAILED`, a score, typed violations, and deterministic
evidence. The validator never calls a model.

### Canonical checks

| Check | Deterministic rule | Failure type |
|---|---|---|
| Topic | A substantive text response contains at least one normalized active-topic term, unless the packet has no active topic. | `TOPIC_MISMATCH` |
| Intent/output type | The candidate satisfies the configured text-shape rule for the expected `OutputType`; it contains no action/tool/image-result marker. | `OUTPUT_TYPE_MISMATCH` |
| Required/completeness | Each active `REQUIRED` rule is represented as `MUST_INCLUDE:<normalized phrase>` or `MUST_STRUCTURE:<rule id>` and passes its literal/structure predicate. | `MISSING_REQUIREMENT` |
| Forbidden | No active `FORBIDDEN` `MUST_NOT_INCLUDE:<normalized phrase>` predicate matches normalized candidate text. | `FORBIDDEN_ACTION` |
| Preserve | No active `PRESERVE` `MUST_NOT_CHANGE:<target>:<verb-set>` predicate matches a configured change verb applied to its target. | `PRESERVATION_VIOLATION` |
| Conditional | Active conditions are evaluated before validation and use their underlying required/forbidden/preserve predicate. | `CONDITIONAL_VIOLATION` |
| Repetition | No normalized sentence occurs more than once, excluding intentionally repeated headings/quoted user text. | `UNNECESSARY_REPETITION` warning |

`PREFERRED`, `OPTIONAL`, and `ASSUMED` rules produce warnings in evidence only;
they cannot fail a candidate. Facts/hallucination detection is deferred because
the MVP has no deterministic truth corpus.

Validation normalizes text using the retrieval normalization rules. A
substantive response has at least one normalized token after empty lines,
markdown heading markers, and configured action markers are removed. A sentence
is a trimmed non-empty span split at a newline or at `.`, `?`, or `!` followed
by whitespace. Only a line beginning `#` (heading) or `> ` (quoted data) is
excluded from repetition; all other repeated normalized sentences are warnings.

`validation.yaml` structural rules are versioned and their rule IDs are stored
in packet evidence. The only MVP shapes are:

- `NON_EMPTY_TEXT`: at least one substantive token.
- `NUMBERED_LIST`: one or more non-empty lines matching `1. `, `2. `, … with
  consecutive positive integers beginning at one.
- `FENCED_CODE`: one matching pair of triple-backtick fences containing at least
  one non-whitespace character.
- `COMPARISON_LIST`: at least two `- label: value` or `* label: value` lines
  with distinct normalized labels.

Every configured `action_marker` is matched case-insensitively as a literal
substring. A required predicate is exactly `MUST_INCLUDE:<normalized phrase>`
or `MUST_STRUCTURE:<output-shape-rule-id>`; a forbidden predicate is exactly
`MUST_NOT_INCLUDE:<normalized phrase>` or `MUST_NOT_EXECUTE:IMAGE_OR_ACTION`;
and a preservation predicate is exactly
`MUST_NOT_CHANGE:<normalized target>:<preserve-change-verb-list-id>`. A
preservation violation requires both a configured change verb and the normalized
target in the same sentence. A `CONDITIONAL` rule is evaluated only from its
persisted `condition_json`, `condition_evaluation`, and
`underlying_constraint_type`; a `TRUE` condition invokes that underlying
predicate, `FALSE` is inactive, and `UNSUPPORTED` never reaches validation.

The score starts at `1.00`, subtracts `0.30` per hard violation,
`0.15` per topic/output violation, and `0.05` per repetition warning, floored
at `0.00`. A candidate passes only when it has no hard/topic/output violations.

Each evidence item contains `check_id`, `rule_id` when applicable, normalized
input, matched span or missing predicate, severity, and explanation. This is
persisted in `validation_results.evidence_json`.

## CorrectionController

Input: failed candidate ID, validation report, and current revision count.
Output: a revision envelope or controlled exhaustion result.

- Attempt count `0` is the initial generation. Only counts `1` and `2` may
  create revisions, capped by validated `validation.max_revisions` (`0..2`).
  The run-specific generation limit is `1 + validation.max_revisions`; three is
  the absolute MVP cap, not a promise to make three calls when the configured
  correction limit is zero or one.
- A revision envelope contains only packet trace IDs, the failed candidate ID,
  typed violations, and the fixed instruction to satisfy unchanged constraints.
- The controller never retries provider transport, weakens a constraint,
  mutates original user text, mutates the packet, or continues beyond attempt
  `2`.
- At exhaustion, persist `ValidationExhaustedError` and return a controlled
  failure. The invalid candidate remains audit data and is not shown as the
  final assistant response.
