# Response Validation and Correction Contract

## Status and ownership

This document is the canonical TASK-0013 contract for deterministic candidate
validation, correction-envelope planning, and the exact validation/correction
objects supplied to later application persistence. TASK-0013 owns the pure
`ResponseValidator` and `CorrectionController` components and bounded repository
contract evidence. It does not call a model, orchestrate the complete message
pipeline, link an assistant message, publish UI state, or own TASK-0014
terminal-flow execution.

Facts, hallucinations, semantic equivalence, edit correctness, and truth against
an external corpus are outside the MVP validator. A rule passes or fails only by
the finite lexical and structural predicates below.

## ResponseValidator input

The public request is:

```text
ValidationRequest {
  packet: immutable mvp-context-packet-v2 ContextPacket,
  model_response_id: uuid,
  validation_result_id: uuid,
  candidate_response: exact complete buffered text,
  created_at: utc
}
```

`packet.packet_json.validation_context` is the sole validation-policy snapshot.
It supplies the active-topic ID and normalized terms, validation rule-set
version, selected output-shape rule, action markers, and preservation verb list.
The validator has no repository, configuration loader, model gateway, clock,
ID generator, UI object, or other hidden input. It never reloads configuration
or topic data and never mutates the packet.

Before inspecting candidate content, the validator requires all of these input
invariants:

- outer/payload packet schema is `mvp-context-packet-v2`;
- `validation_context.active_topic.topic_id` equals
  `active_state.topic_id`, with both null together;
- `request.expected_output_type`, `response_policy.output_type`, and
  `validation_context.output_shape_rule.output_type` are equal;
- `response_policy.correction_limit` is an integer in `0..2`, its generation
  limit is one plus that value, and its absolute cap is `3`;
- every constraint has a legal status/type/condition combination and a
  canonical predicate for its type as defined below; and
- a successful packet contains no `CONFLICTING` constraint, active material
  `ASSUMED` constraint, or `UNSUPPORTED` condition.

A violation of these invariants or an unknown/malformed predicate is a
`LifecycleInvariantError`: it is invalid component input, produces no
`ValidationResult`, is not attributed to the candidate, and never starts
correction. Later application/recovery code handles impossible durable state
under the existing persistence-error contract.

## Canonical predicate grammar

The constraint engine terminology in `DomainAndDecisionRules.md` is the single
authoritative grammar. `MUST_INCLUDE`, `MUST_STRUCTURE`, `MUST_NOT_INCLUDE`, and
the three-part `MUST_NOT_CHANGE:<target>:<verb-list-id>` forms are not MVP
constraint predicates.

`<ACTION>`, `<OBJECT>`, and `<ACTION_AND_TARGET>` are non-empty uppercase
underscore atoms produced by the canonical TASK-0007 predicate encoder. An atom
is evaluated as its lower-case token sequence after splitting at underscores.

| Constraint type | Accepted active predicate | Candidate predicate |
|---|---|---|
| `REQUIRED` | `MUST_<ACTION>:<OBJECT>` | The action token sequence and object token sequence each occur in the same normalized sentence. Their relative order is irrelevant. |
| `REQUIRED` | `MUST_EXACTLY:<ACTION_AND_TARGET>` | The complete atom token sequence occurs consecutively in a normalized sentence. No synonym or approximate match is allowed. |
| `REQUIRED` | `MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME` | The candidate has exactly one non-empty line and that line is a valid numbered-list item numbered `1`. |
| `FORBIDDEN` | `MUST_NOT_<ACTION>:<OBJECT>` | A violation occurs when the action and object token sequences each occur in the same normalized sentence. `MUST_NOT_CHANGE:UNSPECIFIED_CONTENT` is an ordinary instance of this grammar. |
| `FORBIDDEN` | `MUST_NOT_EXECUTE:IMAGE_OR_ACTION` | A violation occurs when any configured action marker occurs. |
| `PRESERVE` | `MUST_PRESERVE:<OBJECT>` | A violation occurs when a configured preservation-change verb and the object token sequence each occur in the same normalized sentence. |
| `PREFERRED` | `PREFER_<ACTION>:<OBJECT>` | Evaluated like the positive `REQUIRED` action/object predicate, but absence is a warning only. |
| `OPTIONAL` | `MAY_<ACTION>:<OBJECT>` | Evaluated like the positive `REQUIRED` action/object predicate, but absence is a warning only. |
| `ASSUMED` | `ASSUME_<ACTION>:<OBJECT>` | Never evaluated as an instruction. A legal packet may retain it only as `OVERRIDDEN` evidence and records a non-failing warning. |
| `CONDITIONAL` | The predicate for its hard `underlying_type` | Evaluated only when status is `ACTIVE` and the persisted condition evaluation is `TRUE`; failure uses `CONDITIONAL_VIOLATION`. |

Phrase matches use complete consecutive normalized tokens. They never match a
substring inside a larger token. For action/object predicates, every complete
contributing occurrence in a qualifying sentence is retained as a match
location, but one constraint creates at most one evidence item and one
violation or warning.

`INACTIVE` and non-assumption `OVERRIDDEN` constraints create deterministic
`NOT_APPLICABLE` evidence and are not evaluated. A false conditional must be
`INACTIVE`. A true conditional must be `ACTIVE`. An `ASSUMED` record must be
`OVERRIDDEN`; it creates `ASSUMED_CONSTRAINT_NON_BINDING` warning evidence and
cannot fail or alter score.

## Normalization, sentences, and matches

Candidate word normalization is exactly the retrieval normalization in
`DomainAndDecisionRules.md`: Unicode NFC, Unicode case-folding, deletion of every
Unicode punctuation code point, Unicode-whitespace splitting, and removal of
empty tokens. Punctuation is deleted rather than replaced. The validator retains
source offsets for normalized token occurrences solely as numeric evidence; it
does not persist a copied candidate substring.

A candidate sentence is a trimmed non-empty source span split at:

- every LF, CRLF, or CR line ending; or
- `.`, `?`, or `!` followed by whitespace or the end of the candidate.

The terminating `.`, `?`, or `!` belongs to the preceding source span; a line
ending and following whitespace do not. Surrounding whitespace is excluded.
Sentence ordinals are contiguous from zero in source order. Predicate matching
never crosses a sentence boundary.

For substantiveness only, empty lines are discarded, leading Markdown heading
markers are removed while retaining heading content, and every configured
action-marker occurrence is removed using the same NFC/case-folded literal
matching defined below before word normalization. A substantive candidate has
at least one remaining normalized token. Quoted-line content remains
substantive.

Each evidence match location is:

```text
MatchLocation {
  source_start: uint,
  source_end: uint,             # exclusive and greater than source_start
  sentence_ordinal: uint or null
}
```

Offsets are zero-based Unicode scalar-value indices into the exact source
candidate, not UTF-8 bytes or UTF-16 code units. `sentence_ordinal` is null
exactly for a literal action-marker occurrence not wholly contained in one
candidate sentence; every other location names its containing sentence.
Locations are sorted by `source_start`, `source_end`, then sentence ordinal with
null before integers. Identical locations are retained once. Multiple matches
are represented in one evidence item's ordered `matches` array; they do not
multiply violations or deductions. Literal and token-sequence searches retain
overlapping occurrences.

## Canonical checks

Checks execute in this order:

1. `TOPIC`
2. `OUTPUT_SHAPE`
3. `ACTION_MARKER`
4. `REQUIRED_CONSTRAINT`
5. `FORBIDDEN_CONSTRAINT`
6. `PRESERVE_CONSTRAINT`
7. `CONDITIONAL_CONSTRAINT`
8. `PREFERRED_CONSTRAINT`
9. `OPTIONAL_CONSTRAINT`
10. `ASSUMED_CONSTRAINT`
11. `REPETITION`

Within a constraint check, constraints retain packet order. This order owns
evidence, violation, and warning ordering.

`TOPIC`, `OUTPUT_SHAPE`, and `ACTION_MARKER` each create exactly one evidence
item. Every packet constraint creates exactly one evidence item under the check
for its type, including inactive/overridden evidence. A constraint check with no
such constraint creates no placeholder. `REPETITION` creates one warning per
distinct repeated normalized sentence; when there is no repeated sentence, it
creates exactly one `PASSED/INFO` evidence item with no matches. It never adds a
separate pass item when one or more repetition warnings exist.

### Topic and intent/output type

If `validation_context.active_topic` is null or its ordered `terms` array is
empty, `TOPIC` is `NOT_APPLICABLE`. Otherwise it passes when at least one
candidate token equals at least one active-topic term. An empty/non-substantive
candidate therefore fails `TOPIC` whenever non-empty topic terms exist.

Intent has no separate semantic-content oracle. It is enforced by the immutable
interpretation-to-output-type equality checked as an input invariant and by the
selected output-shape predicate. This is the complete deterministic MVP meaning
of validating a candidate against intent.

Every configured action marker is matched as an exact literal substring after
Unicode NFC and Unicode case-folding of marker and candidate, retaining mapped
source offsets. No punctuation deletion or whitespace rewriting participates.
`ACTION_MARKER` fails once when one or more configured markers match. The
active derived `MUST_NOT_EXECUTE:IMAGE_OR_ACTION` constraint is independently evaluated under
`FORBIDDEN_CONSTRAINT`; therefore the same marker intentionally produces one
output-policy violation and one constraint violation when that constraint is
present.

### Output shapes

The selected output-shape rule in `validation_context` is authoritative. Shape
matching uses exact source lines after normalizing CRLF/CR to LF and trimming
leading/trailing Unicode whitespace from each line. Empty lines are ignored.

| Shape | Exact predicate |
|---|---|
| `NON_EMPTY_TEXT` | The candidate is substantive. |
| `NUMBERED_LIST` | There is at least one non-empty line; every non-empty line begins with `[1-9][0-9]*`, a literal `.`, one or more whitespace characters, and non-whitespace content; parsed numbers are consecutive and begin at `1`. No heading, leading-zero number, or surrounding prose line is permitted. |
| `FENCED_CODE` | The first non-empty line matches exactly three backticks optionally followed immediately by one non-empty token containing neither whitespace nor a backtick; the last non-empty line is exactly three backticks; there is no other triple-backtick occurrence; there is at least one non-whitespace character between the fences; and no non-empty content occurs outside them. |
| `COMPARISON_LIST` | There are at least two non-empty lines; every non-empty line matches `- label: value` or `* label: value`, splitting at the first literal `:`, with non-empty trimmed label and value. Labels are word-normalized, joined by one ASCII space, required to remain non-empty, and pairwise distinct. No heading or surrounding prose line is permitted. |

Shape failure produces one `OUTPUT_TYPE_MISMATCH`, independently from the
action-marker check.

### Hard and conditional constraints

Each active hard constraint is evaluated exactly once using the predicate table.
Failure codes are:

| Check | Violation code |
|---|---|
| `TOPIC` | `TOPIC_MISMATCH` |
| `OUTPUT_SHAPE`, `ACTION_MARKER` | `OUTPUT_TYPE_MISMATCH` |
| `REQUIRED_CONSTRAINT` | `MISSING_REQUIREMENT` |
| `FORBIDDEN_CONSTRAINT` | `FORBIDDEN_ACTION` |
| `PRESERVE_CONSTRAINT` | `PRESERVATION_VIOLATION` |
| `CONDITIONAL_CONSTRAINT` | `CONDITIONAL_VIOLATION` |

A true conditional always uses `CONDITIONAL_VIOLATION` when its underlying
predicate fails; it does not additionally emit the underlying hard code.

### Soft constraints and assumptions

An active `PREFERRED` or `OPTIONAL` predicate that passes creates `PASSED/INFO`
evidence. A miss creates one `WARNING` evidence item using respectively
`PREFERRED_CONSTRAINT_UNSATISFIED` or
`OPTIONAL_CONSTRAINT_UNSATISFIED`. These warnings never enter
`violations_json`, never enter a correction envelope, never fail a candidate,
and never reduce score.

Every legal retained `ASSUMED` record creates one
`ASSUMED_CONSTRAINT_NON_BINDING` warning without inspecting candidate content.
An active assumption is invalid packet input rather than a warning.

### Repetition

Before sentence normalization, a whole source line whose first character is `#`
or whose first two characters are `> ` is excluded from repetition only. Every
other sentence is word-normalized. Empty normalized sentences are discarded.

For each distinct normalized sentence occurring at least twice, create exactly
one `UNNECESSARY_REPETITION` warning ordered by the first occurrence's sentence
ordinal. Its `matches` array contains every occurrence. A sentence repeated
three or more times still creates one warning and one `0.05` deduction.

## Typed validation report

The aggregate returned by `ResponseValidator` is exactly:

```text
ValidationResult {
  id: ValidationRequest.validation_result_id,
  model_response_id: ValidationRequest.model_response_id,
  status: PASSED | FAILED,
  score: exact decimal in [0.00, 1.00],
  violations: [ValidationViolation, ...],
  evidence: [ValidationEvidence, ...],
  created_at: ValidationRequest.created_at
}
```

The persistence projection maps `violations` to `violations_json` and
`evidence` to `evidence_json` without changing their values or order.

### Canonical enums

```text
ValidationCheckId =
    TOPIC | OUTPUT_SHAPE | ACTION_MARKER |
    REQUIRED_CONSTRAINT | FORBIDDEN_CONSTRAINT | PRESERVE_CONSTRAINT |
    CONDITIONAL_CONSTRAINT | PREFERRED_CONSTRAINT | OPTIONAL_CONSTRAINT |
    ASSUMED_CONSTRAINT | REPETITION

ValidationSeverity = INFO | WARNING | ERROR
ValidationOutcome = PASSED | FAILED | WARNING | NOT_APPLICABLE

ValidationViolationCode =
    TOPIC_MISMATCH | OUTPUT_TYPE_MISMATCH | MISSING_REQUIREMENT |
    FORBIDDEN_ACTION | PRESERVATION_VIOLATION | CONDITIONAL_VIOLATION

ValidationWarningCode =
    PREFERRED_CONSTRAINT_UNSATISFIED |
    OPTIONAL_CONSTRAINT_UNSATISFIED |
    ASSUMED_CONSTRAINT_NON_BINDING |
    UNNECESSARY_REPETITION
```

### Evidence

Every `validation_results.evidence_json` item has exactly:

```text
ValidationEvidence {
  ordinal: contiguous uint starting at 0,
  check_id: ValidationCheckId,
  rule_id: non-empty string or null,
  constraint_id: uuid or null,
  severity: ValidationSeverity,
  outcome: ValidationOutcome,
  normalized_input: {
    candidate_token_count: uint,
    sentence_count: uint,
    predicate: non-empty string or null,
    topic_terms: [normalized non-empty token, ...],
    output_type: canonical model-eligible OutputType or null,
    output_shape: NON_EMPTY_TEXT | NUMBERED_LIST | FENCED_CODE |
                  COMPARISON_LIST | null
  },
  matches: [MatchLocation, ...],
  missing_predicate: non-empty string or null,
  violation_code: ValidationViolationCode or null,
  warning_code: ValidationWarningCode or null,
  explanation: exact canonical explanation below
}
```

`rule_id` is the selected output-shape rule ID for `OUTPUT_SHAPE`, the
preservation verb-list ID for `PRESERVE_CONSTRAINT` and a preserve-underlying
`CONDITIONAL_CONSTRAINT`, and null otherwise.
`constraint_id` is non-null exactly for constraint checks. `topic_terms` is
non-empty only for `TOPIC`; output type/shape are non-null only for
`OUTPUT_SHAPE`; `predicate` is non-null only for a constraint check.

`matches` has these exact contents:

- `TOPIC` contains every candidate-token location equal to a configured topic
  term; `ACTION_MARKER` contains every literal-marker location; and
  `REPETITION` contains every full source-sentence span for that warning;
- a positive predicate that passes contains all complete action/object or exact
  phrase locations from qualifying sentences; a forbidden or preservation
  predicate that fails contains all complete action/object or verb/object
  locations from qualifying sentences; the same rule follows a conditional's
  underlying type; partial occurrences in a non-qualifying sentence are
  omitted;
- `OUTPUT_SHAPE`, structural `MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME`,
  inactive/overridden constraints, assumptions, and every absent predicate
  have an empty array.

Each normalized token location covers the smallest half-open source span whose
characters contributed to that token after normalization. A multi-token phrase
location covers from the first contributing source character through the last.

`missing_predicate` is non-null only as follows: `ANY_ACTIVE_TOPIC_TERM` for a
failed topic check, the exact constraint predicate for a failed positive
`REQUIRED` or positive-underlying `CONDITIONAL`, and the exact constraint
predicate for a `PREFERRED` or `OPTIONAL` miss. It is null for every other
evidence item.

The only explanation values are:

| Outcome | Exact explanation |
|---|---|
| `PASSED` | `The deterministic predicate passed.` |
| `FAILED` | `The deterministic predicate failed.` |
| `WARNING` | `A non-failing deterministic warning was recorded.` |
| `NOT_APPLICABLE` | `The check is not applicable to this packet.` |

The allowed field combinations are exact:

- `FAILED` requires severity `ERROR`, one non-null `violation_code`, null
  `warning_code`, and a non-null `missing_predicate` only when the failure is an
  absence rather than a forbidden match;
- `WARNING` requires severity `WARNING`, one non-null `warning_code`, null
  `violation_code`, and follows the exact `missing_predicate` rule above;
- `PASSED` and `NOT_APPLICABLE` require severity `INFO` and both codes null.

Evidence never stores a candidate substring. It stores only packet/configuration
predicate data, counts, and numeric source locations into the already-persisted
candidate. This keeps routine logs and correction envelopes content-free while
retaining deterministic audit evidence.

### Violations and warnings

`validation_results.violations_json` contains only candidate-failing errors.
Warnings are represented only as `ValidationEvidence` with severity/outcome
`WARNING`; there is no warning object in `violations_json` and no schema change.

Each violation has exactly:

```text
ValidationViolation {
  ordinal: contiguous uint starting at 0,
  code: ValidationViolationCode,
  message: exact canonical message,
  constraint_id: uuid or null,
  evidence: {
    check_id: ValidationCheckId,
    rule_id: non-empty string or null,
    evidence_ordinal: uint
  }
}
```

Messages are fixed and contain no candidate or user text:

| Code | Exact message |
|---|---|
| `TOPIC_MISMATCH` | `The response does not reference the active topic.` |
| `OUTPUT_TYPE_MISMATCH` | `The response does not satisfy the required text output policy.` |
| `MISSING_REQUIREMENT` | `The response does not satisfy a required constraint.` |
| `FORBIDDEN_ACTION` | `The response contains a forbidden action or object.` |
| `PRESERVATION_VIOLATION` | `The response describes a forbidden change to preserved content.` |
| `CONDITIONAL_VIOLATION` | `The response does not satisfy an active conditional constraint.` |

One failing evidence item creates one violation. Evidence and violation
deduplication occurs only within one item by deduplicating identical match
locations. Repetition's explicit grouping of equal normalized sentences into
one warning is its production rule, not a general merge rule. Distinct checks
or distinct constraint IDs are never merged, even when they have the same code
or predicate. Violations retain failing-evidence order and receive new
contiguous ordinals.

The compact violation `evidence` object is the only evidence copied into a
correction envelope. It contains no normalized candidate, source substring, or
match location. Full `ValidationEvidence` remains only in
`validation_results.evidence_json`.

## Score and pass/fail

Score arithmetic uses exact base-10 decimal values:

```text
score = max(
  0.00,
  1.00
  - 0.30 * hard_violation_count
  - 0.15 * topic_or_output_violation_count
  - 0.05 * repetition_warning_count
)
```

`hard_violation_count` counts `MISSING_REQUIREMENT`, `FORBIDDEN_ACTION`,
`PRESERVATION_VIOLATION`, and `CONDITIONAL_VIOLATION` objects.
`topic_or_output_violation_count` counts `TOPIC_MISMATCH` and every
`OUTPUT_TYPE_MISMATCH` object. `repetition_warning_count` counts distinct
`UNNECESSARY_REPETITION` warning evidence items. Other warnings have zero score
impact. No display rounding, binary floating-point, or ambient decimal context
participates.

The result is `FAILED` exactly when its `violations` array (persisted as
`violations_json`) is non-empty; otherwise it is `PASSED`. Warnings never change status. `NOT_RUN` is not returned by
`ResponseValidator`. Identical complete `ValidationRequest` values produce
value-identical status, score, violations, and evidence.

## CorrectionController

The controller accepts explicit immutable lineage rather than performing a
repository lookup:

```text
FailedCandidateLineage {
  processing_run_id: uuid,
  context_packet_id: uuid,
  model_request_id: uuid,
  model_response_id: uuid,
  attempt_number: 0 | 1 | 2,
  request_purpose: INITIAL | REVISION,
  request_status: SUCCEEDED,
  assistant_message_id: null
}

CorrectionPlanRequest {
  packet: immutable mvp-context-packet-v2 ContextPacket,
  failed_candidate: FailedCandidateLineage,
  validation_result: ValidationResult
}
```

The immutable packet is the sole authority for `correction_limit`; there is no
separate `maximum_revisions` or caller-supplied revision count. Attempt number is
the failed request's persisted attempt. The controller requires:

- packet ID/run ID equal the failed lineage IDs;
- response ID equal `validation_result.model_response_id`;
- validation status `FAILED` with at least one canonical violation;
- attempt `0` paired with `INITIAL`, and attempts `1`/`2` paired with `REVISION`;
- attempt number no greater than packet `correction_limit` or absolute cap `2`;
- a succeeded request and null assistant link; and
- every violation points to the corresponding `FAILED/ERROR` evidence ordinal
  with identical check/rule/constraint/code, and the report's status, score,
  ordering, and ordinals satisfy the complete typed report contract.

Any mismatch is `LifecycleInvariantError`, creates neither decision nor durable
row, and never calls a provider.

If `attempt_number < correction_limit`, the controller returns one
`CorrectionEnvelope` whose attempt is `attempt_number + 1`. If
`attempt_number == correction_limit`, it returns `CorrectionExhausted`. Thus
limits `0`, `1`, and `2` permit respectively zero, one, and two correction
envelopes after the initial attempt.

`CorrectionEnvelope` is the canonical public name and exact shape defined in
`ContextPacket.md`. The provisional `RevisionEnvelope` name is not a separate
contract and must not expose a reduced shape. The envelope:

- carries the original packet ID unchanged;
- carries the immediately failed response ID;
- carries every validation violation in existing ordinal order and no warning;
- uses only the fixed instruction from `ContextPacket.md`; and
- never carries candidate response text or full validation evidence.

Exhaustion is:

```text
CorrectionExhausted {
  processing_run_id: uuid,
  context_packet_id: uuid,
  failed_model_request_id: uuid,
  failed_model_response_id: uuid,
  validation_result_id: uuid,
  attempt_number: 0 | 1 | 2,
  correction_limit: 0 | 1 | 2
}
```

The controller is pure. It does not persist `CorrectionExhausted`, create a
`SafeFailure`, render a prompt, create a model request, retry transport, mutate
user text, weaken a constraint, mutate the packet, or display candidate text.

## Controlled exhaustion projection

Later application orchestration maps `CorrectionExhausted` to exactly one
terminal `SafeFailure`:

```text
{
  id: <application-allocated failure UUID>,
  processing_run_id: exhausted.processing_run_id,
  stage: VALIDATION,
  error_code: VALIDATION_EXHAUSTED,
  safe_message: "The response did not pass validation.",
  details: {
    context_packet_id: exhausted.context_packet_id,
    failed_model_request_id: exhausted.failed_model_request_id,
    failed_model_response_id: exhausted.failed_model_response_id,
    validation_result_id: exhausted.validation_result_id,
    attempt_number: exhausted.attempt_number,
    correction_limit: exhausted.correction_limit
  },
  is_terminal: true,
  created_at: <one application-injected clock reading>
}
```

The database persists this `SafeFailure` and `FailureCode`; it does not persist
the `ValidationExhaustedError` exception object. `ProcessUserMessage` may return
that typed application error only after the applicable failure persistence
contract has completed.

The final failed candidate and validation result are committed by the candidate
transaction. TASK-0014 application orchestration then owns a separate terminal
transaction that adds the exact failure and moves the run to
`CONTROLLED_FAILURE` with `completed_at` equal to the same clock reading. No
assistant message is created or linked.

TASK-0013 verifies this exact projection and repository behavior with bounded,
preconstructed component fixtures. It does not execute the complete provider/UI
flow; complete AT-012 orchestration belongs to TASK-0014.
