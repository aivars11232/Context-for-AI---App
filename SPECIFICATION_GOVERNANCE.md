# Context for AI — Specification Governance

## Purpose

This document resolves document-precedence questions for the MVP. It is a root
control document and applies before any implementation or documentation change.

## Authority and precedence

When two documents disagree, apply the first applicable source in this order:

1. The user's current explicit instruction.
2. `AGENTS.md`.
3. This document.
4. `MVP_SCOPE.md` for what is and is not MVP work.
5. `REQUIREMENTS.md` for externally observable MVP behavior.
6. `ARCHITECTURE.md` for boundaries, runtime shape, and dependency direction.
7. `DATABASE_SCHEMA.md` for persisted MVP data and lifecycle invariants.
8. `COMPONENT_CONTRACTS.md` and the detailed documents under `docs/contracts/`
   for component interfaces and deterministic behavior.
9. `ACCEPTANCE_TESTS.md` for executable completion criteria.
10. `IMPLEMENTATION_PLAN.md` and the current task file for implementation order
    and scoped delivery work.
11. `BACKLOG.md`, `ROADMAP.md`, `CODING_STANDARDS.md`, and
    `DEFINITION_OF_DONE.md` for delivery governance that does not conflict with
    higher sources.
12. Accepted ADRs under `docs/adr/`.
13. Documents under `docs/planning/`, which are supporting design material.
14. `README.md` and other descriptive material.

No lower-precedence document may silently broaden MVP scope or alter an
invariant established above it. If two documents at the same precedence level
conflict, stop and update the documents before implementation.

## Canonical MVP decisions

- The MVP is a single local Python process using PySide6 and QML. Application
  services run in process; no HTTP API, FastAPI server, or separate context
  service is part of the MVP.
- SQLite is the only MVP database. Ollama is the only runtime provider and is
  used through an inward-facing model-gateway interface.
- The MVP has one configured text-generation model. It does not route models,
  use cloud providers, stream output to the UI, call tools, or execute actions.
- Context interpretation, reference resolution, constraint processing,
  retrieval scoring, validation, and confidence decisions are deterministic
  rule-based MVP behavior.
- Memory records change only through an explicit user operation. The MVP does
  not automatically create, rewrite, merge, expire-delete, summarize, or
  extract memories in the background.
- Semantic/vector retrieval, embeddings, file indexing, background workers,
  cloud synchronization, and cross-application context are post-MVP work.

## Contract-change rule

Any change to an MVP behavior must update, in the same documentation change,
the applicable requirement, architecture/contract, acceptance test, plan, and
task specification. A planned feature is not implementable until those sources
agree.

## Historical planning material

Planning documents may preserve earlier examples and future design ideas. They
are not implementation instructions unless they agree with the sources above.
Arch Dock, Canva, Blender, and similar examples are historical fixtures only;
they do not define this product's default project, state, provider, or output
behavior.

## Implementation readiness

Documentation is implementation-ready only when the root control documents,
contracts, acceptance tests, implementation plan, and active task agree. A
missing rule that would change data, safety, user-visible behavior, or an
architectural boundary remains a blocker.
