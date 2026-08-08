# Domain and Decision Rules

## Status and scope

This is the canonical MVP taxonomy and deterministic decision contract. It
applies to the local, text-only modular monolith. It does not define embeddings,
file context, image generation, tools, cloud providers, streaming, model
routing, or background workers.

## Common representation

- IDs are UUID text values. Times are UTC ISO-8601 values. Scores are decimal
  values in `[0.00, 1.00]`, rounded to two decimal places only for display.
- Every derived result has `processing_run_id`, `source_message_id`,
  `created_at`, `confidence`, and machine-readable `reason` or evidence.
- The local MVP has one operator. There is no `users` table or multi-user
  authorization model.

## Canonical enums

| Name | Allowed values | MVP meaning |
|---|---|---|
| `MessageRole` | `USER`, `ASSISTANT`, `SYSTEM` | `SYSTEM` is internal safe status text; no tool-message role exists in MVP. |
| `ProjectStatus` | `ACTIVE`, `ARCHIVED` | Archive hides a project from ordinary selection; it does not delete data. |
| `TaskStatus` | `OPEN`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED` | State transition status for a conversation task. |
| `IntentType` | `ANSWER`, `EXPLAIN`, `DESCRIBE`, `PLAN`, `ANALYZE`, `RESEARCH`, `DEBUG`, `EDIT_TEXT`, `CONTINUE`, `CORRECT`, `UNSUPPORTED` | All supported results are text-only. `UNSUPPORTED` never invokes a model. |
| `OutputType` | `TEXT_ANSWER`, `TEXT_EXPLANATION`, `TEXT_DESCRIPTION`, `TEXT_PLAN`, `TEXT_ANALYSIS`, `TEXT_CODE`, `TEXT_COMPARISON`, `CLARIFICATION`, `CONTROLLED_FAILURE` | No image, file, tool, or action output exists in MVP. |
| `ConstraintType` | `REQUIRED`, `FORBIDDEN`, `PRESERVE`, `PREFERRED`, `OPTIONAL`, `CONDITIONAL`, `ASSUMED` | Defined in the constraint rules below. |
| `ConstraintScope` | `CURRENT_RESPONSE`, `CONVERSATION`, `PROJECT`, `GLOBAL` | A scope limits eligibility; it never raises a lower-priority rule above a current explicit rule. |
| `MemoryType` | `PROJECT_FACT`, `USER_PREFERENCE`, `CORRECTION_RULE`, `TECHNICAL_ENVIRONMENT`, `ARCHIVED_SUMMARY` | Session state is not a memory record. |
| `MemoryScope` | `CONVERSATION`, `PROJECT`, `GLOBAL` | Defines retrieval eligibility. |
| `MemoryStatus` | `ACTIVE`, `DELETED` | Stored lifecycle state. `DELETED` is a retained tombstone. |
| `MemoryEffectiveStatus` | `ACTIVE`, `EXPIRED`, `DELETED` | Computed retrieval state; `EXPIRED` is never written as an automatic mutation. |
| `EntityType` | `PROJECT`, `TOPIC`, `TASK`, `NAMED_ITEM` | `NAMED_ITEM` is an explicit user-introduced entity, not model-inferred NER. |
| `ReferenceStatus` | `RESOLVED`, `AMBIGUOUS`, `UNRESOLVED`, `NOT_APPLICABLE` | One outcome is persisted for every final TASK-0008 mention; no synthetic outcome is created when there is no mention. |
| `ProcessingRunStatus` | `PERSISTED`, `CONTEXT_READY`, `GENERATING`, `REVISING`, `SUCCEEDED`, `NEEDS_CLARIFICATION`, `CONTROLLED_FAILURE`, `FAILED`, `CANCELLED` | A run has exactly one terminal status. |
| `ModelRequestStatus` | `PENDING`, `IN_FLIGHT`, `SUCCEEDED`, `TIMED_OUT`, `CANCELLED`, `FAILED` | Model transport lifecycle. |
| `ValidationStatus` | `PASSED`, `FAILED`, `NOT_RUN` | One result exists for every completed candidate response. |
| `ValidationCheckId` | `TOPIC`, `OUTPUT_SHAPE`, `ACTION_MARKER`, `REQUIRED_CONSTRAINT`, `FORBIDDEN_CONSTRAINT`, `PRESERVE_CONSTRAINT`, `CONDITIONAL_CONSTRAINT`, `PREFERRED_CONSTRAINT`, `OPTIONAL_CONSTRAINT`, `ASSUMED_CONSTRAINT`, `REPETITION` | Stable deterministic validator check identity. |
| `ValidationSeverity` | `INFO`, `WARNING`, `ERROR` | Evidence severity; warnings never fail a candidate. |
| `ValidationOutcome` | `PASSED`, `FAILED`, `WARNING`, `NOT_APPLICABLE` | Outcome of one deterministic check/evidence item, distinct from aggregate `ValidationStatus`. |
| `ValidationViolationCode` | `TOPIC_MISMATCH`, `OUTPUT_TYPE_MISMATCH`, `MISSING_REQUIREMENT`, `FORBIDDEN_ACTION`, `PRESERVATION_VIOLATION`, `CONDITIONAL_VIOLATION` | Candidate-failing validation code. |
| `ValidationWarningCode` | `PREFERRED_CONSTRAINT_UNSATISFIED`, `OPTIONAL_CONSTRAINT_UNSATISFIED`, `ASSUMED_CONSTRAINT_NON_BINDING`, `UNNECESSARY_REPETITION` | Non-failing warning stored in validation evidence only. |
| `QualifierKind` | `ONLY`, `EXACTLY`, `APPROXIMATE`, `PROHIBITION`, `PRESERVATION`, `SUBSTITUTION`, `PRIOR_REFERENCE`, `SEQUENTIAL` | A matched phrase category; its effect is fixed below. |
| `ConstraintSourceKind` | `CURRENT_MESSAGE`, `TASK_POLICY`, `CORRECTION_MEMORY`, `PREFERENCE_MEMORY`, `RETRIEVED_MEMORY`, `ASSUMPTION`, `DERIVED_OUTPUT_POLICY` | Canonical origin of a constraint. |
| `ConstraintResolutionStatus` | `ACTIVE`, `INACTIVE`, `OVERRIDDEN`, `CONFLICTING` | `INACTIVE` is a false conditional; `CONFLICTING` never reaches generation. |
| `ConditionKind` | `OUTPUT_TYPE_EQUALS`, `ACTIVE_PROJECT_EQUALS` | The only MVP conditional predicates. |
| `ConditionEvaluation` | `TRUE`, `FALSE`, `UNSUPPORTED` | `UNSUPPORTED` requires clarification before generation. |
| `MemorySourceKind` | `USER_MESSAGE`, `MANUAL_ENTRY`, `USER_EDIT` | Provenance source for a memory revision. |
| `MemoryRevisionOperation` | `CREATE`, `EDIT`, `SOFT_DELETE` | Immutable manual-memory lifecycle operation. |
| `LocalActor` | `LOCAL_USER`, `SYSTEM_RECOVERY` | MVP audit actor; recovery never changes memory content. |
| `ModelRequestPurpose` | `INITIAL`, `REVISION` | Initial generation or validation-driven revision only. |
| `ProviderKind` | `OLLAMA` | The sole configured runtime provider. |
| `PipelineStage` | `ACCEPTANCE`, `CONTEXT`, `REQUEST`, `TRANSPORT`, `VALIDATION`, `CORRECTION`, `TERMINALIZATION`, `RECOVERY`, `MEMORY` | Canonical stage for trace/failure records. |
| `EvaluationProviderMode` | `MOCK`, `OLLAMA` | Deterministic test provider or opt-in local smoke provider. |
| `ClarificationReason` | `AMBIGUOUS_REFERENCE`, `UNRESOLVED_REFERENCE`, `LOW_CONFIDENCE_INTERPRETATION`, `HARD_CONSTRAINT_CONFLICT`, `UNSUPPORTED_INTENT`, `UNSUPPORTED_CONDITION`, `MATERIAL_ASSUMPTION` | Selects one deterministic clarification template. |
| `RetrievalExclusionReason` | `SCOPE_MISMATCH`, `DELETED`, `EXPIRED`, `SCORE_BELOW_THRESHOLD`, `DUPLICATE_CONTENT`, `LIMIT_EXCEEDED` | Durable reason a considered memory was not selected. |
| `FailureCode` | `CONTEXT_BUDGET_EXCEEDED`, `CONTEXT_CONSTRUCTION_FAILED`, `PERSISTENCE_ERROR`, `CONCURRENCY_CONFLICT`, `PROCESS_RESTARTED`, `CONFIGURATION_CHANGED`, `PROVIDER_UNAVAILABLE`, `MODEL_NOT_FOUND`, `MODEL_TIMEOUT`, `MODEL_CANCELLED`, `INVALID_PROVIDER_RESPONSE`, `VALIDATION_EXHAUSTED`, `CONFIGURATION_INVALID`, `CANCELLED_BY_USER` | Safe terminal processing-failure code; clarification and `BusyError` are not failures. |

## Interpretation and qualifier rules

Interpretation uses the versioned, deterministic rule table in `context.yaml`.
Each matching rule records its matched text and rule identifier. A message can
have one primary intent plus zero or more qualifiers. An intent rule has a
unique `id`, one allowed non-`UNSUPPORTED` `intent`, one non-empty lower-case
`phrases` list, an optional permitted `output_type`, and an integer `priority`
from `1` through `100`. Select the matching intent rule with highest priority,
then longest normalized matched phrase. A remaining tie between different
intents becomes `UNSUPPORTED` and `NEEDS_CLARIFICATION`; a tie between rules for
the same intent selects the lexicographically smaller rule ID. Configuration
must include at least one rule for every supported primary intent used by the
shipped fixture configuration.

TASK-0007 matching uses one source-preserving normalization. Normalize the
message to Unicode NFC, apply Unicode case-folding, collapse each non-empty
whitespace run to one ASCII space, and trim leading/trailing whitespace. Phrase
matches require Unicode word boundaries; a word phrase cannot match inside a
larger alphanumeric word. The normalizer retains, for every normalized
character, the half-open `[start, end)` offsets of the contributing original
source text. Evidence therefore contains the exact source slice, normalized
phrase, rule ID, original start/end offsets, and normalized captures. Intent
candidates are ordered by priority descending, normalized phrase code-point
length descending, rule ID ascending, then source start ascending. Every
top-rank candidate needed to explain a selection or tie remains observable.

A unique, completely captured exact rule match has interpretation confidence
`1.00`. No match and a different-intent top tie have confidence `0.00`. A
recognized qualifier whose mandatory operands cannot be captured lowers the
interpretation result to `0.49` and requires clarification; it is never silently
dropped. A command-only topic/task proposal does not invent a primary intent:
ordinary intent matching still applies, and no intent match is `UNSUPPORTED`.

The canonical default output mapping is fixed, not model-chosen:

| Intent | Default output type | Permitted configured output types |
|---|---|
| `ANSWER` | `TEXT_ANSWER` | `TEXT_ANSWER`, `TEXT_COMPARISON` |
| `EDIT_TEXT` | `TEXT_ANSWER` | `TEXT_ANSWER`, `TEXT_CODE` |
| `EXPLAIN` | `TEXT_EXPLANATION` | `TEXT_EXPLANATION` |
| `DESCRIBE` | `TEXT_DESCRIPTION` | `TEXT_DESCRIPTION` |
| `PLAN` | `TEXT_PLAN` | `TEXT_PLAN` |
| `ANALYZE`, `RESEARCH`, `DEBUG` | `TEXT_ANALYSIS` | `TEXT_ANALYSIS` |
| `CONTINUE`, `CORRECT` | The prior non-null state `expected_output_type`, otherwise `TEXT_ANSWER` | The retained state type only |
| `UNSUPPORTED` | `CLARIFICATION` and no model request | None |

`context.yaml` also contains qualifier rules with a unique ID, one
`QualifierKind`, and one or more normalized phrases. A qualifier rule can
recognize a phrase but cannot change the fixed effect in the table below.

| Qualifier | Deterministic result |
|---|---|
| `only` (`ONLY`) | Add a `REQUIRED` rule for the named target and a `PRESERVE` rule stating that changes outside the explicit target are prohibited. |
| `exactly` (`EXACTLY`) | Add a strict `REQUIRED` rule; approximate substitutions fail validation. |
| `roughly`, `could`, `might` (`APPROXIMATE`) | Add a `PREFERRED` rule, never a hard requirement. |
| `do not` (`PROHIBITION`) | Add a `FORBIDDEN` rule for its normalized object/action. |
| `without changing` (`PRESERVATION`) | Add a `PRESERVE` rule for its normalized object/scope. |
| `instead of` (`SUBSTITUTION`) | Add `FORBIDDEN` for the replaced alternative and `REQUIRED` for the replacement when both are explicit. |
| `same as before` (`PRIOR_REFERENCE`) | Emit a reference mention. Reuse only a uniquely resolved prior rule; otherwise request clarification. |
| `one at a time` (`SEQUENTIAL`) | Add a `REQUIRED` text-structure rule to present one ordered step at a time. |

Qualifier evidence is ordered by source start, longer normalized phrase first
when matches overlap, then rule ID. The longer match owns an overlapping source
range. Captures use the containing punctuation/conjunction-bounded clause,
remove boundary punctuation, collapse whitespace, case-fold, and remove the
object determiners `a`, `an`, and `the`. Capture and predicate behavior is:

| Qualifier | Capture | Exact emitted predicate |
|---|---|---|
| `ONLY` | Governing action plus named object around `only` | `MUST_<ACTION>:<OBJECT>` plus `MUST_PRESERVE:UNSPECIFIED_CONTENT` |
| `EXACTLY` | Governing action plus following target | `MUST_EXACTLY:<ACTION_AND_TARGET>` |
| `APPROXIMATE` | Governed action/object after `could`/`might`, or around `roughly` | `PREFER_<ACTION>:<OBJECT>` |
| `PROHIBITION` | Action/object following `do not` | `MUST_NOT_<ACTION>:<OBJECT>` |
| `PRESERVATION` | Object following `without changing` | `MUST_PRESERVE:<OBJECT>` |
| `SUBSTITUTION` | Explicit `<replacement> instead of <replaced>`; a governing action on the replacement is propagated to the replaced object | `MUST_NOT_<ACTION>:<REPLACED>` and `MUST_<ACTION>:<REPLACEMENT>` |
| `PRIOR_REFERENCE` | The matched phrase itself | No constraint; one ordered unresolved reference mention |
| `SEQUENTIAL` | The matched phrase itself | `MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME` |

`<ACTION>`, `<OBJECT>`, and composite values are uppercase underscore atoms made
from normalized alphanumeric tokens. Non-alphanumeric runs become one
underscore and boundary underscores are removed. The normalized lower-case
capture remains separately observable. In the AT-004 combination, `anything
else` following an `ONLY` target canonicalizes to `UNSPECIFIED_CONTENT`, so the
explicit prohibition is `MUST_NOT_CHANGE:UNSPECIFIED_CONTENT`. Duplicate
constraints with the same type, target key, source message, and priority are
coalesced into one result whose evidence retains every contributing match.
Unconfigured modal words have no qualifier effect.

### Canonical constraint predicate grammar

This constraint-engine grammar is the single authoritative MVP predicate
grammar for both packet construction and response validation:

```text
ATOM       = UPPER_ALNUM ("_" UPPER_ALNUM)*
POSITIVE   = "MUST_" ATOM ":" ATOM
FORBIDDEN  = "MUST_NOT_" ATOM ":" ATOM
PRESERVE   = "MUST_PRESERVE:" ATOM
PREFERRED  = "PREFER_" ATOM ":" ATOM
OPTIONAL   = "MAY_" ATOM ":" ATOM
ASSUMED    = "ASSUME_" ATOM ":" ATOM
```

`UPPER_ALNUM` is one or more ASCII `A` through `Z` or `0` through `9`.
`REQUIRED` uses `POSITIVE`; `FORBIDDEN` uses `FORBIDDEN`; `PRESERVE`,
`PREFERRED`, `OPTIONAL`, and `ASSUMED` use their same-named production.
`CONDITIONAL` uses the production selected by its non-null `underlying_type` of
`REQUIRED`, `FORBIDDEN`, or `PRESERVE`.
Because the raw `MUST_` prefixes overlap, the constraint type is part of the
grammar discriminator: a `REQUIRED` action atom may not begin `NOT_` and may
not equal `PRESERVE`; those forms are legal only for their corresponding
`FORBIDDEN` or `PRESERVE` type. A type/production mismatch is malformed input.

The reserved valid instances `MUST_EXACTLY:<ACTION_AND_TARGET>` and
`MUST_PRESENT:ONE_ORDERED_STEP_AT_A_TIME` use the `POSITIVE` production.
`MUST_NOT_EXECUTE:IMAGE_OR_ACTION` and
`MUST_NOT_CHANGE:UNSPECIFIED_CONTENT` use the `FORBIDDEN` production. Their
special deterministic evaluation semantics, as well as phrase matching, are
owned by `ResponseValidation.md`; they do not create additional grammar.

`MUST_INCLUDE`, `MUST_STRUCTURE`, `MUST_NOT_INCLUDE`, and a three-part
`MUST_NOT_CHANGE:<target>:<verb-list-id>` are not legal MVP predicates. A
packet containing one is invalid component input; validation never guesses an
equivalent predicate or silently selects between vocabularies.

`context.yaml` also owns versioned `unsupported_request_rules`. Each rule has a
unique ID, a category of `IMAGE_GENERATION` or `EXTERNAL_ACTION`, and one or more
normalized phrases. A matched unsupported rule makes the result `UNSUPPORTED`
unless intent evidence explicitly requests either a text description
(`DESCRIBE`/`TEXT_DESCRIPTION`) or a written text prompt
(`EDIT_TEXT`/`TEXT_ANSWER`). These exceptions return text only; they never
execute the described action. The MVP never generates an image or invokes an
external action. For every accepted text request, the constraint engine emits
one `FORBIDDEN` constraint with source
`DERIVED_OUTPUT_POLICY`, priority `1000`, normalized rule
`MUST_NOT_EXECUTE:IMAGE_OR_ACTION`, and evidence naming the text-only policy.

Topic and task proposals are deliberately narrow. The only MVP topic commands
are `topic: <label>` and `switch topic to <label>`; the only MVP task commands
are `task: <title>` and `new task: <title>`. Matching is case-insensitive after
Unicode case-folding and the captured label/title must be non-empty after trim.
Other prose retains the current topic/task rather than inferring one. `continue`
and `correct` may be recognized only by configured primary-intent phrases.

## Ambiguity and confidence

- `HIGH` confidence is `>= 0.80`; a high-confidence result may update state.
- `MEDIUM` confidence is `0.50–0.79`; retain the prior state and request
  clarification if the uncertain value would change topic, task, output type,
  a hard constraint, or reference target.
- `LOW` confidence is `< 0.50`; return `NEEDS_CLARIFICATION` before a model
  call when interpretation or reference resolution is material.
- `ASSUMED` records a non-binding hypothesis. It has priority `0`, can never
  override any explicit rule, and must trigger clarification when it would
  materially affect the response.
- `overall_confidence` is the weighted mean of applicable scores: interpretation
  `0.50`, reference resolution `0.30`, retrieval `0.20`. The reference factor
  is the minimum confidence among material reference mentions; the retrieval
  factor is the highest selected retrieval score. A factor with no applicable
  item is omitted and remaining weights are normalized. Comparisons use the
  unrounded value; only display rounds to two decimal places.

The deterministic confidence gate takes the unrounded score and a materiality
flag. `HIGH` never blocks. `MEDIUM` blocks only when the uncertain value would
change topic, task, output type, a hard constraint, or a reference target.
`LOW` blocks whenever the result is material. TASK-0007 does not perform
reference resolution or retrieval; its weighted-confidence helper merely
accepts optional already-computed factors for later callers.

## Clarification contract

`NEEDS_CLARIFICATION` is a terminal non-failure outcome. It writes exactly one
`clarification_requests` record and no model request. The question is generated
without a model using these templates:

| Reason | One-question template |
|---|---|
| `AMBIGUOUS_REFERENCE` | `Which <entity type> do you mean by "<surface text>"? <candidate labels in deterministic rank order>` |
| `UNRESOLVED_REFERENCE` | `Please clarify what "<surface text>" refers to.` |
| `LOW_CONFIDENCE_INTERPRETATION` | `Please clarify whether you want: <candidate intent labels in rule order>.` |
| `HARD_CONSTRAINT_CONFLICT` | `Which instruction should apply: "<rule A>" or "<rule B>"?` |
| `UNSUPPORTED_INTENT` | `Please clarify the text-only result you want.` |
| `UNSUPPORTED_CONDITION` | `Please restate the condition using the supported output-type or active-project form.` |
| `MATERIAL_ASSUMPTION` | `Please confirm the assumption: "<assumed rule>".` |

Candidate labels and conflicting rules are normalized/sorted by the applicable
canonical ranking/order. The `details_json` payload carries the reason, source
IDs, candidates, and template inputs; it never stores a model-produced question.

Only one blocking reason is selected. Inside the TASK-0007 boundary, precedence
is an interpretation block, then `UNSUPPORTED_CONDITION`, then
`HARD_CONSTRAINT_CONFLICT`, then `MATERIAL_ASSUMPTION`. When a TASK-0008
reference decision is composed with that result, global precedence is the
interpretation block, the lowest-ordinal blocking reference, then the three
constraint-stage reasons in their existing order. TASK-0007 constructs a
deterministic question and details but does not persist it or terminalize a
processing run. TASK-0008 likewise returns reference-stage clarification data;
later orchestration owns persistence and run terminalization.

## Constraint priority and conflict rules

The following numeric bands are canonical. Current-message `PREFERRED` and
`OPTIONAL` rules use priority `1000`, but their soft type can never defeat a hard
constraint.

| Priority | Source |
|---:|---|
| 1000 | Current explicit `REQUIRED`, `FORBIDDEN`, or `PRESERVE` instruction |
| 900 | Current explicit `CONDITIONAL` instruction once its condition is true |
| 800 | Current explicit task or expected-output-type instruction |
| 600 | Explicit user correction stored as a memory |
| 500 | Explicit global user preference |
| 400 | Retrieved project/conversation memory |
| 0 | `ASSUMED` hypothesis |

`PREFERRED` and `OPTIONAL` use their source band but cannot defeat a hard
constraint (`REQUIRED`, `FORBIDDEN`, or `PRESERVE`). Source recency is the
immutable source-message sequence when both candidates have one; otherwise it
is the immutable original-source UTC timestamp. Ordinal and source ID order
evidence but do not create authority. Higher priority wins; within one priority,
newer source recency wins. A hard rule defeats an opposing soft rule regardless
of the soft rule's numeric source band. Opposing soft rules use priority,
recency, normalized rule, then constraint UUID as a total ordering and mark the
loser `OVERRIDDEN`; a soft-only tie never stops generation.

Hard opposition is deliberately lexical. `REQUIRED` and `FORBIDDEN` oppose only
when their canonical action/object target key is identical. A required `ADD`,
`REMOVE`, `REPLACE`, `CHANGE`, `MODIFY`, `DELETE`, or `MOVE` action opposes
`PRESERVE` only for the identical object. No synonym, entity, or semantic
mutual-exclusion inference is permitted. Equal-priority, equal-recency opposing
hard rules are both `CONFLICTING`; their conflict-group ID is
`hard-conflict-<digest>`, where `<digest>` is the first 16 lowercase hexadecimal
characters of SHA-256 over the target key and sorted constraint UUIDs. The
result becomes `NEEDS_CLARIFICATION`; no provider-facing result is produced.

When a winner defeats a loser, retain both records and mark the loser
`OVERRIDDEN`. Resolution evidence contains both IDs, the normalized target key,
and the deterministic comparison tuple. A conditional rule is inactive until
its deterministic condition is true; unsupported conditions require
clarification.

An `ASSUMED` rule uses source `ASSUMPTION`, priority `0`, and an
`ASSUME_<ACTION>:<OBJECT>` predicate. It is non-binding. An active explicit rule
with the same compatible target entails it, leaving the assumption as
`OVERRIDDEN` evidence. Otherwise an eligible assumption is material and returns
`MATERIAL_ASSUMPTION`; it never reaches generation as an instruction.

The only accepted conditional grammar is `mvp-condition-v1`, configured by the
fixed `context.conditional_grammar_version` value. It accepts exactly one of:

```text
if output type is <canonical OutputType>, require <action/object clause>
if output type is <canonical OutputType>, do not <action/object clause>
if output type is <canonical OutputType>, preserve <object clause>
if active project is "<exact normalized active-project name>", require <action/object clause>
if active project is "<exact normalized active-project name>", do not <action/object clause>
if active project is "<exact normalized active-project name>", preserve <object clause>
```

The persisted condition object is
`{grammar_version, kind, expected_value, evaluation}`. `kind` is
`OUTPUT_TYPE_EQUALS` or `ACTIVE_PROJECT_EQUALS`; evaluation is `TRUE`, `FALSE`,
or `UNSUPPORTED`. A `CONDITIONAL` row stores the underlying hard constraint type
and normalized predicate separately. `TRUE` gives the condition priority band
and makes it mandatory in the packet/validation; `FALSE` is `INACTIVE` and is
kept only as packet evidence; a syntactically incomplete condition, unknown
output type, or non-matching unquoted project expression is `UNSUPPORTED` and
requires clarification. No other natural-language conditional is guessed.

The public TASK-0007 boundary consists of immutable matched-rule evidence,
intent candidates, unresolved reference mentions, one interpretation decision,
constraint source evidence, conflict groups, the fixed response policy, and one
constraint decision. Interpretation and constraint engines consume immutable
requests and return those objects. They do not call repositories, persist
results, construct a context packet, call a provider, or apply conversation
state. A `same as before` match ends at the unresolved reference-mention output;
candidate search, status selection, reuse, and reference clarification belong to
TASK-0008. TASK-0007 does not inspect the entity registry. TASK-0008 preserves
the TASK-0007 mention as source evidence and merges it with the additional
finite-form and exact-registry-name mentions defined below.

## State transitions and concurrency

- A user explicitly creates a project in `ACTIVE` status or a conversation with
  a default version-`0` state. The sole non-user exception is
  `PrepareApplicationShell`: when no conversation exists on first-run startup,
  it may atomically create exactly one unscoped, null-title conversation and its
  default version-`0` state as defined by `PresentationShell.md`. It creates no
  project or other domain object. A new conversation may be unscoped. The
  selected conversation is an ephemeral UI choice, not a second persisted
  active-project field. A user may select only an existing `ACTIVE` project for
  a conversation; that association is the sole persisted active project and the
  change occurs in the acceptance transaction with one state-version increment.
- A user may explicitly archive an `ACTIVE` project only when it has no
  non-terminal run. Archiving changes only `projects.status`; it preserves its
  conversations, memories, and entity rows, makes it unavailable for new
  selection, and does not rewrite an already-associated conversation.
- `conversation_states` stores an active topic plus active/previous task
  identifiers, expected output type, topic stack, and version. It has no
  `previous_topic_id`.
  The topic stack contains at
  most ten topic IDs; a new explicit high-confidence topic is pushed, repeated
  topics are moved to the top, and the oldest item is dropped when full.
- A high-confidence explicit task replaces `active_task_id` and moves the old
  value to `previous_task_id`. `CONTINUE` retains the active task. `CORRECT`
  retains the task and records a correction constraint.
- Task status transitions are explicit UI operations only: `OPEN -> IN_PROGRESS`
  occurs when a task becomes active; `OPEN|IN_PROGRESS -> COMPLETED|CANCELLED`
  occurs only on the named user operation; `COMPLETED|CANCELLED -> OPEN` is an
  explicit reopen operation. Replacing or continuing a task does not silently
  complete/cancel it. Marking the active task `COMPLETED` or `CANCELLED` first
  moves its ID to `previous_task_id` and sets `active_task_id` to null in the
  same versioned state transaction; reopening does not activate it until an
  explicit select/new-task operation. An active task cannot be terminal.
- A high-confidence primary intent sets `expected_output_type` to its canonical
  mapping. `CONTINUE` and `CORRECT` preserve a non-null existing value; an
  unscoped/default continuation uses `TEXT_ANSWER`. Clarification and terminal
  failures never update expected output type.
- The MVP allows exactly one non-terminal foreground processing run globally,
  not merely per conversation. A repeat of the same `(conversation_id,
  idempotency_key)` returns its existing run. A different key while any
  non-terminal run exists is rejected before acceptance as `BusyError`, creates
  no message/run, and is not queued. State writes use compare-and-swap on
  `version` and reload/retry only the deterministic state transition once on a
  version conflict.

The terminal processing statuses are `SUCCEEDED`, `NEEDS_CLARIFICATION`,
`CONTROLLED_FAILURE`, `FAILED`, and `CANCELLED`; all other run statuses are
non-terminal. The only legal run transitions are:

```text
PERSISTED -> CONTEXT_READY | NEEDS_CLARIFICATION | CONTROLLED_FAILURE | FAILED | CANCELLED
CONTEXT_READY -> GENERATING | FAILED | CANCELLED
GENERATING -> SUCCEEDED | REVISING | CONTROLLED_FAILURE | FAILED | CANCELLED
REVISING -> SUCCEEDED | REVISING | CONTROLLED_FAILURE | FAILED | CANCELLED
```

Recovery may take any non-terminal status to `FAILED` only with a durable
canonical failure code. A model request transitions
`PENDING -> IN_FLIGHT -> SUCCEEDED|TIMED_OUT|CANCELLED|FAILED`; no terminal
request state can change. `PERSISTED -> CANCELLED` is reserved for the
application's accepted pre-gateway cancellation checkpoints; it does not permit
an unpersisted cancellation to fabricate a run. A successful request creates exactly one response; a
response creates exactly one validation result; only a passed validation can
create one linked assistant message. A failed validation either creates the next
allowed correction request or terminalizes the run. No terminal run can receive
another request, assistant message, state update, or correction row.

## Entity and reference rules

### Registry identity, ownership, lifecycle, and provenance

The registry contains only `PROJECT`, `TOPIC`, `TASK`, and `NAMED_ITEM`. Every
owner receives exactly one registry row in the same transaction. The registry
UUID is distinct from, and never derived from, the durable owner UUID;
`native_id` equals that owner UUID and `(entity_type, native_id)` is immutable.
Physical deletion is not an MVP registry operation.

- A `PROJECT` entity has `project_id` equal to its `native_id`. It is active
  exactly while the project is `ACTIVE`.
- A `TOPIC` entity belongs to its topic's conversation and has the
  conversation's current `project_id`. It is active while that project is null
  or `ACTIVE`.
- A `TASK` entity belongs to its task's conversation and has the conversation's
  current `project_id`. It is active only while its project is null or `ACTIVE`
  and its task is `OPEN` or `IN_PROGRESS`.
- A `NAMED_ITEM` entity has the immutable conversation and optional project
  ownership stored by its `named_items` row. It is active while that project is
  null or `ACTIVE`.

Archiving a project retains its registry rows and makes the project and every
project-owned entity inactive. Completing or cancelling a task retains its row
and makes it inactive; explicitly reopening it restores activity when its
project is eligible. A conversation project change updates its topic/task
registry `project_id` and activity in the same transaction. Owner renames update
registry display/normalized names atomically. Registry ID, entity type,
`native_id`, `created_at`, and `source_message_id` never change.

`entity_registry.source_message_id` is the immutable user message that supplied
an explicit creation name. It is nullable for an explicit UI creation that has
no message. For a topic, task, or named item, a non-null source must be a `USER`
message from the owning conversation. A project source must be a `USER` message
used by its explicit local creation operation; it is not required to predate a
conversation-project association. The registry is the canonical source field
for project/topic/task because those owner tables have no source column. A
named-item owner and its registry row carry the same source value. A null source
never denotes inference.

### Explicit named-item registration

A named item is created only by an explicit UI operation or by a whole-message
declaration matching exactly `name "<label>"` or `call this "<label>"` after
trimming outer whitespace and case-folding the command words. Quotes are ASCII
double quotes; the label cannot contain a double quote or a Unicode control
character and must be non-empty after normalization. There is no escape syntax
in MVP.

The display name is the label normalized to Unicode NFC, with leading/trailing
whitespace removed and each internal non-empty whitespace run collapsed to one
ASCII space. `normalized_name` is that display name Unicode-case-folded; name
punctuation is preserved. Uniqueness is exact on `(conversation_id,
normalized_name)`. A duplicate is rejected without creating either row. The
owning conversation is required and `project_id` copies its current project for
a message declaration or the project explicitly selected by the UI operation.
Message registration writes the declaration message as source; UI registration
writes null. The `named_items` and registry rows are created atomically.

The quoted label in its own declaration is registration data, not a reference
mention. In `call this "<label>"`, the word `this` is still recorded as the one
deterministically non-applicable mention described below. No other prose,
automatic named-entity extraction, model result, fuzzy match, or inferred label
can create an entity.

### Reference-mention ownership and complete MVP forms

TASK-0007 continues to own intent/qualifier interpretation and emits
`same as before` as a `ReferenceMention`. TASK-0008 owns a separate deterministic
mention-extraction step before resolution. It accepts the exact current message,
the immutable TASK-0007 mentions, and the scoped registry candidates; it never
changes the TASK-0007 objects. It copies their source evidence into a new final
ordered `ReferenceMention` sequence and adds only these forms:

| Form class | Exact normalized forms | Candidate types |
|---|---|---|
| Generic singular | `it`, `this`, `that` | all entity types |
| Application | `the app`, `this app`, `that app` | `PROJECT`, `NAMED_ITEM` |
| Project | `the project`, `this project`, `that project` | `PROJECT` |
| Topic | `the topic`, `this topic`, `that topic` | `TOPIC` |
| Task | `the task`, `this task`, `that task` | `TASK` |
| Prior | `same as before` | all entity types |
| Unsupported file | `the file`, `this file`, `that file` | none |
| Explicit name | an in-scope registry row's complete `normalized_name` | that entity |

Fixed forms and explicit names use the TASK-0007 NFC/case-fold/whitespace
normalization, exact original half-open offsets, and Unicode alphanumeric word
boundaries. For a fixed noun form, the lookup key removes its leading `the`,
`this`, or `that`; an explicit-name form uses the complete normalized name.
Inactive in-scope entity names are still extracted so stale references retain
evidence. A quoted label inside its own registration declaration is excluded.

Candidate spans are scanned left-to-right. At the same source start, prefer the
longer span; for an identical span, prefer TASK-0007 evidence, then an explicit
registry-name match, then a fixed form, then lexicographically smaller source
rule ID. After accepting a span, discard every candidate span that overlaps it.
Sort accepted spans by start offset, end offset, and source rule ID, then assign
new contiguous final ordinals `0..n-1`. The original TASK-0007 objects and their
local ordinals remain immutable; only the final sequence ordinals are persisted.
TASK-0008-created mentions use stable rule IDs `reference-form:<normalized
form>` or `reference-name:<entity UUID>` in the existing source-rule field.

All gendered/plural pronouns (`he`, `she`, `they`, `them`, `these`, `those`),
`former`/`latter`, possessive forms, partial names, synonyms, misspellings, and
unlisted deictic phrases are unsupported. They create no mention and no outcome.
This is deterministic omission, not `UNRESOLVED`. No semantic inference is
performed.

### Candidate eligibility, matching, and ranking

The scoped registry input contains the conversation's topics, tasks, and named
items plus its associated project, including inactive rows for stale evidence;
cross-conversation and cross-project rows are absent. A tracked entity is an
active, in-scope entity targeted by a prior persisted `RESOLVED` outcome whose
message is in the ordered recent-message input. Its recency tuple is source
message sequence descending, then prior mention ordinal descending. A
source-message match is an exact word-bounded occurrence of the entity's full
`normalized_name` in a prior recent message; its recency is message sequence.

For each type-compatible active candidate, take the maximum applicable score:

| Score | Rank reason | Exact trigger |
|---:|---|---|
| `1.00` | `EXACT_NAME` | Mention lookup key equals the candidate's complete `normalized_name`. |
| `0.90` | `ACTIVE_STATE` | Candidate is the conversation project, active topic, or active task; this band does not apply to `same as before`. |
| `0.80` | `RECENT_TRACKED` | Candidate has the greatest tracked-entity recency tuple among compatible candidates. |
| `0.60` | `SOURCE_MESSAGE` | Candidate has the greatest matching-source-message sequence among otherwise unmatched compatible candidates. |

An inactive compatible entity is retained with score `0.00` and reason
`STALE_ENTITY`; it can never win. Only candidates sharing the greatest
applicable tracked/source recency tuple receive `0.80`/`0.60`; older matches
remain evidence with the matching rank reason and score `0.00`. An active
candidate with no applicable band is omitted. Candidate scores are not added.
`same as before` uses tracked and source bands only. File forms do not search
entity candidates.

Candidate evidence is presented by score descending, rank-reason order
`EXACT_NAME`, `ACTIVE_STATE`, `RECENT_TRACKED`, `SOURCE_MESSAGE`,
`STALE_ENTITY`, then recency descending where applicable, normalized name
ascending, entity-type value ascending, and entity UUID ascending. Presentation
keys never break a resolution tie: every candidate sharing the highest positive
score is a top candidate.

### Status, confidence, and source-message rules

| Status | Exact trigger | Stored confidence |
|---|---|---:|
| `RESOLVED` | Exactly one top candidate, score at least `0.80`. | Winning score (`1.00`, `0.90`, or `0.80`). |
| `AMBIGUOUS` | Two or more candidates share the highest positive score, at any band. | Shared highest score. |
| `UNRESOLVED` | No positive candidate, or exactly one top candidate below `0.80`; all file forms use this status. | Unique positive top score, otherwise `0.00`; file forms are `0.00`. |
| `NOT_APPLICABLE` | Exactly the `this` token serving as the declaration target in `call this "<label>"`; it is not an entity target. | `1.00`. |

No final mention sequence means no reference rows; no synthetic
`NOT_APPLICABLE` row is created. `resolved_entity_id` is non-null only for
`RESOLVED`. The outcome `source_message_id` is the winner's evidence message,
falling back to its entity source for `RESOLVED`; it is null for `AMBIGUOUS`; it
is the unique below-threshold candidate's evidence/source message for that form
of `UNRESOLVED`, otherwise null; and it is the current declaration message for
`NOT_APPLICABLE`.

All extracted entity/file references are material in MVP because changing or
omitting their target can change the response. `NOT_APPLICABLE` is non-material
and omitted from the reference-confidence factor. A material `AMBIGUOUS` result
uses `AMBIGUOUS_REFERENCE`; a material `UNRESOLVED` result uses
`UNRESOLVED_REFERENCE`. Either blocks the TASK-0008 decision before provider use.
The lowest mention ordinal supplies the single reference question. A resolved
or non-applicable outcome does not create reference clarification.

For ambiguity, clarification `entity_type` is the shared lower-case type label,
or `entity` for mixed types. Candidate labels contain only the tied top
candidates in evidence order; append `(<lower-case entity type>)` when types are
mixed or display names repeat. Details retain mention ordinal, exact surface,
candidate evidence, and every non-null source-message ID. TASK-0008 returns this
blocking reason/details but does not persist a clarification, terminalize a run,
create a model request, or present UI.

### Persisted candidate evidence

`candidate_evidence_json` is a non-empty array in the presentation order above.
Every candidate object has exactly these keys:

```text
rank                         one-based integer
entity_id                    UUID or null
entity_type                  EntityType string or null
display_name                 text or null
normalized_name              text or null
score                        number in [0, 1]
rank_reason                  canonical reason string
entity_source_message_id     UUID or null
evidence_message_id          UUID or null
evidence_message_sequence    non-negative integer or null
prior_mention_ordinal        non-negative integer or null
is_active                    boolean or null
```

When there is no entity candidate, the array contains exactly one evidence
object with rank `1`, null entity fields, score `0.00`, and reason
`NO_CANDIDATE`, `FILE_CONTEXT_UNSUPPORTED`, or `DECLARATION_TARGET`. Entity
candidate reasons are exactly the five ranking reasons above. This structure
retains stale, losing, and tied evidence without implying a winner. File
references are always `UNRESOLVED` with `FILE_CONTEXT_UNSUPPORTED`; project file
scanning, ingestion, indexing, and resolution remain excluded.

## Memory lifecycle and deterministic retrieval

### Manual lifecycle ownership and revision history

- Memory creation, editing, inspection, stored-status listing, and soft deletion
  are explicit `LOCAL_USER` operations owned by the TASK-0009 `MemoryManager`
  use cases. There is no automatic creation, extraction, merge, rewrite,
  cleanup, expiry mutation, background mutation, or restore operation.
- Every successful create, edit, or soft-delete operation writes exactly one
  `memory_sources` row and one immutable `memory_revisions` row in the same
  transaction. A direct manual create uses source kind `MANUAL_ENTRY`; edits and
  soft deletions use `USER_EDIT`. Their non-empty user-entered descriptions are
  retained. Failed operations write neither row.
- Create writes an `ACTIVE` memory and revision number `1` with operation
  `CREATE`. Edit preserves the memory ID, creation time, type, scope, and owner
  IDs, replaces only content, keywords, topic terms, importance, confidence,
  and expiry, and appends the next consecutive `EDIT` revision. Soft delete
  preserves content and provenance, sets `status=DELETED`, sets `deleted_at`
  and `updated_at` from one injected-clock reading, and appends the next
  consecutive `SOFT_DELETE` revision. A deleted memory remains inspectable but
  cannot be edited, deleted again, or restored.
- The TASK-0017 presentation adapter supplies the selected aggregate's greatest
  revision number for edit and soft delete. The application reloads and compares
  that number inside the mutation transaction before invoking the canonical
  lifecycle operation. A mismatch is a stale presentation result: it writes no
  memory/source/revision and emits no memory trace. This uses existing immutable
  revisions and adds no stored version field or automatic retry.
- `content_snapshot` is the exact content at that revision. Every revision's
  `metadata_json` is exactly a `memory-revision-v1` object with these keys:

  | Key | Value |
  |---|---|
  | `schema_version` | The literal `memory-revision-v1`. |
  | `source_id` | UUID of the source row written by the same operation. |
  | `memory_type` | Canonical `MemoryType` value. |
  | `scope` | Canonical `MemoryScope` value. |
  | `conversation_id` | Memory conversation UUID or null. |
  | `project_id` | Memory project UUID or null. |
  | `status` | Stored `MemoryStatus` value at the revision. |
  | `keywords` | Exact ordered JSON string array at the revision. |
  | `topic_terms` | Exact ordered JSON string array at the revision. |
  | `importance` | Canonical decimal string at the revision. |
  | `confidence` | Canonical decimal string at the revision. |
  | `expires_at` | Canonical UTC timestamp or null. |
  | `memory_created_at` | Canonical immutable creation timestamp. |
  | `updated_at` | Canonical update timestamp at the revision. |
  | `deleted_at` | Canonical deletion timestamp or null. |

  Together with `memory_id`, `revision_number`, `operation`,
  `content_snapshot`, `performed_by`, and the revision creation time, this
  object reconstructs the complete memory snapshot and links it to inspectable
  provenance without a schema change.

### Effective status and scope eligibility

- `memories.status` stores only `ACTIVE` or `DELETED`. Effective status is
  computed at an injected UTC `evaluated_at`: stored `DELETED` always computes
  `DELETED`; otherwise `expires_at <= evaluated_at` computes `EXPIRED`; all
  other records compute `ACTIVE`. Expiry writes no row, changes no stored value,
  and creates no source or revision. Deleted and expired memories are excluded
  from retrieval; both remain inspectable.
- A conversation-scoped memory is eligible exactly when its non-null
  `conversation_id` equals the retrieval conversation ID; any `project_id` on
  that record does not affect eligibility. A project-scoped memory is eligible
  exactly when the retrieval project ID is non-null and equals its non-null
  `project_id`; any `conversation_id` on that record does not affect
  eligibility. A global memory is eligible for every conversation and has null
  conversation/project owner IDs. Other-conversation and other-project records
  are retained as considered inputs with `SCOPE_MISMATCH` evidence.

### Retrieval normalization and score

- Retrieval word normalization applies Unicode NFC, then Unicode case-folding,
  deletes every code point whose Unicode General Category begins with `P`,
  splits with Unicode whitespace semantics, and discards empty tokens.
  Punctuation is deleted rather than replaced, so `foo-bar` becomes `foobar`;
  non-punctuation symbols remain part of their token. Keyword/topic arrays are
  normalized entry by entry and flattened. Request, keyword, and topic
  comparisons use unique token sets. Normalized content is the normalized token
  sequence joined by one ASCII space; equal normalized strings, including the
  empty string, are exact retrieval duplicates.
- All score arithmetic uses a private decimal context with precision `28` and
  `ROUND_HALF_EVEN`; binary floating-point and the ambient process decimal
  context do not participate. No two-decimal display rounding or other manual
  quantization occurs before comparison or ordering. A canonical decimal string
  uses fixed-point notation, removes trailing fractional zeroes and a trailing
  decimal point, and represents zero as `0`.
- The score is:

  `0.30 project_match + 0.20 topic_match + 0.20 keyword_jaccard + 0.10 recency + 0.10 importance + 0.05 scope_match + 0.05 correction_match`.

  `project_match` is `1` only for an eligible project-scoped memory with the
  same non-null project ID as the retrieval request; otherwise `0`.
  `topic_match` is `1` only when the normalized non-empty active-topic token set
  intersects the memory's normalized topic-term set; otherwise `0`.
  `keyword_jaccard` is the size of the request/keyword token-set intersection
  divided by the size of their union, or `0` for an empty union. `age_days` is
  the exact non-negative UTC duration from `updated_at` to `evaluated_at`
  divided by `86400` seconds; future update times therefore have age zero.
  `recency = max(0, 1 - age_days / 90)`. `importance` is the stored score.
  `scope_match` is `1.00` for conversation, `0.80` for project, and `0.60` for
  global. `correction_match` is `1` only for a `CORRECTION_RULE` memory whose
  normalized keyword set intersects the request token set; otherwise `0`.
- Compare the canonical unrounded score inclusively with
  `context.minimum_relevance_score`; equality is selected. Sort qualifying
  records by score descending, importance descending, `updated_at` descending,
  then canonical UUID text ascending.

### Selection, duplicates, rank, reasons, and exclusions

- After threshold filtering and canonical sorting, retrieval-only duplicate
  collapse retains the first record for each normalized content string. It
  never merges, rewrites, or deletes stored memories. Apply
  `context.retrieved_memory_limit` after duplicate collapse; a zero limit
  selects none. Selected records receive contiguous zero-based ranks.
- Every selected record stores exactly seven reason strings in this order, with
  each `<value>` rendered as a canonical decimal string:
  `project_match=<value>`, `topic_match=<value>`,
  `keyword_jaccard=<value>`, `recency=<value>`, `importance=<value>`,
  `scope_match=<value>`, and `correction_match=<value>`.
- Each distinct considered memory ID appears exactly once as either selected or
  excluded. Select one exclusion by this precedence:
  `SCOPE_MISMATCH`, `DELETED`, `EXPIRED`, `SCORE_BELOW_THRESHOLD`,
  `DUPLICATE_CONTENT`, then `LIMIT_EXCEEDED`. Exclusion fields are:

  | Reason | `computed_score` | Exact `details_json` keys |
  |---|---|---|
  | `SCOPE_MISMATCH` | null | `scope`, `request_conversation_id`, `request_project_id`, `memory_conversation_id`, `memory_project_id` |
  | `DELETED` | null | `stored_status`, `deleted_at` |
  | `EXPIRED` | null | `stored_status`, `expires_at`, `evaluated_at` |
  | `SCORE_BELOW_THRESHOLD` | canonical score | `minimum_relevance_score` as a canonical decimal string |
  | `DUPLICATE_CONTENT` | canonical score | `retained_memory_id` |
  | `LIMIT_EXCEEDED` | canonical score | `result_limit`, `pre_limit_rank` (zero-based after deduplication) |

  The listed keys are complete; details contain no raw or normalized memory
  content. Result and exclusion creation times equal `evaluated_at`. Retrieval
  confidence is the highest selected score, or null when no record is selected.
  The decision has no side effects; existing context-packet persistence stores
  its selected and excluded evidence later without changing the decision.

### TASK-0017 creation-time duplicate guidance

Creation-time duplicate guidance reuses only the normalized-content function
defined above. After create-form validation and before a create write, compare
the proposal against stored-`ACTIVE` records with the exact same `MemoryScope`
and canonical owner identity. Conversation scope compares only the non-null
`conversation_id`, project scope compares only the non-null `project_id`, and
global scope uses the singleton null-owner identity; an irrelevant non-owner ID
is ignored exactly as it is for scope eligibility. Effectively `ACTIVE` and
`EXPIRED` records participate; stored `DELETED` and different-owner/scope
records do not. Equal normalized content is a possible duplicate. Candidate
order is `updated_at` descending and canonical UUID text ascending.

The result is advisory. With no explicit proceed decision, one or more
candidates causes no write; the user may return to editing or explicitly create
a separate memory. Proceeding recomputes the comparison in the create
transaction and creates the independent record without changing any candidate.
There is no merge, replace, rewrite, link, delete, cleanup, or automatic choice.

This rule is not retrieval duplicate collapse. Retrieval considers its own
eligible/scored/thresholded sequence, retains only its first normalized-content
record for that one decision, and never changes storage. TASK-0017 guidance is
same-owner/scope creation advice before persistence and never alters later
retrieval ordering or evidence.
