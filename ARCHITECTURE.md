# Context for AI — Architecture

## Architecture style and MVP runtime

Context for AI is a modular monolith. The MVP is one local Python 3 desktop
process using PySide6, Qt 6, and QML. Its UI, application orchestration,
context intelligence, domain model, SQLite adapters, configuration, logging,
and Ollama client live in one repository with explicit inward interfaces.

The application connects directly to a separately installed, locally configured
Ollama daemon on a numeric loopback address. The daemon must use its native
cloud-disable setting; the adapter verifies that state before every prompt. It
does not host an HTTP API or a separate context-service process. FastAPI, cloud
providers or cloud execution through Ollama, model routing, streaming,
embeddings, vector stores, file indexing, and background-worker systems are
deferred post-MVP work.

## Dependency direction

The following arrows mean static import dependencies, not merely runtime calls:

```text
Presentation ───────────────→ Application
Application ────────────────→ Domain
Application ────────────────→ Context Intelligence
Context Intelligence ───────→ Domain
Infrastructure ─────────────→ Domain and Application ports (implements them)
Composition root ───────────→ Presentation, Application, Infrastructure
```

- Presentation imports application use-case interfaces only; QML contains no
  context or persistence rules.
- Application coordinates ports and use cases. It imports no SQLite, Ollama,
  PySide6, or concrete infrastructure implementation.
- Context intelligence implements deterministic rules and imports domain types
  and ports only.
- Domain has no dependency on PySide6, QML, SQLite, Ollama, HTTP frameworks,
  or concrete infrastructure.
- Infrastructure implements inward ports. `ModelGateway` is an application port;
  `OllamaModelProvider` is its infrastructure implementation.
- The composition root is the sole place allowed to construct concrete adapters.
- Configuration loading owns static endpoint/model validation and normalization;
  it performs no provider request. Ollama adapter construction receives only the
  immutable normalized endpoint and bound model identity. Per-call generation
  settings remain in `GenerationRequest`; the adapter performs no configuration
  discovery.

## Layers

### 1. Presentation

PySide6/QML views, view models, and controllers display state and invoke
application use cases. A submission is dispatched to a bounded foreground
request task outside the QML UI thread. There is at most one active run per
application process; the UI exposes progress, cancellation, typed failures, and
a disabled/duplicate-submit state. This is not a durable background worker,
queue, or autonomous subsystem.

Before Qt/QML creation, one short-lived startup application scope performs the
recovery preflight and initial-conversation selection/first-run creation defined
by `docs/contracts/PresentationShell.md`; its startup-owned SQLite connection is
closed before the GUI is created. No foreground worker starts when preflight
finds no active run. When it finds one, the QML root is created in a disabled
recovery state and `RecoverProcessingRun` is invoked once in the same bounded
foreground model before submissions are enabled.

The Qt GUI thread exclusively owns QML objects, controllers, view models, and
all UI state. `ForegroundRunController` creates one ephemeral worker thread only
for an accepted explicit user submission or required startup recovery; it never
keeps a queue or polls for work. The worker opens one fresh application scope,
creates/uses/closes that scope's SQLite connection in its own thread, and emits
one immutable terminal envelope only after scope closure. The GUI thread never
receives a SQLite connection, cursor/row, mutable domain object, provider buffer,
or worker-affine object. Terminal and worker-finished connections are queued.
Only the terminal envelope may select a result state; the finished notification
may only release worker ownership and update enablement derived from that
ownership.

Cancellation sets a per-execution thread-safe token observed by the application
at its defined checkpoints and by the gateway before and while it waits; it
never force-terminates a Python/Qt thread. A recovery invocation receives a
fresh token rather than reconstructing pre-restart cancellation. On app shutdown
the controller disables new submissions, requests cancellation once, keeps the
GUI event loop alive, and delays final Qt exit until the terminal value and
worker-finished notification arrive. It never blocks the GUI waiting for a live
worker or adds a second transport timeout. A mismatched or late signal after
terminal delivery, replacement, shutdown disposal, or controller disposal is
ignored safely. These foreground tasks are user-owned and finite, not background
workers. The complete states, safe display, worker lifetime, and disposal rules
are authoritative in `docs/contracts/PresentationShell.md`.

TASK-0016 extends that shell with exactly one `CONTEXT_INSPECTION` route while
the entry-point-owned `ShellFacade` remains the sole QObject and presentation-
state owner exposed to QML. One private, finite inspection-query worker may
coexist with the foreground worker only through a separate read-only application
scope and SQLite connection. It performs one snapshot inspection, emits one queued
immutable safe result, and terminates; it has no queue, poller, persistent
thread, processing-run slot, or cross-thread persistence object. Inspection
page state is orthogonal to foreground processing state. Target selection,
redaction, stale-result rejection, refresh coalescing, accessibility, and
shutdown ownership are authoritative in
`docs/contracts/ContextInspection.md`.

### 2. Application

Coordinates `PrepareApplicationShell`, `ProcessUserMessage`,
`RecoverProcessingRun`, explicit memory CRUD, project selection,
project/conversation creation and archive, named-item registration, context
inspection, validation inspection, configuration inspection, and evaluation
execution. Shell preparation owns only the read-only recovery preflight and
deterministic initial-conversation selection/first-run creation. It does not
classify or resume recovery. Application owns run lifecycle transitions and
transaction orchestration, not context rules, UI state, worker creation, or SQL.
`InspectContext` is a read-only application query: it selects the latest
accepted run for one conversation and builds the closed historical, safe
inspection projection inside one repository-backed snapshot. It never re-runs a
decision or returns raw persistence, model, validation, or domain objects.

### 3. Domain

Defines entities, value objects, canonical enums, policies, repository/gateway
ports, events, and typed errors. Canonical decision rules are documented in
`docs/contracts/DomainAndDecisionRules.md`.

### 4. Context intelligence

Contains deterministic interpretation, state transitions, reference resolution,
constraint processing, retrieval, context-packet construction, validation,
correction planning, and confidence calculation. It does not call a provider or
persist directly.

### 5. Infrastructure

Implements SQLite repositories, Ollama transport, configuration loading,
structured logging, and local filesystem paths needed by those functions. It
does not include embeddings, vector stores, files/indexing, cloud integrations,
or background workers in MVP.

The Ollama adapter owns only direct transport communication, its ordered
health/local-only/model checks, private complete-body buffering, timeout and
cancellation propagation, provider-envelope validation, safe metadata
normalization, and translation into the canonical gateway outcomes. It does not
persist, emit application trace events, publish UI state, validate response
meaning, correct output, or coordinate application lifecycle state.

The static model configuration accepts only a direct numeric-loopback HTTP
endpoint and no credential, proxy, cloud-provider, fallback, or bypass field.
For every generation call, the adapter performs uncached health, native
cloud-disabled, and exact local-model checks before the prompt-bearing request.
It disables redirects, proxies, ambient authentication, and provider fallback.
The exact wire, timeout, buffering, failure, and metadata contract is
`docs/contracts/OllamaAdapter.md`.

The local host, operator-supplied direct endpoint, and separately installed
daemon are trusted runtime dependencies. The endpoint must identify Ollama
directly; accidental or deliberate configuration of a loopback intermediary is
unsupported and cannot be proven away by URL parsing. The daemon's status
endpoint is the fail-closed evidence for its native cloud policy, not
cryptographic attestation against a compromised loopback process. An absent or
incompatible status capability makes the provider unavailable and never enables
a less strict path.

TASK-0012 supplies the infrastructure adapter and its construction inputs, but
does not complete `main.py`, the full bootstrap graph, the application pipeline,
or QML composition. A later outer production composition root constructs the
adapter from the already validated endpoint/model identity and injects it into
`SystemPorts.model_gateway`. TASK-0012 test composition constructs it with a
controlled transport; application/pipeline test composition continues to inject
the deterministic mock.

### 6. Testing and evaluation

Contains unit tests, isolated SQLite integration tests, mock-provider complete
pipeline tests, UI acceptance tests, deterministic evaluation cases, and an
optional marked local-Ollama smoke test. Required Ollama-adapter component tests
use a controlled transport in the default suite and require no daemon. Tests that
contact a live daemon are marked `ollama`, opt-in, and separate from complete
pipeline acceptance.

## Proposed MVP source layout

```text
src/context_for_ai/
├── main.py
├── bootstrap/
├── ui/
│   ├── qml/
│   ├── controllers/
│   └── view_models/
├── application/
├── domain/
│   ├── entities/
│   ├── value_objects/
│   ├── ports/
│   └── errors/
├── context_engine/
├── infrastructure/
│   ├── database/
│   ├── ollama/
│   ├── configuration/
│   └── logging/
```

Root-level tests are the sole test layout:

```text
tests/
├── unit/
├── integration/
├── evaluation/
└── fixtures/
```

There is no `api/`, `workers/`, `embeddings/`, or `files/` MVP package. A shared
catch-all package is prohibited; reusable types belong in the innermost owning
layer.

QML assets may be split into nested directories under `ui/qml/`, but every root
and nested asset is packaged recursively and loaded from the installed package
resource tree rather than the process working directory. Missing/unresolved
assets fail through the closed pre-shell QML-load projection before any
foreground worker starts. `docs/contracts/PresentationShell.md` is authoritative
for this loading boundary.

## Main processing pipeline

```text
UI supplies conversation ID, exact text, optional explicit project selection,
idempotency key, and an owned cancellation token
→ Validate/acquire one immutable configuration snapshot
→ Acceptance transaction: same key returns existing; otherwise a global active
  run returns BUSY; otherwise persist exact user message and PERSISTED run
→ Load state and build deterministic snapshot
→ Interpret intent/topic/qualifiers/output type and confidence
→ Resolve references and record outcomes
→ Extract, prioritize, and resolve constraints; clarify on hard conflict
→ Retrieve eligible memories deterministically
→ One joined context transaction: persist contract-defined decisions, compare-
  and-swap state, immutable packet/retrieval aggregate, and CONTEXT_READY run
→ Short PENDING request preparation then IN_FLIGHT claim transactions
→ Call the configured gateway outside a transaction
→ Buffer complete candidate or persist typed timeout/cancel/failure
→ Deterministically validate the complete candidate and persist report
→ If valid: persist byte-exact linked assistant message and mark SUCCEEDED
→ If invalid and revisions remain: persist correction envelope and repeat
→ Otherwise: persist CONTROLLED_FAILURE; never display an invalid candidate
→ Return one exhaustive typed public result
```

After process restart, the pre-QML startup coordinator performs one read-only
application recovery preflight. With no global non-terminal run, it starts no
foreground worker. With one, the loaded shell invokes the separate
`RecoverProcessingRun` use case once in the bounded foreground execution model.
That use case revalidates/classifies the run, resumes only a provably
not-yet-sent step, and terminalizes an uncertain `IN_FLIGHT` request without
another provider call. This is neither a queue nor a background worker.

Memory records are never automatically created, merged, rewritten, expired, or
deleted by this pipeline.

## Persistence and model boundaries

`DATABASE_SCHEMA.md` defines the complete MVP schema. It stores projects,
conversations, topics, tasks, state, messages, entities, reference resolutions,
constraints, memories and revisions, processing runs, packets, retrieval
results, model lifecycle, validation, correction, terminal failures, settings,
and evaluations. The detailed transaction/recovery contract is in
`docs/contracts/Persistence.md`.

The MVP performs at most three text-generation calls per run: one initial call
and two revisions. Provider transport failures are not automatically retried.
Output is fully buffered, then validated before it reaches the UI.
