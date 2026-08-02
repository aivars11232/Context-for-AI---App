# Context for AI — MVP Scope

## Goal

Deliver a local desktop prototype that proves the complete context-processing pipeline works from user input to validated AI response.

## Included in MVP

1. PySide6 and QML desktop shell.
2. Conversation and message storage in SQLite.
3. Conversation-state manager.
4. Active project, topic, task, and output-type tracking.
5. Rule-based intent and qualifier extraction.
6. Basic reference resolution using recent conversation state and named entities.
7. Required, forbidden, preservation, preferred, optional, and conditional constraints.
8. Keyword-based memory retrieval with project and recency filtering.
9. Structured context-packet builder.
10. Ollama provider through a model-gateway abstraction.
11. Rule-based response validation.
12. Maximum of two automatic correction attempts.
13. Context inspection panel showing interpreted intent, resolved references, constraints, and retrieved memories.
14. Unit, integration, and context-behavior evaluation tests.
15. YAML configuration for models, context limits, memory, validation, and logging.

## Excluded from MVP

- Semantic embedding retrieval
- Vector databases
- Cloud synchronization
- Multiple concurrent AI-model pipelines
- Autonomous agents
- Voice input or voice context
- Screen or visual context
- Automatic project-file indexing
- Distributed services or microservices
- External databases
- Autonomous long-term memory rewriting
- Unbounded background workers
- Mobile applications

## MVP completion condition

The MVP is complete only when the acceptance tests in `ACCEPTANCE_TESTS.md` pass and the desktop application can execute the complete message-processing pipeline using a configured local Ollama model.
