# Context for AI — MVP Roadmap

## Milestone 1 — Repository boots

- Python package, sole dependency manifest, YAML configuration, logging, and
  minimal QML startup boundary exist.
- AT-001 passes.

## Milestone 2 — Canonical local data exists

- Domain types/ports, SQLite migrations, repositories, provenance, lifecycle,
  and state-version invariants exist.
- Repository and migration integration tests pass.

## Milestone 3 — Deterministic context is constructed

- State, interpretation, qualifiers, constraints, references, retrieval,
  confidence, and packet construction work without a live model.
- AT-003 through AT-009 pass.

## Milestone 4 — Controlled mock-provider pipeline works

- Buffered model abstraction, deterministic validation, bounded correction,
  global admission, one-shot foreground recovery, transaction/idempotency
  behavior, and complete pipeline pass with a mock provider.
- AT-002 through the public seam, AT-010–AT-011, full AT-012, and AT-015 pass.

## Milestone 5 — Desktop MVP is inspectable and safe

- QML shell remains responsive during the sole global foreground execution,
  including the bounded startup-recovery presentation when one is required.
- Context, manual memory, project, validation, and settings views work through
  application use cases.
- AT-013 and AT-014 pass.

## Milestone 6 — Local Ollama acceptance

- The configured local Ollama model completes the bounded, buffered,
  validate-before-display pipeline.
- AT-016 passes under its explicit opt-in conditions.

Post-MVP ideas such as APIs, cloud providers, embeddings, vector retrieval,
file indexing, model routing, streaming, and workers are not roadmap milestones
until MVP completion is formally accepted.
