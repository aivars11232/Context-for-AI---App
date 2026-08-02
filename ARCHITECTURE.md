# Context for AI — Architecture

## Architecture style

Context for AI begins as a modular monolith. The desktop UI, application orchestration, context engine, domain model, persistence adapters, and AI-provider adapters live in one repository but remain separated by explicit interfaces.

## Dependency direction

```text
Presentation → Application → Domain
                    ↓
          Context Intelligence
                    ↓
            Infrastructure
```

The domain layer must not depend on PySide6, QML, SQLite, Ollama, FastAPI, or concrete infrastructure classes.

## Layers

### 1. Presentation
PySide6 and QML views, view models, and controllers. It displays state and invokes application use cases but contains no context rules.

### 2. Application
Coordinates use cases such as processing a message, rebuilding context, managing memory, opening a project, validating a response, and running evaluations.

### 3. Domain
Defines entities, value objects, repository interfaces, policies, events, enums, and domain errors.

### 4. Context intelligence
Contains interpretation, conversation state, reference resolution, constraint extraction, retrieval, context-packet construction, validation, correction, and confidence calculation.

### 5. Infrastructure
Implements SQLite repositories, Ollama integration, configuration, logging, file access, and later embedding adapters.

### 6. Local service boundary
The MVP may use direct in-process application services. Public interfaces must be designed so a localhost API can be added later without moving domain logic.

### 7. Testing and evaluation
Contains unit tests, infrastructure integration tests, complete-pipeline tests, and behavioral evaluation cases.

## Proposed source layout

```text
src/context_for_ai/
├── main.py
├── ui/
├── application/
├── domain/
├── context_engine/
├── infrastructure/
├── workers/
└── shared/
```

## Main processing pipeline

```text
User message
→ Persist original message
→ Load conversation and project state
→ Interpret intent, topic, qualifiers, and output type
→ Resolve references
→ Extract and prioritize constraints
→ Retrieve relevant memory
→ Build structured context packet
→ Call model gateway
→ Validate response
→ Revise if validation fails and retry limit allows
→ Persist response and validation report
→ Update conversation state and approved memories
→ Return final response to UI
```

## Initial persistence

SQLite stores users, projects, conversations, messages, conversation states, topics, tasks, references, constraints, memories, context packets, model calls, validation results, correction attempts, evaluation cases, and settings.

## Initial runtime

```text
PySide6/QML desktop process
├── Application orchestrator
├── Context engine
├── SQLite database
└── Ollama client
```

No separate service process is required for the first milestone.
