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
| `ReferenceStatus` | `RESOLVED`, `AMBIGUOUS`, `UNRESOLVED`, `NOT_APPLICABLE` | All outcomes are persisted. |
| `ProcessingRunStatus` | `PERSISTED`, `CONTEXT_READY`, `GENERATING`, `REVISING`, `SUCCEEDED`, `NEEDS_CLARIFICATION`, `CONTROLLED_FAILURE`, `FAILED`, `CANCELLED` | A run has exactly one terminal status. |
| `ModelRequestStatus` | `PENDING`, `IN_FLIGHT`, `SUCCEEDED`, `TIMED_OUT`, `CANCELLED`, `FAILED` | Model transport lifecycle. |
| `ValidationStatus` | `PASSED`, `FAILED`, `NOT_RUN` | One result exists for every completed candidate response. |
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
| `FailureCode` | `CONTEXT_BUDGET_EXCEEDED`, `PERSISTENCE_ERROR`, `CONCURRENCY_CONFLICT`, `PROCESS_RESTARTED`, `CONFIGURATION_CHANGED`, `PROVIDER_UNAVAILABLE`, `MODEL_NOT_FOUND`, `MODEL_TIMEOUT`, `MODEL_CANCELLED`, `INVALID_PROVIDER_RESPONSE`, `VALIDATION_EXHAUSTED`, `CONFIGURATION_INVALID`, `CANCELLED_BY_USER` | Safe terminal processing-failure code; clarification and `BusyError` are not failures. |

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

An image/action request is `UNSUPPORTED` unless the explicit requested output is
a text description or text prompt. The MVP never generates an image or invokes
an external action. For every accepted text request, the constraint engine also
persists one `FORBIDDEN` constraint with source
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

## Constraint priority and conflict rules

The following numeric bands are canonical. Within a band, newer source message
sequence wins; an exact tie is a conflict.

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
constraint (`REQUIRED`, `FORBIDDEN`, or `PRESERVE`). When two equally
authoritative hard constraints oppose each other, the run becomes
`NEEDS_CLARIFICATION`; no model call occurs. When a higher rule defeats a lower
one, retain both records and mark the lower rule `OVERRIDDEN` in the packet
evidence. A conditional rule is inactive until its deterministic condition is
true; unsupported conditions require clarification.

The only accepted conditional grammar is `mvp-condition-v1`, configured by the
fixed `context.conditional_grammar_version` value. It accepts exactly one of:

```text
if output type is <canonical OutputType>, <REQUIRED|FORBIDDEN|PRESERVE clause>
if active project is "<exact normalized active-project name>", <REQUIRED|FORBIDDEN|PRESERVE clause>
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

## State transitions and concurrency

- A user explicitly creates a project in `ACTIVE` status or a conversation with
  a default version-`0` state. A new conversation may be unscoped. The selected
  conversation is an ephemeral UI choice, not a second persisted active-project
  field. A user may select only an existing `ACTIVE` project for a conversation;
  that association is the sole persisted active project and the change occurs in
  the acceptance transaction with one state-version increment.
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
PERSISTED -> CONTEXT_READY | NEEDS_CLARIFICATION | CONTROLLED_FAILURE | FAILED
CONTEXT_READY -> GENERATING | FAILED | CANCELLED
GENERATING -> SUCCEEDED | REVISING | CONTROLLED_FAILURE | FAILED | CANCELLED
REVISING -> SUCCEEDED | REVISING | CONTROLLED_FAILURE | FAILED | CANCELLED
```

Recovery may take any non-terminal status to `FAILED` only with a durable
canonical failure code. A model request transitions
`PENDING -> IN_FLIGHT -> SUCCEEDED|TIMED_OUT|CANCELLED|FAILED`; no terminal
request state can change. A successful request creates exactly one response; a
response creates exactly one validation result; only a passed validation can
create one linked assistant message. A failed validation either creates the next
allowed correction request or terminalizes the run. No terminal run can receive
another request, assistant message, state update, or correction row.

## Entity and reference rules

The entity registry contains projects, topics, tasks, and explicit
user-introduced named items. A project/topic/task row creates and owns exactly
one registry row whose `native_id` equals the owning row ID; its activity mirrors
the owning project's archive status and task terminal status. A named item has
its own durable `named_items` row and may be registered only by the explicit UI
operation or one of these user declarations: `name "<label>"` or `call this
"<label>"`. It records the source message and owning conversation/project when
present; free-form model-inferred NER is prohibited. A reference candidate is
ranked deterministically: exact explicit name
match `1.00`; active task/topic/project `0.90`; most recent tracked entity
matching the phrase `0.80`; most recent matching source-message text `0.60`.
The unique highest candidate resolves only when it is at least `0.80` and does
not tie another candidate. A tie or lower score is `AMBIGUOUS`/`UNRESOLVED` and
requires clarification if the target is material. File references are unresolved
in MVP because file ingestion/indexing is excluded.

## Memory lifecycle and deterministic retrieval

- Memory creation, edits, and deletion are explicit user operations only. The
  UI does not offer automatic merging; duplicate records remain separate until
  the user edits or deletes one. Every change writes an immutable revision.
- A memory must have at least one `memory_sources` record. A manual entry uses
  source kind `MANUAL_ENTRY`; it never leaves provenance blank.
- `memories.status` stores only `ACTIVE` or `DELETED`. An elapsed `expires_at`
  computes an effective retrieval status of `EXPIRED`; it does not write a
  revision or mutate the stored record. `DELETED` requires non-null `deleted_at`
  and is excluded from retrieval while retaining revisions/sources; an `ACTIVE`
  memory requires null `deleted_at`.
- Eligible records are active and in the same conversation, same project, or
  global scope as appropriate. Cross-project project memories are ineligible.
- Normalize words by lowercase Unicode case-folding, punctuation removal, and
  whitespace splitting. The score is:

  `0.30 project_match + 0.20 topic_match + 0.20 keyword_jaccard + 0.10 recency + 0.10 importance + 0.05 scope_match + 0.05 correction_match`.

  `project_match` is `1` only when a project-scoped memory has the same
  non-null project ID as the conversation; otherwise `0`. `topic_match` is `1`
  only when the normalized non-empty active-topic label shares a token with the
  memory's normalized `topic_terms_json`; otherwise `0`. `keyword_jaccard` is
  the size of the intersection divided by the size of the union of unique
  normalized request tokens and unique normalized `keywords_json` tokens (zero
  for an empty union). `recency = max(0, 1 - age_days / 90)`, where `age_days`
  is the non-negative UTC-clock difference from `updated_at`; boolean matches
  are `0` or `1`; `importance` is the stored score. `scope_match` is `1.00` for
  conversation, `0.80` for project, and `0.60` for global.
  `correction_match` is `1` only when a `CORRECTION_RULE` memory has a non-empty
  normalized keyword intersection with the request; otherwise `0`.
- Include records at or above `context.minimum_relevance_score`; sort by score
  descending, importance descending, updated time descending, then UUID
  ascending. Retrieval-only deduplication collapses exact normalized content,
  retaining the first record under that order. Apply
  `context.retrieved_memory_limit` after deduplication. Persist each selected
  record's rank, score, and reasons, and persist every rejected eligible/input
  memory with `SCOPE_MISMATCH`, `DELETED`, `EXPIRED`, `SCORE_BELOW_THRESHOLD`,
  `DUPLICATE_CONTENT`, or `LIMIT_EXCEEDED` evidence.
