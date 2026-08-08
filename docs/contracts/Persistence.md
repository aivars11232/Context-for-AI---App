# Persistence Contracts

## Boundary

`DATABASE_SCHEMA.md` is the canonical logical schema. Repositories expose
domain objects and typed operations; domain, context-intelligence, and
application code must not depend on SQLite rows or SQL strings.

## Required repositories

- `ProjectRepository`
- `ConversationRepository`
- `TopicRepository`
- `TaskRepository`
- `ConversationStateRepository`
- `MessageRepository`
- `EntityRepository`
- `ReferenceResolutionRepository`
- `ConstraintRepository`
- `MemoryRepository` (including sources and revisions)
- `ProcessingRunRepository`
- `ContextPacketRepository` (including retrieval results and retrieval exclusions)
- `ModelCallRepository` (requests, responses, corrections, failures)
- `ValidationRepository`
- `ClarificationRepository`
- `SettingsRepository`
- `EvaluationRepository`

## Transaction joining and rollback

`TransactionBoundary.transaction()` is re-entrant only within one synchronous
execution and its one repository connection. The first call opens the physical
transaction and is the sole owner of commit/rollback. A nested call joins that
transaction: it opens no savepoint or second connection and cannot commit
independently. An exception or typed write failure at any joined depth marks the
outer transaction for rollback; the outermost exit rolls back every joined
write.

A new best-effort terminalization or retry transaction is opened only after the
failed outer transaction has exited and rolled back. Transaction context never
crosses a thread, gateway call, queued signal, or use-case return. Calling a
repository with a different connection while a joined transaction is active is
a composition error.

These semantics allow the TASK-0010 `ContextPacketStage` to retain standalone
transaction ownership while joining TASK-0014's wider context transaction when
called by `ProcessUserMessage`. There is one physical commit and no partial
context projection.

## TASK-0015 connection and thread ownership

`PresentationShell.md` defines two composition scope kinds. Each scope creates
its repositories, connection-local `TransactionBoundary`, and SQLite connection
on the calling thread and closes the connection on that same thread.

- The pre-QML `StartupApplicationScope` is opened synchronously before a Qt
  application, controller, or QML object exists. It performs only the recovery
  preflight and initial-conversation selection/first-run creation, then closes.
  Migration bootstrap uses a separate earlier short-lived connection. Neither
  connection is retained into GUI startup.
- A `ForegroundApplicationScope` is opened inside the one ephemeral worker for
  an accepted submission or required recovery. Every repository operation for
  that execution uses that scope's single worker-owned connection. The scope
  closes before the worker emits its immutable terminal envelope.

No connection, transaction context, cursor, SQLite row, or repository instance
crosses the startup/GUI/worker boundaries. The GUI-owned controller and QML
never receive or invoke one. Disabling SQLite thread-affinity enforcement or
constructing a connection on the GUI thread for later worker use is prohibited.
Non-SQLite immutable application result DTOs may cross only through the queued
terminal handoff defined by `PresentationShell.md`.

## Canonical transaction boundaries

No SQLite transaction is held during a gateway/provider call.
`ProcessUserMessage` uses these transactions in order:

1. **Acceptance transaction.** Perform the idempotency lookup, global active-run
   check, cancellation check, exact user-message append, optional explicit
   project/state-version change, and `PERSISTED` run creation in the exact order
   in `ProcessUserMessage.md`. An existing key or busy/cancelled pre-acceptance
   branch writes nothing. The partial unique index is the final global race
   guard.
2. **Joined context transaction.** Pure interpretation, reference, constraint,
   state-transition, retrieval, and packet inputs are computed from one state
   version outside the transaction. Within one outer transaction, call
   `ContextPacketStage.execute`; only on packet success, persist the
   contract-defined reference/constraint projections and compare-and-swap the
   proposed conversation state. The packet stage's inner boundary joins the
   outer boundary and atomically adds the packet/retrieval aggregate and moves
   the run to `CONTEXT_READY`. A false compare-and-swap rolls the whole joined
   transaction back, including packet, retrieval, decisions, and run status.
   Clarification is detected before packet construction and instead atomically
   persists the produced reference/constraint evidence, exactly one
   clarification row, and `NEEDS_CLARIFICATION`; it performs no derived state
   write. Initial packet-budget overflow uses the joined packet-stage failure
   projection and commits no reference, constraint, retrieval, packet, or
   derived-state projection. Generic context failure
   commits no partial context decision and uses its fresh terminal transaction.
3. **Request preparation and claim transactions.** For an initial request,
   create one `PENDING` request and move the run to `GENERATING`. For a revision,
   atomically create the adjacent `PENDING` request and correction row and move
   or retain the run in `REVISING`. Commit. In a second short transaction,
   change that request from `PENDING` to `IN_FLIGHT` and set `started_at`; commit
   immediately before entering the gateway.
4. **Candidate or transport transaction.** A completed generation uses one
   injected clock reading for request `completed_at`, response `created_at`, and
   validation `created_at`; it marks the request `SUCCEEDED`, adds the exact
   response, runs deterministic validation against the immutable packet, and
   adds the report atomically. Candidate text is not eligible for assistant
   linkage here. A returned gateway failure instead updates the request, adds
   its exact terminal failure, and terminalizes the run in one transaction as
   specified by `ModelGateway.md`.
5. **Terminal transaction.** A validation pass creates the linked assistant
   message and marks the run `SUCCEEDED`; deterministic state already committed
   with the packet and is not updated again. Exhaustion, application
   cancellation, correction-budget failure, concurrency conflict, and recovery
   failure use the exact terminal projections below. Memory records are never
   automatically changed.

All trace events describing a commit are emitted after that outermost commit,
never from inside the transaction.

## Durable interpretation and context projection

There is no separate interpretation table in the MVP and no schema change is
required for TASK-0014. “Persist context decisions” means only these existing
authoritative projections:

- On successful packet construction, `context_packets.packet_json.request`
  contains the exact durable intent, rule ID, output type, qualifiers, source
  text, and confidence. The packet plus `reference_resolutions`, `constraints`,
  retrieval rows, and committed `conversation_states` version is the complete
  successful context projection.
- On clarification, `clarification_requests.reason_code`, `question_text`, and
  closed `details_json` are the authority for the blocking decision. Any
  produced reference and constraint evidence is stored in its existing tables.
  A full non-blocking interpretation object is not promised or reconstructed,
  and no packet/state update is written.
- On initial context-budget failure, the canonical `pipeline_failures` row is
  the sole durable context decision. No reference, constraint, packet,
  retrieval, or derived state row from that computation is written, and no full
  interpretation projection is promised.

Application code must not invent an interpretation JSON blob in a request,
failure, trace event, or unrelated table to compensate for the absence of a
dedicated table.

## Closed model-request projection

`model_requests.request_json` has exactly this schema:

```text
{
  "schema_version": "mvp-model-request-v1",
  "correlation": {
    "processing_run_id": <uuid>,
    "context_packet_id": <uuid>,
    "model_request_id": <uuid>,
    "attempt_number": <0 | 1 | 2>
  },
  "generation_settings": {
    "context_window_tokens": <integer >= 1024>,
    "request_timeout_seconds": <integer 1..300>,
    "temperature_decimal": <canonical base-10 string>
  },
  "rendering": {
    "render_kind": "INITIAL" | "CORRECTION",
    "prompt_policy_version": "mvp-prompt-policy-v1",
    "estimated_prompt_tokens": <non-negative integer>,
    "effective_prompt_budget": <non-negative integer>,
    "included_sections": [<canonical section>, ...],
    "omitted_sections": [<canonical OmissionRecord>, ...]
  }
}
```

The decimal string uses no exponent or leading plus, removes insignificant
trailing fractional zeroes and the decimal point when empty, and represents
zero as `"0"`. Correlation fields equal the row/foreign-key values. Settings and
rendering fields equal the exact `GenerationRequest` and `PromptRenderResult`
inputs. `rendered_prompt` remains the separate column and is byte-for-byte the
render result; it is not duplicated in JSON. Provider, model name, and purpose
remain their typed columns and are not duplicated.

For attempt `0`, purpose is `INITIAL`, render kind is `INITIAL`, and no
correction row exists. For attempt `N` in `1..2`, purpose is `REVISION`, render
kind is `CORRECTION`, and exactly one `correction_attempts` row for `N` points to
this request and the immediately preceding failed response. `request_json` is
render/settings evidence, not a second correction-envelope authority.

## Closed completed-response projection

`model_responses.metadata_json` has exactly this outer schema:

```text
{
  "schema_version": "mvp-completed-generation-v1",
  "correlation": {
    "processing_run_id": <uuid>,
    "context_packet_id": <uuid>,
    "model_request_id": <uuid>,
    "model_response_id": <uuid>,
    "attempt_number": <0 | 1 | 2>
  },
  "elapsed_microseconds": <non-negative integer>,
  "token_usage": null | {
    "prompt_tokens": <non-negative integer or null>,
    "generated_tokens": <non-negative integer or null>,
    "total_tokens": <non-negative integer or null>
  },
  "provider_metadata": <exact normalized provider metadata object>
}
```

`elapsed_microseconds` is the exact non-negative
`CompletedGeneration.elapsed` duration expressed as integral microseconds; no
floating-point seconds are stored. Token usage preserves nulls value-for-value.
Correlation is derived from the persisted request plus the application-allocated
response ID and must agree with all columns/lineage.

`provider_metadata` is copied value-for-value from the already normalized,
recursively immutable `CompletedGeneration.provider_metadata`; the application
does not enrich or re-filter it. For the sole MVP runtime provider, it has
exactly the allowlisted keys and value rules in `OllamaAdapter.md`. A mock
fixture supplies its exact safe object explicitly, and persistence equality
assertions compare that object exactly. Prompt, response, partial content, raw
provider objects/exceptions, headers, endpoints, and secrets are prohibited.

## Validation, correction, and exhaustion projections

`ValidationRepository` persists the exact closed `ValidationResult` from
`ResponseValidation.md`. `violations_json` is the ordered array of failing
`ValidationViolation` objects only. `evidence_json` is the complete ordered
array of `ValidationEvidence`, including `WARNING` items. Warnings are never
duplicated into `violations_json`; `NOT_RUN` is never written for a received
candidate; repositories do not recompute status, score, ordering, or
deduplication.

The pure correction controller writes nothing. When it returns a
`CorrectionEnvelope` and rendering succeeds, request preparation atomically
creates:

- the one `PENDING` `REVISION` request for envelope attempt `N`; and
- one `correction_attempts` row with attempt `N`, the immediately failed
  response ID, the new request ID, and `reason_json` value-for-value equal to the
  envelope's ordered `violations` array.

`reason_json` contains no warning, candidate text, match location, or full
validation evidence. A correction row is not created for exhaustion, invalid
lineage, correction-render overflow, or a rolled-back revised request. The row
and request either both commit or neither does.

The envelope is reconstructed for inspection/recovery from contract constants,
the immutable packet, correction row, revised request, and `reason_json`. The
request/row must satisfy the same-run adjacent-attempt rules; `request_json` is
not a second envelope authority.

For validation exhaustion, the final candidate transaction first commits the
failed response/report. A separate terminal transaction persists exactly the
`VALIDATION/VALIDATION_EXHAUSTED` projection in `ResponseValidation.md`, with
`created_at` and run `completed_at` from one clock reading. No correction row or
assistant message is created. TASK-0013 owns bounded component/repository
evidence from preconstructed values; TASK-0014 owns this complete lifecycle.

## Assistant-message content and linkage

On a passing validation, the application constructs the final `ASSISTANT`
message with `messages.original_text.encode("utf-8")` byte-for-byte equal to
the accepted `model_responses.response_text.encode("utf-8")`. No Unicode
normalization, trimming, newline conversion, prefix, or suffix is permitted.

The terminal transaction atomically appends that message, calls
`ModelCallRepository.link_assistant_message`, and moves the run to
`SUCCEEDED`. The application checks equality before writing; the repository
link operation independently reloads the response/message and rejects a role,
conversation, passed-validation, or UTF-8 byte-equality mismatch before commit.
Linking is idempotent only for the same assistant ID. Public-use-case acceptance
tests assert both persisted values and the returned assistant text.

## Exact safe-failure projections

Unless an owning predecessor contract explicitly supplies the timestamp/ID
(the TASK-0010 initial-overflow projection), TASK-0014 allocates one failure ID
immediately before the fresh terminal transaction and reads the injected clock
once. That instant is used for `SafeFailure.created_at`, run `completed_at`, and
any request completion performed by the same transaction. If the transaction
rolls back, the unused ID/time do not authorize a retry or persisted claim.

Gateway failures use the exact mapping in `ModelGateway.md`; validation
exhaustion uses `ResponseValidation.md`; initial packet overflow uses
`ContextPacket.md`. The remaining TASK-0014 projections are authoritative
below.

### Correction-render budget overflow

```text
typed result: ControlledFailureResult(ContextBudgetExceededError)
stage/code: CORRECTION / CONTEXT_BUDGET_EXCEEDED
run: GENERATING|REVISING -> CONTROLLED_FAILURE
request: immediately failed SUCCEEDED request remains SUCCEEDED
safe_message: "The correction context exceeds the configured prompt budget."
details: {
  phase: "CORRECTION",
  context_packet_id: <uuid>,
  failed_model_response_id: <uuid>,
  attempt_number: <proposed correction attempt 1 | 2>,
  token_estimator: "conservative_utf8_v1",
  estimated_required_tokens: <non-negative integer>,
  effective_prompt_budget: <non-negative integer>
}
```

No revised request, correction row, response, validation, or assistant message
is created. The failed candidate/report and immutable packet remain durable.

### Second state compare-and-swap conflict

The first false compare-and-swap rolls back the entire joined context
transaction, reloads the state, and recomputes only pure deterministic context
once. Every ID/time allocated solely for the rolled-back first context attempt
is discarded; the retry obtains fresh deterministic `IdGenerator`/`Clock`
values and emits no trace for the rolled-back attempt. A second false result
rolls back again, then uses a fresh transaction:

```text
typed result: ConcurrencyConflictResult(ConcurrencyConflictError)
stage/code: CONTEXT / CONCURRENCY_CONFLICT
run: PERSISTED -> FAILED
request: none
safe_message: "The conversation changed while context was being prepared."
details: {
  conversation_id: <uuid>,
  expected_state_version: <version used by the second attempt>,
  observed_state_version: <version loaded after its failed CAS>,
  retry_count: 1
}
```

No context packet, reference, constraint, retrieval, model, validation,
correction, or assistant row from either rolled-back attempt remains.

### Pre-gateway application cancellation

```text
typed result: CancelledResult(cancellation_code=CANCELLED_BY_USER)
code: CANCELLED_BY_USER
run: PERSISTED|CONTEXT_READY|GENERATING|REVISING -> CANCELLED
request: create no new request; any prior terminal SUCCEEDED request remains
         unchanged; a current PENDING/IN_FLIGHT request follows gateway/recovery
         handling instead
safe_message: "The request was cancelled."
details: {
  checkpoint: "AFTER_ACCEPTANCE" | "CONTEXT_CONSTRUCTION" |
              "BEFORE_REQUEST_PREPARATION",
  context_packet_id: <uuid or null>
}
```

Stage is `CONTEXT` for `AFTER_ACCEPTANCE` and `CONTEXT_CONSTRUCTION`, with null
packet ID. Stage is `REQUEST` for `BEFORE_REQUEST_PREPARATION`, with the durable
packet ID. The failure and terminal run update commit atomically. Pre-acceptance
cancellation has no durable projection.

### Changed configuration during recovery

```text
typed result: ControlledFailureResult
stage/code: RECOVERY / CONFIGURATION_CHANGED
run: any non-terminal status -> FAILED
request: unchanged; no provider call
safe_message: "The application configuration changed before processing could resume."
details: {
  stored_configuration_fingerprint: <non-empty string>,
  current_configuration_fingerprint: <non-empty string>,
  prior_run_status: PERSISTED | CONTEXT_READY | GENERATING | REVISING
}
```

No packet is rebuilt and no existing context/model artifact is rewritten.

### Restart with an uncertain model call

For `GENERATING|REVISING` with an `IN_FLIGHT` request and no durable response:

```text
typed result: ControlledFailureResult
stage/code: RECOVERY / PROCESS_RESTARTED
run: GENERATING|REVISING -> FAILED
request: IN_FLIGHT -> FAILED
request.error_code: PROCESS_RESTARTED
request.safe_error_message: "The interrupted model request cannot be safely repeated."
safe_message: "The interrupted model request cannot be safely repeated."
details: {
  model_request_id: <uuid>,
  attempt_number: <0 | 1 | 2>,
  context_packet_id: <uuid>,
  prior_request_status: "IN_FLIGHT"
}
```

The same clock instant completes the request, failure, and run. No response is
invented and the provider is never called again for that attempt.

### Impossible recovery state

The closed `recovery_reason` values, in selection precedence, are:

```text
MISSING_REQUIRED_PACKET
PACKET_STATUS_MISMATCH
DUPLICATE_REQUEST_ATTEMPT
REQUEST_PACKET_MISMATCH
RESPONSE_REQUEST_MISMATCH
VALIDATION_RESPONSE_MISMATCH
ASSISTANT_VALIDATION_MISMATCH
CORRECTION_LINEAGE_MISMATCH
STATUS_ARTIFACT_MISMATCH
```

When more than one invariant fails, persist the first value in that order.
`model_request_id`/`attempt_number` identify the lexicographically smallest
relevant request ID and its attempt, or are both null when none exists.

```text
typed result: ControlledFailureResult
stage/code: RECOVERY / PERSISTENCE_ERROR
run: any non-terminal status -> FAILED
request: unchanged; no provider call
safe_message: "Stored processing state is inconsistent and cannot be resumed safely."
details: {
  recovery_reason: <closed value above>,
  prior_run_status: PERSISTED | CONTEXT_READY | GENERATING | REVISING,
  model_request_id: <uuid or null>,
  attempt_number: <0 | 1 | 2 or null>
}
```

This is a successfully persisted controlled diagnosis, not
`PersistenceFailureResult`. The latter is reserved for an operation that could
not complete its mandatory write.

### Mandatory persistence failure

After any accepted-run mandatory write rolls back, make exactly one
best-effort fresh terminal transaction:

```text
typed result: PersistenceFailureResult
stage/code: TERMINALIZATION / PERSISTENCE_ERROR
run: last durable non-terminal status -> FAILED, only if best effort commits
request: unchanged from its last durable status
safe_message: "Processing could not be saved safely."
details: {
  failed_stage: <PipelineStage of the rolled-back mandatory write>,
  prior_run_status: PERSISTED | CONTEXT_READY | GENERATING | REVISING
}
```

If this transaction commits, return `failure_persisted=true`, the terminal run,
and exact failure. If it fails, return `failure_persisted=false`, the last known
durable status, and no failure; do not claim terminalization. Recovery may
classify that durable state on a later startup. An acceptance rollback is the
special no-run case in `ProcessUserMessage.md`: no best-effort failure insert or
recreated acceptance is attempted. A read-only error while classifying an
existing/busy submission likewise never terminalizes the run owned by another
execution; it returns an unpersisted persistence result.

### Generic context-construction failure

```text
typed result: ControlledFailureResult(ContextConstructionError)
stage/code: CONTEXT / CONTEXT_CONSTRUCTION_FAILED
run: PERSISTED -> CONTROLLED_FAILURE
request: none
safe_message: "Context could not be constructed safely."
details: {
  component: "INTERPRETATION" | "REFERENCE_RESOLUTION" |
             "CONSTRAINT_RESOLUTION" | "RETRIEVAL" | "PACKET_BUILD",
  reason_code: "INVALID_COMPONENT_RESULT" |
               "REQUIRED_CONTEXT_RECORD_MISSING" |
               "CONTEXT_INVARIANT_VIOLATION"
}
```

The application selects the component it was invoking and a canonical reason;
raw exception text/type and content are never persisted. Any active joined
context transaction rolls back before this fresh terminal transaction. No
derived state, packet, model request, candidate, validation, correction, or
assistant row is committed.

## Idempotency, concurrency, and recovery

- Repeating `(conversation_id, idempotency_key)` returns the existing run and
  never creates another message/request. A different payload does not replace
  the first accepted payload.
- At most one global non-terminal foreground run exists. A fresh key while it
  exists is rejected before acceptance; there is no queue or autonomous worker.
- State compare-and-swap retries pure deterministic context once. The exact
  second-conflict terminal projection is above.
- `RecoverProcessingRun` finds at most one global non-terminal run, validates
  complete lineage, and compares its fingerprint before any resumed write or
  provider call. With a matching fingerprint, exactly one row applies:

| Durable state | One recovery action and public outcome |
|---|---|
| `PERSISTED`, no packet/request | Check application cancellation; otherwise rerun deterministic context once and continue to its terminal public outcome. |
| `CONTEXT_READY`, one packet, no request | Check application cancellation; otherwise create/claim the initial request and continue. |
| `GENERATING`/`REVISING`, current request `PENDING` | Claim it and enter the gateway with the fresh token. Gateway-entry cancellation yields `MODEL_CANCELLED`; no provider work starts. |
| `GENERATING`/`REVISING`, current request `IN_FLIGHT`, no response | Commit `PROCESS_RESTARTED` exactly as above; never call the provider. |
| Non-terminal run, `SUCCEEDED` request/response/passing validation, assistant link absent or already equal | Repeat only the idempotent assistant terminal transaction and return `SucceededResult`. Cancellation is not retroactive. |
| Non-terminal run, failed validation below packet limit, no next request | Check application cancellation; otherwise reconstruct the envelope, render, create exactly one adjacent correction/request, claim, and continue. |
| Non-terminal run, failed validation at packet limit | Commit the canonical exhaustion projection and return `ValidationExhaustedResult`; cancellation is not retroactive. |
| Non-terminal run, terminal failed/timed-out/cancelled request | Commit the corresponding already-recorded transport safe failure/run status without another provider call and return the matching controlled/cancelled result. |

A fingerprint mismatch uses `CONFIGURATION_CHANGED`. Any lineage combination
outside this table uses the closed impossible-state projection. Recovery does
not repair, delete, or overwrite inconsistent artifacts and never repeats an
uncertain call. A persistence return ends that recovery invocation; it does not
loop or schedule itself.

## Lifecycle invariants

- One run has one user message and zero or one immutable packet. A successful
  packet is required before any model request; `CONTEXT_READY` and later
  generation states have exactly one packet.
- A non-terminal run has null `completed_at`. A terminal run has non-null
  `completed_at >= started_at`.
- Attempt `0` is `INITIAL`; attempts `1`/`2` are `REVISION`. A unique constraint
  enforces one request per run/attempt; repositories enforce purpose pairing.
- `PENDING` has null lifecycle/error fields. `IN_FLIGHT` has non-null
  `started_at` and null completion/error fields. `SUCCEEDED` has ordered
  timestamps and null errors. `TIMED_OUT`, `CANCELLED`, and `FAILED` have ordered
  timestamps and non-empty error fields. A timestamp cannot precede the run.
- The recovery-owned `IN_FLIGHT -> FAILED/PROCESS_RESTARTED` mapping is the only
  way an uncertain pre-restart attempt is closed; it creates no response.
- A response may be added only for its terminal `SUCCEEDED` request and cannot
  initially carry an assistant link. It has exactly one validation result.
- Correction attempt `N` links failed validation from attempt `N-1` to revision
  request `N` in the same run. Repositories reject cross-run, cross-packet, or
  skipped-attempt lineage before commit.
- Only passed validation permits an assistant link, and linked message content
  obeys the byte-exact invariant above. Failed candidates remain unlinked.
- A controlled failure has no final assistant candidate. UI/presentation may
  render only the typed safe result, never candidate text.
- A terminal `CONTROLLED_FAILURE`, `FAILED`, or `CANCELLED` run has exactly one
  `is_terminal=true` `SafeFailure`; `SUCCEEDED` and `NEEDS_CLARIFICATION` have
  none. Idempotent terminal/recovery repetition reuses the equal terminal row
  and never adds a duplicate. A non-terminal run may have no terminal failure.
- No terminal run receives another request, state update, correction, or new
  assistant link. Manual memory operations remain separate and provenance-
  preserving.
