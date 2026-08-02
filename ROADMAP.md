# Context for AI — Roadmap

## Milestone 1 — Repository boots

- Python package structure exists.
- Configuration and logging bootstrap load.
- Test suite runs.

## Milestone 2 — Core data exists

- Domain entities and interfaces exist.
- SQLite persists conversations, messages, state, memories, context packets, and validation results.

## Milestone 3 — Context is constructed

- State tracking, interpretation, constraints, references, retrieval, and packet building work deterministically.

## Milestone 4 — Model responses flow

- Mock model gateway works.
- Ollama adapter is isolated behind the gateway.
- Complete backend pipeline passes integration tests.

## Milestone 5 — Responses are controlled

- Validation detects violations.
- Correction attempts are limited to two.
- Failures return controlled results.

## Milestone 6 — Desktop MVP works

- QML shell accepts messages.
- Context inspection is visible.
- Memory and project views operate through application use cases.

## Milestone 7 — Local Ollama acceptance

- Configured local Ollama model completes the end-to-end pipeline.
- AT-014 passes.
