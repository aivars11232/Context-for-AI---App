# TASK-0002 — Canonical Domain Primitives and Policies

Status: Blocked by TASK-0001

## Goal

Implement the dependency-free domain vocabulary required by the canonical MVP
contracts.

## Sources

- `docs/contracts/DomainAndDecisionRules.md`
- `DATABASE_SCHEMA.md`
- `ARCHITECTURE.md`
- `CODING_STANDARDS.md`

## Required work

1. Add UUID/value-object types, UTC time helpers, canonical enums, entities,
   typed domain errors, and immutable result objects.
2. Add domain representations for project, conversation, topic, task, message,
   state, entity, reference outcome, constraint, memory, packet, processing
   run, model lifecycle, validation, correction, and safe failure.
3. Add deterministic domain policies for priority bands, state transitions,
   confidence bands, and lifecycle invariants.
4. Add unit tests for enum validity, equality/immutability, score/range checks,
   transition rules, and error behavior.

## Boundaries

- No SQLite, PySide6, QML, Ollama, HTTP, YAML, or infrastructure imports.
- No repositories, migrations, model calls, UI, or context-engine parsing.
- Do not add post-MVP types for tools, streaming, cloud providers, embeddings,
  files, workers, or multi-user identity.

## Verification

- Run focused domain unit tests.
- Run an import-boundary check proving domain modules have no forbidden imports.
- Run the full current test suite and syntax/import validation.

## Exit criteria

- Every canonical enum and typed lifecycle state is represented once.
- Domain policies match the named contracts without duplicate ownership.
- All verification is green.
