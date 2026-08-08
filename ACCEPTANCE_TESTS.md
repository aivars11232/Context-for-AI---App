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
  conversations. Deterministic fixture versions are persisted in their
  evaluation results. AT-016 instead records its fixture version in the closed
  standalone evidence artifact defined below; it does not create an
  `evaluation_cases` or `evaluation_runs` row.
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

**TASK-0016 context-page fixtures:** use isolated databases containing (a) one
empty conversation; (b) multiple accepted runs whose linked user-message
sequences make one unambiguous latest target; (c) one rich post-validation run
with active-state IDs, qualifiers, resolved and not-applicable references with
evidence, non-conflicting constraints, selected memories, every confidence
component, multiple validation attempts, and committed corrections; (d) every
durable checkpoint and clarification-reason availability row in
`ContextInspection.md`, including ambiguous/unresolved references and a
persisted hard-conflict group; and (e) cancelled and controlled-failure terminal
runs.
Put unique prohibited sentinels in rendered prompts, invalid candidates,
provider metadata, unsafe failure/clarification details, raw validation fields,
and exceptions. Use the real facade and packaged QML offscreen, an instrumented
inspection scope/connection, a held inspection query, fault injection, queued
out-of-order envelopes, Qt accessibility-interface queries, and an accessibility
announcement recorder.

**TASK-0016 context-page action:** navigate from the initial chat route to the
real context page; hold the first query in `LOADING`; post GUI sentinels and
exercise repeated navigation/refresh, conversation/project change, navigation
away, and a current-conversation processing terminal event. Release held queries
and deliver matching, duplicate, stale-generation, wrong-conversation, and late
terminal/finished notifications. Separately load the rich, checkpoint,
clarification, cancellation, controlled-failure, empty, and injected-load-error
fixtures, then request shutdown with inspection alone and with foreground work
also active.

**TASK-0016 context-page pass:** all of these assertions hold independently:

- target selection uses the greatest linked `USER` message sequence in the
  current conversation; an existing conversation with no run displays exactly
  `No processed request is available for this conversation.`;
- the rich view displays active project/topic/task, intent, output type,
  qualifier rule/source evidence, reference status/safe evidence, constraints,
  selected-memory content/scores/seven reasons, overall plus component
  confidence, the latest-attempt safe validation subset, and correction count.
  The reason/terminal fixtures display persisted conflict membership and the
  applicable clarification or safe terminal status, with the exact ordering,
  canonical labels, and score formatting in `ContextInspection.md`;
- every field at every checkpoint and clarification reason has the contracted
  `AVAILABLE`, `EMPTY`, `NOT_APPLICABLE`, or `UNAVAILABLE` value and exact
  placeholder text; current state never fills missing historical evidence;
- clarification, controlled processing failure, cancellation, empty, loading,
  ready, and inspection-load error follow their distinct states and safe text;
  controlled pipeline failure is never presented as a load error, and starting
  a load clears prior data;
- first/repeated navigation, explicit refresh, current-conversation terminal
  processing, and conversation/project changes trigger exactly the contracted
  start or single coalesced refresh; intermediate commits, traces, busy results,
  and pre-acceptance cancellation do not; navigation away and shutdown clear and
  invalidate the view;
- matching results apply once on the GUI thread, while duplicate, stale,
  mismatched, late, or post-shutdown envelopes cause no route, page, chat, or
  enablement mutation;
- none of the prohibited sentinels, hidden IDs, raw/open DTOs, database objects,
  prompts, candidates, provider data, or unsafe details occurs in the application
  result, facade values/models, QML text, accessibility tree, or announcements;
  QML invokes only facade actions and performs no repository/SQL/context/model
  access or presentation-side join;
- while an inspection read is held, GUI sentinels, navigation, foreground
  cancellation, and close actions remain responsive. Inspection and foreground
  work coexist only through separate scopes/connections, with at most one finite
  inspection worker and no queue, poller, timer, run admission, or forced
  termination;
- instrumentation proves that the inspection connection is created, every read
  occurs, and it closes on the same non-GUI inspection thread; terminal and
  finished delivery are explicitly queued, and final disposal waits
  asynchronously for every owned worker; and
- the exact accessible IDs, names, roles, scalar/list item templates, state text,
  polite announcement text, and monotonically revised announcements in
  `ContextInspection.md` are observable through Qt's native accessibility
  interfaces without a live screen reader, KDE service, or window-manager rule.

TASK-0015 owns only the unchanged shell-responsiveness pass and must not register
or render a context-page placeholder. TASK-0016 owns the context-page pass. Full
AT-013 is satisfied only when both passes are green.

### AT-014 Manual memory lifecycle and manual-operation UI

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

**TASK-0017 fixtures:** use fixed clocks/UUIDs, validated configuration with
every visible origin kind, isolated SQLite, the real facade and packaged QML on
the offscreen platform, instrumented startup/manual scope and connection/
transaction/trace factories, held workers, queued out-of-order envelopes, a Qt
color-scheme recording seam, Qt accessibility queries, and a polite-announcement
recorder. Fixtures contain:

- active, effectively expired, and deleted memories with complete multi-source/
  revision history; equal-normalized same-owner duplicates plus different-
  owner/status controls; editable and stale revision snapshots;
- active/archived projects, null/active/archived current associations, equal-
  timestamp ordering controls, one prohibited associated non-terminal run, a
  state conflict that succeeds on the existing one bounded retry, and a second
  conflict that fails; preservation sentinels cover conversations/messages/
  memories/entities;
- several accepted runs whose user-message sequence selects one latest target,
  plus initial/revision requests, passed/failed validation, both corrections,
  pending/in-flight/transport-failed attempts, clarification, controlled
  failure, and a no-run conversation; and
- absent/default, valid, invalid, and unknown SQLite settings rows plus the safe
  configuration allowlist/fingerprint. Unique prohibited sentinels occur in
  prompts, every candidate/response, provider metadata, correction envelopes,
  raw validation fields, unsafe failures/exceptions, endpoints/model identity,
  paths, environment/`.env` content, secrets, and rejected values.

**TASK-0017 action:** start through the additive pre-QML preference read, then
navigate from Chat through Memory, Projects, Validation history, and Settings.
Exercise initial/repeated loads, filters, selection, refresh, navigation away,
conversation/project/terminal-run invalidation, one held query while other
worker kinds run, stale/mismatched/duplicate/late envelopes, and shutdown with
each worker combination. Perform memory create, duplicate return, duplicate
proceed, edit, stale edit, delete cancel, and delete confirm. Perform project
select/re-select/clear, archived-selection rejection, archive cancel, blocked
archive, and successful current-project archive. Load every validation fixture.
Load settings defaults, reject invalid/unknown/non-owned updates, atomically save
theme/context values, and observe startup/immediate application.

**TASK-0017 pass:** all of these assertions hold independently:

- the route set/order, one-facade ownership, exact page-state algebras, safe
  state text, confirmation/editor behavior, invalidation matrix, and navigation-
  away clearing match `ManualOperationsUI.md`; no placeholder route exists;
- memory Active/Deleted filtering, one evaluated-at value, effective Expired,
  ordering, explicit selection, safe owner/type/scope/content/keyword/topic/
  score/time/status fields, and complete ordered provenance/revisions match the
  contract; expiry writes nothing and deleted tombstones remain inspectable;
- create/edit/delete validation and immutable fields are exact; a stale revision
  writes/emits nothing; cancel delete invokes nothing; confirmed success writes
  one canonical source/revision, produces the contracted selection/filter, and
  deleted records cannot edit/delete/restore;
- creation duplicate guidance uses canonical normalization, same scope/owner,
  stored Active including Expired, deterministic order and safe fields. Return
  changes nothing; Proceed creates a separate record; no candidate is merged,
  rewritten, replaced, linked, or deleted and no merge control exists;
- after each successful memory commit, application integration emits exactly
  `memory_created`, `memory_edited`, or `memory_soft_deleted` in operation order
  with stage `MEMORY`, affected non-null memory/revision IDs, null processing/
  model correlation and `error_type`, and the validated fingerprint. No failed,
  stale, cancelled, guidance-only, or suppressed action emits an event, and no
  event/log contains memory content or form/provenance text;
- project lists/order/current association and state version are exact; actual
  select/clear changes state once, facade re-selection and a raced unchanged
  result write nothing, the existing one bounded CAS retry is preserved, a
  second conflict and archived selection reject safely, and actual change causes
  the contracted TASK-0016/Memory/Projects invalidations;
- archive cancel writes nothing, the non-terminal-run guard rejects, and success
  changes only project status/update time. Every preservation sentinel and
  association remains; a current archived project is labeled as such and is not
  eligible for new selection;
- Validation history and Context inspection select the same latest run by
  linked user-message sequence. Attempt/outcome/report/violation/evidence and
  correction rows/count/order/adjacency are exact for terminal and non-terminal
  fixtures; empty, clarification, transport, controlled-failure, and load-error
  behavior remains distinct;
- none of the prohibited sentinels or any raw/open DTO, internal ID, prompt,
  candidate/response, provider value, correction prompt, raw validation detail,
  unsafe failure, exception, path, endpoint/model identity, environment value,
  secret, or rejected configuration value occurs in a safe application result,
  envelope, facade/list model, QML text, accessibility tree, announcement,
  trace, or log;
- absent preferences produce `SYSTEM`, `true`, and null without a write. Only
  theme/context are direct settings controls and save changed rows atomically;
  invalid/unknown/last-conversation writes reject, YAML/configuration never
  changes, and TASK-0015 still owns later last-conversation selection behavior;
- the exact safe configuration category/field/order/value/origin labels and full
  64-character lowercase fingerprint appear, while every prohibited source
  value is absent. The loader's immutable origin metadata is not fingerprinted
  or persisted;
- startup and successful saves map `SYSTEM`/`LIGHT`/`DARK` only to the exact Qt
  color-scheme calls; changes apply immediately with no normal restart or
  `QQuickStyle`/KDE/KWin dependency. Context visibility applies immediately and
  hiding an active Context page moves safely to Chat;
- at most one finite TASK-0017 worker exists. Repeated reads retain one latest
  coalesced route; mutation repeats are suppressed, never queued. Manual,
  foreground, and inspection work coexist only through separate scopes/
  connections, and connection create/read-or-write/close thread identities are
  equal and non-GUI;
- terminal delivery is immutable/queued and GUI mutation GUI-thread-only;
  stale/mismatched/late results change nothing; held work leaves GUI sentinels,
  navigation, cancellation, and close responsive; shutdown performs no blocking
  join/force termination and disposes only after all owned scopes close;
- every exact accessible ID/name/role/value/action/focus/description and polite
  announcement/revision is observable through native Qt interfaces without a
  screen reader, KDE service, or window-manager rule; and
- source-checkout and installed-package nested QML loading, valid application
  startup, both existing AT-013 ownership passes, the unchanged TASK-0009
  component pass above, and the complete then-current non-live suite remain
  green.

UI, trace, orchestration, and provider integration remain outside TASK-0009;
the TASK-0017 pass owns them without changing the component pass.

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

AT-016 may run only after the complete default/non-live suite and every AT-001
through AT-015 criterion are green in their required environments. If either
prerequisite is not green, AT-016 is not started and no AT-016 evidence artifact
is written. The completion report retains the prerequisite commands and
results; a later AT-016 artifact records only their closed `PASSED` statuses.

When AT-016 is explicitly selected, an absent
`CONTEXT_FOR_AI_RUN_OLLAMA` skips as environment absence, writes no artifact,
and never counts as evidence. A present value other than exactly `1` fails as an
invalid opt-in before the AT-016 artifact lifecycle begins. Exact value `1`
begins one opted-in acceptance execution and requires a present, non-empty
`CONTEXT_FOR_AI__MODEL__NAME`; absence or invalidity is a failed execution and
must produce a safe failed artifact when artifact writing remains available.
`CONTEXT_FOR_AI__MODEL__BASE_URL` remains an optional validated override, not a
third opt-in variable.

#### Versioned synthetic fixture

The fixture directory is `tests/fixtures/at_016_local_ollama_smoke/`. Its
`VERSION` file contains exactly:

```text
at-016-local-ollama-smoke-v1
```

It is an independent copy of
`tests/fixtures/complete_configuration/`, whose source `VERSION` is
`mvp-config-fixture-v2`. The copy contains `config/app.yaml`,
`config/context.yaml`, `config/logging.yaml`, `config/memory.yaml`,
`config/models.yaml`, and `config/validation.yaml` plus its own `VERSION`; the
live fixture does not load or mutate the source directory. Every unlisted rule,
list, scalar, and path value is copied value-for-value. The AT-016 copy has only
these fixed differences and live substitutions:

- `model.base_url` is `http://127.0.0.1:11434`; the optional existing
  `CONTEXT_FOR_AI__MODEL__BASE_URL` override may replace it only through the
  normal loader and must still be direct numeric-loopback HTTP.
- `model.name` is the valid non-live placeholder
  `at-016-model-must-be-overridden`; exact opt-in rejects a missing model-name
  environment value before this placeholder can reach composition or the
  adapter. The required override supplies one installed model identity and is
  normalized by the existing configuration contract.
- `model.context_window_tokens` is `4096`.
- `model.request_timeout_seconds` is `60`.
- `model.temperature` is `0.0`.
- `context.maximum_prompt_tokens` is `2048` and
  `context.reserved_response_tokens` is `512`; the effective prompt budget is
  therefore `2048`.
- `validation.max_revisions` is `0`. Every other validation rule is copied
  unchanged, including `TEXT_ANSWER -> NON_EMPTY_TEXT`.

The fixture is copied to one isolated application root. Its `../data` and
`../data/logs` paths therefore resolve inside that isolated root. The empty
database contains no project, topic, task, message, memory, named item, or
processing run. Normal startup creates/selects exactly one unscoped
conversation with the canonical version-`0` state: null project, topic, active
task, previous task, and expected output type, plus an empty topic stack.

The exact submitted user message is:

```text
Exactly answer CONTEXT_FOR_AI_SMOKE_OK.
```

The deterministic pre-provider expectations are:

- one `answer` intent-rule match, `IntentType.ANSWER`, confidence `1.00`, and
  expected output `TEXT_ANSWER`;
- one `exactly` qualifier with normalized capture
  `answer context for ai smoke ok`, action `answer`, and object
  `context for ai smoke ok`;
- zero reference mentions and an empty retrieval selection;
- no project, topic, or task proposal; the committed state changes only its
  expected output type to `TEXT_ANSWER` under the existing state contract;
- one active current-message `REQUIRED` constraint at priority `1000` with
  normalized rule `MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK`;
- the unchanged active derived `FORBIDDEN`
  `MUST_NOT_EXECUTE:IMAGE_OR_ACTION` constraint at priority `1000`; and
- response policy `TEXT_ANSWER`, `NON_EMPTY_TEXT`, text-only, no actions, and
  correction limit `0`.

No new validation predicate exists. The normal validator evaluates
`MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK` as the consecutive normalized
token sequence `answer context for ai smoke ok` in one candidate sentence. The
candidate must also be substantive and contain no configured action marker.
Separately, the AT-016 test performs a content-private smoke assertion that the
raw buffered candidate contains at least one exact case-sensitive
`CONTEXT_FOR_AI_SMOKE_OK` occurrence whose adjacent characters, when present,
are not ASCII letters, digits, or underscore. The assertion inspects content
in memory but never emits the sentinel or candidate to a log or artifact.

Raw response equality is not required. Additional natural-language text is
permitted only when the normal validator still passes and the bounded exact
sentinel occurrence exists. This makes the oracle structural rather than an
exact-prose comparison.

`validation.max_revisions: 0` makes AT-016 a one-generation smoke. There is
exactly one attempt-`0` request and at most one completed buffered response; no
correction row or revision request is permitted. If that first response fails
provider-envelope validation, the normal response validator, or the private
sentinel assertion, AT-016 fails. Production correction behavior outside this
fixture is unchanged.

#### Live action and success assertions

The real outer composition loads and validates the fixture, constructs the
production Ollama adapter from the normalized endpoint/model identity, and runs
the complete one-process/QML submission path. The adapter performs its exact
uncached `/api/version`, `/api/status`, `/api/show`, and `/api/generate`
sequence. `/api/show`, not `ollama list`, pulling, alias discovery, or an
operator assertion, proves model existence. `/api/version` is the only Ollama
version source. The one absolute `60`-second gateway deadline and the existing
`stream:false`, `raw:true`, `think:false`, `truncate:false`, and `shift:false`
wire contract remain unchanged.

Pass requires all of the following:

1. The default suite and AT-001 through AT-015 prerequisite statuses are
   `PASSED`.
2. Static configuration and all three live preflight checks pass before the
   prompt-bearing request.
3. One complete valid response is privately buffered within the shared
   deadline, and both the normal response validator and the private sentinel
   assertion pass.
4. Exactly one initial request, one response, one passed validation, and one
   final `ASSISTANT` message persist with the complete correlation set. The
   assistant message, persisted response, returned `assistant_text`, facade
   value, and QML-visible accepted text obey the existing byte-exact lineage
   contract.
5. The normal no-correction success trace sequence persists with exact stages
   and correlations. Serialized routine logs and traces contain none of the
   fixture user text, sentinel, rendered/raw prompt, packet JSON, candidate or
   assistant text, raw provider body/exception, endpoint, headers, credentials,
   cookies, environment values, `.env` content, absolute sensitive paths, or
   complete configuration.
6. The standalone evidence artifact below is written atomically, re-read, and
   validated against its closed schema.

Every invalid configuration, non-local endpoint, unavailable or incompatible
daemon, failed native cloud-disable attestation, missing or remote-marked model,
timeout, cancellation, malformed or wrong-model provider response, validation
failure, sentinel mismatch, persistence or lineage failure, missing or
redaction-violating trace, QML result mismatch, or evidence failure is a failed
opted-in acceptance result, never a dynamic skip.

#### Standalone evidence ownership and schema

The AT-016 acceptance harness in the testing/evaluation layer owns one
standalone local JSON artifact. Production application code, SQLite
repositories, `evaluation_cases`, `evaluation_runs`, routine logging, and QML
do not own or write it. The Definition-of-Done completion report references and
summarizes the artifact but is not the artifact itself.

The UTF-8 JSON document is one closed object with exactly these fields. JSON
object keys are serialized in lexicographic order with compact separators, no
duplicate keys, no ASCII escaping of ordinary Unicode, and one final LF.

```text
{
  "acceptance_id": "AT-016",
  "configuration_fingerprint": <64 lowercase hex characters or null>,
  "failure": null | {
    "code": <closed code permitted for the stage below>,
    "stage": <closed stage below>
  },
  "fixture_version": "at-016-local-ollama-smoke-v1",
  "gateway_elapsed_microseconds": <non-negative integer or null>,
  "limitations": [
    "MODEL_SPECIFIC_LIVE_ACCEPTANCE",
    "NON_CRYPTOGRAPHIC_LOCALITY_ATTESTATION",
    "STRUCTURAL_SMOKE_ORACLE_ONLY"
  ],
  "model": null | {
    "identity": <normalized configured model identity>,
    "tag": <normalized explicit or inserted model tag>
  },
  "os": null | {
    "machine": <non-empty string>,
    "release": <non-empty string>,
    "system": <non-empty string>
  },
  "prerequisites": {
    "at_001_through_at_015": "PASSED",
    "default_non_live_suite": "PASSED"
  },
  "provider": null | {
    "cloud_disable_source": "env" | "config" | "both",
    "name": "ollama",
    "version": <validated /api/version string>
  },
  "recorded_at_utc": <YYYY-MM-DDTHH:MM:SS.ffffffZ>,
  "result": "PASSED" | "FAILED",
  "schema_version": "at-016-evidence-v1"
}
```

`model` and `configuration_fingerprint` are non-null after successful complete
configuration validation and null when that evidence is unavailable. `provider`
is non-null only when the exact normalized fields are available from a durably
persisted `CompletedGeneration`; its `version` is the artifact's sole
Ollama-version field. Provider duration fields, token usage, and `done_reason`
are not required evidence and are omitted.

`gateway_elapsed_microseconds` is the persisted integral-microsecond projection
of the already-authoritative monotonic `CompletedGeneration.elapsed`, covering
all preflight checks through final envelope validation. It is non-null exactly
when that completed-generation evidence is durably available; it is null rather
than guessed for every earlier failure. There is no second total-test duration.

During artifact finalization for every otherwise writable exact-opt-in
execution, the acceptance harness collects OS evidence only through Python
standard-library `platform.system()`, `platform.release()`, and
`platform.machine()`, applies `str.strip()` to each result, and stores them
respectively as `system`, `release`, and `machine`. It does not call or serialize
`platform.node()`, `platform.platform()`, `platform.uname()`, hostname,
username, distribution marketing data, or any machine-unique identifier. If any
of the three allowed values is empty, `os` is null. That observation selects
`EVIDENCE/OS_METADATA_UNAVAILABLE` when the execution has no earlier failure;
it does not replace an already-selected earlier safe failure pair.

`result=PASSED` requires null `failure` and non-null configuration fingerprint,
model, provider, OS, and gateway elapsed fields. `result=FAILED` requires one
non-null failure pair from this closed table. The first safely classifiable
failure in the table's execution order is retained; a later assertion or OS
observation cannot replace it. Producing steps that were safely completed retain
their allowlisted fields, steps not reached leave their fields null, and OS is
handled by the finalization rule above. `ACCEPTANCE/UNEXPECTED_RESULT` is the
last-resort safe projection only when no earlier observation maps to another
listed pair; it never retains the unexpected value or exception.

| Stage | Permitted safe code |
|---|---|
| `CONFIGURATION` | `MODEL_NAME_REQUIRED`, `CONFIGURATION_INVALID` |
| `STARTUP` | `STARTUP_FAILED` |
| `TRANSPORT` | `PROVIDER_UNAVAILABLE`, `MODEL_NOT_FOUND`, `MODEL_TIMEOUT`, `MODEL_CANCELLED`, `INVALID_PROVIDER_RESPONSE` |
| `VALIDATION` | `VALIDATION_EXHAUSTED`, `SMOKE_SENTINEL_MISMATCH` |
| `PERSISTENCE` | `PERSISTENCE_ERROR` |
| `LINEAGE` | `LINEAGE_MISMATCH` |
| `TRACE` | `TRACE_ASSERTION_FAILED` |
| `REDACTION` | `REDACTION_ASSERTION_FAILED` |
| `UI` | `UI_ASSERTION_FAILED` |
| `EVIDENCE` | `OS_METADATA_UNAVAILABLE` |
| `ACCEPTANCE` | `UNEXPECTED_RESULT` |

No message, diagnostic, provider status/payload, exception text/type, traceback,
or unrestricted details field exists. The fixed `limitations` array is the
complete artifact limitation vocabulary and order; free-form limitations are
prohibited. The completion report may explain these codes without quoting any
prohibited content.

The artifact additionally prohibits fixture user text, sentinel/token text,
rendered or raw prompt, packet JSON, raw candidate/response/final assistant
text, raw provider objects, endpoint/base URL, headers, authorization/cookie
data, credentials, secrets, process environment values, `.env` content,
absolute sensitive paths, complete configuration, hostname, username, and
machine-unique identifiers.

#### File location, publication, and retention

Each exact-opt-in execution creates one unique artifact under the
repository-relative local directory `data/acceptance/at-016/`. The filename is
`at-016-<timestamp>.json`, where `<timestamp>` is the artifact's
`recorded_at_utc` with punctuation removed, for example
`at-016-20260808T123456123456Z.json`. The harness creates the directory when
needed and never embeds its absolute path in the document.

The harness writes a uniquely named temporary sibling, closes it, re-reads and
validates the exact schema and prohibited-content assertions, then publishes it
by an atomic same-directory rename only when the final filename does not exist.
A collision fails rather than overwriting. Every repeated execution therefore
creates a distinct artifact; the harness never appends to or replaces an older
artifact.

`data/acceptance/` is local-only completion evidence and must be covered by the
repository ignore rules before TASK-0018 live execution is implemented. Neither
the application nor acceptance harness automatically expires or deletes it. It
is retained until the operator explicitly removes it after it is no longer
needed for completion evidence, and it must not be committed.

An exact-opt-in execution attempts to write a `PASSED` or `FAILED` artifact
after all safely classifiable assertions. If artifact creation, serialization,
schema validation, prohibited-content validation, or atomic publication fails,
AT-016 fails and no valid evidence may be claimed. Because a failed writer
cannot reliably attest to its own failure, `EVIDENCE_WRITE_FAILED` is reported
only as a safe test/completion-report code; it is not fabricated inside a valid
artifact. No evidence failure becomes a warning or skip.

## Requirement traceability

| Requirement area | Acceptance IDs |
|---|---|
| Configuration, startup, local runtime | AT-001, AT-016 |
| Exact persistence, state, entity/reference | AT-002–AT-007, AT-015 |
| Constraints, retrieval, packet | AT-004–AT-009 |
| Gateway, validation, correction | AT-010–AT-012, AT-016 |
| UI and manual-operation safety | AT-013–AT-014 |
| Transaction, idempotency, recovery, traceability | AT-002, AT-012, AT-015–AT-016 |
