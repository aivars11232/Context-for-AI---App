# Context for AI — Executable Acceptance Criteria

## Test harness rules

- Every deterministic application/pipeline acceptance case uses fixed UUIDs, an
  injected UTC clock, an isolated temporary SQLite database, fixture YAML, and
  `MockModelProvider`. The isolated TASK-0011 mock and TASK-0012 controlled-
  transport gateway component cases use their explicitly defined fixtures and
  no application database.
- A case asserts observable data, UI state, or returned result; it does not only
  assert that a mock method was called.
- Fixture files are versioned, synthetic, and free of prior private
  conversations. The fixture version is persisted in evaluation results.
- Every test that contacts live Ollama is marked `ollama` and excluded from the
  default test command. AT-016 is the sole live-model complete-pipeline
  criterion; TASK-0012's marked live adapter test execution is component
  evidence and neither executes nor satisfies AT-016.
- The implementation must map each ID below to a named pytest test or evaluation
  fixture. A test may cover multiple IDs only when its assertions identify each
  ID independently.

## Deterministic MVP acceptance tests

### AT-001 Application startup and configuration

**Configuration/migration fixture and retained ownership:** use a complete valid
six-file YAML configuration, including intent, qualifier, output-shape,
preserve-verb, and action-marker rules, and an isolated data directory. Existing
configuration and migration owners retain exhaustive validation and canonical
ledger/schema assertions. A valid fixture validates and initializes the empty
database. One invalid key/range/rule-table violation per fixture fails before
startup-scope or QML creation with a typed `ConfigurationError` naming the
file/key and no rejected value. TASK-0015 does not redefine those validators or
migrations.

**TASK-0015 shell fixture/action:** use the valid empty database, the offscreen
QML platform, a recording startup-error presenter, and the same recursively
packaged QML tree from both a source checkout and an installed-package fixture.
Run complete shell startup with no non-terminal run.

**TASK-0015 shell pass:** startup follows the exact order in
`PresentationShell.md`; the startup scope creates/selects exactly one unscoped
conversation with its version-`0` state and closes before QML creation; no
foreground worker starts; exactly one packaged root is created on route `CHAT`;
the shell enters `IDLE` and is send-ready; all local nested QML imports resolve
without a current-working-directory fallback; and no unhandled import,
configuration, composition, or QML error occurs.

**TASK-0015 startup-failure pass:** inject, separately, typed configuration,
migration, composition, recovery-preflight, and QML root/nested-asset load
failures. Each produces exactly its closed `StartupFailureView`, one safe stderr
record, and one recording-presenter call for an interactive launch; creates no
usable QML root or foreground worker; exits non-zero; and exposes none of the
prohibited diagnostics. Configuration failure alone exposes its typed file/key.
The offscreen presenter never opens a modal dialog. The production contract is
the same projection rendered by the non-QML Qt modal dialog.

### AT-002 Exact user-message persistence

**TASK-0014 public-use-case fixture:** a conversation, fixed IDs/clock, an
observing mock gateway, and text containing leading/trailing whitespace,
Unicode, and a newline. **Action:** invoke `ProcessUserMessage.execute` with one
idempotency key, allow processing to finish, then reload the durable lineage.
**Pass:** the stored user `messages.original_text.encode("utf-8")` is
byte-for-byte equal to the submitted text; acceptance committed the user message
and `PERSISTED` run before the mock gateway was entered; and the public result's
run/message IDs are those durable IDs. TASK-0014 owns AT-002 through this public
seam; repository-only append evidence does not satisfy it.

### AT-003 State tracking and transition

**Fixture:** no project/conversation, then one created active project, one
created conversation, topic, task, and state version. **Action:** select the
project, submit a high-confidence continuation and then an explicit new task,
complete the task, and archive the project after the terminal run. **Pass:** the
first retains the task; the second moves the old task to `previous_task_id`,
updates state once, increments version, and packet state equals persisted state;
the named task-status transitions are legal; archive preserves its conversations
and makes the project unavailable for new selection.

### AT-004 Qualifier and constraint handling

**Fixture:** `Remove only the blue line and do not change anything else.`
**Action:** interpret and extract constraints. **Pass:** it creates a current
`REQUIRED` normalized target `remove blue line`, a current `PRESERVE` rule for
unspecified content, and a `FORBIDDEN` rule for additional changes, all at
priority `1000` with source evidence. No unrelated constraint is inferred.

### AT-005 Output-type protection

**Fixture:** prior design context and `Do not generate anything; give me a
description.` **Action:** interpret and build a packet. **Pass:** expected
output is `TEXT_DESCRIPTION`, response policy is text-only/no-actions, and the
packet contains a forbidden image/action rule. This test verifies policy only;
the MVP does not invoke an image generator.

### AT-006 Reference resolution

**Fixture:** an active project `Context for AI`, its entity-registry row, the
explicit user message that supplied its creation name, and a separate message
`name "architecture"`. **Action:** atomically register the declared named item,
then submit `correct the app structure` and run the TASK-0008 mention extractor,
resolver, and outcome persistence against isolated SQLite. **Pass:** `the app`
is the sole final mention at ordinal `0`; the active-project candidate uniquely
wins at `0.90`; one `reference_resolutions` row has `RESOLVED`, the project
entity ID, project source-message ID, confidence `0.90`, and the exact ranked
candidate-evidence shape. The named item has one owning `named_items` row and
one registry row with its declaration source, and no inferred registry entry
exists.

### AT-007 Ambiguous reference clarification

**Fixture:** an in-scope active project and explicit named item both normalized
as `app`, so `the app` gives both an exact-name score of `1.00`. **Action:** run
the TASK-0008 extractor and resolver. **TASK-0008 component pass:** the sole
outcome is `AMBIGUOUS` with confidence `1.00`, null resolved/source entity
selection, both tied candidates in canonical evidence order, and a blocking
`ReferenceDecision` carrying the canonical `AMBIGUOUS_REFERENCE` reason and
question inputs. The resolver has no model/provider dependency and performs no
run, clarification, or UI mutation.

**Later full-pipeline pass:** orchestration persists the outcome and exactly one
canonical `clarification_requests` row, terminalizes the run as
`NEEDS_CLARIFICATION`, creates no model request, and exposes the one safe
question to the UI. These integration/presentation assertions are not owned by
TASK-0008.

### AT-008 Deterministic context retrieval

**Fixture:** active-project, different-project, conversation, global,
expired, deleted, and duplicate memories with known dates/importance/keywords.
**Action:** run the TASK-0009 retriever for a Context for AI message using the
fixed clock, then persist its returned evidence against a caller-supplied
existing context-packet fixture. **TASK-0009 component pass:** every considered
memory appears exactly once as selected or excluded; only scope-eligible,
non-expired, non-deleted memories at or above threshold are selected;
cross-project and cross-conversation records are excluded; exact duplicates
collapse only in the retrieval result; zero-based ranks, 28-digit decimal
scores, ordered reasons, exclusion details, and tie-breaking exactly follow the
canonical contract and round-trip through the existing repository without any
memory mutation or packet construction.

**Later full-pipeline pass:** orchestration supplies the considered input set
and injected-clock time, persists the already-computed decision with the packet,
and passes selected memories to later packet/provider stages. Those integration
assertions do not change TASK-0009 retrieval decisions and are not owned here.

### AT-009 Context-packet completeness and truncation

**TASK-0010 component fixture:** fixed immutable run/message/state/project
objects; already-computed interpretation, admissible reference and constraint
decisions, and retrieval decision; one complete packet-lineage companion per
constraint; the immutable active-topic snapshot; the complete normalized
validation configuration; selected memory snapshots; a preallocated packet ID
already used by retrieval evidence; fixed caller-supplied creation time; and
scalar budget values. Include resolved/not-applicable references, active hard/
true-conditional/preferred/optional constraints, inactive conditionals,
complete override evidence, ranked memories, strings that resemble every
prompt marker, every canonical TASK-0008 candidate score/reason pairing, and
budgets that exercise fit and overflow.

**Component action:** call
`ContextPacketBuilder.build(ContextPacketBuildRequest)` and
`PromptRenderer.render(PromptRenderRequest)` directly. Exercise the narrow
`ContextPacketStage.execute(ContextPacketBuildRequest)` separately with a fixed
ID generator and temporary SQLite; do not construct a provider mock or broader
pipeline service.

**Pass — complete packet and initial render:** the success is one
`ContextPacketBuildSuccess` containing an immutable `ContextPacketRecord` and
initial `PromptRenderResult`. Outer identity/time remain outside
`packet_json`; `trace.state_version` identifies the represented state snapshot;
the payload has schema `mvp-context-packet-v2`, exact original text, the closed
topic/rule `validation_context`, all other required fields, complete ordered
decision/evidence data, and selected memory snapshots. Validation context is
not rendered or budgeted, and the prompt policy remains
`mvp-prompt-policy-v1`.
Retrieval exclusions remain aggregate evidence outside the payload in canonical
memory-UUID order, and retrieval confidence equals the upstream decision value
without recomputation. The prompt uses `mvp-prompt-policy-v1`, the exact section
bytes/order and canonical JSON, and includes every mandatory item. Rebuilding
and rerendering the same fixture is byte-for-byte identical. Successful inputs
contain only `RESOLVED`/`NOT_APPLICABLE` references, no active material
`ASSUMED` constraint, and no `CONFLICTING` constraint; ambiguous, unresolved,
assumed, conflicting, incomplete-lineage, and mismatched-lineage pre-packet
fixtures produce no packet or render. `OVERRIDDEN` records retain complete
mandatory source and winner/related evidence.

**Pass — estimator and truncation:** `conservative_utf8_v1` returns `0` for
`""`, `1` for `"abc"`, `2` for `"abcd"`, `1` for `"é"`, and `2` for `"😀"`,
and estimates the complete UTF-8 render. Equality with the effective budget
fits. Smaller fitting budgets tail-prune only whole items from the fixed total
sequence—references, inactive-condition evidence, preferred constraints,
retrieval by rank, then optional constraints—rerendering the whole prompt after
each removal with no backfill. Exact projection/item-key omission records and
included sections are deterministic, including a fixture whose whole-item
removal has zero marginal estimated tokens; packet evidence and mandatory
content are unchanged.

**Pass — canonicalization, injection, and correction:** marker-like user,
reference, constraint `source_texts`/resolution evidence, and memory strings—
including quotes, backslashes, CR/LF, U+2028, and U+2029—remain inside one
canonical-JSON data line and cannot create, close, or reorder a trusted section.
The correction block uses only the closed typed violation and compact-evidence
objects. Reordered input object keys render identically; exact decimals render
in fixed-point form. TASK-0008 source candidate scores `0.0`, `0.6`, `0.8`,
`0.9`, and `1.0` project to exact packet decimals `0`, `0.6`, `0.8`, `0.9`, and
`1`; a noncanonical score/reason pair is invalid, and every other binary
floating-point value reaching canonical JSON is rejected. A valid
`mvp-correction-envelope-v1` names the same packet, has an attempt within its
packet correction limit, and inserts the exact fixed correction blocks before
`@@CFA/END@@`; a cross-packet, zero-limit, or out-of-range envelope is rejected
as invalid input. A correction starts from the initial retained optional prefix,
can only prune further, reports final included sections and only additional
correction token omissions, and does not repeat initial omissions or mutate
packet bytes/initial rendering metadata. Correction mandatory overflow returns
`ContextBudgetExceeded(phase=CORRECTION)` and no prompt, persistence, or run
transition.

**Pass — persistence and impossible budget:** success atomically writes exactly
one packet aggregate, including retrieval result/exclusion rows, and changes
the run from `PERSISTED` to `CONTEXT_READY`; an induced write failure rolls back
both. An initial budget below the complete mandatory estimate returns
`ContextBudgetExceeded(phase=INITIAL)` with code
`CONTEXT_BUDGET_EXCEEDED`, estimator, required estimate, and effective budget,
and no packet or prompt. The packet application stage atomically writes exactly
one specified terminal `SafeFailure` with the generated failure ID, request
processing-run ID, `stage=CONTEXT`, and the exact code/message/details/time, then
changes the run from `PERSISTED` to `CONTROLLED_FAILURE`; an induced failure
rolls back both. It writes zero packet, retrieval-result, retrieval-exclusion,
model-request, model-response, validation, correction, or assistant-message
rows.

### AT-010 Model abstraction and buffering

**TASK-0011 component fixture:** one fixed `GenerationRequest` compatible with
the `PromptRenderResult` handoff, fixed UUIDs/settings, an immutable
`mock-model-provider-v1` script covering complete success, provider unavailable,
model not found, timeout, invalid provider response, and a held success step, a
thread-safe test cancellation token, and a static absolute/relative import
boundary check.

**TASK-0011 action:** call the gateway directly for every terminal outcome; hold
one success before its terminal checkpoint; separately exercise pre-call and
held-checkpoint cancellation; inspect the mock's immutable call snapshot.

**TASK-0011 pass:**

- every valid matched, non-exhausted invocation returns exactly one value in the
  documented `GenerationOutcome` sum, with the exact fixed safe code/message
  mapping; malformed scripts, request mismatches, and exhaustion instead produce
  the documented deterministic fixture errors and no terminal call record;
- the mock selects only by call order, exactly matches the complete request,
  consumes/repeats/exhausts as documented, and is value-deterministic across
  fresh equal scripts;
- before a held step is released, the call has not returned, no terminal call
  record exists, and no response text or result is observable; release returns
  exactly one `CompletedGeneration` containing the full fixture text;
- timeout, cancellation, unavailable-provider, unavailable-model, and invalid
  provider response return no complete or partial text; cancellation wins at a
  shared terminal checkpoint and never force-terminates a worker;
- request correlation is preserved exactly through the mock call record:
  `processing_run_id`, `context_packet_id`, `model_request_id`, and
  `attempt_number` are neither allocated nor changed by the gateway;
- the request and outcome expose every provider-independent input required by
  the documented later persistence mapping, but the gateway/mock performs no
  persistence or trace emission; and
- domain and application modules import no mock or Ollama implementation;
  context-engine modules have no gateway dependency; and presentation/QML
  import application use-case interfaces only, with no gateway or provider
  dependency. Test composition injects the mock through the existing gateway
  port; positive Ollama construction is not a TASK-0011 claim.

**TASK-0012 component extension:** after the TASK-0011 component pass is green,
construct the real Ollama adapter through a test composition fixture using
validated fixture configuration and a controlled transport. The unmarked,
daemon-free assertions must prove the exact uncached
version/status/show/generate order, local-only fail-closed behavior, one bound
model, payload and terminal-envelope mapping, canonical typed failures, shared
timeout, cancellation-driven transport closure, metadata allowlisting, and no
retry, redirect, proxy, authentication, routing, fallback, or streaming path.
Hold a fragmented response body before its terminal envelope is complete: the
call has not returned and no content is observable. Release of a complete valid
envelope returns one complete result; timeout, cancellation, transport failure,
or an invalid envelope discards the full internal buffer and returns no content.

The marked live TASK-0012 transport test definitions and fixture are required
TASK-0012 test surface; executing them against a daemon is optional. They use the
same adapter contract, are marked `ollama`, and require
`CONTEXT_FOR_AI_RUN_OLLAMA=1`. When explicitly selected, an absent variable skips
as environment absence; a present value other than `1` fails as an invalid
opt-in; exact `1` runs the tests and every invalid configuration, non-local
endpoint, local-only attestation failure, unavailable daemon, missing model,
timeout, malformed response, or failed assertion is a failure rather than a
dynamic skip. The default selection excludes these tests.

**Integrated assertions outside the TASK-0011/TASK-0012 gateway component
scopes:** when broader pipeline integration exists, the already-created request
row carries the same run/packet/request IDs, attempt, model, prompt, and terminal
request status; a completed response links through `model_request_id`; a failure
creates no response row; trace events use the same correlation set; and no
partial provider text reaches persistence or the UI. QML behavior, UI
responsiveness, actual lifecycle persistence, response validation, correction,
and broader pipeline orchestration are not TASK-0011 or TASK-0012 exit criteria.

### AT-011 Response validation

**TASK-0013 fixture:** immutable `mvp-context-packet-v2` values with fixed topic
terms and validation configuration covering one required predicate, one
forbidden predicate, one preservation predicate, each output shape, action
markers, true and false conditionals, preferred and optional rules, one retained
overridden assumption, repetition, and empty candidates. Include malformed and
unknown predicates only as invalid-input fixtures.

**TASK-0013 action:** call the validator directly for separate passing, failing,
and warning candidates; repeat each complete request unchanged. No provider or
repository is supplied to the validator.

**TASK-0013 pass:** identical requests produce value-identical aggregate status,
exact decimal score, ordered violations, and ordered evidence. Every canonical
check follows the documented lexical/structural grammar; empty content, topic,
shape, phrase, marker, preservation, conditional, and repetition behavior is
exact. Violations contain only errors; preferred/optional misses and an
overridden assumption are warning evidence only and have zero score impact;
each distinct repeated sentence is warning evidence with exactly one `0.05`
deduction. Warnings never change pass/fail. Malformed/unknown predicates fail as
invalid component input with no validation result or correction decision. The
validator performs no model call, lookup, packet mutation, or fact judgment.

### AT-012 Bounded correction and controlled exhaustion

**TASK-0013 component fixture:** immutable packets whose correction limits are
`0`, `1`, and `2`; fixed failed validation reports containing errors and
warnings; explicit succeeded/unlinked candidate lineage for attempts `0`, `1`,
and `2`; invalid cross-run, cross-packet, skipped-attempt, and out-of-range
lineage; and preconstructed repository records for the bounded durable
projections. No provider or complete pipeline use case is used.

**TASK-0013 component action:** call the correction controller directly and
exercise the validation, correction-attempt, and exhaustion repository
projections independently.

**TASK-0013 component pass:** attempt `N` below the packet limit yields exactly
one envelope for attempt `N+1`; attempt `N` equal to the limit yields the exact
typed exhaustion value; invalid lineage yields an invariant error and no
decision or write. Limits `0`, `1`, and `2` permit exactly zero, one, and two
correction envelopes. Every envelope retains the original packet ID and bytes,
names the immediately failed response, contains ordered violations but no
warnings/candidate/full evidence, and never weakens a constraint. Exact
validation reports persist; a successful correction projection atomically
persists one adjacent revision request and correction row whose `reason_json`
is the violation array; exhaustion persists the canonical safe failure with no
correction row or assistant link. These assertions are bounded component
evidence and do not by themselves satisfy complete AT-012.

**TASK-0014 full fixture/action:** use mock responses that fail a hard rule,
parameterized with `validation.max_revisions` values `0`, `1`, and `2`, and run
the complete correction lifecycle.

**TASK-0014 full pass:** the lifecycle makes exactly one, two, or three model
requests respectively with consecutive attempts beginning at `0`; creates
exactly zero, one, or two correction rows; persists every candidate and report;
and ends exhausted runs as `CONTROLLED_FAILURE` with the exact
`VALIDATION_EXHAUSTED` projection. A failing candidate below the limit points to
the one adjacent correction/request and correction rendering overflow creates
neither while persisting the exact `CORRECTION/CONTEXT_BUDGET_EXCEEDED`
projection. No assistant message links an invalid response, no public result
contains invalid candidate text, and the caller gets the canonical safe
failure. TASK-0014 owns full application acceptance of AT-012; TASK-0013 retains
the component assertions above.

### AT-013 Context inspection UI and shell responsiveness

**TASK-0015 shell fixture:** a prepared shell conversation, fixed idempotency and
execution IDs, an isolated SQLite database, final TASK-0014 application use
cases, a mock gateway held before its terminal checkpoint, an instrumented scope
and connection factory, a recording facade-thread observer, and the QML offscreen
platform. No context-inspection route or page participates.

**TASK-0015 shell action:** reject an empty composer value, then start one chat
submission whose non-empty text includes leading/trailing whitespace; wait until
the mock is held, attempt a second submit, post multiple GUI event-loop
sentinels, request cancellation, release the held checkpoint, and observe the
terminal state. In a separate held execution, request application close while
the worker is active.

**TASK-0015 shell-responsiveness pass:** all of these assertions hold
independently:

- while the mock is held, every posted GUI sentinel is processed within the
  bounded test timeout and the shell remains readable/actionable;
- the accepted execution shows only contracted indeterminate controller
  progress, never trace-derived stage/percent/token/partial-output progress;
- empty input dispatches nothing; the accepted request carries the composer text
  byte-for-byte, `project_id=null`, and exactly one caller-owned idempotency key;
  the composer clears only after acceptance, while rejected/duplicate actions
  preserve it;
- the second submit is suppressed in both QML enablement and the controller,
  allocates no key/token/worker, invokes no use case, and creates no queue item;
- the first cancellation action moves the GUI immediately to
  `CANCELLATION_REQUESTED`, repeated cancellation is a no-op, and the eventual
  typed terminal value alone selects the terminal state;
- the foreground SQLite connection is created, used by every repository, and
  closed on the same worker thread, which differs from the GUI thread; no
  connection/cursor/row/repository crosses the boundary and SQLite thread checks
  are not disabled;
- the worker emits one immutable terminal envelope after scope closure; its
  explicitly queued delivery is handled on the GUI thread and is the only
  worker-to-UI result-state mutation path; the queued finished notification
  changes only worker ownership/derived enablement, and a mismatched/late
  envelope is ignored;
- success exposes only exact validated assistant text, clarification only the
  deterministic question, and every cancellation/busy/existing/persistence/
  controlled/recovery failure only the allowlisted safe presentation in
  `PresentationShell.md`; no candidate or hidden diagnostic reaches QML; and
- shutdown disables submission, requests cancellation once, continues to
  process GUI events, performs no blocking join or force termination, closes the
  scope/worker after the terminal/finished notifications, and only then allows
  Qt exit.

The test timeout is a harness bound for a failed liveness assertion, not a
product polling interval or latency promise.

**Later context-page fixture/action/pass:** the later context-inspection owner
uses one processed mock-provider message containing state, intent, references,
constraints, retrieval, confidence, and validation data, opens the real
context-inspection page, and visibly presents every FR-015 field, including
reference status/evidence, retrieval scores/reasons, confidence, validation
status, and any controlled failure or clarification.

TASK-0015 owns only the shell-responsiveness pass and must not register or render
a context-page placeholder. The later context-inspection task owns the page pass.
Full AT-013 is satisfied only when both passes are green.

### AT-014 Manual memory lifecycle

**Fixture:** a manual memory create, edit, duplicate candidate, expiry timestamp,
and delete request. **Action:** perform the explicit TASK-0009 use-case
operations with an injected clock. **TASK-0009 component pass:** each successful
create, edit, and soft delete atomically creates exactly one source and one
consecutive immutable `memory-revision-v1` revision; get/list expose the complete
source/revision history and computed effective status; duplicate records are not
automatically merged; expiry computes `EXPIRED` while stored status remains
`ACTIVE` and creates no revision; delete writes an inspectable `DELETED`
tombstone that cannot be edited or restored. No automatic lifecycle operation,
UI, trace event, orchestration, or provider call is exercised by this pass.

**Later integration/presentation pass:** presentation invokes the same use cases
through explicit user actions. After each successful commit it emits exactly
`memory_created`, `memory_edited`, or `memory_soft_deleted` with stage `MEMORY`,
the affected non-null `memory_id` and `memory_revision_id`, null processing/model
correlation and `error_type`, and the validated configuration fingerprint. The
events occur in operation order and contain no raw memory content. UI, trace,
orchestration, and provider integration are not TASK-0009 work; these exact
assertions close the memory-event portion of the trace specification without
changing later delivery ownership.

### AT-015 Complete mock-provider pipeline, idempotency, and recovery

**TASK-0014 fixture:** valid fixed configuration, isolated databases, fixed
UUID/clock sequences, exact mock generation outcomes/metadata/durations/token
usage, controllable cancellation tokens and held mock checkpoints, a trace
recorder implementing `TraceLogger.emit`, and repository fault injection at
each transaction boundary. Recovery fixtures contain exactly one canonical
durable state at a time; corruption fixtures use each closed
`recovery_reason`.

**Public action:** invoke `ProcessUserMessage.execute` and
`RecoverProcessingRun.execute` directly. No QML, live Ollama, queue, poller,
daemon, or background worker participates.

**Admission and public-result pass:**

- A first key follows `lookup -> global active check -> acceptance`; the same
  key, even with different text/project, returns `ExistingRunResult` with the
  same IDs/snapshot and no write/provider call. A different key in the same or a
  different conversation returns the exact `BusyResult` and creates no
  message/run. A partial-index race loser captures the conflicting row before
  rollback and is reclassified as existing or busy without leaking its
  uncommitted message/run.
- Success, existing, busy, clarification, cancellation, validation exhaustion,
  configuration failure, persistence failure, second-CAS conflict, and every
  controlled-failure family return the exact public variant and field
  nullability in `ProcessUserMessage.md`; expected conditions do not escape as
  exceptions and no failure variant contains candidate text.
- Pre-acceptance cancellation creates nothing. Cancellation after acceptance,
  between context phases, before request preparation, and at gateway entry uses
  the exact checkpoint, request/run status, code, message, details, and legal
  transition. A completed gateway outcome is not replaced by later
  cancellation.

**Persistence and lineage pass:**

- All five transaction groups commit in canonical order and no database
  transaction spans the mock call. Joined packet-stage/context writes have one
  outer commit; a first CAS conflict leaves no partial rows and recomputes once;
  a second persists the exact conflict failure and no packet/request.
- `request_json` and completed `metadata_json` are exactly the closed versioned
  projections, including decimal rendering, integral elapsed microseconds,
  token nulls, safe provider metadata, and correlation equality. Every revision
  has same-run adjacent correction lineage and an unchanged packet.
- A passing response produces one assistant message whose `original_text` UTF-8
  bytes exactly equal both persisted response text and returned assistant text.
  Repository linkage rejects a mismatched role, conversation, validation, ID,
  or byte sequence. Invalid responses remain unlinked and unreturned.
- An acceptance write failure rolls back message/run and returns an unpersisted
  persistence result without attempting a failure row. A later mandatory write
  failure makes exactly one fresh best-effort terminalization; both its committed
  and failed forms report `failure_persisted` truthfully and never claim
  unwritten state.
- Correction render overflow, generic context failure, changed configuration,
  process restart, impossible recovery state, persistence failure, gateway
  failures, cancellation, and validation exhaustion match their authoritative
  closed failure projections, allocated IDs, and single-clock timestamp rules.

**Recovery pass:**

- Direct invocation of the empty-request TASK-0014 recovery use case with no
  active run returns `NoRecoveryRequiredResult`; the application use case itself
  never creates a worker. Each active-run fixture produces one finite result.
  TASK-0015 startup separately performs `PrepareApplicationShell`: with no active
  run, no foreground worker starts; a required run starts one foreground recovery
  only after the QML root loads and before admission, as exercised by
  AT-001/AT-013.
- Every recovery-matrix row is exercised: `PERSISTED`, `CONTEXT_READY`,
  `PENDING`, uncertain `IN_FLIGHT`, passing validation without final link,
  failed validation below/at its packet limit, and terminal
  failed/timed-out/cancelled request. Resumable rows create only the missing
  artifact; idempotent terminalization duplicates nothing.
- A changed fingerprint invokes no context/model component. An uncertain
  request becomes request/run `FAILED/PROCESS_RESTARTED`, creates no response,
  and records zero repeated mock calls. Each impossible state uses the first
  canonical `recovery_reason` and leaves existing artifacts unchanged.
- A fresh recovery cancellation token is used. Recovery never reconstructs the
  old token, retries an uncertain call, loops after persistence failure, selects
  a caller-provided run, queues, or polls.

**TASK-0014 trace pass:**

- A normal successful initial attempt records exactly
  `run_accepted`, `context_built`, `reference_resolved`,
  `constraints_resolved`, `retrieval_completed`, `packet_built`,
  `model_request_started`, `model_request_finished`,
  `validation_completed`, and `run_succeeded` in that order. Revision adds one
  `correction_started` after the failed attempt's validation and repeats the
  request/finish/validation sequence.
- Clarification ends with `run_clarification`; every durably terminal failure or
  cancellation ends with `run_failed`. AT-014 separately fixes
  `memory_created`, `memory_edited`, and `memory_soft_deleted`. Across AT-007,
  full AT-012, AT-014, and AT-015, every required event name is specified and
  observed by its owning acceptance scope.
- Active recovery records `recovery_started`, optional `recovery_resumed`, the
  applicable normal events, then `recovery_completed` exactly as specified. A
  changed fingerprint, uncertain call, or impossible state omits
  `recovery_resumed`; no-active recovery and non-mutating existing/busy results
  emit no new lifecycle event.
- Every event asserts its exact `PipelineStage`, required non-null correlation,
  additive IDs, and nulls for unknown fields. Failure events use the canonical
  `FailureCode`; successful/clarification events use null. Events after a shared
  commit retain canonical order, and no mutation event precedes its commit.
- Serialized trace records contain none of: original message, rendered prompt,
  packet JSON, candidate/assistant text, raw memory, raw provider body or
  exception, headers, endpoint, credential, cookie, or full configuration. A
  post-commit trace-adapter failure does not alter the database or public
  result.

TASK-0014 owns AT-015 idempotency, global concurrency, cancellation, persistence,
recovery, lineage, and trace integration through these public seams.

### AT-016 Local Ollama smoke acceptance

This is the only live-model complete-pipeline acceptance criterion. TASK-0012's
marked live Ollama transport test execution is isolated adapter component
verification; it neither executes nor satisfies AT-016. Both scopes use the
`ollama` marker and `CONTEXT_FOR_AI_RUN_OLLAMA` convention, while the default
suite excludes all marked live tests.

When AT-016 is explicitly selected, an absent variable skips as environment
absence and never counts as evidence. A present value other than exactly `1`
fails as an invalid opt-in. With exact value `1`, every preflight condition below
is executed and a missing or invalid condition fails the test:

1. The fixture configuration uses a direct numeric-loopback Ollama endpoint,
   `temperature: 0.0`, timeout `60`, and a named installed local model supplied
   through `CONTEXT_FOR_AI__MODEL__NAME`.
2. The daemon health, native cloud-disabled status, and exact local-model
   preflight from `OllamaAdapter.md` succeed before the prompt is sent.
3. The test records only normalized allowlisted model/provider metadata,
   configuration fingerprint, Ollama version, OS, and elapsed time as an
   artifact. It records no raw CLI/provider response, endpoint, header, secret,
   message, prompt, partial output, or response content in logs or metadata.
4. The deterministic fixture asks for the exact text token
   `CONTEXT_FOR_AI_SMOKE_OK`; packet constraints require that token.

**Action:** run the complete one-process pipeline against local Ollama.
**Pass:** health check succeeds, one buffered response arrives within timeout,
validation passes the token constraint, every lifecycle/trace record persists,
and the QML UI displays the linked accepted assistant text. A missing daemon,
cloud-disable attestation, local model, timeout, malformed response, or token
mismatch is a failed opt-in acceptance result—not a silently skipped pass.

## Requirement traceability

| Requirement area | Acceptance IDs |
|---|---|
| Configuration, startup, local runtime | AT-001, AT-016 |
| Exact persistence, state, entity/reference | AT-002–AT-007, AT-015 |
| Constraints, retrieval, packet | AT-004–AT-009 |
| Gateway, validation, correction | AT-010–AT-012, AT-016 |
| UI and manual memory safety | AT-013–AT-014 |
| Transaction, idempotency, recovery, traceability | AT-002, AT-012, AT-015–AT-016 |
