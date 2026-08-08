# Context Inspection Contract

## Authority and scope

This document is the normative detailed contract for TASK-0016. It refines
FR-015, the context-page portion of AT-013, and the later-page extension point
reserved by `PresentationShell.md`. It does not change the TASK-0015 `CHAT`
route, shell state machine, submission/recovery result algebra, or foreground
worker semantics.

TASK-0016 owns one read-only context-inspection application use case, its safe
immutable projection, one `CONTEXT_INSPECTION` route, the page state owned by
the existing `ShellFacade`, and the deterministic page/accessibility assertions
defined below. It does not own context decisions, persistence writes, model
calls, memory mutation, project/conversation-management UI, validation-history
UI, or settings UI.

The page observes only existing durable decisions. It does not reconstruct or
re-run interpretation, reference resolution, constraint processing, retrieval,
validation, or correction.

## MVP target and temporal semantics

The sole MVP inspection target is the latest accepted processing run for the
conversation currently selected by the shell.

`InspectContext` accepts the shell's current `conversation_id`. Inside one
read-only snapshot it verifies that the conversation exists and selects the run
whose linked `USER` message has the greatest `messages.sequence_number` in that
conversation. A conversation with no processing run has no target and produces
the empty result below.

`messages(conversation_id, sequence_number)` is unique and
`processing_runs.user_message_id` is unique, so two valid targets cannot tie.
More than one run for the same message sequence is an invariant failure and
produces the safe load-failure result; UUID or timestamp tie-breaking must not
hide it. A non-terminal accepted run remains a valid latest target. A busy or
pre-acceptance-cancelled submission creates no run and cannot become a target.

Every context decision displayed for a target is historical run evidence:

- intent, output type, qualifiers, active-state IDs, retrieval, and confidence
  come from that run's immutable packet when one exists;
- references, constraints, validation, corrections, clarification, and terminal
  failure come from rows linked to that run; and
- no current conversation state is substituted for missing run evidence.

For an active-state ID snapshotted in a packet, the application resolves the
current canonical persisted owner label (`projects.name`, `topics.label`, or
`tasks.title`) only to make that historical ID readable. The identity and
presence/null decision are historical; the label is the current canonical
label for that same retained owner row at query time. The MVP has no separate
historical label snapshot. A missing or mismatched owner row violates persisted
lineage and produces a load failure rather than a guessed label.

Changing conversations selects the latest accepted run of the newly selected
conversation. Changing the current project without creating a run does not
retarget or reinterpret the latest run; a refresh continues to show that run's
historical packet state. A later accepted run becomes the target after its
durable acceptance, but automatic refresh occurs only at the terminal events
defined below. There is no polling or trace-driven refresh.

## Application interface

The existing placeholder `InspectContext` protocol is superseded for TASK-0016
by this closed contract:

```text
InspectContextRequest {
  conversation_id: uuid
}

InspectContextResult =
    ContextInspectionReadyResult
  | ContextInspectionEmptyResult
  | ContextInspectionLoadFailureResult

ContextInspectionReadyResult {
  result_kind: "CONTEXT_INSPECTION_READY",
  view: ContextInspectionView
}

ContextInspectionEmptyResult {
  result_kind: "CONTEXT_INSPECTION_EMPTY",
  safe_message: "No processed request is available for this conversation."
}

ContextInspectionLoadFailureResult {
  result_kind: "CONTEXT_INSPECTION_LOAD_FAILURE",
  code: INSPECTION_LOAD_FAILED,
  safe_message: "Context inspection could not be loaded safely."
}

InspectContext.execute(
  request: InspectContextRequest
) -> InspectContextResult
```

All request, result, view, field, and nested collection values are frozen,
slotted, recursively immutable application values. Collections are tuples.
They contain no SQLite row, repository, mutable domain aggregate, QObject,
model request, model response, prompt, provider object, or exception.

The empty result is legal only when the requested conversation exists with its
required state but has no processing run. A missing conversation/state,
repository failure, invalid lineage, malformed persisted JSON, disagreement
between a packet and its normalized rows, or failure to construct the complete
safe projection returns `ContextInspectionLoadFailureResult`. No partial view is
returned with a load failure.

## Common safe values and formatting

### Availability

Every top-level optional scalar or collection in `ContextInspectionView`, plus
each nested field explicitly typed as `InspectionValue`, uses one of these
values:

```text
InspectionAvailability =
    AVAILABLE | EMPTY | NOT_APPLICABLE | UNAVAILABLE
```

- `AVAILABLE` means the authoritative durable evidence exists. A scalar has a
  non-null value; a collection has at least one item.
- `EMPTY` applies only to a collection whose owning stage durably completed and
  produced zero items. Its tuple is empty.
- `NOT_APPLICABLE` means the completed run path did not require that field, such
  as validation for a clarification or a provider failure before a candidate.
- `UNAVAILABLE` means the selected durable checkpoint does not retain enough
  evidence to determine the field. It is never inferred from current state,
  traces, prompts, candidates, or transient objects.

Unless a field-specific exact override is stated below, the application supplies
these default presentation strings:

| Availability | Exact `display_text` when no value/item text exists |
|---|---|
| `EMPTY` | `None recorded.` |
| `NOT_APPLICABLE` | `Not applicable.` |
| `UNAVAILABLE` | `Unavailable for this run.` |

`AVAILABLE` uses the value's contracted display text. The active-state null
overrides below are the only field-specific `NOT_APPLICABLE` strings. QML does
not translate an availability enum into a user-facing string.

```text
InspectionValue[T] {
  availability: AVAILABLE | NOT_APPLICABLE | UNAVAILABLE,
  value: T or null,
  display_text: exact safe presentation text
}

InspectionCollection[T] {
  availability: AVAILABLE | EMPTY | NOT_APPLICABLE | UNAVAILABLE,
  items: tuple[T],
  display_text: exact safe presentation text or empty
}
```

For `AVAILABLE`, `InspectionValue.value` is non-null and
`InspectionCollection.items` is non-empty. For every other availability the
value is null or the tuple is empty.

### Canonical labels

Every canonical enum is preserved as `code` and receives an application-owned
`display_label`. The label is derived by splitting the ASCII enum value on
underscores, lower-casing every word, joining with one space, and upper-casing
only the first character. Thus `EDIT_TEXT` displays as `Edit text` and
`NOT_APPLICABLE` displays as `Not applicable`. QML does not format enum values.

```text
CanonicalLabelView {
  code: exact canonical enum value,
  display_label: deterministic label
}
```

### Scores

Every score uses the authoritative base-10 decision value, not a value parsed
back from visible text:

```text
InspectionScoreView {
  canonical_decimal: canonical fixed-point unrounded decimal string,
  display_text: fixed two-decimal string
}
```

`display_text` is rounded from the exact decision value to two fractional digits
with `ROUND_HALF_EVEN`, includes a leading zero, never uses exponent notation,
and is locale-independent. Examples are `0.00`, `0.80`, and `1.00`. QML does no
numeric conversion, rounding, percentage conversion, or locale formatting.
`canonical_decimal` also never uses exponent notation; it removes trailing
fractional zeroes and a trailing decimal point and represents zero as `0`,
matching the canonical score spelling in `DomainAndDecisionRules.md`.

## Complete safe data model

```text
ContextInspectionView {
  target: InspectionTargetView,
  active_project: InspectionValue[ActiveStateItemView],
  active_topic: InspectionValue[ActiveStateItemView],
  active_task: InspectionValue[ActiveStateItemView],
  intent: InspectionValue[CanonicalLabelView],
  expected_output_type: InspectionValue[CanonicalLabelView],
  qualifier_evidence: InspectionCollection[QualifierEvidenceView],
  references: InspectionCollection[ReferenceInspectionView],
  constraints: InspectionCollection[ConstraintInspectionView],
  conflicts: InspectionCollection[ConflictInspectionView],
  retrieved_memories: InspectionCollection[RetrievedMemoryInspectionView],
  confidence: InspectionValue[ConfidenceInspectionView],
  validation: InspectionValue[ValidationInspectionView],
  correction_count: InspectionValue[uint],
  clarification: InspectionValue[ClarificationInspectionView],
  terminal_status: InspectionValue[SafeTerminalStatusView]
}
```

No field may be omitted or replaced by an open JSON payload.

### Target and active state

```text
InspectionRunOutcome =
    PROCESSING | SUCCEEDED | CLARIFICATION | CONTROLLED_FAILURE | CANCELLED

InspectionCheckpoint =
    ACCEPTED | CONTEXT_COMMITTED | VALIDATION_COMMITTED |
    CLARIFICATION_COMMITTED | TERMINAL_WITHOUT_CONTEXT

InspectionTargetView {
  user_message_sequence: uint,
  request_label: exact "Request <N>",
  outcome: InspectionRunOutcome,
  checkpoint: InspectionCheckpoint,
  outcome_label: deterministic canonical label,
  checkpoint_label: deterministic canonical label
}

ActiveStateItemView {
  kind: PROJECT | TOPIC | TASK,
  display_name: exact non-empty persisted owner label
}
```

`request_label` is the safe display identity, where `<N>` is the unsigned
base-10 `user_message_sequence`. The application supplies all three labels;
QML does not format the integer or enums. Processing, message, packet, request,
response, validation, entity, memory, and failure UUIDs are not exposed.

`PERSISTED`, `CONTEXT_READY`, `GENERATING`, and `REVISING` map to `PROCESSING`;
`SUCCEEDED` maps to `SUCCEEDED`; `NEEDS_CLARIFICATION` maps to
`CLARIFICATION`; `CONTROLLED_FAILURE` and `FAILED` map to
`CONTROLLED_FAILURE`; and `CANCELLED` maps to `CANCELLED`. Raw
`ProcessingRunStatus` is not exposed to QML.

A null packet project/topic/task ID is `NOT_APPLICABLE` and displays exactly
`No active project.`, `No active topic.`, or `No active task.` respectively. A
missing packet makes all three fields `UNAVAILABLE`.

### Intent and qualifier evidence

Intent and expected output type copy the packet request's canonical enum values.
They are `UNAVAILABLE` without a packet.

```text
QualifierEvidenceView {
  ordinal: uint starting at 1,
  kind: CanonicalLabelView,
  rule_id: exact non-empty rule identifier,
  matched_text: exact non-empty source text
}
```

Qualifier order is packet source order. A packet with no qualifier is `EMPTY`;
without a packet the collection is `UNAVAILABLE`. Exact `matched_text` is
allowlisted source evidence, not a rendered prompt.

### References and safe source evidence

```text
ReferenceInspectionView {
  mention_number: uint starting at 1,
  surface_text: exact non-empty source text,
  status: CanonicalLabelView,
  resolved_display_name: InspectionValue[string],
  source_message: InspectionValue[ReferenceMessageSourceView],
  confidence: InspectionScoreView,
  evidence: tuple[ReferenceEvidenceView]
}

ReferenceMessageSourceView {
  message_sequence: uint,
  display_text: "Message <N>"
}

ReferenceEvidenceView {
  rank: uint starting at 1,
  candidate_display_name: string or null,
  candidate_type: CanonicalLabelView or null,
  score: InspectionScoreView,
  rank_reason: CanonicalLabelView,
  evidence_message: ReferenceMessageSourceView or null,
  is_active: boolean or null,
  activity_display_text: "Active" | "Inactive" | null
}
```

References are ordered by persisted `mention_ordinal`; `mention_number` is that
ordinal plus one. Candidate evidence preserves persisted rank order. A resolved
display name is the winning candidate's display name. It is `NOT_APPLICABLE`
for non-resolved statuses. A non-null `source_message_id` is resolved to its
sequence number and exposes no ID or message content; a null source is
`NOT_APPLICABLE`. Missing referenced message lineage is a load failure.

Within an available candidate-evidence item, null candidate name/type and null
evidence message are omitted rather than rendered as top-level field
availability. `is_active` and `activity_display_text` are both null or both
non-null; true displays `Active` and false displays `Inactive`. QML does not
format the boolean. A non-null evidence-message ID is resolved to the same safe
`Message <N>` record used above, and missing lineage is a load failure.

Candidate entity IDs, normalized names, source IDs, prior mention IDs, and raw
message content are not exposed. The exact reference surface text, candidate
display label, band score, rank reason, evidence message sequence, and activity
flag are the complete reference evidence allowlist.

### Constraints and conflicts

```text
ConstraintConditionView {
  grammar_version: exact non-empty identifier,
  kind: CanonicalLabelView,
  expected_value: exact non-empty persisted value,
  evaluation: CanonicalLabelView
}

ConstraintInspectionView {
  ordinal: uint starting at 1,
  type: CanonicalLabelView,
  underlying_type: CanonicalLabelView or null,
  scope: CanonicalLabelView,
  normalized_rule: exact non-empty persisted rule,
  priority: uint,
  source_kind: CanonicalLabelView,
  source_text: exact non-empty persisted evidence,
  confidence: InspectionScoreView,
  resolution_status: CanonicalLabelView,
  condition: ConstraintConditionView or null
}

ConflictRuleView {
  constraint_ordinal: uint starting at 1,
  type: CanonicalLabelView,
  normalized_rule: exact non-empty persisted rule,
  source_text: exact non-empty persisted evidence
}

ConflictInspectionView {
  ordinal: uint starting at 1,
  rules: tuple[ConflictRuleView] with at least two items
}
```

Constraints preserve persisted ordinal order. A condition is non-null exactly
for a conditional constraint. Conflict presentation groups only persisted
`CONFLICTING` constraints with the same non-null `conflict_group_id`; it does not
perform opposition analysis. Groups sort by their smallest member ordinal, then
by the persisted group identifier only as a hidden deterministic tie-breaker.
Members sort by constraint ordinal. The identifier itself is not exposed.

When the constraint stage completed with no constraint, both collections are
`EMPTY`. A completed constraint stage without a hard conflict has an `EMPTY`
conflict collection. Exact source text is allowlisted constraint evidence.

### Retrieved memories

```text
RetrievedMemoryInspectionView {
  rank: uint starting at 1,
  content: exact selected packet-snapshot text,
  scope: CanonicalLabelView,
  memory_confidence: InspectionScoreView,
  retrieval_score: InspectionScoreView,
  reasons: tuple[string] with exactly seven items
}
```

Items are ordered by persisted zero-based retrieval rank and expose that rank
plus one. `content`, scope, and memory confidence come only from the selected
immutable packet snapshot; score and reasons must agree with the corresponding
`retrieval_results` row. Reasons remain the exact seven canonical factor strings
in their contracted order. Selected memory content is explicitly allowlisted
for this detailed inspection page. Memory UUIDs, source/revision history, and
excluded-memory content are not exposed. Retrieval exclusions are not part of
FR-015 and remain outside TASK-0016.

### Confidence

FR-015's singular confidence means the overall score is the primary displayed
value, with the three persisted components as inspection evidence:

```text
ConfidenceInspectionView {
  overall: InspectionScoreView,
  interpretation: InspectionScoreView,
  references: InspectionValue[InspectionScoreView],
  retrieval: InspectionValue[InspectionScoreView]
}
```

The reference or retrieval component is `NOT_APPLICABLE` exactly when the
packet component is null. Confidence is `UNAVAILABLE` without a packet.

### Validation and correction

Among the run's validation results, the application selects the one whose linked
model request has the greatest persisted attempt number. It may read raw model
request/response records to join lineage inside the application scope, but
neither object nor either text field may enter the result.

```text
SafeValidationViolationView {
  ordinal: uint starting at 1,
  code: CanonicalLabelView,
  message: exact canonical safe violation message
}

SafeValidationEvidenceView {
  ordinal: uint starting at 1,
  check_id: CanonicalLabelView,
  severity: CanonicalLabelView,
  outcome: CanonicalLabelView,
  violation_code: CanonicalLabelView or null,
  warning_code: CanonicalLabelView or null,
  explanation: exact canonical explanation
}

ValidationInspectionView {
  attempt_number: uint starting at 1,
  status: CanonicalLabelView,
  score: InspectionScoreView,
  violations: tuple[SafeValidationViolationView],
  evidence: tuple[SafeValidationEvidenceView]
}
```

Displayed `attempt_number` is persisted zero-based request attempt plus one.
Violation and evidence order preserve their persisted ordinals. Rule IDs,
constraint IDs, normalized candidate inputs, match locations, missing
predicates, rendered prompts, response text, and provider metadata are omitted.
Only the non-null violation or warning code is rendered for an evidence item;
the null counterpart is omitted rather than formatted by QML.

`correction_count` is the number of committed `correction_attempts` rows for the
target and is in `[0,2]`. It is `AVAILABLE` whenever a packet exists, including
zero before the first correction. It is `NOT_APPLICABLE` for a completed
clarification or terminal run without a packet, and `UNAVAILABLE` for a
non-terminal accepted run that has not committed a packet.

### Clarification and terminal status

```text
ClarificationInspectionView {
  reason: CanonicalLabelView,
  question_text: exact deterministic persisted question
}

SafeTerminalKind = CONTROLLED_FAILURE | CANCELLED

SafeTerminalStatusView {
  kind: SafeTerminalKind,
  kind_label: deterministic canonical label,
  stage: CanonicalLabelView,
  code: CanonicalLabelView,
  safe_message: exact persisted safe message
}
```

Clarification is `AVAILABLE` exactly for `NEEDS_CLARIFICATION` and otherwise
`NOT_APPLICABLE`. Only reason and question are exposed; `details_json` is not.

Terminal status is `AVAILABLE` for `CONTROLLED_FAILURE`, `FAILED`, and
`CANCELLED`, using the one terminal `SafeFailure`. The first two use kind
`CONTROLLED_FAILURE`; the last uses `CANCELLED`. It is `NOT_APPLICABLE` for
success and clarification and `UNAVAILABLE` for a non-terminal run. Failure IDs,
details, internal checkpoints, exception data, and failed persistence objects
are not exposed.

## Durable checkpoint and availability matrix

The application derives one checkpoint only from committed artifacts:

| Durable evidence | `InspectionCheckpoint` |
|---|---|
| Non-terminal `PERSISTED`, no packet/clarification | `ACCEPTED` |
| Packet exists, no validation result | `CONTEXT_COMMITTED` |
| Packet and at least one validation result exist | `VALIDATION_COMMITTED` |
| `NEEDS_CLARIFICATION` with its sole clarification row | `CLARIFICATION_COMMITTED` |
| Terminal run with no packet and no clarification | `TERMINAL_WITHOUT_CONTEXT` |

`CONTEXT_READY` and `GENERATING` must map to `CONTEXT_COMMITTED`; `REVISING`
must map to `VALIDATION_COMMITTED`; and `SUCCEEDED` must map to
`VALIDATION_COMMITTED`. A terminal failure/cancellation may map to
`TERMINAL_WITHOUT_CONTEXT`, `CONTEXT_COMMITTED`, or `VALIDATION_COMMITTED`
according to its committed artifacts. Any impossible combination is a load
failure.

In this matrix `A` means `AVAILABLE`, `E` means `EMPTY` when the collection has
no items and otherwise `A`, `N` means `NOT_APPLICABLE`, and `U` means
`UNAVAILABLE`.

| Field | `ACCEPTED` | `CONTEXT_COMMITTED` | `VALIDATION_COMMITTED` | `CLARIFICATION_COMMITTED` | `TERMINAL_WITHOUT_CONTEXT` |
|---|---:|---:|---:|---:|---:|
| Active project/topic/task | U | A or N per packet ID | A or N per packet ID | U | U |
| Intent / expected output | U | A | A | U | U |
| Qualifier evidence | U | A/E | A/E | U | U |
| References | U | A/E | A/E | reason-specific below | U |
| Constraints | U | A | A | reason-specific below | U |
| Conflicts | U | E | E | reason-specific below | U |
| Retrieved memories | U | A/E | A/E | U | U |
| Confidence | U | A | A | U | U |
| Validation | U | U for non-terminal; N for terminal | A | N | N |
| Correction count | U | A | A | N | N |
| Clarification | N | N | N | A | N |
| Terminal status | U | U for non-terminal; A for controlled/cancelled terminal | U for non-terminal; N for success; A for controlled/cancelled terminal | N | A |

Clarification stage availability is determined by the persisted reason and the
global blocking precedence already owned by `DomainAndDecisionRules.md`:

| Clarification reason | References | Constraints | Conflicts |
|---|---:|---:|---:|
| `LOW_CONFIDENCE_INTERPRETATION`, `UNSUPPORTED_INTENT` | U | U | U |
| `AMBIGUOUS_REFERENCE`, `UNRESOLVED_REFERENCE` | A | U | U |
| `UNSUPPORTED_CONDITION`, `MATERIAL_ASSUMPTION` | A/E | A | E |
| `HARD_CONSTRAINT_CONFLICT` | A/E | A | A |

`HARD_CONSTRAINT_CONFLICT` requires at least one conflict group. A missing
required artifact or an artifact from a phase that could not have run is a load
failure, not an unavailable value.

## Aggregation and persistence boundary

`InspectContext` owns all target selection, repository aggregation, lineage
validation, availability assignment, safe source resolution, ordering,
canonical labels, score formatting, and redaction. Presentation does not join
`InspectContext` with validation inspection or any other use case.

The application reads through repository ports only. Infrastructure may add the
minimum read query needed to select the latest run by conversation/message
sequence, but the complete inspection executes in one read-only SQLite snapshot
on one connection. It writes no row, setting, trace event, or lifecycle state
and invokes no context component, validator, correction controller, model
gateway, or configuration reload.

The existing schema retains every datum required by this contract. Explicit
`UNAVAILABLE` and `NOT_APPLICABLE` states preserve the authoritative rule that a
clarification or early context failure does not invent a packet/interpretation
projection. TASK-0016 requires no database migration.

## Safe exposure allowlist

Only the following data values, plus the exact application-owned labels,
availability/status strings, list/scalar text, and accessibility strings defined
by this contract, may reach the context page:

- target message sequence, safe outcome, and durable checkpoint;
- current canonical labels for packet-snapshotted active-state owner IDs;
- packet intent/output codes, qualifier kind/rule ID/exact matched text;
- reference surface/status/confidence, resolved/candidate display labels,
  candidate type/rank/reason/evidence message sequence/activity;
- constraint type/scope/rule/priority/source kind/exact source text/confidence/
  resolution/condition and grouped conflict rules;
- selected memory snapshot content/scope/confidence/rank/score/seven reasons;
- packet confidence overall and component scores;
- latest validation status/score and the safe validation subset defined above;
- correction count;
- clarification reason/question; and
- terminal failure/cancellation kind, stage, code, and safe message.

The application result, facade, list models, QML tree, accessibility names, and
announcements must contain none of:

- `rendered_prompt`, prompt fragments, correction envelopes, or packet original
  request text except the explicitly allowlisted qualifier/reference/constraint
  source evidence;
- any invalid or unlinked candidate response text;
- raw model request/response DTOs, response buffers, token usage, or provider
  metadata;
- raw validation match locations, normalized candidate inputs, or candidate
  substrings;
- raw exceptions, tracebacks, SQL, database paths, configuration values, or
  unsafe failure/clarification details;
- repository, transaction, SQLite connection/cursor/row, domain aggregate,
  context-engine, gateway, transport, cancellation token, or worker object; or
- hidden UUIDs and internal lineage/checkpoint data not explicitly represented
  by the safe target/checkpoint records above.

Application and worker-boundary redaction is mandatory. QML string hiding is
not a substitute.

## Route and single-facade integration

TASK-0016 extends the route set to exactly `{CHAT, CONTEXT_INSPECTION}` while
preserving `CHAT` as the initial route and preserving every TASK-0015 `CHAT`
behavior. The visible context navigation item is registered only when the real
page and use case are implemented.

The entry-point-owned GUI-thread `ShellFacade` remains the sole QObject and
presentation-state owner exposed to QML. TASK-0016 adds a private inspection-
query execution role; it is not a second public controller or state store. QML
may invoke only:

```text
navigate_to_chat() -> boolean
navigate_to_context_inspection() -> boolean
refresh_context_inspection() -> boolean
```

The route is read-only from QML. Navigation returns `false` and changes nothing
before a non-null shell conversation exists or after shutdown begins.
`navigate_to_context_inspection()` returns `true` when it selects the route and
starts or coalesces the required load. Invoking it while already on the route is
an explicit refresh. `refresh_context_inspection()` is accepted only on that
route outside shutdown and likewise starts or coalesces one refresh.

Inspection page state is orthogonal to `ShellState`. Opening, loading, or
failing inspection does not change chat terminal content, processing progress,
composer text, submit/cancel enablement, or foreground cancellation ownership.

QML branches only on `Route` and the closed `ContextInspectionPageState` below.
The facade maps the safe application view into presentation-owned read-only
primitive properties and list models on the GUI thread. QML does not parse
packet JSON, application result variants, domain enums, or availability rules.

## Inspection scope, threading, and delivery

TASK-0016 adds one narrow scope without changing the two TASK-0015 scopes:

```text
ShellApplicationScopeFactory {
  open_startup_scope() -> StartupApplicationScope
  open_foreground_scope() -> ForegroundApplicationScope
  open_inspection_scope() -> InspectionApplicationScope
}

InspectionApplicationScope {
  inspect_context: InspectContext
  close()
}
```

An accepted load creates one ephemeral inspection worker. On that worker thread
it opens one fresh `InspectionApplicationScope`, performs exactly one
`InspectContext.execute`, closes the scope and its SQLite connection on the same
thread, then emits exactly one immutable terminal envelope:

```text
InspectionTerminalEnvelope {
  generation: controller-local monotonically increasing uint,
  conversation_id: uuid,
  result: InspectContextResult | InspectionExecutionFailureView
}

InspectionExecutionFailureView {
  result_kind: "INSPECTION_EXECUTION_FAILURE",
  code: INSPECTION_EXECUTION_FAILED,
  safe_message: "Context inspection could not be loaded safely."
}
```

Scope-open failure and unexpected programming defects map only to
`InspectionExecutionFailureView`; no exception crosses the boundary. The
terminal and finished connections are explicitly queued. Only the matching
terminal envelope may select a page result state. The finished notification
may release worker ownership and start one coalesced refresh; it cannot select
a result state.

At most one inspection worker exists at a time. It is finite, read-only,
user/navigation-owned, and never persistent. There is no executor pool, queue,
poller, timer refresh, daemon, detached task, or trace subscription.

An inspection read may coexist with the one TASK-0015 submission/recovery
foreground worker. It uses a separate scope, connection, and read-only snapshot;
it neither consumes the global processing-run slot nor changes foreground
enablement. SQLite waiting or failure occurs off the GUI thread and maps through
the safe load result. No connection, repository, row, or transaction crosses
either worker boundary.

While a query is active, another refresh request invalidates its generation and
sets one coalesced `refresh_required` flag. It does not start a second worker or
retain a queue of requests. After the first worker finishes, exactly one fresh
query starts only if the context route, conversation, and non-shutdown state
still require it. Multiple invalidations collapse into that one query.

## Page state machine

```text
ContextInspectionPageState =
    INACTIVE | LOADING | READY | EMPTY | CLARIFICATION |
    CONTROLLED_FAILURE | LOAD_ERROR | SHUTDOWN
```

| State | Entry | Visible data |
|---|---|---|
| `INACTIVE` | Route is not `CONTEXT_INSPECTION`. | No inspection dataset or status. |
| `LOADING` | A first load/refresh is required or active. | Old dataset is cleared; indeterminate `Loading context inspection…`. |
| `READY` | Matching ready result with `PROCESSING`, `SUCCEEDED`, or `CANCELLED`. | Complete safe view with availability placeholders. |
| `EMPTY` | Matching empty result. | Exact empty safe message only. |
| `CLARIFICATION` | Matching ready result with clarification outcome. | Complete safe view and deterministic question. |
| `CONTROLLED_FAILURE` | Matching ready result with controlled-failure outcome. | Complete safe view and safe terminal status. |
| `LOAD_ERROR` | Matching load/execution failure. | Exact load-failure safe message only; no prior dataset. |
| `SHUTDOWN` | Shell shutdown accepted. | No inspection dataset; no new action. |

The facade exposes one exact `inspection_status_text` for the page status item:

| State/transition | Exact status text |
|---|---|
| `INACTIVE`, `SHUTDOWN` | Empty string; no status item is exposed. |
| `LOADING` | `Loading context inspection…` |
| First result enters `READY` | `Context inspection loaded.` |
| Refresh result enters `READY` | `Context inspection refreshed.` |
| First/refresh result enters `EMPTY` | `No processed request is available for this conversation.` |
| First result enters `CLARIFICATION` | `Context inspection loaded. Clarification is required.` |
| Refresh result enters `CLARIFICATION` | `Context inspection refreshed. Clarification is required.` |
| First result enters `CONTROLLED_FAILURE` | `Context inspection loaded. Processing ended with a controlled failure.` |
| Refresh result enters `CONTROLLED_FAILURE` | `Context inspection refreshed. Processing ended with a controlled failure.` |
| `LOAD_ERROR` | `Context inspection could not be loaded safely.` |

An `INITIAL` load is the first accepted navigation from `INACTIVE` to the
context route. Every load requested while that route remains active—including
repeated navigation, explicit refresh, terminal-result invalidation, and
conversation/project change—is a `REFRESH`. A coalesced follow-up retains
`REFRESH`; merely starting that already-announced follow-up after the prior
worker finishes does not announce loading a second time.

`CANCELLED` is a successfully loaded historical outcome and therefore uses
`READY`; its safe terminal status remains visible. A controlled pipeline
failure is persisted content and uses `CONTROLLED_FAILURE`. Failure to read or
aggregate that content uses `LOAD_ERROR`. The two must never share a DTO,
message source, or state transition.

The refresh control is enabled in `READY`, `EMPTY`, `CLARIFICATION`,
`CONTROLLED_FAILURE`, and `LOAD_ERROR`; it is disabled in `INACTIVE`, `LOADING`,
and `SHUTDOWN`. Starting any load clears the prior view immediately; stale data
is never displayed underneath loading or load error.

## Refresh, invalidation, and transition rules

| Event | Required transition/action |
|---|---|
| First accepted navigation to context | Clear data, increment generation, enter `LOADING`, start one query. |
| Repeated context navigation or Refresh | Clear data, increment generation, enter `LOADING`; start or coalesce one query. |
| Matching ready result | `READY`, `CLARIFICATION`, or `CONTROLLED_FAILURE` according to outcome. |
| Matching empty result | Enter `EMPTY`. |
| Matching load/execution failure | Enter `LOAD_ERROR`. |
| Accepted success, clarification, or controlled-failure result for current conversation | Invalidate; if context route is active, enter `LOADING` and start/coalesce one query. |
| Busy or pre-acceptance cancellation | No inspection invalidation because no run was accepted. |
| Accepted cancellation | Refresh as a processing terminal result; the target outcome becomes `CANCELLED` when latest. |
| Current conversation changes | Clear data, invalidate generation; load the new conversation if route remains active. |
| Current project changes without a new run | Invalidate and refresh if active; target and historical packet state remain unchanged. |
| Intermediate processing commit | No automatic action; manual refresh may observe it. Traces and polling are prohibited. |
| Navigate away | Enter `INACTIVE`, clear data, invalidate generation; an active worker finishes only for cleanup. |
| Late/mismatched/duplicate envelope | Ignore with no page, route, chat, or enablement mutation. |
| Shutdown | Enter `SHUTDOWN`, clear data, invalidate generation, refuse navigation/refresh. |

An inspection envelope applies only when its generation and conversation ID
match the current owned query, the route is still `CONTEXT_INSPECTION`, and
shutdown has not begun. Result handling occurs only on the GUI thread.

Navigation away and shutdown do not force-terminate or synchronously join an
inspection thread. On shutdown, no coalesced refresh starts; the GUI event loop,
root, and facade remain alive until both any TASK-0015 foreground worker and any
inspection worker have emitted terminal/finished notifications and closed their
scopes. Only then may final Qt disposal proceed.

## Accessibility contract

Qt Quick's native `Accessible` attached type is the MVP accessibility boundary.
Qt 6.8 provides names, roles, stable accessible IDs, and polite announcement
events, so TASK-0016 requires no KDE/KWin rule, desktop-specific integration, or
custom accessibility service.

The real QML page must expose these exact accessible identities:

| Element | `Accessible.id` | `Accessible.role` | Exact `Accessible.name` |
|---|---|---|---|
| Context navigation action | `contextInspectionNavigation` | `Button` | `Context inspection` |
| Page root | `contextInspectionPage` | `Pane` | `Context inspection` |
| Refresh action | `contextInspectionRefresh` | `Button` | `Refresh context inspection` |
| Page status/announcement item | `contextInspectionStatus` | `StaticText` | Exact current `inspection_status_text` |

The page contains these named `Grouping` sections when a view is loaded, in the
exact rendering and accessibility order shown:

| `Accessible.id` | Exact `Accessible.name` |
|---|---|
| `contextInspectionSectionTarget` | `Inspected request` |
| `contextInspectionSectionActiveState` | `Active state` |
| `contextInspectionSectionInterpretation` | `Interpretation` |
| `contextInspectionSectionReferences` | `References` |
| `contextInspectionSectionConstraints` | `Constraints and conflicts` |
| `contextInspectionSectionMemories` | `Retrieved memories` |
| `contextInspectionSectionConfidence` | `Confidence` |
| `contextInspectionSectionValidation` | `Validation` |
| `contextInspectionSectionFinalStatus` | `Final status` |

All nine groups are present in `READY`, `CLARIFICATION`, and
`CONTROLLED_FAILURE`, even when a field carries an availability placeholder.
They are absent in `INACTIVE`, `LOADING`, `EMPTY`, `LOAD_ERROR`, and `SHUTDOWN`.

The required scalar summaries use these exact visible field labels:

| Value | Exact visible field label |
|---|---|
| Target request/outcome/checkpoint | `Request`, `Outcome`, `Processing checkpoint` |
| Active state | `Active project`, `Active topic`, `Active task` |
| Interpretation | `Intent`, `Expected output type` |
| Confidence | `Overall confidence`, `Interpretation confidence`, `Reference confidence`, `Retrieval confidence` |
| Validation/correction | `Validation attempt`, `Validation status`, `Validation score`, `Correction count` |
| Clarification | `Clarification reason`, `Clarification question` |
| Terminal status | `Final outcome`, `Failure stage`, `Failure code`, `Status message` |

When a composite is not `AVAILABLE`, its single placeholder label is exactly
`Confidence`, `Validation`, `Clarification`, or `Final status`; its child scalar
rows are absent. When available, the composite placeholder is absent and the
listed child labels are used.

Every visible collection container uses role `List` and these exact identities:

| Collection | `Accessible.id` | Exact `Accessible.name` |
|---|---|---|
| Qualifier evidence | `contextInspectionQualifiers` | `Qualifier evidence` |
| References | `contextInspectionReferences` | `References` |
| Evidence for reference `<mention_number>` | `contextInspectionReferenceEvidence-<mention_number>` | `Evidence for reference <mention_number>` |
| Constraints | `contextInspectionConstraints` | `Constraints` |
| Conflicts | `contextInspectionConflicts` | `Conflicts` |
| Rules in conflict `<ordinal>` | `contextInspectionConflictRules-<ordinal>` | `Rules in conflict <ordinal>` |
| Retrieved memories | `contextInspectionMemories` | `Retrieved memories` |
| Validation violations | `contextInspectionValidationViolations` | `Validation violations` |
| Validation evidence | `contextInspectionValidationEvidence` | `Validation evidence` |

The five top-level collection containers (qualifiers, references, constraints,
conflicts, and memories) are present in every loaded-view state. A non-available
collection has no `ListItem` and exposes its exact placeholder as a labeled
`StaticText`. A nested reference/conflict/validation list exists only when its
owning parent record is available; an empty validation-violation list likewise
contains no item and exposes `None recorded.`.

Each item uses role `ListItem` and this exact primary accessible-name template:

- qualifier: `Qualifier <ordinal>: <kind label>, <matched_text>`;
- reference: `Reference <mention_number>: <surface_text>, <status label>`;
- reference evidence: `Reference <mention_number> evidence <rank>: <rank reason label>, score <two-decimal score>`;
- constraint: `Constraint <ordinal>: <type label>, <resolution label>`;
- conflict: `Conflict <ordinal>: <rule count> rules`;
- conflict rule: `Conflict <conflict ordinal> rule <constraint ordinal>: <type label>, <normalized_rule>`;
- memory: `Retrieved memory <rank>: score <two-decimal score>`;
- validation violation: `Validation violation <ordinal>: <code label>`; and
- validation evidence: `Validation evidence <ordinal>: <check label>, <outcome label>`.

Every scalar visible value uses role `StaticText` and exact name
`<visible field label>: <display_text>`. Availability placeholders use the same
template and their exact contracted availability text. Decorative duplicate
labels are `Accessible.ignored=true` so names are not announced twice.

The facade exposes read-only `inspection_announcement_text` and
`inspection_announcement_revision`, initially empty string and `0`. On each
accepted initial/refresh load request and each matching result transition below,
it sets the exact text and increments the revision by exactly one on the GUI
thread. No other event changes either property. The QML status item issues
exactly one native polite `Accessible.announce` call for each new revision:

| Transition | Exact announcement text |
|---|---|
| Accept an initial/refresh load request and enter/re-enter `LOADING` | `Loading context inspection.` |
| First result enters `READY` | `Context inspection loaded.` |
| Refresh result enters `READY` | `Context inspection refreshed.` |
| First/refresh result enters `EMPTY` | `No processed request is available for this conversation.` |
| First result enters `CLARIFICATION` | `Context inspection loaded. Clarification is required.` |
| Refresh result enters `CLARIFICATION` | `Context inspection refreshed. Clarification is required.` |
| First result enters `CONTROLLED_FAILURE` | `Context inspection loaded. Processing ended with a controlled failure.` |
| Refresh result enters `CONTROLLED_FAILURE` | `Context inspection refreshed. Processing ended with a controlled failure.` |
| Enter `LOAD_ERROR` | `Context inspection could not be loaded safely.` |

`INACTIVE` and `SHUTDOWN` produce no announcement. Repeated equal text still
announces because the revision changes; QML must not infer announcements from
text equality or use timers.

Offscreen tests query the Qt accessibility interfaces for every contracted ID,
name, role, and value. They install a recording Qt accessibility update seam and
assert the emitted announcement event's exact text and polite priority. A live
screen reader, AT-SPI daemon, KDE service, window-manager rule, or platform-
specific accessibility process is not a test prerequisite.

## Deterministic verification invariants

TASK-0016 verification must demonstrate independently that:

1. latest-target selection uses message sequence and empty selection is exact;
2. one rich successful run displays every field, qualifier evidence, reference
   evidence, retrieval score/reasons, all confidence values, latest validation,
   and correction count;
3. each checkpoint and clarification-reason row in the availability matrices
   produces the exact availability and placeholder text;
4. hard-conflict clarification groups only persisted conflict membership;
5. controlled failure, cancellation, clarification, and inspection load failure
   use their distinct states and safe projections;
6. unique sentinels placed in rendered prompts, invalid candidate responses,
   provider metadata, raw exceptions, failure details, and prohibited validation
   evidence appear nowhere in the application result, facade properties, list
   models, QML text, accessibility names, or announcements;
7. QML invokes only the facade and receives no repository/application/domain/
   persistence object or raw DTO algebra;
8. the inspection connection is created, all repository reads occur, and the
   connection closes on the same inspection-worker thread, distinct from the
   GUI thread;
9. held inspection reads do not prevent GUI event-loop sentinels, navigation,
   foreground cancellation, or shutdown actions from being processed;
10. terminal delivery is queued, GUI mutation occurs only on the GUI thread,
    and stale/mismatched/late envelopes change nothing;
11. foreground processing and one inspection read can coexist only through
    separate owned scopes/connections and never create a second processing run,
    queue, or shared SQLite object;
12. every accessibility ID/name/role/value and announcement matches this
    contract; and
13. source-checkout and installed-package QML loading, TASK-0015 shell
    responsiveness, startup validation, and the complete then-current non-live
    suite remain green.

## Prohibited behavior

Direct QML-to-SQL, QML-to-repository, QML-to-context-engine,
QML-to-model-gateway, QML parsing of packet/persistence JSON, presentation
joining of raw inspection/validation outputs, current-state substitution for
missing historical evidence, prompt/candidate exposure, trace-driven refresh,
polling, refresh timers, an HTTP API, a persistent/background worker, a work
queue, forced thread termination, cross-thread SQLite use, automatic memory
mutation, file context, embeddings, vector search, provider configuration, and
future-page placeholders are prohibited.
