# Context for AI — Implementation Plan

Implement one stage at a time. Do not begin a later stage until the current stage passes its tests and startup checks.

## Stage 1 — Repository foundation

- Create `pyproject.toml`.
- Create source and test package structure.
- Add configuration loading.
- Add logging bootstrap.
- Add a minimal application-startup test.

Exit condition: imports succeed and pytest passes.

## Stage 2 — Domain model

- Add identifiers and enums.
- Add Conversation, Message, Project, ConversationState, Constraint, Reference, Memory, ContextPacket, ModelResponse, and ValidationResult.
- Add repository interfaces.
- Add instruction-priority and memory-retention policies.

Exit condition: domain unit tests pass without importing infrastructure.

## Stage 3 — SQLite persistence

- Add database connection and migrations.
- Implement conversation, message, state, memory, context-packet, and validation repositories.
- Add transaction handling.

Exit condition: repository integration tests pass against a temporary SQLite database.

## Stage 4 — Conversation state

- Implement active project, topic, task, previous task, output type, and topic stack.
- Persist and restore state.

Exit condition: state-transition tests pass.

## Stage 5 — Interpretation and constraints

- Implement rule-based intent, topic, qualifier, and output-type detection.
- Implement constraint extraction, normalization, priority, and conflict detection.

Exit condition: qualifier and instruction-conflict evaluation tests pass.

## Stage 6 — Reference resolution

- Implement mention extraction, recent-entity tracking, candidate ranking, and confidence.

Exit condition: basic reference-resolution evaluation tests pass.

## Stage 7 — Memory retrieval

- Implement keyword retrieval, project filtering, recency scoring, importance scoring, and deduplication.

Exit condition: relevant memories are selected and unrelated memories are excluded in tests.

## Stage 8 — Context packet

- Implement token budgeting, packet assembly, and prompt rendering.

Exit condition: packet-completeness tests pass.

## Stage 9 — Model gateway

- Add provider interface, mock provider, and Ollama provider.
- Add health check and controlled error handling.

Exit condition: gateway tests pass with the mock provider and optional Ollama integration test passes when Ollama is available.

## Stage 10 — Validation and correction

- Implement topic, intent, constraint, preservation, output-type, completeness, and repetition checks.
- Implement bounded correction with a maximum of two revisions.

Exit condition: invalid responses are rejected and retry limits are enforced.

## Stage 11 — Complete backend pipeline

- Implement `ProcessUserMessage` orchestration.
- Persist every stage result and return a final response object.

Exit condition: complete-pipeline integration test passes using the mock provider.

## Stage 12 — Desktop interface

- Add QML application shell, chat page, context panel, memory page, project page, validation page, and settings.
- Connect UI actions to application use cases.

Exit condition: application starts and the context-inspection acceptance test passes.

## Stage 13 — Local Ollama validation

- Configure the selected local model.
- Run the complete pipeline with Ollama.
- Record limitations and performance.

Exit condition: `AT-014 Complete pipeline` passes.
