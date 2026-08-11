# Context for AI — Requirements

The detailed deterministic behavior for these requirements is normative in
`docs/contracts/DomainAndDecisionRules.md`, `docs/contracts/ContextPacket.md`,
`docs/contracts/ProcessUserMessage.md`, `docs/contracts/ModelGateway.md`,
`docs/contracts/OllamaAdapter.md`, `docs/contracts/Persistence.md`,
`docs/contracts/ResponseValidation.md`, and
`docs/contracts/PresentationShell.md`, with context-inspection behavior in
`docs/contracts/ContextInspection.md` and the remaining bounded manual-operation
presentation behavior in `docs/contracts/ManualOperationsUI.md`.

## Functional requirements

### FR-001 User messages

For each accepted text submission, the system shall persist exact original
Unicode text before any interpretation, model call, or processing failure path
can occur. A new submission rejected before acceptance because the single global
foreground run is busy creates no message or run and returns typed `BusyError`.

### FR-002 Conversation persistence

The system shall persist the canonical MVP data model in SQLite, including
conversations, messages, state, named entities, reference resolutions,
constraints, clarifications, memories, retrieval selections/exclusions, packets,
processing runs, model calls, validation, correction, and terminal failures.

### FR-003 Active state

The system shall maintain one versioned state per conversation. Its active
project is the conversation's single project association; it also tracks active
topic, active task, previous task, and expected text output type.

The user shall be able to explicitly create/select conversations and
create/select/archive projects under the canonical lifecycle invariants.
Before the minimum shell becomes send-ready, startup shall select the last valid
conversation, otherwise the most recently updated conversation, or atomically
create exactly one unscoped null-title conversation with a version-`0` state on
an empty first-run database. This startup default does not replace the explicit
conversation-management operations owned by later UI work.

The TASK-0017 project presentation slice shall list active and archived
projects, select or clear only the current conversation's association using its
versioned state, and archive only an eligible active project. Archiving shall
preserve existing associations and every conversation, message, and memory as
defined by `docs/contracts/ManualOperationsUI.md`.

### FR-004 Intent interpretation

The system shall deterministically classify each request into a canonical
intent and expected output type, record confidence, and return a clarification
result rather than silently guessing when confidence or ambiguity rules require
it. It shall use the versioned YAML phrase table, canonical intent/output mapping,
and narrow topic/task proposal grammar.

### FR-005 Qualifier detection

The system shall detect and normalize `only`, `exactly`, `roughly`, `could`,
`might`, `do not`, `same as before`, `without changing`, and `instead of`
according to the canonical qualifier rules.

### FR-006 Reference resolution

The system shall resolve eligible references such as `it`, `that`, `this`,
`the previous one`, and `the app` against the entity registry, active state,
and recent messages. It shall persist resolved, ambiguous, and unresolved
outcomes with source evidence, immutable mention order, and confidence. It shall
register a named item only through the explicit declaration/UI operation.

### FR-007 Constraint extraction

The system shall represent constraints as `REQUIRED`, `FORBIDDEN`, `PRESERVE`,
`PREFERRED`, `OPTIONAL`, `CONDITIONAL`, or `ASSUMED`, with immutable ordering,
source/evidence, condition AST/evaluation, and underlying predicate where
applicable.

### FR-008 Constraint priority and conflict safety

The system shall apply the canonical priority order, retain evidence for every
discarded lower-priority constraint, and return a clarification result before a
model call when equally authoritative hard constraints conflict.

### FR-009 Memory retrieval

The system shall retrieve eligible memories with deterministic keyword,
project, topic, recency, importance, scope, correction, threshold, and
tie-breaking rules, and shall retain selection/exclusion evidence. It shall not
use embeddings or vector search in the MVP.

### FR-010 Context packet

The system shall build an immutable, versioned context packet containing the
exact request, interpretation, state, references, constraints, retrieved
memories, confidence, response policy, and trace identifiers. It shall apply
the canonical token-budget and truncation rules, including non-droppable hard
conditional and conflict evidence.

Every newly constructed packet shall use `mvp-prompt-policy-v2`. Its trusted
prompt shall retain each constraint's canonical `normalized_rule` as
machine-audit data and shall also render the deterministic model-facing
semantic instruction derived from that rule. The prompt shall additionally
render only the closed topic, output-shape, action-marker, and active-preserve
semantics needed for the same production validator to judge the response. No
candidate-failing production requirement may depend on model semantics absent
from those trusted projections.

This requirement does not authorize a wholesale `validation_context` dump,
untrusted source text as instruction, free-form or model-generated paraphrase,
or weaker validation. Historical `mvp-prompt-policy-v1` packets and model
requests remain immutable, historically truthful, and renderable only through
their version-specific compatibility path; they are not rewritten as v2.

### FR-011 AI provider abstraction

The system shall call one configured local-only Ollama text-generation model
through an inward-facing provider-independent gateway. Before every
prompt-bearing request, the Ollama adapter shall fail closed unless the direct
numeric-loopback daemon is healthy, reports its native cloud features disabled,
and reports the exact configured model as local. It shall buffer complete output
before validation and shall not stream, route, pull or substitute a model, fall
back to another provider, call tools, or execute actions in the MVP. The exact
provider wire and failure behavior is normative in
`docs/contracts/OllamaAdapter.md`.

### FR-012 Response validation

The system shall deterministically validate a complete candidate response
against the immutable packet's snapshotted topic terms, intent-to-output-type
mapping, required constraints, forbidden actions, preservation rules, selected
output-shape rule, completeness, and repetition rules. Validation shall use
only the canonical finite lexical and structural predicates, produce the same
typed report and exact score for identical inputs, treat documented warnings as
non-failing, and perform no model call, repository lookup, packet mutation, or
fact/hallucination judgment.

Prompt-policy v2 changes only what trusted semantics are communicated before
generation. It shall not change candidate normalization, canonical predicate
parsing, `MUST_EXACTLY` consecutive-token matching, violation behavior, score,
or any other TASK-0013 validator rule; no acceptance-only or model-specific
validator path is permitted.

### FR-013 Bounded correction

The system shall make at most the configured zero through two automatic revision
calls after the initial generation. Its run-specific call limit is one plus that
configuration value copied into the immutable packet, with three as an absolute
cap. The packet value is the sole correction-limit authority; a correction
retains the packet and hard constraints unchanged. A timed-out, cancelled, or
failed transport call is not retried automatically. Exhaustion persists the
canonical validation controlled failure, creates no assistant link, and never
displays an invalid candidate as the final answer.

### FR-014 Memory provenance and lifecycle

Every memory shall retain one or more non-null provenance records, scope,
confidence, creation and update times, immutable revision history, and a
retrieval-visible lifecycle state. Expiry excludes a memory from retrieval; it
does not delete it. Manual inspection shall expose the stored and effective
status at one query `evaluated_at`, complete ordered provenance/revisions, and
retained deleted tombstones through the safe projection in
`docs/contracts/ManualOperationsUI.md`; inspection and expiry shall write
nothing.

### FR-015 Context inspection

For the latest accepted processing run in the shell's current conversation, the
UI shall show the historical active project/topic/task decision, interpreted
intent, expected output type, qualifier evidence, references and safe source
evidence, constraints and persisted conflict groups, selected memories with
scores/reasons, overall and component confidence, latest safe validation
evidence, and committed correction count. A clarification run shall show its
deterministic reason/question; a controlled-failure or cancellation run shall
show its safe terminal status.

Every field shall distinguish available, empty, not-applicable, and unavailable
durable evidence as defined in `docs/contracts/ContextInspection.md`; current
conversation state shall not fill a historical gap. Inspection is a read-only
application use case exposed through the existing shell facade. No prompt,
candidate response, provider metadata, raw exception, unsafe detail, or open
persistence/domain DTO shall reach QML or accessibility output.

The separate TASK-0017 validation-history page shall target that same latest
accepted run deterministically and expose every ordered safe validation attempt,
correction relationship/count, and controlled failure. It shall not expose any
prompt, candidate/response text, provider metadata, raw validation internals,
unsafe failure detail, or internal ID through its application result, facade,
QML, accessibility tree, or announcements.

### FR-016 Manual memory control

The user shall be able to inspect, create, edit, and soft-delete memories
through explicit UI operations. The MVP shall not automatically create, merge,
rewrite, or delete a memory. Soft deletion shall require the exact explicit
confirmation in `docs/contracts/ManualOperationsUI.md`, retain content and full
history, and provide no restore or repeated-delete action. Creation-time
same-scope/owner normalized duplicate guidance shall be advisory: proceeding
creates a separate record and no merge button or automatic mutation exists.

### FR-017 Processing lifecycle

Every accepted submission shall have an idempotent processing run with durable
request, response, validation, correction, clarification, recovery, and
terminal-state lineage back to the user message. A successful run shall link the
displayed assistant message to exactly one accepted model response with
byte-exact UTF-8 text equality. Repeating an
existing idempotency key returns the existing run; a fresh key during an active
global run is a pre-acceptance busy result. Before QML creation, startup shall
perform one bounded application recovery preflight. It shall start no foreground
worker when no non-terminal run exists; when one exists, it shall invoke exactly
one bounded foreground `RecoverProcessingRun` after the shell root loads and
before accepting new submissions. Recovery shall resume only provably
not-yet-sent work and shall terminalize, never retry, an uncertain `IN_FLIGHT`
model call.

TASK-0017 reads and mutations shall execute through at most one finite manual-
operations worker at a time, separately from the foreground and context-
inspection workers, with one same-thread-owned SQLite scope/connection per
operation, queued immutable safe delivery, stale-result rejection, no mutation
queue or presentation-side retry, and asynchronous disposal as defined by
`docs/contracts/ManualOperationsUI.md`.

### FR-018 Configuration and observability

The application shall validate a documented YAML configuration at startup and
emit structured, redacted trace events that link each processing stage to the
conversation, message, processing run, and manual-memory lifecycle. Required
events, recovery order, correlation fields, safe error codes, and redaction
rules are defined in `docs/contracts/ConfigurationAndLogging.md` and are
acceptance-tested.

Configuration, migration, composition, recovery-preflight, and QML-load startup
failures shall use the closed safe presentation in
`docs/contracts/PresentationShell.md`. Failures before QML loading shall create
no QML engine or root; a QML-load failure shall leave no usable root. None shall
start a foreground worker or reveal a raw diagnostic or configured value.

TASK-0017 shall expose only `ui.theme` and `ui.context_panel_visible` as direct
settings controls, preserve later conversation-selection ownership of
`ui.last_selected_conversation_id`, and keep every YAML/process configuration
value read-only. Its configuration view shall contain only the closed safe
field allowlist, per-field origin, and full normalized non-secret fingerprint in
`docs/contracts/ManualOperationsUI.md`. Theme is an immediately applied Qt
color-scheme preference, not a Qt Quick Controls/KDE/KWin style change. Each
successful manual-memory trace event remains application-owned, post-commit,
fingerprinted, correlated, and content-redacted.

## Non-functional requirements

### NFR-001 Local-first

The application shall operate locally and shall send message content only through
a direct numeric-loopback transport to the configured Ollama daemon after an
uncached native cloud-disabled and local-model attestation. It shall not send
content through any DNS name, redirect, proxy, tunnel, API-key/cloud-provider
path, or response-supplied location that it configures, discovers, or follows.
The configured loopback endpoint is a trusted operational prerequisite and must
identify the daemon directly; undisclosed local-host interception is outside the
MVP threat model. If the application cannot establish its defined locality
conditions, it shall send no prompt and return the canonical safe gateway
failure.

### NFR-002 Modular monolith

The MVP shall remain one repository and one local desktop process with explicit
presentation, application, domain, context-intelligence, infrastructure, and
testing boundaries.

### NFR-003 Deterministic tests

Core context rules and the complete pipeline with a mock provider shall be
testable without a live AI model, real clock, or shared user database. Required
Ollama-adapter protocol tests shall use a controlled transport and require no
daemon; every live-daemon test is separately marked and opt-in.

### NFR-004 Traceability

Context decisions, retrieval results, model calls, validation failures,
correction attempts, failures, and memory changes shall be traceable to the
originating message and processing run.

### NFR-005 Data preservation

Numbered SQLite migrations shall preserve existing data, run transactionally,
record their version/checksum, and have integration coverage for upgrades.

### NFR-006 Failure safety

The pipeline shall stop at a failed stage, make the documented best effort to
persist a typed safe failure, and never silently skip a stage or expose an
unvalidated candidate as final output. If persistence itself is unavailable, it
shall return `PersistenceError` and leave recovery evidence rather than claim an
unwritten failure record.

### NFR-007 Extensibility

Persistence and model-provider implementations shall be replaceable through
inward interfaces without changing domain or context-intelligence rules.

### NFR-008 Responsive UI

Long-running processing shall not block the QML UI thread. The UI shall expose
presentation-owned indeterminate progress, cancellation, duplicate-submit
prevention, and typed error states. It shall enforce one global foreground
execution, including one-shot startup recovery only when preflight requires it,
and use the canonical ephemeral-worker/queued-signal/SQLite-thread ownership
contract in `docs/contracts/PresentationShell.md`. UI state may change only on
the GUI thread by applying the immutable startup-preparation value, handling
local actions, handling queued immutable terminal values, or handling the queued
worker-finished ownership notification; that notification cannot select a
result state. Progress shall not be derived from infrastructure traces, and no
worker thread may be force-terminated.

The same GUI-thread-only mutation, queued immutable handoff, connection/thread
ownership, stale-result, responsiveness, and non-blocking shutdown requirements
apply to the finite TASK-0017 execution role in
`docs/contracts/ManualOperationsUI.md`. It may coalesce only one latest pending
read route; it never queues a mutation or creates a persistent/background
worker.
