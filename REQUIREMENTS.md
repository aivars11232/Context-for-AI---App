# Context for AI — Requirements

The detailed deterministic behavior for these requirements is normative in
`docs/contracts/DomainAndDecisionRules.md`, `docs/contracts/ContextPacket.md`,
`docs/contracts/ProcessUserMessage.md`, `docs/contracts/ModelGateway.md`,
`docs/contracts/Persistence.md`, and `docs/contracts/ResponseValidation.md`.

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

### FR-011 AI provider abstraction

The system shall call one configured local Ollama text-generation model through
an inward-facing provider-independent gateway. It shall buffer complete output
before validation and shall not stream, route, fall back to another provider,
call tools, or execute actions in the MVP.

### FR-012 Response validation

The system shall deterministically validate a complete candidate response
against the packet's topic, intent, required constraints, forbidden actions,
preservation rules, expected output type, completeness, and repetition rules.

### FR-013 Bounded correction

The system shall make at most the configured zero through two automatic revision
calls after the initial generation. Its run-specific call limit is one plus that
configuration value, with three as an absolute cap. A timed-out, cancelled, or
failed transport call is not retried automatically.
Exhaustion returns a persisted controlled failure and never displays an invalid
candidate as the final answer.

### FR-014 Memory provenance and lifecycle

Every memory shall retain one or more non-null provenance records, scope,
confidence, creation and update times, immutable revision history, and a
retrieval-visible lifecycle state. Expiry excludes a memory from retrieval; it
does not delete it.

### FR-015 Context inspection

The UI shall show the active state, interpreted intent, expected output type,
references and their outcomes, constraints and conflicts, retrieved memories
with scores/reasons, confidence, validation result, and controlled-failure
status or deterministic clarification question when applicable.

### FR-016 Manual memory control

The user shall be able to inspect, create, edit, and soft-delete memories
through explicit UI operations. The MVP shall not automatically create, merge,
rewrite, or delete a memory.

### FR-017 Processing lifecycle

Every accepted submission shall have an idempotent processing run with durable
request, response, validation, correction, clarification, recovery, and
terminal-state lineage back to the user message. A successful run shall link the
displayed assistant message to exactly one accepted model response. Repeating an
existing idempotency key returns the existing run; a fresh key during an active
global run is a pre-acceptance busy result.

### FR-018 Configuration and observability

The application shall validate a documented YAML configuration at startup and
emit structured, redacted trace events that link each processing stage to the
conversation, message, processing run, and manual-memory lifecycle. Required
events and redaction fields are acceptance-tested.

## Non-functional requirements

### NFR-001 Local-first

The application shall operate locally by default and shall send message content
only to the configured local Ollama endpoint.

### NFR-002 Modular monolith

The MVP shall remain one repository and one local desktop process with explicit
presentation, application, domain, context-intelligence, infrastructure, and
testing boundaries.

### NFR-003 Deterministic tests

Core context rules and the complete pipeline with a mock provider shall be
testable without a live AI model, real clock, or shared user database.

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
progress, cancellation, duplicate-submit prevention, and typed error states.
It shall use the canonical ephemeral-worker/queued-signal/SQLite-thread
ownership contract and never force-terminate a worker thread.
