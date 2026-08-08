# ProcessUserMessage Contract

## Authority and responsibility

`ProcessUserMessage` is the public application use case that coordinates one
idempotent user-message pipeline. It owns admission, transaction ordering,
foreground cancellation checks, provider invocation, validation/correction
coordination, terminalization, and returned application results. It does not
own context rules, SQL, provider-specific transport, UI state, or an autonomous
worker.

`RecoverProcessingRun` is the separate public application use case that resumes
the one possible accepted non-terminal run after process startup. Its bounded
foreground contract is defined below.

## Public submission call

```text
ProcessUserMessageRequest {
  conversation_id: uuid,
  user_text: exact string,
  idempotency_key: uuid,
  project_id: uuid or null
}

ProcessUserMessage.execute(
  request: ProcessUserMessageRequest,
  cancellation_token: CancellationToken
) -> ProcessUserMessageResult
```

The caller owns the UUID idempotency key and the monotonic thread-safe token.
`user_text` is not trimmed, normalized, repaired, or regenerated. Configuration
loading/validation and immutable snapshot acquisition occur before admission.
A failure there returns `ConfigurationFailureResult` and performs no repository
read or write.

## Exhaustive public result algebra

```text
ProcessUserMessageResult =
    SucceededResult
  | ExistingRunResult
  | BusyResult
  | ClarificationResult
  | CancelledResult
  | ValidationExhaustedResult
  | ConfigurationFailureResult
  | PersistenceFailureResult
  | ConcurrencyConflictResult
  | ControlledFailureResult
```

The following projections are closed. A named object contains exactly its
listed fields; adding a nullable catch-all error/payload field is prohibited.
`current_state` is the persisted conversation state loaded after the applicable
commit. `latest_validation_result` is the result for the greatest persisted
attempt number, or null when no candidate was committed.

```text
SucceededResult {
  result_kind: "SUCCEEDED",
  processing_run_id: uuid,
  user_message_id: uuid,
  processing_status: SUCCEEDED,
  current_state: ConversationState,
  context_packet_id: uuid,
  latest_validation_result: ValidationResult(status=PASSED),
  assistant_message_id: uuid,
  assistant_text: exact string
}

ExistingRunResult {
  result_kind: "EXISTING_RUN",
  processing_run_id: uuid,
  user_message_id: uuid,
  processing_status: any ProcessingRunStatus,
  current_state: ConversationState,
  context_packet_id: uuid or null,
  latest_validation_result: ValidationResult or null,
  assistant_message_id: uuid or null,
  assistant_text: exact string or null,
  clarification: ClarificationRequest or null,
  safe_failure: SafeFailure or null
}

BusyErrorValue {
  code: "BUSY",
  safe_message: "Another request is already being processed.",
  active_processing_run_id: uuid,
  active_processing_status: PERSISTED | CONTEXT_READY | GENERATING | REVISING
}

BusyResult {
  result_kind: "BUSY",
  active_processing_run_id: uuid,
  active_processing_status: PERSISTED | CONTEXT_READY | GENERATING | REVISING,
  error: BusyErrorValue
}

ClarificationResult {
  result_kind: "CLARIFICATION_REQUIRED",
  processing_run_id: uuid,
  user_message_id: uuid,
  processing_status: NEEDS_CLARIFICATION,
  current_state: ConversationState,
  context_packet_id: null,
  latest_validation_result: null,
  clarification: ClarificationRequest
}

CancelledResult {
  result_kind: "CANCELLED",
  processing_run_id: uuid or null,
  user_message_id: uuid or null,
  processing_status: CANCELLED or null,
  current_state: ConversationState or null,
  context_packet_id: uuid or null,
  latest_validation_result: ValidationResult or null,
  cancellation_code: CANCELLED_BY_USER | MODEL_CANCELLED,
  checkpoint: BEFORE_ACCEPTANCE | AFTER_ACCEPTANCE |
              CONTEXT_CONSTRUCTION | BEFORE_REQUEST_PREPARATION |
              GATEWAY,
  safe_failure: SafeFailure or null,
  failure_persisted: boolean
}

ValidationExhaustedResult {
  result_kind: "VALIDATION_EXHAUSTED",
  processing_run_id: uuid,
  user_message_id: uuid,
  processing_status: CONTROLLED_FAILURE,
  current_state: ConversationState,
  context_packet_id: uuid,
  latest_validation_result: ValidationResult(status=FAILED),
  error: ValidationExhaustedErrorValue,
  safe_failure: SafeFailure(error_code=VALIDATION_EXHAUSTED)
}

ValidationExhaustedErrorValue {
  code: VALIDATION_EXHAUSTED,
  safe_message: "The response did not pass validation."
}

ConfigurationErrorValue {
  code: CONFIGURATION_INVALID,
  safe_message: "The application configuration is invalid.",
  file: non-empty configuration file name,
  key: non-empty dotted key path
}

ConfigurationFailureResult {
  result_kind: "CONFIGURATION_FAILURE",
  error: ConfigurationErrorValue
}

PersistenceErrorValue {
  code: PERSISTENCE_ERROR,
  safe_message: "Processing could not be saved safely.",
  failed_stage: PipelineStage
}

PersistenceFailureResult {
  result_kind: "PERSISTENCE_FAILURE",
  processing_run_id: uuid or null,
  user_message_id: uuid or null,
  processing_status: ProcessingRunStatus or null,
  current_state: ConversationState or null,
  context_packet_id: uuid or null,
  latest_validation_result: ValidationResult or null,
  error: PersistenceErrorValue,
  safe_failure: SafeFailure(error_code=PERSISTENCE_ERROR) or null,
  failure_persisted: boolean
}

ConcurrencyConflictResult {
  result_kind: "CONCURRENCY_CONFLICT",
  processing_run_id: uuid,
  user_message_id: uuid,
  processing_status: FAILED,
  current_state: ConversationState,
  context_packet_id: null,
  latest_validation_result: null,
  error: ConcurrencyConflictErrorValue,
  safe_failure: SafeFailure(error_code=CONCURRENCY_CONFLICT)
}

ConcurrencyConflictErrorValue {
  code: CONCURRENCY_CONFLICT,
  safe_message: "The conversation changed while context was being prepared."
}

ControlledFailureError {
  code: CONTEXT_BUDGET_EXCEEDED | CONTEXT_CONSTRUCTION_FAILED |
        CONFIGURATION_CHANGED | PROCESS_RESTARTED | PERSISTENCE_ERROR |
        PROVIDER_UNAVAILABLE | MODEL_NOT_FOUND | MODEL_TIMEOUT |
        INVALID_PROVIDER_RESPONSE,
  safe_message: exact SafeFailure.safe_message
}

ControlledFailureResult {
  result_kind: "CONTROLLED_FAILURE",
  processing_run_id: uuid,
  user_message_id: uuid,
  processing_status: CONTROLLED_FAILURE | FAILED,
  current_state: ConversationState,
  context_packet_id: uuid or null,
  latest_validation_result: ValidationResult or null,
  error: ControlledFailureError,
  safe_failure: SafeFailure
}
```

For `ExistingRunResult`, assistant ID and text are both non-null exactly for a
`SUCCEEDED` run; clarification is non-null exactly for
`NEEDS_CLARIFICATION`; and `safe_failure` is non-null exactly for a terminal
failure/cancellation. A non-terminal existing result has none of those three
terminal payloads. Its returned snapshot is reconstructed from existing durable
records; returning it creates no row and invokes no context component or
provider.

A pre-acceptance cancellation is the only `CancelledResult` with null run,
message, status, state, packet, validation, and failure, and has
`checkpoint=BEFORE_ACCEPTANCE`, `cancellation_code=CANCELLED_BY_USER`, and
`failure_persisted=false`. Every accepted cancellation has both IDs, terminal
status, state, and a durably persisted failure. If that persistence fails, the
return is `PersistenceFailureResult`, never a cancellation result that claims a
write succeeded.

`PersistenceFailureResult.failure_persisted=true` requires a non-null accepted
run/message, `processing_status=FAILED`, and the exact persisted failure.
`failure_persisted=false` reports the last status that is known to be durable,
or null when acceptance rolled back. No process result ever contains candidate
response text except `SucceededResult.assistant_text` or the already accepted
assistant text reconstructed by `ExistingRunResult`.

## Returned conditions and remaining exceptions

Every expected operational condition in the result algebra is a returned value,
not an application exception. This includes configuration, repository,
concurrency, context, clarification, budget, transport, cancellation, validation
exhaustion, recovery, and terminalization failures. Gateway failures remain the
returned `GenerationOutcome` values defined by `ModelGateway.md` until the
application maps them to one public result.

Only malformed public input, an invalid dependency/composition graph, or a
programming invariant violated before the use-case execution boundary may raise
`DomainValidationError`, `LifecycleInvariantError`, or
`InvalidStateTransitionError`. Such exceptions are defects, not UI outcomes.
After a message is accepted, the application boundary converts a context
component/integrity failure to the authoritative generic context or recovery
projection in `Persistence.md`; it does not expose an implementation exception.

The closed `*ErrorValue` objects and `ControlledFailureError` are immutable
result payloads, not raised exceptions. The existing application vocabulary
`ValidationExhaustedError`, `ConcurrencyConflictError`,
`ContextConstructionError`, and `ContextBudgetExceededError` identifies the
corresponding typed result/error family at this boundary; the database stores
only its canonical `SafeFailure` projection, never an exception object.

## Admission order and race result

After successful request/configuration validation, one acceptance transaction
performs this exact order:

1. Look up `(conversation_id, idempotency_key)`.
2. If found, commit no mutation and return `ExistingRunResult`. This branch wins
   even when the stored run is the global active run. Text or project values on
   a duplicate invocation are ignored; the first accepted submission is the
   sole authority for that key.
3. If the key is new, read the one global non-terminal run. If present, commit
   no mutation and return `BusyResult` with that run. The check is global, not
   per conversation.
4. If no run is active and the token is already cancelled, commit no mutation
   and return the pre-acceptance `CancelledResult`.
5. Otherwise append the exact `USER` message, apply the optional explicit
   active-project selection and its one state-version increment, create the
   `PERSISTED` run whose `state_version_at_start` is the resulting committed
   state version, and commit atomically.

The schema's global partial unique index is the final race guard. If concurrent
acceptance loses that index race, the repository captures the conflicting
durable row while the losing transaction still holds its admission boundary,
then rolls back all loser writes. A matching key becomes `ExistingRunResult`; a
different key becomes `BusyResult` using the captured non-terminal ID/status.
If a uniqueness violation cannot identify either row, the repository contract
itself failed and the loser returns the no-durable-ID acceptance
`PersistenceFailureResult`. No classification read occurs after releasing the
boundary, so a fast terminal transition cannot make the result ambiguous. An
expected identified race is neither a persistence failure nor the context-stage
compare-and-swap conflict.

If any other mandatory acceptance read or write fails, the whole transaction
rolls back. The application returns `PersistenceFailureResult` with all durable
IDs, status, state, packet, validation, and failure null and
`failure_persisted=false`. It does not recreate a user message/run merely to
terminalize and does not attempt a foreign-key-impossible `pipeline_failures`
insert.

## Canonical execution order

After acceptance commits, the foreground execution proceeds in this order:

1. Build deterministic interpretation, references, constraints, proposed state,
   retrieval, and packet inputs from the accepted version snapshot.
2. Commit the one joined context transaction described by `Persistence.md` and
   `ContextPacket.md`. Clarification and context failure branches terminalize
   there; only successful packet construction commits a derived state change,
   packet, and `CONTEXT_READY`.
3. Prepare one `PENDING` initial/revision request in a short transaction, then
   claim it as `IN_FLIGHT` in a second short transaction.
4. Call `ModelGateway.generate` outside every database transaction.
5. For a completed generation, commit the response and exact deterministic
   validation report in the candidate transaction. Candidate text is not yet
   assistant text.
6. On a pass, commit the byte-exact assistant link and `SUCCEEDED`. On a failed
   validation, call the pure correction controller. Either commit one adjacent
   correction/request pair and repeat from request claim, or commit the exact
   validation-exhaustion terminal projection.
7. Map transport, cancellation, persistence, recovery, and controlled failures
   only through the exact projections in the owning contracts.

The immutable packet's `response_policy.correction_limit` is the sole revision
limit. No transport failure or uncertain call is retried. No branch mutates
memory automatically or exposes an invalid candidate as final output.

## Cancellation ownership and checkpoints

The foreground caller creates one token per submission/recovery execution and
is the only component allowed to move it monotonically to cancelled. The
application and gateway only observe it. It is never persisted, reset, or
reconstructed after restart.

Application cancellation checks occur at exactly these checkpoints:

| Checkpoint | Durable run before check | Result when cancelled |
|---|---|---|
| `BEFORE_ACCEPTANCE` | none | Unpersisted `CancelledResult`; no message/run/failure. |
| `AFTER_ACCEPTANCE` | `PERSISTED` | Discard not-yet-started context work and persist `CANCELLED_BY_USER`. |
| `CONTEXT_CONSTRUCTION` | `PERSISTED` | Check between pure context phases and immediately before the context transaction; discard all in-memory decisions and persist `CANCELLED_BY_USER`. |
| `BEFORE_REQUEST_PREPARATION` | `CONTEXT_READY`, or `GENERATING`/`REVISING` immediately after a failed validated candidate and before correction planning/rendering | Persist `CANCELLED_BY_USER`; create no new request/correction. Any prior succeeded request remains unchanged. |
| `GATEWAY` | request `IN_FLIGHT`; run `GENERATING` or `REVISING` | Gateway returns `ModelCancelledFailure`; persist its `MODEL_CANCELLED` mapping. |

There is no application cancellation check between committing a `PENDING`
request, claiming it, and entering the gateway. This closes the handoff without
inventing a `PENDING -> CANCELLED` transition. A recovered `PENDING` request is
likewise claimed and passed to the gateway; a pre-cancelled fresh recovery token
is observed on gateway entry before provider work begins. Cancellation after a
`CompletedGeneration` has returned is not retroactive; candidate validation and
safe terminalization continue. At an application checkpoint, observed
cancellation wins over an in-memory continuation that has not selected a
terminal result. Once correction rendering returns its typed budget-overflow
terminal result, later cancellation is likewise not retroactive.

The exact pre-gateway application projection and legal
`PERSISTED|CONTEXT_READY|GENERATING|REVISING -> CANCELLED` transitions are in
`Persistence.md` and `DomainAndDecisionRules.md`. During a provider wait,
cancellation ordering is owned by `ModelGateway.md`.

## Public recovery entry

```text
RecoverProcessingRunRequest {}

NoRecoveryRequiredResult {
  result_kind: "NO_RECOVERY_REQUIRED"
}

RecoveryCompletedResult {
  result_kind: "RECOVERY_COMPLETED",
  processing_run_id: uuid,
  outcome: SucceededResult | ClarificationResult | CancelledResult |
           ValidationExhaustedResult | ConcurrencyConflictResult |
           ControlledFailureResult
}

RecoveryResult =
    NoRecoveryRequiredResult
  | RecoveryCompletedResult
  | ConfigurationFailureResult
  | PersistenceFailureResult

RecoverProcessingRun.execute(
  request: RecoverProcessingRunRequest,
  cancellation_token: CancellationToken
) -> RecoveryResult
```

The request is deliberately empty: recovery selects only the repository's one
global non-terminal run and accepts no caller-selected run, conversation,
attempt, or retry policy. A successful terminalization is wrapped in
`RecoveryCompletedResult`; configuration or persistence inability is returned
directly because no completed recovery may be claimed. A recovered
`CancelledResult` is necessarily the accepted form with non-null run/message and
durable failure; recovery can never produce the pre-acceptance cancellation
shape.

TASK-0015 presentation startup first calls the separate
`PrepareApplicationShell` application entry defined by
`PresentationShell.md`. Its read-only preflight neither classifies nor resumes a
run. When preflight reports no active run, presentation does not invoke this use
case and starts no foreground worker. When preflight reports one active run,
presentation loads the shell in its disabled recovery state and invokes this use
case exactly once before enabling submissions.

That one finite foreground invocation uses a fresh owned token and the same
bounded gateway timeout rules as a submission. The visible foreground controller
hosts it without enqueueing, polling, scheduling, detaching, or keeping a daemon
alive. `RecoverProcessingRun` still performs its own authoritative lookup and
may return `NoRecoveryRequiredResult` if state changed after preflight or when a
non-presentation caller invokes it directly. The application use case itself
never creates a worker in either branch.

Recovery first validates the current immutable configuration snapshot, loads
the one run and lineage, compares fingerprints, then applies exactly one row of
the recovery matrix in `Persistence.md`. It never repeats an `IN_FLIGHT` call,
never selects a second run, and never loops after a returned persistence
failure. A later explicit startup invocation may inspect the remaining durable
state again. Recovery classification has precedence over cancellation: invalid
current configuration returns configuration failure; fingerprint mismatch,
impossible lineage, an uncertain call, or an already completed candidate is
handled by its matrix projection. The fresh token is checked only before a
resumable deterministic phase or new request handoff, so cancellation cannot
rewrite an already durable provider/validation outcome.

## Required inward surfaces

Both use cases receive the already-defined repository ports, connection-local
`TransactionBoundary`, deterministic context components and packet stage,
`ModelGateway`, `ResponseValidator`, `CorrectionController`, immutable validated
configuration snapshot access, `Clock`, `IdGenerator`, and `TraceLogger` through
composition. `RecoverProcessingRun` additionally uses only the same lineage
queries required to classify the matrix; it introduces no scheduler, queue,
worker repository, retry policy, or provider-specific dependency. The outer
composition root remains the only constructor of concrete SQLite, logging, and
gateway adapters.

## Trace and ownership boundaries

Application trace emission uses only `TraceLogger.emit(TraceEvent)`. The exact
events, correlations, stages, redaction, commit-relative ordering, and recovery
ordering are authoritative in `ConfigurationAndLogging.md`. Trace emission is
not a transaction participant; an adapter logging failure cannot roll back a
commit or change the public result.

TASK-0013 owns pure validation/correction decisions and bounded repository
projection evidence from preconstructed lineage. TASK-0014 owns the public
submission/recovery use cases, provider-facing transaction sequence, repeated
candidate/correction lifecycle, assistant linkage, and complete AT-002, AT-012,
and AT-015 application acceptance. This split does not move SQL, context rules,
gateway transport, or presentation ownership into the application use case.
TASK-0015 owns only the separate shell preflight, foreground presentation, and
worker composition described by `PresentationShell.md`; it does not alter this
public algebra or any TASK-0014 transaction/recovery decision.

## Prohibited behavior

Direct SQL, provider-specific HTTP, QML/UI mutation, model routing, hidden
requirement inference, automatic memory mutation, content logging, an
unbounded/transport retry, a background queue, polling recovery, daemon work,
or displaying an unvalidated candidate is prohibited.
