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

**Fixture:** a complete valid six-file YAML configuration, including intent,
qualifier, output-shape, preserve-verb, and action-marker rules, and an isolated
data directory. **Action:** bootstrap the application using the QML offscreen
test platform. **Pass:** configuration validates, the migration bootstrap ledger
initializes an empty database (canonical schema migrations are accepted in
AT-002/Task 0004), the QML root window is created, and no unhandled
import/configuration error occurs. Repeat with one invalid key/range/rule-table
violation per fixture; each run must fail before QML creation with a typed
`ConfigurationError` naming the file/key.

### AT-002 Exact user-message persistence

**Fixture:** a conversation and text containing whitespace, Unicode, and a
newline. **Action:** submit it with an idempotency key, then reload it. **Pass:**
the stored `messages.original_text` is byte-for-byte equal to the input and the
`processing_runs` row exists before a mock provider is invoked.

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
constraint; selected memory snapshots; a preallocated packet ID already used by
retrieval evidence; fixed caller-supplied creation time; scalar budget values;
and a correction limit. Include resolved/not-applicable references, active
hard/true-conditional/preferred/optional constraints, inactive conditionals,
complete override evidence, ranked memories, strings that resemble every prompt
marker, every canonical TASK-0008 candidate score/reason pairing, and budgets
that exercise fit and overflow.

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
the payload has schema `mvp-context-packet-v1`, exact original text, all required
fields, complete ordered decision/evidence data, and selected memory snapshots.
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
reference, constraint `source_texts`/resolution evidence, memory, and violation
strings—including quotes, backslashes, CR/LF, U+2028, and U+2029—remain inside
one canonical-JSON data line and cannot create, close, or reorder a trusted
section. Reordered input object keys render identically; exact decimals render
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

**Fixture:** a packet with one required phrase, one forbidden phrase, one
preservation predicate, active topic, and text output type. **Action:** validate
separate passing and failing candidates. **Pass:** each failed candidate has the
expected typed violation, deterministic evidence, and score; each configured
output shape, action marker, preserve verb, and true conditional predicate
follows its documented grammar; preferred, optional, assumed, and repetition
rules are warnings only; no model call occurs during validation.

### AT-012 Bounded correction and controlled exhaustion

**Fixture:** mock responses that fail a hard validation rule, parameterized with
`validation.max_revisions` values `0`, `1`, and `2`. **Action:** run the full
correction flow. **Pass:** it makes exactly one, two, or three model requests
respectively with consecutive attempts beginning at `0`; it creates exactly the
matching number of correction rows; all candidates and reports persist; exhausted
runs are `CONTROLLED_FAILURE`; no assistant message links an invalid response;
UI gets a safe failure rather than candidate text.

### AT-013 Context inspection UI

**Fixture:** one processed mock-provider message containing state, intent,
references, constraints, retrieval, confidence, and validation data. **Action:**
open the context-inspection page. **Pass:** it visibly presents every FR-015
field, including reference status/evidence, retrieval scores/reasons, confidence,
validation status, and any controlled failure or clarification. The QML UI stays
responsive while a pending foreground request is cancelled; the worker-owned
SQLite connection is not accessed from the GUI thread, and its queued terminal
signal is the only UI state mutation path.

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
through explicit user actions, and later pipeline ownership supplies the exact
redacted `memory_*` trace events with memory/revision IDs and no raw content.
Exact trace-event names and correlation assertions remain with D-010; UI,
trace, orchestration, and provider integration are not TASK-0009 work.

### AT-015 Complete mock-provider pipeline, idempotency, and recovery

**Fixture:** valid configuration, an isolated database, fixed clock, and a
passing mock response. **Action:** submit once, repeat the same idempotency key,
attempt a concurrent second key, and simulate restart at each non-terminal run
state. **Pass:** the first submission persists every required stage and one
linked assistant message; duplicate submission returns the same run (including
an in-progress status); a fresh concurrent submission gets a pre-acceptance
typed busy result; restart recovery exercises every matrix row, including
pending, in-flight, persisted validated candidate, correction preparation, and
changed configuration fingerprint, without duplicating an uncertain model call.
Its applicable trace events carry correlation IDs and contain no raw request,
packet, response, memory, or secret content; the combined assertions in
AT-007, AT-012, AT-014, and AT-015 cover every required trace event name.

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
