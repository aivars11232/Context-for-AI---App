# Context for AI — Requirements

## Functional requirements

### FR-001 User messages
The system shall accept a user message and preserve its exact original text.

### FR-002 Conversation persistence
The system shall store conversations and messages in SQLite.

### FR-003 Active state
The system shall track the active project, topic, task, output type, and previous task for each conversation.

### FR-004 Intent interpretation
The system shall classify the current request into a supported intent and record confidence.

### FR-005 Qualifier detection
The system shall detect important qualifiers including `only`, `exactly`, `roughly`, `could`, `might`, `do not`, `same as before`, `without changing`, and `instead of`.

### FR-006 Reference resolution
The system shall resolve references such as `it`, `that`, `this`, `the previous one`, `the app`, and `the file` using recent conversation state.

### FR-007 Constraint extraction
The system shall represent constraints as REQUIRED, FORBIDDEN, PRESERVE, PREFERRED, OPTIONAL, CONDITIONAL, or ASSUMED.

### FR-008 Constraint priority
The system shall prioritize current explicit user instructions over older inferred context.

### FR-009 Memory retrieval
The system shall retrieve relevant memories using keyword, project, topic, recency, and importance filters.

### FR-010 Context packet
The system shall build a structured context packet containing the original request, interpreted intent, active state, references, constraints, retrieved context, confidence, and response policy.

### FR-011 AI provider abstraction
The system shall call Ollama through a provider-independent model gateway.

### FR-012 Response validation
The system shall validate the generated response against topic, intent, required constraints, forbidden actions, preservation rules, and expected output type.

### FR-013 Bounded correction
The system shall permit no more than two automatic response-revision attempts.

### FR-014 Memory provenance
Every stored memory shall retain its source, scope, confidence, creation time, and update time.

### FR-015 Context inspection
The UI shall show the active state, interpreted intent, resolved references, extracted constraints, retrieved memories, and validation result.

### FR-016 Manual memory control
The user shall be able to inspect, edit, and delete stored memories.

## Non-functional requirements

### NFR-001 Local-first
The application shall operate locally by default.

### NFR-002 Modular monolith
The MVP shall remain one repository and one local application with explicit internal boundaries.

### NFR-003 Deterministic tests
Core context rules shall be testable without a live AI model.

### NFR-004 Traceability
Context decisions, model calls, validation failures, and memory changes shall be logged with identifiers linking them to the originating message.

### NFR-005 Data preservation
Database migrations shall preserve existing data.

### NFR-006 Failure safety
The pipeline shall stop and report errors rather than silently skipping failed stages.

### NFR-007 Extensibility
AI providers and persistence implementations shall be replaceable through interfaces without changing domain logic.
