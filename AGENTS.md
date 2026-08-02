# Context for AI — Codex Instructions

## Project purpose

Context for AI is a local desktop application that adds a structured context-understanding layer between a user and an AI model.

The application must interpret user intent, resolve references, extract and prioritize constraints, retrieve relevant memory, build a structured context packet, send that packet to an AI model, validate the generated response, and update conversation and project state.

## Source of truth

The authoritative project documents are, in priority order:

1. The user's current explicit instruction.
2. `MVP_SCOPE.md` for MVP boundaries.
3. `REQUIREMENTS.md` for required behavior.
4. `ARCHITECTURE.md` for approved engineering boundaries.
5. `ACCEPTANCE_TESTS.md` for completion criteria.
6. `IMPLEMENTATION_PLAN.md` for implementation order.
7. Supporting planning documents under `docs/planning/`.

Codex must read the relevant documents before implementing or modifying a component.

If authoritative documents conflict, do not silently choose an interpretation. Report the conflict and stop before implementation.

## Approved technology stack

- Python 3.12 or newer
- PySide6
- Qt 6
- QML
- SQLite
- Ollama
- pytest
- YAML configuration files

Do not replace these technologies unless explicitly instructed.

## Architecture

The application must begin as a modular monolith with these boundaries:

- Presentation layer
- Application layer
- Domain layer
- Context intelligence layer
- Infrastructure layer
- Local service boundary
- Testing and evaluation layer

Do not introduce microservices, distributed systems, cloud synchronization, Kubernetes, message brokers, or an external database during the MVP.

## Development method

Work on one file at a time and make one meaningful change at a time.

Before editing a file:

1. State which file will be changed.
2. Explain why the change is required.
3. Identify the requirement or planning document that supports it.

After every meaningful change:

1. Run the relevant tests.
2. Run syntax, import, or type validation where applicable.
3. Confirm that existing tests still pass.
4. Stop immediately if tests, imports, application startup, or runtime validation fail.

Do not continue to another feature while an error remains unresolved.

## Implementation rules

- Do not invent missing requirements.
- Do not silently alter the approved architecture.
- Do not rename architectural components without justification.
- Do not create duplicate implementations of the same responsibility.
- Do not present empty placeholders as completed functionality.
- Do not implement future-stage features during MVP development.
- Do not modify unrelated files.
- Do not rewrite working code unnecessarily.
- Keep domain logic independent from Qt, SQLite, Ollama, and external APIs.
- Access AI providers through an abstraction layer.
- Access persistence through repository interfaces.
- Preserve traceability between requirements, code, and tests.
- Prefer deterministic rule-based behavior where the MVP specification requires it.
- Keep automatic correction attempts bounded.

## Testing rules

Every implemented component must have relevant tests.

Required test categories:

- Unit tests
- Integration tests
- Context-behavior evaluation tests

Tests must verify observable behavior, not only that mocks were called.

The complete message-processing pipeline must eventually be covered by an integration test.

## MVP boundary

Only features explicitly listed in `MVP_SCOPE.md` may be implemented during the MVP.

Anything listed as excluded or future work must not be added without explicit approval.

## Validation requirements

The application must validate generated responses against:

- active topic
- user intent
- required constraints
- forbidden actions
- preservation rules
- expected output type

No infinite retry or self-correction loops are allowed.

## Data safety

- Use local storage by default.
- Do not transmit user data to external services unless explicitly configured.
- Do not delete conversations, memories, or project data without an explicit operation.
- Database migrations must preserve existing data.
- Memory records must retain their source, scope, confidence, and timestamps.

## Documentation

Update documentation when architecture, configuration, interfaces, or behavior changes.

Do not mark a feature complete unless its implementation, tests, and documentation agree.

## Stopping conditions

Stop and report the issue when:

- authoritative requirements conflict
- the current file state is uncertain
- a required dependency is unavailable
- tests fail
- imports or application startup fail
- implementation would require changing the approved architecture
- the next step would exceed the requested scope
