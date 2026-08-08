# Context for AI — MVP Scope

## Goal

Deliver a local desktop prototype that proves the complete context-processing pipeline works from user input to validated AI response.

## Included in MVP

1. One local Python 3 desktop process using PySide6, Qt 6, and QML. The UI
   calls in-process application services; there is no localhost HTTP service or
   durable worker. Exactly one user-owned foreground processing run may be
   non-terminal in the application at a time.
2. Conversation, message, project, topic, task, context-decision, model-call,
   validation, and memory storage in SQLite.
3. Explicit create/select/archive project operations, explicit create/select
   conversation operations, one deterministic unscoped first-run conversation
   bootstrap before the minimum shell becomes send-ready, and conversation state
   tracking for the active project, topic, task, previous task, and expected text
   output type.
4. Deterministic rule-based intent, qualifier, output-type, and confidence
   interpretation.
5. Deterministic basic reference resolution using recent state, recent
   messages, and an explicit entity registry, including explicit named-item
   registration/declaration only.
6. Required, forbidden, preserve, preferred, optional, conditional, and
   assumed constraints, including deterministic priority and conflict handling.
7. Explicit-user-operation memory CRUD, provenance, revisions, expiry state,
   and deletion auditability. Automatic memory extraction, rewriting, merging,
   and cleanup are not MVP behavior.
8. Deterministic keyword-based memory retrieval using project, topic, recency,
   importance, scope, and stable tie-breaking.
9. A versioned, immutable structured context packet with deterministic token
   budgeting and prompt rendering.
10. One configured Ollama text-generation provider behind a model-gateway
    abstraction. Responses are fully buffered before validation and display.
11. Deterministic response validation and at most two automatic revisions after
    the initial generation, for a maximum of three generation calls per run.
12. A context inspection panel showing active state, interpreted intent,
    references, constraints, retrieved memories, confidence, and validation
    status; manual memory management; project/conversation management;
    validation history; and the narrowly permitted presentation settings.
13. Unit, SQLite integration, complete-pipeline, UI acceptance, and
    context-behavior evaluation tests using deterministic fixtures and a mock
    provider, plus a separately marked local-Ollama smoke acceptance test.
14. YAML configuration for application, model, context, memory, validation,
    logging, and storage settings.

## Excluded from MVP

- Semantic embedding retrieval
- Vector databases
- Embedding models
- Cloud synchronization
- Multiple concurrent AI-model pipelines; the MVP permits one global foreground
  processing run only
- Cloud AI providers
- Model routing or fallback model selection
- Streaming output to the UI
- Tool calls or action execution, including image generation
- Autonomous agents
- Voice input or voice context
- Screen or visual context
- Automatic project-file indexing
- File or image attachment ingestion
- Distributed services or microservices
- FastAPI or any localhost HTTP API
- External databases
- Autonomous long-term memory rewriting
- Automatic memory extraction, merging, expiry deletion, or rewriting
- Background workers
- Mobile applications

## MVP completion condition

The MVP is complete only when the executable acceptance criteria in
`ACCEPTANCE_TESTS.md` pass and the desktop application executes the complete,
buffered message-processing pipeline with a configured local Ollama model.
