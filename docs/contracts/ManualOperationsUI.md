# Manual Operations UI Contract

## 1. Purpose and ownership

This document is the normative detailed TASK-0017 presentation/application-
boundary contract. It refines FR-003, FR-014 through FR-018, AT-014, and the
later-page extension points in `PresentationShell.md` and
`ContextInspection.md`. It adds only manual-memory, project, full validation-
history, and permitted settings/configuration presentation to the existing
shell.

The entry-point-owned, GUI-thread `ShellFacade` remains the sole public QObject
and presentation-state owner exposed to QML. TASK-0017 adds one private manual-
operations execution role to that facade; it is not a second public controller
or state store. Presentation owns navigation, confirmation, editor, and page
state. Application use cases own every query, transaction, mutation, lineage
check, safe projection, deterministic label, ordering decision, and trace call.
QML owns none of those decisions.

This contract closes G17-01, G17-02, G17-M01, G17-M02, G17-M03, G17-P01,
G17-V01, G17-S01, G17-S02, G17-S03, and G17-A01 in specification terms. It does
not make TASK-0017 implemented: implementation remains ordered behind completed,
green TASK-0016 and its prerequisite chain.

## 2. Explicit MVP exclusions

TASK-0017 does not add conversation creation/selection/history, project
creation, restoration of a deleted memory, automatic memory extraction,
creation, merging, rewriting, cleanup, or expiry deletion. It does not add a
merge button, candidate-response viewer, prompt viewer, raw validation viewer,
YAML editor, provider/model selector, endpoint editor, credential/proxy/cloud
setting, file indexing, attachment ingestion, tool/action execution, model
routing, streaming, or a future-page placeholder.

It introduces no API server, queue, poller, executor pool, persistent worker,
daemon, timer-driven refresh, detached task, autonomous subsystem, or forced
thread termination. A finite operation directly caused by navigation or an
explicit user action is not a background subsystem.

Theme support adds no KDE, Breeze, Kirigami, KWin, portal, desktop-service, or
screen-reader runtime dependency. KDE/KWin configuration remains an optional
operator concern and is neither application behavior nor an acceptance-test
prerequisite.

## 3. Route and navigation contract

After TASK-0017 the complete route set is exactly:

```text
Route = CHAT | CONTEXT_INSPECTION | MEMORY | PROJECTS |
        VALIDATION_HISTORY | SETTINGS
```

`CHAT` remains the initial route. The navigation order is Chat, Context
inspection when visible, Memory, Projects, Validation history, Settings. Each
new navigation item is registered only with its implemented page and application
boundary; no disabled or empty placeholder is permitted.

The existing facade gains only these QML-callable actions:

```text
navigate_to_memory() -> boolean
refresh_memories() -> boolean
set_memory_filter(filter: ACTIVE | DELETED) -> boolean
select_memory(row: uint) -> boolean
begin_create_memory() -> boolean
begin_edit_memory() -> boolean
submit_memory_editor(form values) -> boolean
return_from_duplicate_guidance() -> boolean
proceed_with_duplicate_create() -> boolean
request_memory_soft_delete() -> boolean
cancel_memory_soft_delete() -> boolean
confirm_memory_soft_delete(source_description: string) -> boolean

navigate_to_projects() -> boolean
refresh_projects() -> boolean
select_active_project(row: uint) -> boolean
clear_project_selection() -> boolean
request_project_archive(row: uint) -> boolean
cancel_project_archive() -> boolean
confirm_project_archive() -> boolean

navigate_to_validation_history() -> boolean
refresh_validation_history() -> boolean

navigate_to_settings() -> boolean
refresh_settings() -> boolean
set_pending_theme(value: SYSTEM | LIGHT | DARK) -> boolean
set_pending_context_panel_visible(value: boolean) -> boolean
save_settings() -> boolean
```

The existing `navigate_to_chat()`, `navigate_to_context_inspection()`, and
`refresh_context_inspection()` actions retain their TASK-0016 meanings, subject
only to the context-panel preference below. Every route value is read-only from
QML.

A navigation action returns `false` and changes nothing before the shell has a
current conversation, after shutdown starts, or when its stated local guard
fails. Selecting a TASK-0017 route returns `true`, clears any editor or
confirmation owned by the previous route, and starts or coalesces that route's
required load. Invoking navigation for the already-active TASK-0017 route is an
explicit refresh. A refresh action is accepted only on its own route. Row
actions include the facade's current dataset generation implicitly; a stale or
out-of-range row returns `false` without starting work.

`ui.context_panel_visible=false` hides only the Context inspection navigation
item. The `CONTEXT_INSPECTION` enum remains registered, but navigation to it is
refused. Applying `false` while that route is active moves to `CHAT`, clears the
inspection page through its existing navigation-away rule, and emits no
processing or manual-operation action. Applying `true` makes the item visible
without navigating automatically.

## 4. Shared page-state conventions

The four exact, orthogonal page-state algebras are:

```text
MemoryPageState =
    INACTIVE | LOADING | READY | EMPTY | EDITING |
    DUPLICATE_GUIDANCE | DELETE_CONFIRMATION | SAVING |
    LOAD_ERROR | MUTATION_ERROR | SHUTDOWN

ProjectsPageState =
    INACTIVE | LOADING | READY | EMPTY | ARCHIVE_CONFIRMATION |
    SAVING | LOAD_ERROR | MUTATION_ERROR | SHUTDOWN

ValidationHistoryPageState =
    INACTIVE | LOADING | READY | EMPTY | LOAD_ERROR | SHUTDOWN

SettingsPageState =
    INACTIVE | LOADING | READY | SAVING | VALIDATION_ERROR |
    LOAD_ERROR | MUTATION_ERROR | SHUTDOWN
```

These states do not change `ShellState`, chat output, composer text, foreground
progress, or cancellation ownership. A page is `INACTIVE` whenever its route is
not selected. An accepted first load or refresh clears its prior dataset and
enters `LOADING`. A successful memory/project query is `READY` when its selected
collection is non-empty and `EMPTY` under the exact rules below. A validation
query is `EMPTY` only when no accepted run exists; a run with no completed
validation attempt is a valid `READY` view. A successful settings query is
always `READY`.

`EDITING` retains one facade-owned create/edit form. Inline field errors do not
create another state; a locally or application-rejected form remains `EDITING`
and exposes the ordered field errors. `VALIDATION_ERROR` is reserved for a
settings save rejected before persistence and retains the pending controls.
Confirmation and duplicate-guidance states retain the last safe dataset but
disable unrelated page actions. `SAVING` retains the safe dataset/form only for
visual continuity and disables every page mutation until the worker finishes.

`MUTATION_ERROR` retains only the last safe dataset and the exact safe operation
message. An edit/create form may also be retained for an ordinary retryable
failure, but a stale-memory or stale-project result discards the stale editor or
pending selection and requires an explicit refresh. There is no automatic
retry. `LOAD_ERROR` exposes no prior or partial dataset.

The closed load/empty messages are:

| Page/result | Exact safe message |
|---|---|
| Memory empty | `No memories match the selected filter.` |
| Memory load error | `Memories could not be loaded safely.` |
| Projects empty | `No projects are available.` |
| Projects load error | `Projects could not be loaded safely.` |
| Validation empty | `No validation history is available for this conversation.` |
| Validation load error | `Validation history could not be loaded safely.` |
| Settings load error | `Settings could not be loaded safely.` |

Navigation away clears the page dataset, editor, validation errors, duplicate
guidance, and unaccepted confirmation, increments its generation, and enters
`INACTIVE`. It does not cancel or roll back an already accepted mutation. A
matching completed mutation may still update global facade state and mark pages
dirty, but it cannot reopen the old route or publish off-route page content.

## 5. Shared query and mutation execution model

`ManualOperationsController` is a private execution role of `ShellFacade`. At
most one TASK-0017 worker and one TASK-0017 application scope exist at a time
across all four pages. Every accepted load, refresh, duplicate check/create,
memory mutation, project mutation, or settings save creates one finite worker,
invokes exactly one top-level application use case, closes its scope, queues one
immutable terminal envelope, and terminates.

While that worker is active:

- a repeated or new read request invalidates the old page generation and
  replaces one optional `pending_read_route` with the currently active
  TASK-0017 route; repeated requests collapse to that single latest route;
- navigating to `CHAT` or `CONTEXT_INSPECTION` clears `pending_read_route`;
- a second mutation, confirmation accept, or editor submit returns `false` and
  creates no request, token, worker, queue entry, or state transition; and
- navigation and the GUI event loop remain responsive.

`pending_read_route` is one replaceable coalescing value, not a FIFO/LIFO work
queue. After the active worker's finished notification, at most one fresh read
starts when that route is still active, dirty, and non-shutdown. Mutations are
never queued or coalesced. A duplicate-guidance `Proceed anyway` action is a new
explicit mutation after the prior guidance worker has finished.

One manual-operations worker may coexist with the TASK-0015 foreground worker
and the TASK-0016 inspection worker. Thus the process can own at most one worker
of each of those three distinct kinds at once. They share no application scope,
SQLite connection, repository, transaction, worker object, result envelope, or
processing-run admission slot. SQLite waiting/failure occurs off the GUI thread
and maps to the safe result for the owning operation.

Repeated user actions are presentation suppression, not synthetic application
failures. No suppressed action changes a page message or clears a form.

## 6. Thread, scope, and transaction ownership

TASK-0017 additively extends the shell factory with:

```text
ShellApplicationScopeFactory {
  open_startup_scope() -> StartupApplicationScope
  open_foreground_scope() -> ForegroundApplicationScope
  open_inspection_scope() -> InspectionApplicationScope
  open_manual_operations_scope() -> ManualOperationsApplicationScope
}

ManualOperationsApplicationScope {
  inspect_memories: InspectMemories
  create_memory_with_guidance: CreateMemoryWithGuidance
  edit_memory_for_presentation: EditMemoryForPresentation
  soft_delete_memory_for_presentation: SoftDeleteMemoryForPresentation
  inspect_projects: InspectProjects
  select_project_for_presentation: SelectProjectForPresentation
  archive_project_for_presentation: ArchiveProjectForPresentation
  inspect_validation_history: InspectValidationHistory
  inspect_manual_settings: InspectManualSettings
  update_manual_settings: UpdateManualSettings
  close()
}
```

The safe presentation adapters above compose the existing canonical
`MemoryManager`, project, validation, settings, and repository ports; they do not
duplicate their domain rules. Each `open_manual_operations_scope()` call creates
all collaborators and exactly one SQLite connection on the calling worker
thread. Every repository operation and transaction for that execution uses that
connection. The scope closes it on the same worker thread on success, returned
failure, unexpected defect, navigation-away completion, and shutdown.

Every TASK-0017 route load and duplicate-only result uses one read-only SQLite
snapshot. A top-level mutating application adapter owns one connection-local
outer transaction; any existing use-case transaction joins it under
`Persistence.md`. Validation, duplicate comparison needed by that call, version
recheck, canonical mutation, source/revision persistence, and any settings
writes happen inside that one transaction. Trace emission and GUI application
happen only after its successful outer commit.

No SQLite connection, transaction, cursor, row, repository, mutable domain
aggregate, QObject, exception, raw configuration object, or worker-affine value
crosses the worker boundary. The worker closes the scope before emitting:

```text
ManualOperationsTerminalEnvelope {
  operation_id: facade-local immutable identifier,
  generation: facade-local monotonically increasing uint,
  route: MEMORY | PROJECTS | VALIDATION_HISTORY | SETTINGS,
  conversation_id: uuid,
  operation_kind: closed query/mutation kind,
  result: recursively immutable safe application result |
          ManualOperationsExecutionFailureView
}

ManualOperationsExecutionFailureView {
  result_kind: "MANUAL_OPERATIONS_EXECUTION_FAILURE",
  code: MANUAL_OPERATION_EXECUTION_FAILED,
  safe_message: page-specific load or mutation message from this contract
}
```

Terminal and finished connections are explicitly queued. The facade handles
both only on the GUI thread. A read envelope applies once only when operation,
generation, route, and conversation match current ownership. A mutation
envelope applies its global current-conversation/project or preference effect
only when the operation ID and target match; page content additionally requires
the route/generation match. Unknown, duplicate, stale, wrong-route, wrong-
conversation, already-consumed, disposed, or post-shutdown content is ignored.
The finished notification may release ownership and start one coalesced read;
it cannot select a result state.

## 7. Safe result and redaction rules

All TASK-0017 application requests, results, views, field errors, and nested
collections are frozen, slotted, and recursively immutable; collections are
tuples. The application owns canonical labels, decimal/timestamp formatting,
availability text, redaction, and safe errors. QML receives primitive
properties and presentation list models only and does not branch over raw
application/domain DTOs or parse JSON.

QML row actions use a zero-based row plus the facade-owned dataset generation.
The facade privately maps that pair to the authoritative UUID. UUIDs, state
versions, revision IDs, source IDs, request/response/validation IDs, database
keys, and configuration paths never enter QML, visible text, accessible names,
or announcements. Safe display identities are `Memory <N>`, `Project <N>`,
`Request <N>`, `Source <N>`, `Revision <N>`, `Attempt <N>`, and `Correction <N>`
using the one-based ordinals defined below.

Canonical enum labels and scores use the exact `CanonicalLabelView` and
`InspectionScoreView` rules in `ContextInspection.md`. UTC timestamps are
application-formatted as `YYYY-MM-DD HH:MM:SS UTC`, with no locale conversion.
An absent optional timestamp has its field-specific text below. QML never
formats an enum, decimal, timestamp, boolean, or identifier.

Exact memory content, memory revision snapshots, memory source descriptions,
project names/descriptions, safe validation messages/evidence, and the safe
configuration allowlist below are explicitly permitted only on their owning
page. Every other prompt, model candidate/response, provider value, normalized
candidate input, validation match position/sub-string, correction prompt,
unsafe failure detail, exception/traceback, SQL, absolute path, endpoint/model
identity, environment content, secret, credential, API key, header, cookie, raw
configuration value/dump, trace payload, or open DTO is prohibited at the
application result boundary. Hiding a field in QML is not redaction.

## 8. Memory inspection data model

`InspectMemories` inspects all locally stored memories for exactly one stored-
status filter. The initial/default filter is `ACTIVE`. `ACTIVE` includes stored
`ACTIVE` records whose computed effective status is either `ACTIVE` or
`EXPIRED`; `DELETED` includes only stored `DELETED` records, whose effective
status is also `DELETED`. Expiry never changes the stored filter.

The application reads the clock exactly once per query and uses that one
`evaluated_at` for every item. It orders records by `updated_at` descending and
then canonical memory UUID text ascending as a hidden tie-breaker. Source rows
order by `created_at` ascending and hidden source UUID ascending. Revisions
order by `revision_number` ascending; an absent, repeated, or non-consecutive
revision is a whole-query load failure.

```text
InspectMemoriesRequest {
  stored_status: ACTIVE | DELETED,
  selected_memory_id: uuid or null       # facade-private, never QML
}

InspectMemoriesResult =
    MemoryInspectionReadyResult
  | MemoryInspectionEmptyResult
  | MemoryInspectionLoadFailureResult

MemoryInspectionReadyResult {
  result_kind: "MEMORY_INSPECTION_READY",
  view: MemoryInspectionCollectionView
}

MemoryInspectionEmptyResult {
  result_kind: "MEMORY_INSPECTION_EMPTY",
  stored_status: ACTIVE | DELETED,
  evaluated_at_text: application-formatted UTC,
  safe_message: "No memories match the selected filter."
}

MemoryInspectionLoadFailureResult {
  result_kind: "MEMORY_INSPECTION_LOAD_FAILURE",
  code: MEMORY_INSPECTION_LOAD_FAILED,
  safe_message: "Memories could not be loaded safely."
}

MemoryInspectionCollectionView {
  stored_status_filter: ACTIVE | DELETED,
  evaluated_at_text: application-formatted UTC,
  items: tuple[MemoryInspectionItemView],
  selected_ordinal: uint or null
}

MemoryInspectionItemView {
  ordinal: uint starting at 1,
  display_identity: "Memory <ordinal>",
  summary: MemorySummaryView,
  details: MemoryDetailsView
}

MemorySummaryView {
  content: exact stored content,
  type: CanonicalLabelView,
  scope: CanonicalLabelView,
  owner: MemoryOwnerView,
  stored_status: CanonicalLabelView,
  effective_status: CanonicalLabelView,
  updated_at_text: application-formatted UTC
}

MemoryOwnerView {
  kind: CONVERSATION | PROJECT | GLOBAL,
  display_text: exact safe owner text,
  project_status: CanonicalLabelView or null
}

MemoryDetailsView {
  content: exact stored content,
  keywords: tuple[exact strings],
  topic_terms: tuple[exact strings],
  importance: InspectionScoreView,
  confidence: InspectionScoreView,
  expires_at_text: application-formatted UTC | "Does not expire.",
  created_at_text: application-formatted UTC,
  updated_at_text: application-formatted UTC,
  deleted_at_text: application-formatted UTC | "Not deleted.",
  stored_status: CanonicalLabelView,
  effective_status: CanonicalLabelView,
  evaluated_at_text: application-formatted UTC,
  sources: tuple[MemorySourceView],
  revisions: tuple[MemoryRevisionView]
}

MemorySourceView {
  ordinal: uint starting at 1,
  display_identity: "Source <ordinal>",
  kind: CanonicalLabelView,
  description: exact persisted description,
  source_message: "Message <sequence>" | "Not applicable.",
  created_at_text: application-formatted UTC
}

MemoryRevisionView {
  revision_number: uint starting at 1,
  display_identity: "Revision <revision_number>",
  operation: CanonicalLabelView,
  source_ordinal: uint starting at 1,
  content_snapshot: exact persisted snapshot,
  keywords: tuple[exact strings],
  topic_terms: tuple[exact strings],
  importance: InspectionScoreView,
  confidence: InspectionScoreView,
  expires_at_text: application-formatted UTC | "Does not expire.",
  stored_status: CanonicalLabelView,
  updated_at_text: application-formatted UTC,
  deleted_at_text: application-formatted UTC | "Not deleted.",
  performed_by: CanonicalLabelView,
  performed_at_text: application-formatted UTC
}
```

A conversation owner displays `Conversation: <title>` or exactly
`Conversation: Untitled conversation` for a null title. A project owner displays
`Project: <name>` and carries the current project status so an archived owner is
not presented as selectable. Global displays `All conversations and projects`.
A missing/mismatched owner or source-message row is a load failure, not a UUID
or guessed label.

The source UUID retained in `memory-revision-v1` is resolved inside the
application snapshot to `source_ordinal`; it never crosses the safe boundary.
The revision view exposes the reconstructable safe snapshot fields but omits
the metadata schema string and all owner/source/memory/revision UUIDs. Empty
keyword/topic collections display `None recorded.` without inventing an item.

The first load has no implicit selection. An explicit row selection is local
and reveals the already-loaded details without another worker. A refresh
preserves selection only when the facade-private memory UUID remains in the
filtered result; otherwise selection becomes null. `EMPTY` has no selection or
details.

## 9. Memory mutation request and result models

A create form may edit memory type, scope, content, keywords, topic terms,
importance, confidence, expiry, and a non-blank source description. Scope owns
the target deterministically: `CONVERSATION` uses the shell's current
conversation and null project; `PROJECT` uses that conversation's currently
associated `ACTIVE` project and null conversation; `GLOBAL` uses both owner IDs
null. Project scope is unavailable when the association is null or archived.

An edit form may replace only content, keywords, topic terms, importance,
confidence, expiry, and source description. Memory ID, creation time, type,
scope, and both owner IDs are immutable. Content and each keyword/topic entry
are preserved exactly, including empty strings and whitespace, because the
canonical domain permits them. Presentation performs no trimming or token
normalization. Source description must contain at least one non-whitespace code
point but is otherwise retained exactly. Importance/confidence must be finite
base-10 values in `[0,1]`; expiry is null or a valid UTC instant and may be in
the past, in which case the new memory is immediately effectively `EXPIRED`.
Edit and soft-delete controls are available for every stored-`ACTIVE` selection,
including an effectively `EXPIRED` one; stored-`DELETED` selections are
inspection-only.

```text
CreateMemoryPresentationRequest {
  conversation_id: uuid,
  memory_type: MemoryType,
  scope: MemoryScope,
  content: string,
  keywords: tuple[string],
  topic_terms: tuple[string],
  importance: canonical decimal,
  confidence: canonical decimal,
  expires_at: UTC instant or null,
  source_description: string,
  duplicate_decision: CHECK | PROCEED
}

EditMemoryPresentationRequest {
  memory_id: uuid,
  expected_revision_number: uint,
  content: string,
  keywords: tuple[string],
  topic_terms: tuple[string],
  importance: canonical decimal,
  confidence: canonical decimal,
  expires_at: UTC instant or null,
  source_description: string
}

SoftDeleteMemoryPresentationRequest {
  memory_id: uuid,
  expected_revision_number: uint,
  source_description: string
}
```

The selected snapshot's greatest revision number is the expected revision for
edit/delete. Inside the mutation transaction the application reloads the
aggregate and compares it before writing. A mismatch writes nothing, emits no
trace, returns `MemoryMutationStaleResult`, discards the stale editor or
confirmation, and requires explicit refresh. No automatic retry is allowed.
This guard uses existing revision rows and requires no schema version column.

```text
MemoryMutationResult =
    MemoryMutationSucceededResult
  | MemoryDuplicateGuidanceResult
  | MemoryMutationValidationFailureResult
  | MemoryMutationStaleResult
  | MemoryMutationRejectedResult
  | MemoryMutationFailureResult

MemoryMutationSucceededResult {
  result_kind: "MEMORY_MUTATION_SUCCEEDED",
  operation: CREATE | EDIT | SOFT_DELETE,
  affected: MemoryInspectionItemView,
  revision_number: uint,
  safe_message: "Memory created." | "Memory updated." |
                "Memory soft-deleted."
}

MemoryMutationValidationFailureResult {
  result_kind: "MEMORY_MUTATION_VALIDATION_FAILURE",
  code: MEMORY_INPUT_INVALID,
  errors: tuple[MemoryFieldError] in form-field order,
  safe_message: "Review the highlighted memory fields."
}

MemoryFieldError {
  field: TYPE | SCOPE | OWNER | IMPORTANCE | CONFIDENCE |
         EXPIRY | SOURCE_DESCRIPTION,
  safe_message: exact field message below
}

MemoryMutationStaleResult {
  result_kind: "MEMORY_MUTATION_STALE",
  code: MEMORY_REVISION_CONFLICT,
  safe_message: "This memory changed. Review the latest version before trying again."
}

MemoryMutationRejectedResult {
  result_kind: "MEMORY_MUTATION_REJECTED",
  code: MEMORY_NOT_FOUND | MEMORY_DELETED | MEMORY_SCOPE_UNAVAILABLE,
  safe_message: "The memory is no longer available." |
                "Deleted memories cannot be changed or deleted again." |
                "An active project is required for project memory."
}

MemoryMutationFailureResult {
  result_kind: "MEMORY_MUTATION_FAILURE",
  code: MEMORY_MUTATION_FAILED,
  safe_message: "Memory could not be created safely." |
                "Memory could not be updated safely." |
                "Memory could not be soft-deleted safely."
}
```

The field-error messages are exact: Type — `Choose a valid memory type.`;
Scope — `Choose a valid memory scope.`; Owner — `An active project is required
for project memory.`; Importance — `Importance must be between 0 and 1.`;
Confidence — `Confidence must be between 0 and 1.`; Expiry — `Expiry must be a
valid UTC date and time or empty.`; Source description — `Describe why this
memory is being changed.` Duplicate errors for one field collapse to the first
message in this field order.

A form validation result returns to `EDITING`; it starts no persistence and
emits no trace. After create success the page selects filter `ACTIVE` and the new
memory. After edit success it remains on `ACTIVE` and selects the updated
memory. After delete success it selects filter `DELETED` and the retained
tombstone. Each success replaces the page from the returned post-commit item
and marks Memory dirty for one full refresh; if a coalesced refresh is already
required, that refresh is the authority. A failure never claims a mutation.

For create/edit/delete, application integration owns the canonical trace call.
Only after the successful outer commit it emits respectively `memory_created`,
`memory_edited`, or `memory_soft_deleted`, with stage `MEMORY`, the affected
non-null internal memory/revision IDs, null processing/model correlation and
`error_type`, and the immutable validated bootstrap configuration fingerprint.
QML, the facade, repositories, and `MemoryManager` do not emit that event.
Trace emission is best-effort and outside the transaction; a trace-adapter
failure cannot roll back the mutation, change its success result, retry it, or
fall back to content logging.

## 10. Memory confirmation semantics

Soft delete is available only for a selected stored-`ACTIVE` memory, including
an effectively expired one. Requesting it starts no worker and enters
`DELETE_CONFIRMATION` with this exact dialog:

| Element | Exact text |
|---|---|
| Title | `Soft-delete memory?` |
| Body | `This memory will remain available in Deleted with its provenance and revision history. It cannot be edited, deleted again, or restored.` |
| Safe/default action | `Cancel` |
| Destructive action | `Soft-delete` |

`Cancel` has initial focus and Escape semantics. Cancelling returns to `READY`,
preserves selection and data, and performs no use-case call, write, source,
revision, trace, invalidation, or announcement of success. Accept is enabled
only with a valid non-blank source description; the first accepted action
captures the selected UUID/revision privately, enters `SAVING`, and starts
exactly one mutation. Repeated accept is suppressed.

Deleted records expose no edit/delete/restore control. A crafted attempt is
rejected by both facade and application. There is no hard-delete or restore
confirmation in the MVP.

## 11. Memory provenance, revision, and expiry semantics

Every successful manual create/edit/soft-delete continues to write exactly one
source and one consecutive immutable `memory-revision-v1` revision in the same
transaction under `DomainAndDecisionRules.md`. The memory page always exposes
the full retained source/revision tuples for the selected record. A soft delete
preserves content, type, scope, owners, sources, prior revisions, and current
snapshot, then adds only the canonical tombstone source/revision and timestamps.

`evaluated_at` is query evidence, not persistence. An `ACTIVE` stored record
with `expires_at <= evaluated_at` displays stored status `Active` and effective
status `Expired`; it remains under the Active filter but cannot be retrieved by
the processing pipeline. Loading or displaying expiry writes no row, creates no
source/revision/trace, and never moves it to Deleted.

No page action infers or fabricates provenance. Missing provenance, invalid
revision metadata, a revision/source mismatch, or a lifecycle-inconsistent
stored aggregate fails the complete query safely.

## 12. Duplicate-guidance semantics

Duplicate guidance is evaluated only for creation, after form validation and
before any create write. Editing does not invoke it. The application applies
the exact retrieval content normalization in `DomainAndDecisionRules.md`:
Unicode NFC, case folding, deletion of Unicode punctuation, Unicode-whitespace
splitting, empty-token removal, and one-ASCII-space joining. Guidance equality
is equality of the resulting normalized content, including the empty string.

Candidates are all stored-`ACTIVE` memories with the exact same scope and
canonical owner identity as the proposed record. For `CONVERSATION` that
identity is the matching non-null `conversation_id` and any non-owning project
ID is ignored; for `PROJECT` it is the matching non-null `project_id` and any
non-owning conversation ID is ignored; `GLOBAL` is the singleton null-owner
identity. They include effectively
`ACTIVE` and `EXPIRED` records and exclude stored `DELETED` records and every
other scope/owner. They order by `updated_at` descending and hidden UUID
ascending. This is creation-time advisory comparison; it is distinct from the
processing retriever's later candidate eligibility, scoring, thresholding, and
retrieval-only duplicate collapse.

```text
MemoryDuplicateGuidanceResult {
  result_kind: "MEMORY_DUPLICATE_GUIDANCE",
  safe_message: "Possible duplicate memories were found.",
  candidates: tuple[MemoryDuplicateCandidateView]
}

MemoryDuplicateCandidateView {
  ordinal: uint starting at 1,
  display_identity: "Memory <ordinal>",
  content: exact stored content,
  scope: CanonicalLabelView,
  owner_display_text: exact safe owner text,
  effective_status: CanonicalLabelView,
  updated_at_text: application-formatted UTC
}
```

With `duplicate_decision=CHECK`, zero candidates creates normally in that same
top-level call. One or more candidates returns the guidance result with no
write, ID allocation, source, revision, trace, or mutation-success message and
enters `DUPLICATE_GUIDANCE`. The exact actions are `Return to memory editor`
(default/focused) and `Create separate memory`. There is no merge/replace/delete
action.

Returning restores the unchanged editor and performs no application call.
Proceeding sends the same exact form with `duplicate_decision=PROCEED`; the
application recomputes the candidate set inside the create transaction for
deterministic evidence but creates one independent new memory regardless of the
current candidate count. It does not merge, rewrite, link, replace, delete, or
otherwise mutate any candidate. The explicit proceed action is the sole
authority to bypass guidance.

## 13. Project query, selection, and archive models

`InspectProjects` reads the shell's current conversation, its required current
state, and all projects in one snapshot. Active and archived lists are both
visible. Each list orders by `created_at` ascending and hidden canonical project
UUID ascending, matching the repository contract.

```text
InspectProjectsRequest {
  conversation_id: uuid
}

InspectProjectsResult =
    ProjectInspectionReadyResult
  | ProjectInspectionEmptyResult
  | ProjectInspectionLoadFailureResult

ProjectInspectionReadyResult {
  result_kind: "PROJECT_INSPECTION_READY",
  view: ProjectInspectionView
}

ProjectInspectionEmptyResult {
  result_kind: "PROJECT_INSPECTION_EMPTY",
  safe_message: "No projects are available."
}

ProjectInspectionLoadFailureResult {
  result_kind: "PROJECT_INSPECTION_LOAD_FAILURE",
  code: PROJECT_INSPECTION_LOAD_FAILED,
  safe_message: "Projects could not be loaded safely."
}

ProjectInspectionView {
  active_projects: tuple[ProjectItemView],
  archived_projects: tuple[ProjectItemView],
  current_association: ProjectAssociationView | null,
  conversation_state_version: uint        # facade-private
}

ProjectItemView {
  ordinal: uint starting at 1 within its list,
  display_identity: "Project <ordinal>",
  name: exact persisted name,
  description: exact persisted description | "No description.",
  status: CanonicalLabelView,
  created_at_text: application-formatted UTC,
  updated_at_text: application-formatted UTC,
  is_current_association: boolean,
  archive_eligible: boolean,
  archive_ineligible_text: empty |
      "This project cannot be archived while it has an active request."
}

ProjectAssociationView {
  name: exact persisted name,
  status: CanonicalLabelView,
  display_text: exact name | "<name> — Archived (current association)"
}
```

Both empty lists and a null association produce `ProjectInspectionEmptyResult`
with `No projects are available.` Otherwise the page is `READY`. A current
association must resolve to exactly one active or archived row. Missing
conversation/state/project lineage is a load failure, not a cleared selection.

Active selection uses the privately held project UUID and the query's state
version with the existing `SelectProject` use case. Archived rows have no select
action. A crafted archived selection returns `PROJECT_MUTATION_REJECTED` and
`Archived projects cannot be selected.` with no write. Clearing supplies null.
Select and clear apply immediately after acceptance and have no confirmation;
only archive uses the destructive confirmation below.

Selecting the already-associated active project, or clearing an already-null
association, is a facade-local no-op: it returns `false`, starts no worker,
does not increment state, and triggers no invalidation. An actual selection or
clear increments the conversation state version exactly once in its canonical
transaction. The application preserves the existing state-transition contract:
an initial version mismatch/conflict reloads and retries the same deterministic
selection once. If the reloaded association already equals the requested value,
the result is unchanged and writes/increments nothing. A second conflict returns
the stale result below; presentation performs no additional retry.

```text
ProjectMutationResult =
    ProjectSelectionChangedResult
  | ProjectSelectionUnchangedResult
  | ProjectArchiveSucceededResult
  | ProjectArchiveBlockedResult
  | ProjectMutationStaleResult
  | ProjectMutationRejectedResult
  | ProjectMutationFailureResult

ProjectSelectionChangedResult {
  result_kind: "PROJECT_SELECTION_CHANGED",
  current_association: ProjectAssociationView or null,
  conversation_state_version: uint,       # facade-private
  safe_message: "Project selection changed."
}

ProjectSelectionUnchangedResult {
  result_kind: "PROJECT_SELECTION_UNCHANGED",
  current_association: ProjectAssociationView or null,
  conversation_state_version: uint,       # facade-private
  safe_message: "Project selection is unchanged."
}

ProjectArchiveSucceededResult {
  result_kind: "PROJECT_ARCHIVE_SUCCEEDED",
  archived_project: ProjectItemView,
  safe_message: "Project archived."
}

ProjectArchiveBlockedResult {
  result_kind: "PROJECT_ARCHIVE_BLOCKED",
  code: PROJECT_HAS_ACTIVE_REQUEST,
  safe_message: "This project cannot be archived while it has an active request."
}

ProjectMutationStaleResult {
  result_kind: "PROJECT_MUTATION_STALE",
  code: PROJECT_STATE_CONFLICT,
  safe_message: "The project selection changed. Refresh projects before trying again."
}

ProjectMutationRejectedResult {
  result_kind: "PROJECT_MUTATION_REJECTED",
  code: ARCHIVED_PROJECT_NOT_SELECTABLE | PROJECT_NOT_ARCHIVABLE,
  safe_message: "Archived projects cannot be selected." |
                "The project is no longer available for archiving."
}

ProjectMutationFailureResult {
  result_kind: "PROJECT_MUTATION_FAILURE",
  code: PROJECT_SELECTION_FAILED | PROJECT_ARCHIVE_FAILED,
  safe_message: "Project selection could not be changed safely." |
                "The project could not be archived safely."
}
```

Changed success updates the facade's current conversation association/version
on the GUI thread and then uses the invalidation matrix below. Unchanged success
updates a stale private version snapshot if necessary but emits no change
announcement and triggers no cross-page invalidation.

Archiving is available only for an `ACTIVE` row that has no prohibited non-
terminal run. Requesting it starts no worker and enters `ARCHIVE_CONFIRMATION`:

| Element | Exact text |
|---|---|
| Title | `Archive project?` |
| Body | `This hides the project from new selection. Existing conversation associations, messages, memories, and project data are preserved.` |
| Safe/default action | `Cancel` |
| Destructive action | `Archive` |

Cancel has initial focus/Escape semantics, returns to `READY`, and does nothing.
Accept enters `SAVING` and invokes `ArchiveProject` once; application rechecks
status and the global non-terminal run inside the archive transaction. A blocked
archive returns exact safe text `This project cannot be archived while it has an
active request.` An already-archived/missing target returns `The project is no
longer available for archiving.` A persistence/defect boundary returns `The
project could not be archived safely.` Repeated accept is suppressed and no
archive retry is automatic.

After success the row moves to the archived list in canonical order. If it is
the current conversation association, that association is deliberately retained
and displays `<name> — Archived (current association)`; it cannot be newly
selected but does not silently become null.

## 14. Project archive safety

Archive changes only `projects.status` and its canonical update timestamp. It
does not delete or rewrite a project, conversation, message, memory, source,
revision, entity, topic, task, processing run, packet, validation row, setting,
or conversation-project association. It cannot run for an already archived
project or for an active project whose associated conversation owns the global
non-terminal processing run.

The presentation never infers archive safety from a disabled button alone. The
application/domain transaction remains the final authority and returns a safe
rejection if eligibility changed after the query. No schema change, cascade,
restore operation, or implicit clear-selection behavior is introduced.

## 15. Validation and correction-history target

The sole TASK-0017 validation-history target is the latest accepted processing
run for the shell's current conversation. `InspectValidationHistory` uses the
same target algorithm as TASK-0016 `InspectContext`: inside one read-only
snapshot, choose the run whose linked `USER` message has the greatest
conversation message sequence. There is no run picker, message picker, UUID
field, timestamp tie-breaker, or implementation choice.

A conversation with no accepted run returns the exact `EMPTY` result below. A
non-terminal accepted run is a valid target and returns `READY`, even before
validation starts. Busy and pre-acceptance cancellation create no run and
cannot become the target. The validation page never retargets because a project
changes and never substitutes the current conversation state for run evidence.

```text
InspectValidationHistoryRequest {
  conversation_id: uuid
}

InspectValidationHistoryResult =
    ValidationHistoryReadyResult
  | ValidationHistoryEmptyResult
  | ValidationHistoryLoadFailureResult

ValidationHistoryReadyResult {
  result_kind: "VALIDATION_HISTORY_READY",
  view: ValidationHistoryView
}

ValidationHistoryEmptyResult {
  result_kind: "VALIDATION_HISTORY_EMPTY",
  safe_message: "No validation history is available for this conversation."
}

ValidationHistoryLoadFailureResult {
  result_kind: "VALIDATION_HISTORY_LOAD_FAILURE",
  code: VALIDATION_HISTORY_LOAD_FAILED,
  safe_message: "Validation history could not be loaded safely."
}
```

## 16. Validation and correction safe data model

The full-history projection imports `InspectionTargetView`,
`CanonicalLabelView`, `InspectionScoreView`, `SafeValidationViolationView`,
`SafeValidationEvidenceView`, and `SafeTerminalStatusView` exactly from
`ContextInspection.md`. It uses the same enum-label, score, safe-message,
violation/evidence ordering, and terminal-failure rules. It expands from the
latest validation only to all persisted request attempts; it does not broaden
the safe field allowlist.

```text
ValidationHistoryView {
  target: InspectionTargetView,
  attempts: ValidationHistoryCollection[ValidationHistoryAttemptView],
  corrections: tuple[CorrectionHistoryView],
  correction_count: uint in [0,2],
  terminal_status: SafeTerminalStatusView or null
}

ValidationHistoryCollection[T] {
  items: tuple[T],
  display_text: empty | "Validation has not started for this request."
}

ValidationAttemptOutcome = WAITING | IN_PROGRESS | VALIDATED |
                           TRANSPORT_FAILURE

ValidationHistoryAttemptView {
  attempt_number: uint starting at 1,
  display_identity: "Attempt <attempt_number>",
  purpose: CanonicalLabelView,
  outcome: CanonicalLabelView,
  validation: ValidationAttemptReportView or null,
  validation_display_text: empty |
      "Validation has not completed for this attempt." |
      "Validation was not applicable to this attempt.",
  safe_transport_failure: ValidationAttemptFailureView or null,
  correction_from_previous: uint or null
}

ValidationAttemptReportView {
  status: CanonicalLabelView,
  score: InspectionScoreView,
  violations: tuple[SafeValidationViolationView],
  evidence: tuple[SafeValidationEvidenceView]
}

ValidationAttemptFailureView {
  stage: CanonicalLabelView,
  code: CanonicalLabelView,
  safe_message: exact persisted safe message
}

CorrectionHistoryView {
  correction_number: uint starting at 1,
  display_identity: "Correction <correction_number>",
  from_attempt_number: uint,
  to_attempt_number: uint,
  display_text: "Correction <N>: attempt <N> to attempt <N+1>."
}
```

Attempts include every persisted model request for the target and order by its
zero-based attempt number ascending, displayed plus one. Attempt numbers must
start at zero, be unique, and be contiguous. `PENDING` maps to `WAITING`;
`IN_FLIGHT` maps to `IN_PROGRESS`; a `SUCCEEDED` request with its response and
validation maps to `VALIDATED`; and `TIMED_OUT`, `CANCELLED`, or `FAILED` maps
to `TRANSPORT_FAILURE` with only its safe stage/code/message. Raw request status
is not exposed.

A succeeded request without exactly one response and validation is a load
failure. A pending/in-flight attempt has null validation and exact incomplete
text. A transport-failed attempt has null validation, exact not-applicable text,
and a safe failure. A validated attempt preserves persisted violation/evidence
ordinal order and exposes both passed and failed validation without candidate
text.

Correction rows order by their canonical correction attempt number. Correction
`N` links failed display attempt `N` to revision display attempt `N+1`; it also
sets the destination attempt's `correction_from_previous=N` when that request
exists. A correction remains visible when its revised request is pending,
in-flight, or transport-failed. Missing, duplicate, skipped, cross-run, or
non-adjacent lineage fails the load. `correction_count` equals the committed
correction tuple length, including zero.

The target's one terminal controlled-failure/cancellation projection is shown
only through `SafeTerminalStatusView`. Success/clarification and a non-terminal
run have null terminal status. Clarification can be the latest accepted target
and yields a ready view with no attempts/corrections; it is not validation-page
`EMPTY`.

## 17. Invalid-candidate policy

No model candidate or response text is allowlisted for validation history.
Invalid, failed, unlinked, pending, accepted, and superseded candidate text is
absent from `InspectValidationHistoryResult`, the worker envelope, facade/list
models, QML objects, accessibility interfaces, and announcements. The accepted
assistant text remains visible only through the TASK-0015 chat success boundary;
the validation page does not duplicate it.

The application may read model requests, responses, raw validation rows, and
correction records inside its worker-owned snapshot solely to validate lineage
and build the closed projection. It must discard `rendered_prompt`, raw response
text, provider metadata, generation settings, request/response IDs, validation
IDs, normalized candidate inputs, match positions, candidate substrings,
correction envelopes/prompts, unrestricted failure details, and every internal
ID before returning. QML never receives an unsafe DTO to hide selectively.

This policy is identical to TASK-0016's candidate boundary. Full history means
all safe attempt/report/correction lineage, not historical candidate content.

## 18. Settings classification matrix

SQLite settings remain non-secret presentation preferences and are distinct
from validated process/YAML configuration. Each permitted key has exactly this
ownership:

| Key | Effective default if absent | Owning action | On settings page | Directly editable there | Valid values |
|---|---|---|---|---|---|
| `ui.theme` | `SYSTEM` | TASK-0017 theme control | yes | yes | `SYSTEM`, `LIGHT`, `DARK` |
| `ui.context_panel_visible` | `true` | TASK-0017 context-panel toggle | yes | yes | JSON boolean |
| `ui.last_selected_conversation_id` | `null` | a later explicit conversation-selection action | no | no | UUID string or JSON null |

Reading a missing row returns its default in memory and does not write a row or
`updated_at`. A settings save writes only changed, directly editable keys.
Unknown keys, additional value types, and attempts to edit
`ui.last_selected_conversation_id` through TASK-0017 are rejected before a
write. An existing unknown or invalid settings row makes the settings/startup
preference query fail safely; it is never silently treated as a default.

`ui.last_selected_conversation_id` remains the TASK-0015 startup preference:
missing/null/stale falls through to the canonical latest/first-run selection,
and shell preparation does not write it. The later conversation-management
owner writes it only after an actual explicit conversation selection. TASK-0017
provides no raw UUID field, display row, reset action, or indirect update for it.

## 19. Settings defaults and ownership

`InspectManualSettings` validates all stored settings, resolves missing defaults,
and combines the two visible preferences with the immutable safe configuration
projection from the validated bootstrap snapshot:

```text
ManualSettingsView {
  theme: SYSTEM | LIGHT | DARK,
  context_panel_visible: boolean,
  configuration: ConfigurationInspectionView
}

InspectManualSettingsResult =
    ManualSettingsReadyResult
  | ManualSettingsLoadFailureResult

ManualSettingsLoadFailureResult {
  result_kind: "MANUAL_SETTINGS_LOAD_FAILURE",
  code: SETTINGS_LOAD_FAILED,
  safe_message: "Settings could not be loaded safely."
}
```

TASK-0017 also adds one bounded pre-QML read to the existing startup scope;
this is not a worker or user operation:

```text
StartupApplicationScope {
  prepare_application_shell: PrepareApplicationShell
  load_initial_ui_preferences: LoadInitialUiPreferences
  close()
}

InitialUiPreferences {
  theme: SYSTEM | LIGHT | DARK,
  context_panel_visible: boolean
}
```

After a successful `PrepareApplicationShell` result and before closing that same
calling-thread startup scope, the entry point invokes
`LoadInitialUiPreferences` once. It validates the same three-key settings
boundary and applies missing defaults without writes. A returned/raised settings
load failure maps to the existing generic `COMPOSITION` startup failure; no Qt
application, QML engine, facade, or worker is created. This is the smallest
additive startup integration and does not change shell conversation selection,
recovery classification, or TASK-0015 result algebra.

After the scope closes, the entry point creates `QApplication`, applies the
initial theme as specified below before creating/loading QML, initializes the
facade's context-navigation visibility, and continues the existing startup
order. Recovery still starts only after one valid packaged root exists.

## 20. Settings update and apply semantics

The settings page holds pending theme/context values separately from the loaded
effective values. A save with no changed value is a facade-local no-op returning
`false`. Otherwise one worker submits both pending values as a complete closed
request. The application validates the keys/types first, reads one injected UTC
clock value, and atomically upserts only changed rows with that same
`updated_at` inside one transaction. A rejected request writes neither row.

```text
UpdateManualSettingsRequest {
  values: tuple[SettingUpdate] in key order
}

SettingUpdate {
  key: UI_THEME | UI_CONTEXT_PANEL_VISIBLE,
  value: closed value for key
}

UpdateManualSettingsResult =
    ManualSettingsUpdateSucceededResult
  | ManualSettingsValidationFailureResult
  | ManualSettingsMutationFailureResult

ManualSettingsUpdateSucceededResult {
  result_kind: "MANUAL_SETTINGS_UPDATE_SUCCEEDED",
  effective_theme: SYSTEM | LIGHT | DARK,
  effective_context_panel_visible: boolean,
  changed_keys: tuple[UI_THEME | UI_CONTEXT_PANEL_VISIBLE] in key order,
  safe_message: "Settings saved and applied.",
  restart_required: false
}

ManualSettingsValidationFailureResult {
  result_kind: "MANUAL_SETTINGS_VALIDATION_FAILURE",
  code: SETTING_VALUE_INVALID | SETTING_KEY_NOT_EDITABLE | SETTING_KEY_UNKNOWN,
  errors: tuple[SettingsFieldError] in key order,
  safe_message: "Review the highlighted settings."
}

SettingsFieldError {
  field: THEME | CONTEXT_PANEL_VISIBLE | LAST_SELECTED_CONVERSATION | UNKNOWN,
  safe_message: exact field message below
}

ManualSettingsMutationFailureResult {
  result_kind: "MANUAL_SETTINGS_MUTATION_FAILURE",
  code: SETTINGS_UPDATE_FAILED,
  safe_message: "Settings could not be saved safely."
}
```

The settings field messages are exact: Theme — `Theme must be System, Light, or
Dark.`; Context panel — `Show context inspection must be true or false.`; Last
selected conversation — `This setting is not editable here.`; Unknown — `Only
permitted presentation settings can be changed.` Duplicate errors for one key
collapse to the first message in the matrix key order, with unknown keys after
all known keys and ordered by their exact key string.

On queued success, the facade applies both returned effective values on the GUI
thread and only then enters `READY`, replaces the loaded/pending values, and
announces success. Applying theme uses the next section. Applying context-panel
visibility updates the navigation immediately; hiding an active context page
moves to Chat under section 3. No restart is required on the normal path.

There is no database rollback after the durable success result: persistence is
the authority, while theme/context application is a GUI-thread operation after
commit. The contracted Qt theme setters return no failure value and context
visibility is facade-local, so no ordinary partial-apply result exists. An
unexpected presentation defect after commit is contained as
the following presentation-only value; it does not attempt a cross-thread
compensating write:

```text
SettingsApplyFailureView {
  result_kind: "SETTINGS_APPLY_FAILURE",
  code: SETTINGS_APPLY_FAILED,
  safe_message: "Settings were saved but could not be applied completely. Restart the application to apply them.",
  persisted: true,
  restart_required: true
}
```

The next startup reapplies the persisted values. Such a defect enters
`MUTATION_ERROR` and is not reported as a persistence rollback or ordinary
success.

Settings changes never reload, rewrite, or override YAML, `.env`, process
overrides, model/storage/validation/security/logging behavior, the configuration
fingerprint, or a processing run's snapshot.

## 21. Theme semantics

`ui.theme` is a Qt application color-scheme preference, not a Qt Quick Controls
style selector:

| Stored value | Exact Qt behavior |
|---|---|
| `SYSTEM` | Call `QGuiApplication.styleHints().unsetColorScheme()`; follow future system color-scheme changes. |
| `LIGHT` | Call `QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)`. |
| `DARK` | Call `QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Dark)`. |

At startup this call occurs after `QApplication` creation and before QML engine
creation. After a settings save it occurs immediately on the GUI thread. QML
controls and application-specific colors must follow Qt's effective palette and
palette-change notifications. The application never changes `QQuickStyle`,
sets a Breeze/KDE style, or restarts QML to apply the preference.

Light/dark override is a platform hint and a platform may not visually honor
it. The persisted/effective application preference remains the selected enum;
TASK-0017 does not claim control over the desktop compositor or platform theme.
Normal saves always report `restart_required=false`.

## 22. Safe configuration-inspection model

Configuration inspection is read-only and derives from the one already-
validated immutable bootstrap snapshot. Categories and fields occur in exactly
this order; no other configuration value is visible:

| Category | Field label | Visible value |
|---|---|---|
| Application | `Foreground processing limit` | `1` |
| Model | `Provider` | `Ollama` |
| Model | `Execution locality` | `Direct numeric loopback only` |
| Model | `Model routing` | `Disabled` |
| Storage | `Database` | `SQLite` |
| Storage | `Data location` | `Local path (value hidden)` |
| Memory | `Manual create` | `Enabled` |
| Memory | `Manual edit` | `Enabled` |
| Memory | `Manual soft-delete` | `Enabled` |
| Memory | `Automatic mutation` | `Disabled` |
| Validation | `Maximum automatic revisions` | base-10 configured integer `0`, `1`, or `2` |
| Logging | `Level` | configured `Debug`, `Info`, `Warning`, or `Error` |
| Logging | `Retention` | configured `<N> days` |
| Logging | `Content logging` | `Disabled` |
| Logging | `Log location` | `Local path (value hidden)` |
| Security | `Cloud providers` | `Disabled` |
| Security | `Credentials and API keys` | `Unsupported` |
| Security | `Proxy and provider fallback` | `Disabled` |
| Security | `Ollama cloud-disable attestation` | `Required before each prompt` |

```text
ConfigurationInspectionView {
  categories: tuple[ConfigurationCategoryView] in table order,
  fingerprint_label: "Configuration fingerprint",
  fingerprint: exactly 64 lowercase hexadecimal SHA-256 characters
}

ConfigurationCategoryView {
  ordinal: uint starting at 1,
  name: Application | Model | Storage | Memory | Validation | Logging | Security,
  fields: tuple[ConfigurationFieldView] in table order
}

ConfigurationFieldView {
  ordinal: uint starting at 1 within category,
  label: exact table label,
  value_text: exact table value,
  origin: ConfigurationOriginView
}
```

The display explicitly hides model name/tag, base URL/port, context-window and
generation values, actual data/log directories, environment label, rule IDs and
phrases, action markers, raw limits not listed above, source filenames/paths,
and every unrestricted nested setting. A local-path label is metadata, not the
path. Runtime daemon health/model availability is not configuration and is not
shown.

Secrets, credentials, API keys, authorization, cookies, proxy/cloud/provider-
routing fields, raw environment or `.env` content, endpoint details, absolute
or relative paths, rejected values, expected-shape diagnostics, and full
configuration dumps are prohibited even if introduced by a faulty fixture.

## 23. Configuration origin and fingerprint

Origin is per visible field, never one ambiguous global source. Each field has
exactly one of:

| Origin enum | Exact label | Meaning |
|---|---|---|
| `PROCESS_OVERRIDE` | `Process override` | The visible source-backed scalar came from its allowed explicit process override. |
| `LOCAL_YAML` | `Local YAML` | It came from a validated required YAML field. |
| `DOCUMENTED_DEFAULT` | `Documented default` | Its allowed field was absent and the documented default supplied it. |
| `FIXED_MVP` | `Fixed MVP rule` | The displayed value is a fixed architecture/configuration invariant rather than an editable scalar. |

Data/log location fields show the origin of their underlying hidden configured
path. Validation maximum, log level, and retention show their actual scalar
origin. All constant provider/runtime/storage/memory/security and
content-logging fields use `FIXED_MVP`. `.env` only chooses allowed bootstrap
inputs; a field read from a selected YAML file remains `LOCAL_YAML` and no `.env`
key/path becomes visible.

The configuration loader must retain the smallest additional immutable
bootstrap metadata: an origin enum for each normalized scalar field after
override/default/YAML selection. That map is part of the in-memory configuration
snapshot, is neither fingerprint input nor persisted in SQLite, and is passed
only to the application configuration-inspection projector. QML never receives
the map or full snapshot.

The visible fingerprint is the existing complete normalized non-secret
configuration SHA-256 hex digest, without truncation, regrouping, rehashing, or
recalculation from the visible subset. The exact label is `Configuration
fingerprint`. A missing/malformed fingerprint or origin for a visible
source-backed field fails the complete settings query with
`Settings could not be loaded safely.`; no partial configuration view is shown.
Existing precedence remains process override, bootstrap-only `.env`, local
YAML, then documented default.

## 24. Refresh and invalidation rules

Each page has a GUI-owned dirty flag. Marking an inactive page dirty starts no
work; its next navigation loads it. Marking the active TASK-0017 page dirty
starts or coalesces one read under the shared execution rule. These flags are
state invalidation, not queued operation objects.

| Event | Required effect |
|---|---|
| First TASK-0017 route navigation, repeated same-route navigation, or its Refresh action | Clear that page, increment generation, enter `LOADING`, start/coalesce its query. |
| Memory filter changes | Clear selection/details, increment generation, load that stored-status filter. |
| Memory row selection | Change only facade-local selected details; no worker or invalidation. |
| Memory create/edit/soft-delete success | Apply the post-success filter/selection in section 9, mark Memory dirty, and perform at most one coalesced Memory refresh. |
| Memory guidance/cancel/validation/rejection/failure | No cross-page invalidation; stale result marks Memory dirty but waits for explicit refresh. |
| Actual project select or clear success | Update current association/version; mark Projects, Memory, and Context inspection dirty. If Context inspection is active and visible, invoke its existing one-coalesced-refresh rule. |
| Project no-op/rejection/stale/failure | No cross-page invalidation; stale marks Projects dirty but waits for explicit refresh. |
| Project archive success | Mark Projects and Memory dirty. If the archived project remains the current association, also mark Context inspection dirty and refresh it if active. Never clear the association. |
| Current-conversation processing success, clarification, controlled failure, or accepted cancellation | Preserve TASK-0016 Context invalidation and also mark Validation history dirty; refresh either page only when it is active. |
| Busy, pre-acceptance cancellation, or intermediate processing commit | No Task-0017 invalidation. Manual refresh may observe a committed intermediate state. |
| A later explicit conversation change | Clear/dirty Context inspection, Memory, Projects, and Validation history for the new conversation; Settings is unchanged. |
| Theme-only settings success | Refresh no data page; apply palette preference immediately. |
| Context-panel setting success | Apply navigation visibility; if false on the context route, navigate to Chat and invalidate Context inspection. |
| Navigate away | Clear/inactivate the old page and invalidate its generation; any accepted worker finishes for cleanup. |
| Late/mismatched/duplicate envelope | No route, page, global association/preference, chat, or enablement mutation. |
| Shutdown | Enter every page's `SHUTDOWN`, clear content, invalidate generations, and start no coalesced read. |

Project selection does not retarget Validation history. Project archive does not
rewrite historical Context or Validation evidence. Memory operations cannot
invalidate processing history because the processing pipeline never performs an
automatic memory mutation. No invalidation is trace-driven, timer-driven, or
polled.

## 25. Interaction with TASK-0016 context inspection

TASK-0016's `CONTEXT_INSPECTION` page, latest-run target, safe evidence model,
page states, inspection worker, refresh coalescing, and AT-013 assertions remain
unchanged. TASK-0017 integrates only in these additive ways:

- the total route set expands as specified in section 3;
- `ui.context_panel_visible` controls whether its navigation action is exposed;
- an actual current-project selection change preserves TASK-0016's mandatory
  refresh, while re-selection is a no-op;
- validation history uses the identical latest-run target but shows every safe
  attempt/correction rather than replacing TASK-0016's latest-validation
  summary;
- both pages enforce the same no-prompt/no-candidate/no-provider boundary; and
- the one inspection worker and one manual-operations worker may coexist only
  through separate scopes/connections, alongside at most one foreground worker.

Neither page joins the other's result in presentation. `InspectContext` remains
read-only and does not call `InspectValidationHistory`; both application queries
build their own closed projection inside their own snapshot. A project refresh
never reinterprets the selected historical run.

## 26. Accessibility contract

Qt Quick's native `Accessible` attached type is the boundary. Every interactive
control exposes its visual label as accessible name, supports the equivalent
native accessibility action, has a deterministic focus order, and never places
a prohibited value in name, description, value, or announcement. Qt 6.8 polite
announcement events are used; a live screen reader, AT-SPI daemon, KDE service,
KWin rule, compositor, or platform-specific process is not required by tests.

The exact navigation/page identities are:

| Element | `Accessible.id` | Role | Exact name |
|---|---|---|---|
| Memory navigation | `memoryNavigation` | `Button` | `Memory` |
| Projects navigation | `projectsNavigation` | `Button` | `Projects` |
| Validation navigation | `validationHistoryNavigation` | `Button` | `Validation history` |
| Settings navigation | `settingsNavigation` | `Button` | `Settings` |
| Memory page | `memoryPage` | `Pane` | `Memory` |
| Memory status | `memoryStatus` | `StaticText` | exact current memory status text |
| Memory refresh | `memoryRefresh` | `Button` | `Refresh memories` |
| Projects page | `projectsPage` | `Pane` | `Projects` |
| Projects status | `projectsStatus` | `StaticText` | exact current projects status text |
| Projects refresh | `projectsRefresh` | `Button` | `Refresh projects` |
| Validation page | `validationHistoryPage` | `Pane` | `Validation history` |
| Validation status | `validationHistoryStatus` | `StaticText` | exact current validation status text |
| Validation refresh | `validationHistoryRefresh` | `Button` | `Refresh validation history` |
| Settings page | `settingsPage` | `Pane` | `Settings` |
| Settings status | `settingsStatus` | `StaticText` | exact current settings status text |
| Settings refresh | `settingsRefresh` | `Button` | `Refresh settings` |

The exact principal control identities are:

| Element | `Accessible.id` | Role | Exact name |
|---|---|---|---|
| Memory filter | `memoryFilter` | `ComboBox` | `Memory filter` |
| Memory list | `memoryList` | `List` | `Memories` |
| Create memory | `memoryCreate` | `Button` | `Create memory` |
| Edit memory | `memoryEdit` | `Button` | `Edit memory` |
| Delete memory | `memorySoftDelete` | `Button` | `Soft-delete memory` |
| Memory editor | `memoryEditor` | `Pane` | `Memory editor` |
| Source list | `memorySources` | `List` | `Memory sources` |
| Revision list | `memoryRevisions` | `List` | `Memory revisions` |
| Duplicate dialog | `memoryDuplicateDialog` | `Dialog` | `Possible duplicate memories` |
| Return from duplicate guidance | `memoryDuplicateReturn` | `Button` | `Return to memory editor` |
| Proceed with duplicate | `memoryDuplicateProceed` | `Button` | `Create separate memory` |
| Delete dialog | `memoryDeleteDialog` | `Dialog` | `Soft-delete memory?` |
| Delete cancel | `memoryDeleteCancel` | `Button` | `Cancel` |
| Delete confirm | `memoryDeleteConfirm` | `Button` | `Soft-delete` |
| Active project list | `activeProjectList` | `List` | `Active projects` |
| Archived project list | `archivedProjectList` | `List` | `Archived projects` |
| Clear project | `projectClearSelection` | `Button` | `Clear project selection` |
| Archive project | `projectArchive` | `Button` | `Archive project` |
| Archive dialog | `projectArchiveDialog` | `Dialog` | `Archive project?` |
| Archive cancel | `projectArchiveCancel` | `Button` | `Cancel` |
| Archive confirm | `projectArchiveConfirm` | `Button` | `Archive` |
| Validation attempt list | `validationHistoryAttempts` | `List` | `Validation attempts` |
| Correction list | `validationHistoryCorrections` | `List` | `Corrections` |
| Theme control | `settingsTheme` | `ComboBox` | `Theme` |
| Context-panel control | `settingsContextPanelVisible` | `CheckBox` | `Show context inspection` |
| Save settings | `settingsSave` | `Button` | `Save settings` |
| Configuration list | `settingsConfiguration` | `List` | `Configuration` |
| Fingerprint | `settingsConfigurationFingerprint` | `StaticText` | `Configuration fingerprint: <64-character fingerprint>` |

Dynamic items use role `ListItem` and these exact ID/name templates:

- memory: `memoryItem-<ordinal>`, `Memory <ordinal>: <type label>, <effective status label>`;
- source: `memorySource-<ordinal>`, `Source <ordinal>: <source kind label>`;
- revision: `memoryRevision-<number>`, `Revision <number>: <operation label>`;
- duplicate: `memoryDuplicate-<ordinal>`, `Possible duplicate <ordinal>: <effective status label>`;
- active project: `activeProject-<ordinal>`, `Active project <ordinal>: <name>`;
- archived project: `archivedProject-<ordinal>`, `Archived project <ordinal>: <name>` plus `, current association` only when true;
- validation attempt: `validationAttempt-<number>`, `Attempt <number>: <purpose label>, <outcome label>`;
- correction: `validationCorrection-<number>`, the exact correction `display_text`; and
- configuration field: `configurationField-<category ordinal>-<field ordinal>`, `<field label>: <value text>. Origin: <origin label>`.

Visible scalar memory labels are `Type`, `Scope`, `Owner`, `Content`,
`Keywords`, `Topic terms`, `Importance`, `Confidence`, `Expiry`, `Stored
status`, `Effective status`, `Evaluated at`, `Created`, `Updated`, and `Deleted`.
Project scalar labels are `Current project`, `Name`, `Description`, `Status`,
`Created`, and `Updated`. Validation target/report labels are exactly those in
`ContextInspection.md`, with `Attempt`, `Purpose`, `Attempt outcome`, and
`Correction count` added. Every scalar uses role `StaticText` and exact name
`<label>: <application-owned display text>`. Decorative duplicate text is
`Accessible.ignored=true`.

Delete/archive dialogs are modal within the application window, move focus to
their `Cancel` button, trap focus until resolved, restore focus to the invoking
control after cancel, and expose their exact body as description. Duplicate
guidance moves focus to `Return to memory editor`. Dialog focus/name supplies
the confirmation announcement; the facade does not issue a second explicit
announcement for merely opening/cancelling a dialog.

For each page the facade exposes read-only `<page>_announcement_text` and
`<page>_announcement_revision`, initially empty and zero. Each accepted
transition below sets the exact text and increments its revision by one, even
when text repeats. Its status item performs exactly one native polite
`Accessible.announce` for each new revision. No timer/text-equality heuristic is
allowed.

| Page transition | Exact announcement/status text |
|---|---|
| Memory load accepted | `Loading memories.` |
| First/refresh memory ready | `Memories loaded.` / `Memories refreshed.` |
| Memory empty/load error | exact closed message from section 4 |
| Create/edit/delete accepted | `Creating memory.` / `Updating memory.` / `Soft-deleting memory.` |
| Duplicate guidance | `Possible duplicate memories were found.` |
| Memory validation/stale/rejection/failure/success | exact result `safe_message` from sections 9 and 12 |
| Projects load accepted | `Loading projects.` |
| First/refresh projects ready | `Projects loaded.` / `Projects refreshed.` |
| Projects empty/load error | exact closed message from section 4 |
| Select/clear accepted | `Changing project selection.` |
| Changed select/clear success | `Project selection changed.` |
| Archive accepted/success | `Archiving project.` / `Project archived.` |
| Project rejection/stale/failure | its exact safe result message |
| Validation load accepted | `Loading validation history.` |
| First/refresh validation ready | `Validation history loaded.` / `Validation history refreshed.` |
| Validation empty/load error | exact closed message from section 4 |
| Settings load accepted | `Loading settings.` |
| First/refresh settings ready | `Settings loaded.` / `Settings refreshed.` |
| Settings save accepted | `Saving settings.` |
| Settings validation/failure/success | exact result safe message from section 20 |

`INACTIVE` and `SHUTDOWN` have empty status and issue no announcement. Row
selection, form edits, cancelled confirmation, facade-local no-ops, dirtying an
inactive page, stale/late envelopes, and worker-finished cleanup issue no
explicit announcement. Native controls still expose their ordinary state/value
changes.

Offscreen tests query Qt accessibility interfaces for the contracted IDs,
roles, names, descriptions, actions, focus, and values and use a recording Qt
accessibility update seam for announcement text and polite priority.

## 27. Shutdown and disposal

An accepted shell close enters the existing `SHUTDOWN` state, moves every
TASK-0017 page to `SHUTDOWN`, clears datasets/forms/dialogs, invalidates every
generation, clears `pending_read_route`, and permanently refuses new manual
operations. With no manual worker, that private role can dispose immediately.

With a manual query or mutation active, no forced termination, blocking GUI
join, detached cleanup, or replacement operation occurs. The finite operation
is allowed to return/commit or roll back normally, close its scope/connection on
its worker thread, and queue terminal/finished cleanup. During shutdown its
content is consumed only for resource ownership; it does not apply theme,
navigation, page content, association, or announcement. A committed preference
or mutation remains durable and is observed on next startup/load.

The GUI event loop, root, facade, and scope factory remain alive until every
owned foreground, inspection, and manual-operations worker has closed its scope
and delivered its finished notification. Only then may final Qt/QML disposal
and process exit occur. No coalesced refresh starts after shutdown.

## 28. Deterministic verification invariants

TASK-0017 offscreen/application/integration verification uses fixed UUIDs and
clock, isolated SQLite, validated fixture configuration/origin metadata, the
real facade and packaged QML, instrumented scope/connection/transaction/trace
seams, held workers, out-of-order envelopes, and Qt accessibility recording.
It must demonstrate independently that:

1. the route set/order, actions, one-facade ownership, four exact page-state
   algebras, initial/refresh/empty/error/mutation/confirmation transitions, and
   navigation-away clearing match this contract;
2. there is at most one finite manual-operations worker, repeated reads
   coalesce to one latest route, mutations suppress repeats, no queue/poller/
   persistent worker exists, and foreground/inspection/manual work coexists
   only through three separate scopes/connections;
3. every manual connection is created, used, and closed on its own non-GUI
   worker thread; mutations have one outer commit/rollback, terminal delivery
   is queued/immutable, GUI mutation is GUI-thread-only, and stale/mismatched/
   late results change nothing;
4. held operations preserve GUI sentinels, navigation, foreground cancellation,
   and close responsiveness, while shutdown waits asynchronously without force
   termination or a blocking join;
5. the default Active memory query includes effective Active/Expired, Deleted
   is separately inspectable, ordering/selection/owners/types/scopes/content/
   keywords/topic terms/scores/times/statuses/evaluated-at are exact, and full
   provenance/revision ordering and source-ordinal linkage are visible;
6. expiry performs no write/revision; create/edit/delete each produces exactly
   one canonical source/revision, preserves immutable fields/history, enforces
   expected revision, suppresses repeats, projects safe failures, selects the
   contracted post-success tombstone/record, and emits exactly one redacted
   post-commit canonical memory trace event;
7. soft-delete cancel performs no application call/write/trace and confirmation
   performs one; deleted memory cannot edit/delete again/restore and remains
   inspectable with content/provenance;
8. creation-time duplicate comparison uses exact normalization, same scope and
   owner, stored Active including Expired, canonical order and safe fields;
   guidance is advisory, Proceed creates an independent record, and no merge/
   replace/rewrite/delete mutation or merge button exists;
9. project active/archived lists and current association are ordered/projected
   exactly; actual select/clear increments state once, repeat is a no-op,
   archived selection and stale versions reject safely, and project-change
   invalidation preserves TASK-0016 refresh behavior;
10. archive cancel writes nothing; blocked archive rejects; successful archive
    changes only project status/update time, preserves every conversation,
    message, memory, entity, and association, and displays an archived current
    association that cannot be newly selected;
11. Validation history and Context inspection choose the same latest run by
    user-message sequence; requests/attempts/corrections/count/failures are
    ordered and related exactly, including non-terminal/clarification/transport
    paths and all safe validation evidence;
12. unique sentinels in prompts, every candidate/response, provider metadata,
    correction envelopes, raw validation internals, unsafe failure detail,
    IDs, and exceptions occur nowhere in the safe application result, envelope,
    facade/list models, QML text, accessibility tree, or announcements;
13. absent settings resolve to `SYSTEM`, `true`, and null without writes; only
    theme/context controls save atomically; invalid values, unknown keys, and
    direct last-conversation edits reject; the later conversation owner and
    TASK-0015 startup semantics remain intact;
14. configuration categories/fields/order/origin labels/full 64-character
    fingerprint are exact, while paths/endpoints/model identity/environment/
    secrets/raw source/rejected values are absent and YAML never changes;
15. `SYSTEM`/`LIGHT`/`DARK` map only to the contracted Qt color-scheme calls at
    startup and immediately after save, normal success requires no restart,
    context-panel visibility applies immediately, and no KDE/KWin/style-change
    dependency or setting override exists;
16. every exact accessibility ID/name/role/value/focus/action and polite
    announcement/revision is observable through native Qt offscreen interfaces
    without a live assistive service;
17. all root and nested QML assets load from both source checkout and installed
    package, application startup succeeds with valid initial preferences, and
    failure stays within the existing safe startup boundary; and
18. both existing TASK-0015/TASK-0016 AT-013 passes, complete AT-014 including
    this TASK-0017 pass, and the complete then-current non-live suite remain
    green.

Gate-to-contract closure is exact:

| Gate | Owning sections |
|---|---|
| G17-01 | 3, 4, 24, 26 |
| G17-02 | 5, 6, 24, 27 |
| G17-M01 | 7, 8, 11 |
| G17-M02 | 9, 10, 11 |
| G17-M03 | 12 |
| G17-P01 | 13, 14, 24 |
| G17-V01 | 15, 16, 17, 25 |
| G17-S01 | 18, 19 |
| G17-S02 | 22, 23 |
| G17-S03 | 20, 21 |
| G17-A01 | 26, 28 |
