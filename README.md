# Context for AI

Context for AI is a local desktop context layer for AI systems. It interprets intent, tracks active state, resolves references, extracts constraints, retrieves relevant memory, constructs a controlled context packet, validates model output, and updates state.

## Status and entry point

Open and follow `START_HERE.md`.

Read `START_HERE.md` and `SPECIFICATION_GOVERNANCE.md` before working. The
first permitted implementation task is
`tasks/TASK-0001-REPOSITORY-FOUNDATION.md`.

## Current state

- Product and engineering planning: complete for MVP start
- Repository control documents: complete
- Application code: not started
- Active task: TASK-0001

The MVP is a single local Python/PySide6/QML modular monolith using SQLite and
one local Ollama text-generation model. It does not include a network API,
cloud provider, streaming, embeddings, vector storage, file indexing, or
background workers.
