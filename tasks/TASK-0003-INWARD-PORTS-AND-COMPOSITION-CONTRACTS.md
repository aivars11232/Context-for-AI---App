# TASK-0003 — Inward Ports and Composition Contracts

Status: Blocked by TASK-0002

## Goal

Define the inward interfaces that preserve the modular-monolith dependency
direction before any infrastructure adapter is implemented.

## Sources

- `ARCHITECTURE.md`
- `COMPONENT_CONTRACTS.md`
- `docs/contracts/Persistence.md`
- `docs/contracts/ModelGateway.md`
- `docs/contracts/ProcessUserMessage.md`

## Required work

1. Define typed repository ports for every repository named in the persistence
   contract. This explicitly includes the one-record clarification operations on
   `ClarificationRepository` and retrieval-result/retrieval-exclusion operations
   on `ContextPacketRepository`; their implementations remain later-task work.
2. Define model-gateway, clock, ID-generation, configuration, logging, and
   transaction-boundary ports.
3. Define use-case input/output types for processing, context inspection,
   project selection, manual memory CRUD, validation inspection, and evaluation.
4. Define composition-root contracts that are the only allowed location to wire
   concrete adapters.
5. Add contract tests or import-boundary tests for port signatures and forbidden
   outward imports.

## Boundaries

- Do not implement SQLite, Ollama, QML, or a composition root yet.
- Do not create an API, HTTP transport, background worker, router, or fallback.
- Do not move domain/context rules into ports or application orchestration.

## Verification

- Run focused port/contract tests and import-boundary checks.
- Verify all required repository names occur once in the port layer.
- Run all current tests and syntax/import validation.

## Exit criteria

- Application/context components can depend only on inward typed ports.
- Infrastructure implementation can begin without inventing an interface.
- All verification is green.
