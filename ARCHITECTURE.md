# Context for AI — Architecture

## Architecture style and MVP runtime

Context for AI is a modular monolith. The MVP is one local Python 3 desktop
process using PySide6, Qt 6, and QML. Its UI, application orchestration,
context intelligence, domain model, SQLite adapters, configuration, logging,
and Ollama client live in one repository with explicit inward interfaces.

The application connects to a separately installed, locally configured Ollama
daemon. It does not host an HTTP API or a separate context-service process.
FastAPI, cloud providers, model routing, streaming, embeddings, vector stores,
file indexing, and background-worker systems are deferred post-MVP work.

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

## Layers

### 1. Presentation

PySide6/QML views, view models, and controllers display state and invoke
application use cases. A submission is dispatched to a bounded foreground
request task outside the QML UI thread. There is at most one active run per
application process; the UI exposes progress, cancellation, typed failures, and
a disabled/duplicate-submit state. This is not a durable background worker,
queue, or autonomous subsystem.

The Qt GUI thread exclusively owns QML objects, controllers, view models, and
all UI state. `ForegroundRunController` creates one ephemeral worker thread only
after an explicit user submission and invokes the application use case there;
it never keeps a queue or polls for work. The worker owns every SQLite
connection it uses, creates/closes it in that thread, and returns immutable
result DTOs through queued Qt signals. The GUI thread never passes a SQLite
connection, ORM row, mutable domain object, or provider buffer across the
thread boundary.

Cancellation sets a thread-safe token observed by the gateway before and while
it waits; it never force-terminates a Python/Qt thread. On app shutdown the
controller disables new submissions, requests cancellation, and delays final
Qt exit until the worker emits a terminal DTO or the bounded provider timeout
has produced its typed terminal outcome. A late signal after a controller is
disposed is ignored safely. The controller joins/closes the ephemeral worker
after terminal delivery. These foreground tasks are user-owned and finite, not
background workers.

### 2. Application

Coordinates `ProcessUserMessage`, explicit memory CRUD, project selection,
project/conversation creation and archive, named-item registration, context
inspection, validation inspection, configuration inspection, and evaluation
execution. It owns run lifecycle transitions and transaction orchestration, not
context rules or SQL.

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

### 6. Testing and evaluation

Contains unit tests, isolated SQLite integration tests, mock-provider complete
pipeline tests, UI acceptance tests, deterministic evaluation cases, and an
optional marked local-Ollama smoke test.

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

## Main processing pipeline

```text
UI supplies conversation ID, exact text, optional explicit project selection,
and idempotency key
→ Short acceptance transaction: persist immutable user message and PERSISTED run
→ Load state and build deterministic snapshot
→ Interpret intent/topic/qualifiers/output type and confidence
→ Resolve references and record outcomes
→ Extract, prioritize, and resolve constraints; clarify on hard conflict
→ Retrieve eligible memories deterministically
→ Persist deterministic state/decision changes, immutable context packet, and CONTEXT_READY run
→ Short request-start transaction; call local Ollama outside a transaction
→ Buffer complete candidate or persist typed timeout/cancel/failure
→ Deterministically validate the complete candidate and persist report
→ If valid: persist linked assistant message and mark SUCCEEDED
→ If invalid and revisions remain: persist correction envelope and repeat
→ Otherwise: persist CONTROLLED_FAILURE; never display an invalid candidate
→ Return final text, clarification, or typed controlled failure to the UI
```

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
