# Presentation Shell Contract

## Authority and scope

This document is the normative TASK-0015 contract for the minimum PySide6/QML
application shell. It refines NFR-008 and the presentation/runtime rules in
`ARCHITECTURE.md` without changing the TASK-0014 public submission or recovery
algebra in `ProcessUserMessage.md`.

TASK-0015 owns only the shell, chat input/output, the single permitted initial
route, startup-error presentation, application-facing presentation adapters, and
one bounded foreground execution at a time. Detailed context inspection, memory,
project, conversation-management, validation-history, and settings pages remain
later-task work. TASK-0015 must not create empty or misleading versions of those
pages.

## Exact inward application interfaces

The presentation layer consumes these final TASK-0014 interfaces unchanged:

```text
ProcessUserMessage.execute(
  request: ProcessUserMessageRequest,
  cancellation_token: CancellationToken
) -> ProcessUserMessageResult

RecoverProcessingRun.execute(
  request: RecoverProcessingRunRequest,
  cancellation_token: CancellationToken
) -> RecoveryResult
```

The request and every result variant are exactly those in
`ProcessUserMessage.md`. Presentation must not add a catch-all result, convert an
expected returned condition into an exception, or pass a presentation progress
callback into either use case.

TASK-0015 adds one narrow application entry for shell preparation; it does not
alter either TASK-0014 use case:

```text
PrepareApplicationShellRequest {}

ShellReadyResult {
  result_kind: "SHELL_READY",
  conversation_id: uuid,
  initial_conversation_created: boolean
}

RecoveryRequiredResult {
  result_kind: "RECOVERY_REQUIRED",
  processing_run_id: uuid,
  conversation_id: uuid
}

ShellPreparationFailureResult {
  result_kind: "SHELL_PREPARATION_FAILURE",
  failure_kind: RECOVERY_PREFLIGHT_FAILED | CONVERSATION_SETUP_FAILED,
  code: PERSISTENCE_ERROR,
  safe_message: exact closed message for `failure_kind`
}

PrepareApplicationShellResult =
    ShellReadyResult
  | RecoveryRequiredResult
  | ShellPreparationFailureResult

PrepareApplicationShell.execute(
  request: PrepareApplicationShellRequest
) -> PrepareApplicationShellResult
```

The closed preparation messages are:

| `failure_kind` | Exact `safe_message` |
|---|---|
| `RECOVERY_PREFLIGHT_FAILED` | `Previous processing state could not be inspected safely.` |
| `CONVERSATION_SETUP_FAILED` | `A conversation could not be opened safely.` |

`PrepareApplicationShell` first performs one read-only lookup for the sole
global non-terminal run. If one exists, it returns `RecoveryRequiredResult` for
that run and its conversation, creates no conversation, mutates no setting, and
does not classify or resume recovery. If none exists, it selects a usable
conversation in this exact order:

1. the existing conversation named by `ui.last_selected_conversation_id`, when
   that setting is non-null and resolves;
2. otherwise the existing conversation with greatest `updated_at`, breaking an
   equal timestamp by ascending conversation UUID; or
3. otherwise one newly created unscoped conversation with `title=null`, its
   required version-`0` state, and IDs/time from the composed `IdGenerator` and
   `Clock`.

A preferred conversation “resolves” only when its conversation row and one
valid current `conversation_states` row load together. A preference whose
conversation row no longer exists is stale and falls through to the second
choice. An existing selected/latest conversation with missing or invalid state,
or a repository failure while reading the setting/conversations/state, returns
`CONVERSATION_SETUP_FAILED`; preparation does not skip, repair, or partially
recreate it.

The new conversation and state commit atomically. This one first-run bootstrap
does not create a project, topic, task, message, processing run, memory, or named
item. The returned selection is an in-memory shell choice;
`PrepareApplicationShell` never writes `ui.last_selected_conversation_id`.
Later explicit conversation-management UI remains responsible for user
create/select operations beyond this startup default and for updating that
preference.

All three preparation results are immutable values. A preparation failure
contains no database path, SQL, exception text/type, row, processing identifier,
or partial conversation object.

## Composition scopes and connection ownership

The application layer declares, and the outer composition root implements, this
presentation-facing scope factory:

```text
ShellApplicationScopeFactory {
  open_startup_scope() -> StartupApplicationScope
  open_foreground_scope() -> ForegroundApplicationScope
}

IdempotencyKeyFactory {
  new_key() -> uuid
}

StartupApplicationScope {
  prepare_application_shell: PrepareApplicationShell
  close()
}

ForegroundApplicationScope {
  process_user_message: ProcessUserMessage
  recover_processing_run: RecoverProcessingRun
  close()
}
```

`IdempotencyKeyFactory` is the presentation caller's UUID source required by the
TASK-0014 request contract. Production composition supplies a local UUID
implementation; deterministic UI composition supplies fixed keys. The facade
calls `new_key()` exactly once only after its local state/duplicate/text guards
accept a submission. It does not allocate a key for startup, recovery, an empty
string, or a suppressed duplicate.

Each `open_*_scope` call creates its repositories, connection-local
`TransactionBoundary`, and application services on the calling thread. A scope
owns exactly one SQLite connection for its repositories, and `close()` closes
that connection on the same thread. Scope closing is mandatory on success,
returned failure, cancellation, raised programming defect, and shutdown.

The entry point opens one `StartupApplicationScope` synchronously before a Qt
application or QML object exists. That scope performs only shell preparation and
closes before Qt/QML startup continues. Migration bootstrap uses its own earlier
short-lived startup connection and also closes it before shell preparation.
Neither startup connection is retained by the composition root, controller, or
QML.

For TASK-0015, `ShellFacade` is the one GUI-thread QObject exposed to QML and
`ForegroundRunController` is that object's private foreground-execution role;
they are not two independently composed public controllers or competing state
stores. The entry point creates and owns the object, QML receives only a borrowed
context reference, and QML cannot destroy or replace it. Its lifetime extends
until the QML root/engine can be disposed under the shutdown rules below.

`ForegroundRunController` owns only the scope factory, the active worker/thread,
the per-execution cancellation token, immutable startup/result values, and GUI
state. It never owns a repository, SQLite connection, concrete gateway, provider
buffer, or transaction. For each accepted recovery or submission, the worker
thread opens one fresh `ForegroundApplicationScope`, invokes exactly one of its
two use cases, closes the scope, and then emits one immutable terminal envelope.
The scope and its SQLite connection never cross the worker boundary.

The concrete cancellation token is thread-safe, Qt-independent, idempotent, and
monotonic. The GUI-owned controller is its sole mutator; the application and
gateway only observe it. A fresh token is created for every accepted submission
and every accepted startup recovery.

If opening a foreground scope or an unexpected programming defect prevents a
use case from returning its closed application result, the worker boundary emits
one immutable presentation failure instead of an exception:

```text
ForegroundExecutionFailureView {
  result_kind: "FOREGROUND_EXECUTION_FAILURE",
  execution_kind: SUBMISSION | RECOVERY,
  code: APPLICATION_EXECUTION_FAILED,
  safe_message: "Processing could not be completed safely." |
                "Previous processing could not be recovered safely."
}
```

The first message is exact for `SUBMISSION`; the second is exact for `RECOVERY`.
No exception/type/traceback or partial application value crosses the boundary.
Submission maps this value to `CONTROLLED_FAILURE`; recovery maps it to
`RECOVERY_FAILURE`. Both keep submission disabled and require restart because
the durable global slot cannot be proven free. This projection is presentation
containment for a defect, not a new TASK-0014 expected result or persisted
failure.

The controller creates no queue, executor pool, persistent thread, poller,
timer-driven recovery, daemon, or detached work. One application process has at
most one foreground scope and one foreground worker at a time.

## Deterministic startup order

Normal desktop startup has this exact order:

1. With no `QApplication`, QML engine, controller, or QML object yet, resolve and
   validate configuration and acquire the immutable configuration snapshot.
2. Configure structured logging. Failure to configure the logger is a
   configuration startup failure.
3. Apply/validate migrations using one short-lived startup-owned SQLite
   connection, then close it.
4. Construct the outer scope factory. Validate all non-runtime construction
   inputs without opening a foreground scope.
5. Open one startup scope, call `PrepareApplicationShell` once, and close the
   scope.
6. On a preparation or earlier failure, present the pre-QML startup failure and
   terminate non-zero. Create no QML engine and start no foreground worker.
7. On `ShellReadyResult` or `RecoveryRequiredResult`, create `QApplication`, the
   GUI-owned controller/view model, and the QML engine; load the packaged root.
8. If root loading fails, present the pre-shell QML-load failure, dispose the
   engine/controller, and terminate non-zero. Start no recovery worker.
9. After exactly one root object exists, publish the immutable preparation
   result. `ShellReadyResult` enters `IDLE`. `RecoveryRequiredResult` enters
   `RECOVERY` and starts exactly one foreground recovery worker.

The `--check` path performs configuration, logging, migrations, and composition
validation, then stops. It does not open a startup/foreground application scope,
perform recovery preflight, select/create a conversation, or create
`QApplication`, QML, a controller, or a foreground worker. It reports failure
only through the safe stderr presenter.

No foreground worker is started for configuration, logging, migration,
composition, shell-preparation, QML-load, or `--check` failure; for a successful
`ShellReadyResult`; for an invalid or duplicate UI action; or for idle shutdown.
A foreground worker is started only after a successfully loaded root for a
`RecoveryRequiredResult`, or after the controller accepts one explicit user
submission.

`RecoverProcessingRun` still handles and returns `NoRecoveryRequiredResult` if
the durable state changes between preparation and execution or when the use case
is invoked directly. That defensive TASK-0014 branch does not require the shell
to start a worker when preparation already established that no recovery exists.

## Startup-error presentation

Pre-shell startup failures—from configuration through the attempt to create one
usable QML root—use this closed immutable projection:

```text
StartupFailureView {
  failure_kind: CONFIGURATION | MIGRATION | COMPOSITION |
                QML_LOAD | RECOVERY_PREFLIGHT,
  code: non-empty closed code,
  safe_message: exact closed message,
  file: non-empty configuration file name or null,
  key: non-empty configuration key or null
}
```

```text
StartupErrorPresenter.present(
  failure: StartupFailureView,
  mode: INTERACTIVE | NON_INTERACTIVE
) -> None
```

The entry point invokes this interface exactly once for a pre-shell failure. A
recording acceptance implementation captures the immutable value and performs no
GUI work. Presenter failure cannot replace the original failure or cause a QML
fallback.

| `failure_kind` | `code` | Exact `safe_message` | Allowed optional fields |
|---|---|---|---|
| `CONFIGURATION` | `CONFIGURATION_INVALID` | `The application configuration is invalid.` | `file`, `key` from the typed configuration error |
| `MIGRATION` | `MIGRATION_FAILED` | `The local database could not be prepared safely.` | none |
| `COMPOSITION` | `APPLICATION_STARTUP_FAILED` | `The application could not be started safely.` | none |
| `QML_LOAD` | `QML_LOAD_FAILED` | `The application window could not be opened.` | none |
| `RECOVERY_PREFLIGHT` | `RECOVERY_PREFLIGHT_FAILED` | `Previous processing state could not be inspected safely.` | none |

`CONVERSATION_SETUP_FAILED` is presented as `COMPOSITION` with the generic
composition code/message. Configuration `file` and `key` are displayed as one
location; the rejected value and the loader's expected-shape diagnostic are not
displayed.

Every pre-shell failure writes one safe line to stderr. A normal interactive
desktop launch (`mode=INTERACTIVE`) additionally uses one non-QML Qt modal error
dialog owned by the entry point, titled `Context for AI — Startup Error`, with
only the safe message and optional configuration location. For a failure before
QML loading, the dialog may create a short-lived `QApplication` after the
failure is known; for `QML_LOAD`, it uses the existing application only after
the failed engine/root has been disposed. It never creates or loads a QML error
view. The `--check` path uses `NON_INTERACTIVE`; the offscreen recording
presenter records the requested mode but always uses stderr/recording only and
must not open a modal dialog. If graphical presentation itself is unavailable,
the safe stderr line remains authoritative and the process exits non-zero.

Raw exceptions, tracebacks, SQL, database/configuration absolute paths, QML
filesystem paths/import diagnostics, endpoint/model identity, IDs, configuration
values, prompts, response content, and provider data are never shown in the
dialog or safe stderr line.

A direct `ConfigurationFailureResult` or `PersistenceFailureResult` returned by
an already-started recovery is not a pre-shell failure. The existing shell enters
`RECOVERY_FAILURE`, displays only the result's safe message plus allowed
configuration file/key, keeps submission disabled, and requires restart. It
does not open another modal dialog. A `RecoveryCompletedResult` instead maps its
terminal `outcome` through the ordinary terminal-state rules below.

## Route and shell content

The TASK-0015 route set is exactly `{CHAT}` and the initial route is `CHAT`.
The root contains the application frame, one visible Chat navigation item, the
exact-text composer, current terminal output, submit/cancel controls,
progress/status presentation, and startup/recovery state presentation.

The minimum shell does not hydrate or synthesize a persisted conversation
transcript: the composer is its chat-input surface and the closed facade output
fields below are its chat-output surface. Loading historical messages or adding
a conversation-management/history view requires a later owning application
query and route; TASK-0015 does not infer history from returned identifiers.

Context, memory, project, conversation-management, validation, and settings
destinations are not registered, displayed as disabled items, or represented by
empty placeholder pages. A later owning task may add those routes without
changing the `CHAT` route contract.

The conversation ID comes only from `PrepareApplicationShell` or the recovered
run. TASK-0015 exposes no project selector, so every new shell submission uses
`project_id=null`. The composer sends the entered string byte-for-byte as
`user_text`; it performs no trimming, normalization, repair, or regeneration.
An empty string is not dispatchable, but a non-empty whitespace-only string is
preserved and dispatchable.

The shell is send-ready only when it has a non-null conversation ID, the root is
loaded, no foreground worker is owned, shutdown has not begun, and the current
state's enablement rules permit submission.

## QML-facing facade

QML receives exactly one GUI-thread-owned presentation facade. The facade's only
non-Qt collaborators are `ShellApplicationScopeFactory` and
`IdempotencyKeyFactory`; QML never receives raw repositories, connections,
application services, gateway outcomes, domain objects, configuration objects,
or infrastructure adapters.

The facade exposes these read-only values and actions:

```text
ShellFacade {
  route: CHAT
  state: ShellState
  conversation_id: uuid or null
  input_enabled: boolean
  submit_enabled: boolean
  cancel_enabled: boolean
  progress_visible: boolean
  progress_label: exact presentation string or empty
  status_kind: canonical result/failure kind or empty
  status_message: safe string or empty
  assistant_text: exact validated/final string or empty
  clarification_text: exact deterministic question or empty

  submit_exact(user_text: string) -> boolean
  request_cancellation() -> boolean
  request_shutdown()
}
```

`submit_enabled` reports state/ownership availability. The QML submit control is
enabled only when `submit_enabled` is true and the current composer value has
length greater than zero. `submit_exact("")` returns `false`; every other string
is preserved. A successful `submit_exact` return means one worker was accepted
and one UUID idempotency key was allocated for it. `false` means no key, token,
worker, queue item, use-case call, or display mutation was created.
`request_cancellation` returns `true` only for the first request against an
active owned execution.

All facade values and their notify signals are read/mutated only on the GUI
thread. The controller may map immutable application values into primitive
presentation fields; QML does not branch over the application DTO algebra.

## Complete shell state machine

`ShellState` is exactly:

```text
STARTUP | RECOVERY | IDLE | PENDING | CANCELLATION_REQUESTED |
CANCELLED | CLARIFICATION | SUCCESS | CONTROLLED_FAILURE | BUSY |
EXISTING_RUN | PERSISTENCE_FAILURE | RECOVERY_FAILURE | SHUTDOWN
```

| State | Entry | Progress | Input / submit / cancel |
|---|---|---|---|
| `STARTUP` | Root exists but preparation result has not yet been applied. | `Starting…` indeterminate | disabled / disabled / disabled |
| `RECOVERY` | Required recovery worker accepted. | `Recovering an interrupted request…` indeterminate | disabled / disabled / enabled |
| `IDLE` | Shell ready with no displayed terminal result. | hidden | enabled / enabled when composer non-empty / disabled |
| `PENDING` | User submission worker accepted. | `Processing…` indeterminate | disabled / disabled / enabled |
| `CANCELLATION_REQUESTED` | First cancel request accepted for recovery or submission. | `Cancelling…` indeterminate | disabled / disabled / disabled |
| `CANCELLED` | Terminal `CancelledResult`. | hidden | enabled / enabled when composer non-empty / disabled |
| `CLARIFICATION` | Terminal `ClarificationResult` or matching recovered outcome. | hidden | enabled / enabled when composer non-empty / disabled |
| `SUCCESS` | Terminal `SucceededResult` or matching recovered outcome. | hidden | enabled / enabled when composer non-empty / disabled |
| `CONTROLLED_FAILURE` | Validation exhaustion, concurrency conflict, controlled failure, runtime configuration failure, or submission `ForegroundExecutionFailureView`. | hidden | result-dependent as defined below |
| `BUSY` | `BusyResult`. | hidden | disabled / disabled / disabled |
| `EXISTING_RUN` | `ExistingRunResult`. | hidden | terminality-dependent as defined below |
| `PERSISTENCE_FAILURE` | Submission `PersistenceFailureResult`. | hidden | durable-state-dependent as defined below |
| `RECOVERY_FAILURE` | Direct recovery configuration/persistence failure or recovery-scope start failure. | hidden | disabled / disabled / disabled |
| `SHUTDOWN` | Application close accepted. | `Closing safely…` only while a worker remains | disabled / disabled / disabled |

The initial GUI state is `STARTUP`. Applying `ShellReadyResult` moves to `IDLE`.
Applying `RecoveryRequiredResult` moves to `RECOVERY`. An accepted submission
moves any send-enabled idle/terminal state to `PENDING`. The first accepted
cancel moves `RECOVERY` or `PENDING` to `CANCELLATION_REQUESTED` immediately on
the GUI thread; it does not claim terminal cancellation before the worker result.

Recovery outer results map exactly as follows: `NoRecoveryRequiredResult` moves
to `IDLE`; `RecoveryCompletedResult` maps its `outcome` through the ordinary
terminal table; direct `ConfigurationFailureResult` or
`PersistenceFailureResult` moves to `RECOVERY_FAILURE`; and a recovery
`ForegroundExecutionFailureView` also moves to `RECOVERY_FAILURE`. No recovery
result is mapped to `BUSY` or `EXISTING_RUN`.

Terminal application results map as follows:

| Result | State | Visible content |
|---|---|---|
| `SucceededResult` | `SUCCESS` | exact `assistant_text` only |
| `ClarificationResult` | `CLARIFICATION` | exact `clarification.question_text` only |
| `CancelledResult` | `CANCELLED` | exact persisted `safe_failure.safe_message`, or `The request was cancelled.` for the pre-acceptance null-failure form |
| `ValidationExhaustedResult` | `CONTROLLED_FAILURE` | exact `error.safe_message` |
| `ConcurrencyConflictResult` | `CONTROLLED_FAILURE` | exact `error.safe_message` |
| `ControlledFailureResult` | `CONTROLLED_FAILURE` | exact `error.safe_message` |
| `ConfigurationFailureResult` from submission | `CONTROLLED_FAILURE` | exact `error.safe_message` and optional file/key location; submission remains disabled until restart |
| `BusyResult` | `BUSY` | exact `error.safe_message`; no cancellation control |
| `PersistenceFailureResult` from submission | `PERSISTENCE_FAILURE` | exact `error.safe_message` |

For every displayed terminal result, `status_kind` is that result's exact
`result_kind`; a `RecoveryCompletedResult` is unwrapped and uses its
`outcome.result_kind`, while a `ForegroundExecutionFailureView` uses its own
kind. `assistant_text` carries exact text only for a displayed succeeded result
or a `SUCCEEDED` existing run. `clarification_text` carries exact text only for a
displayed clarification result or `NEEDS_CLARIFICATION` existing run.
`status_message` is non-empty only for the safe
cancellation/failure/busy/non-terminal-existing presentations defined here.
Every unused output field is the empty string. The
startup, pending, cancellation-requested, shutdown, and plain idle states have
an empty `status_kind` and empty terminal-output fields.

For `ExistingRunResult`, the state remains `EXISTING_RUN` so the idempotent
branch is observable. A `SUCCEEDED` existing run displays only its exact
`assistant_text`; `NEEDS_CLARIFICATION` displays only its exact question; a
terminal failure/cancellation displays only `safe_failure.safe_message`; and a
non-terminal existing run displays the presentation constant
`This request is already being processed.` A terminal existing result enables a
new submission; a non-terminal existing result disables it and exposes no cancel
action because the current controller does not own that execution.

`PERSISTENCE_FAILURE` permits another submission only when the returned durable
state proves that no run was accepted (`processing_run_id=null` and
`processing_status=null`) or that best-effort terminalization committed
(`failure_persisted=true` and terminal `processing_status`). It remains disabled
for a known non-terminal durable status or any shape that cannot prove the
global slot is free. `CONTROLLED_FAILURE` permits another submission for every
terminal run result, but not for a runtime `ConfigurationFailureResult` or a
`ForegroundExecutionFailureView`.

The input/submit enablement shown for an ordinary terminal state becomes true
only after the controller has also handled the active worker's queued finished
notification and released that worker. Between terminal-result handling and
finished cleanup, terminal content may be visible but input/submit remain
disabled. The finished notification may update only worker ownership and the
derived enablement; it cannot select or replace a result state.

No terminal state automatically clears or times out. A later accepted submission
clears prior status/assistant/clarification fields before entering `PENDING`.
The composer is cleared only after `submit_exact` returns `true`; suppressed
submissions and failures before worker acceptance preserve it.

## Duplicate submission and cancellation

QML disables submit whenever `submit_enabled=false`. Independently, the
controller atomically refuses `submit_exact` when a worker/scope is active or the
state is `STARTUP`, `RECOVERY`, `PENDING`, `CANCELLATION_REQUESTED`, `BUSY`, a
non-terminal `EXISTING_RUN`, unresolved `PERSISTENCE_FAILURE`,
`RECOVERY_FAILURE`, or `SHUTDOWN`.

Suppression is local presentation behavior, not a synthetic `BusyResult`. It
does not invoke TASK-0014, allocate a second idempotency key/token, replace the
first text, or queue work. The TASK-0014 global active-run and idempotency checks
remain the final persistence race guard for an accepted call.

Cancellation only sets the owned token and changes GUI state to
`CANCELLATION_REQUESTED`. It never calls thread termination, discards a returned
terminal result, edits persistence, or invents partial text. Repeated cancel
requests return `false` and change nothing. The bounded responsiveness promise is
event-loop responsiveness plus observation at the application/gateway
checkpoints; it is not immediate provider termination.

## Progress and safe presentation

Progress is presentation-owned and indeterminate. It reports only `Starting…`,
`Recovering an interrupted request…`, `Processing…`, `Cancelling…`, or
`Closing safely…` from the controller state machine. It exposes no percentage,
pipeline stage, trace event, token count, provider chunk, elapsed estimate, or
candidate text. Presentation must not subscribe to `TraceLogger` or inspect
infrastructure state to derive progress.

The minimum shell may display only:

- byte-exact validated assistant text from `SucceededResult` or terminal
  `ExistingRunResult`;
- the deterministic clarification question;
- the exact safe public messages defined by the closed result/startup mappings;
  and
- configuration file/key where this contract explicitly allows it.

It must hide processing/message/packet/request/response/validation IDs, internal
statuses, checkpoints, failure details, `failed_stage`, configuration values,
paths, raw exceptions, trace data, prompts, provider metadata, validation
evidence, and every unvalidated candidate. Detailed inspection pages may expose
their separately contracted safe evidence only when their later owner is
implemented.

## Queued result delivery and responsiveness

The GUI thread exclusively owns QML, the facade, controller, and all shell state.
The worker never calls a facade method or mutates a QML-visible object. After its
application scope is closed, it emits exactly one terminal envelope containing:

```text
ForegroundTerminalEnvelope {
  execution_id: controller-local immutable identifier,
  execution_kind: SUBMISSION | RECOVERY,
  result: immutable ProcessUserMessageResult | RecoveryResult |
          ForegroundExecutionFailureView
}
```

The worker-to-controller terminal connection is explicitly queued. The
controller handles it on the GUI thread, checks `execution_id` and current
ownership, and applies at most one result-state transition. It releases the
worker only after the matching queued finished notification. A terminal envelope
with an unknown, replaced, already-consumed, or disposed execution ID is ignored
without any UI mutation. A late envelope never re-enables submission or
overwrites a newer result. While in `SHUTDOWN`, the one matching active terminal
envelope is consumed for cleanup but does not replace `SHUTDOWN` or publish its
content; an unknown/duplicate envelope remains ignored.

Only immutable DTOs cross the boundary. A SQLite connection/cursor/row, mutable
repository/domain object, QObject with worker affinity, provider response buffer,
transport object, exception, or configuration object must not cross it.

While a mock gateway is held before its terminal checkpoint, the QML event loop
must continue to process posted events, property reads, repaint/input events, the
first cancellation action, and the close action. The acceptance timeout only
bounds a failed test; it is not a product latency or polling interval. No GUI
operation waits synchronously for provider completion or calls a blocking thread
join while the worker is running.

For each foreground execution, instrumented acceptance evidence must show that
the SQLite connection is created, every repository call occurs, and the
connection closes on the same worker thread, whose identity differs from the GUI
thread. SQLite's thread-affinity checks must not be disabled to make cross-thread
access appear valid.

## Shutdown and disposal

An accepted close request enters `SHUTDOWN` and permanently disables new
submission. With no active worker, the controller disposes and Qt may exit
immediately. With an active worker, the controller requests cancellation once,
keeps the event loop alive, and delays root/controller destruction and final Qt
exit until the terminal envelope has been handled and the worker thread has
finished.

The configured gateway timeout remains the execution bound; the controller does
not add a second transport timeout or force-kill fallback. Cleanup after the
thread's finished notification may release/delete the worker and scope
references. The GUI thread must not block waiting for a still-running worker.
Controller disposal marks every outstanding execution ID unowned; any queued
late delivery is ignored safely.

## QML packaging and loading

Every `.qml` file under `context_for_ai/ui/qml/`, at any nesting depth, is a
runtime package asset. Package configuration must include the root and nested
QML files recursively, or include an equivalent compiled Qt resource collection
that contains the same tree. A direct-only `ui/qml/*.qml` rule is insufficient
once a nested component exists.

The application loads one canonical packaged `Main.qml` resource independent of
the process working directory. Local QML imports resolve only within the packaged
resource tree. Startup must work from both a source checkout and an installed
wheel; it must not fall back to a developer checkout, current-working-directory
path, or unversioned external QML file.

Successful loading creates exactly one root object with
`objectName="contextForAiRoot"`. A missing root/nested asset, unresolved local
import, component creation error, or zero/multiple root object is a `QML_LOAD`
startup failure. Recovery/submission workers start only after this check
succeeds.

## Acceptance ownership

TASK-0015 owns:

- the shell/startup-error/packaged-root portion of AT-001;
- the AT-013 shell-responsiveness portion: pending event-loop liveness,
  cancellation, duplicate suppression, queued-only UI mutation, worker-owned
  connection evidence, immutable result crossing, safe terminal presentation,
  and shutdown; and
- complete mock-provider UI integration only through the final TASK-0014 public
  interfaces.

The later context-inspection owner owns the FR-015 page, its navigation route,
and visible context/reference/retrieval/confidence/validation evidence. Full
AT-013 passes only when both ownership portions pass. TASK-0015 must neither
claim the page portion nor implement a placeholder for it.

## TASK-0016 additive extension

TASK-0016 is that later context-inspection owner. When TASK-0016 is implemented,
`docs/contracts/ContextInspection.md` extends this contract only as follows:

- the complete route set becomes exactly `{CHAT, CONTEXT_INSPECTION}`, while
  `CHAT` remains the initial route and every TASK-0015 chat behavior remains
  unchanged;
- the existing entry-point-owned `ShellFacade` remains the sole QObject and
  presentation-state owner exposed to QML, and gains only the inspection route,
  actions, safe primitive/list-model projection, announcement properties, and
  orthogonal page state defined there;
- `ShellApplicationScopeFactory` gains
  `open_inspection_scope() -> InspectionApplicationScope`, whose sole use case is
  `inspect_context: InspectContext` and whose separate SQLite connection is
  created, used, and closed on the inspection worker thread;
- one finite read-only inspection worker may coexist with the sole foreground
  worker because neither shares a scope, connection, transaction, repository,
  worker object, or processing-run admission slot;
- inspection invalidation may coalesce to one boolean follow-up refresh but may
  never create a queue, poller, persistent thread, timer, or forced termination;
  and
- final Qt disposal waits asynchronously for both owned worker kinds, if
  present, to deliver their queued cleanup notifications and close their scopes.

The facade interface and scope algebra above remain the exact TASK-0015 slice;
their complete post-TASK-0016 additive form is normative in
`docs/contracts/ContextInspection.md`. Its explicitly closed safe-evidence
allowlist is the only exception to TASK-0015's minimum-shell display restriction.
It does not permit prompts, candidate responses, unsafe details, open DTOs, or
presentation-side joins.

## Prohibited behavior

Direct QML-to-SQL, QML-to-context-engine, QML-to-gateway/Ollama, raw application
DTO branching in QML, progress from traces, token streaming, provider routing,
an API server, a persistent worker, a queue, polling, force termination,
cross-thread SQLite use, automatic recovery retry, raw diagnostic display,
unvalidated candidate display, and deferred-page placeholders are prohibited.
