# TASK-0010 — Immutable Context Packet and Prompt Rendering

Status: Blocked by TASK-0009

## Goal

Implement the formal versioned context packet, deterministic budgeting, safe
prompt rendering, and omission evidence.

## Sources

- `docs/contracts/ContextPacket.md`
- `docs/contracts/DomainAndDecisionRules.md`
- `DATABASE_SCHEMA.md`
- `ACCEPTANCE_TESTS.md` AT-009

## Required work

1. Implement `mvp-context-packet-v1` exactly, including trace, request, state,
   references, constraints, retrieval, confidence, response policy, and
   rendering metadata.
2. Implement `conservative_utf8_v1`, effective prompt budget calculation,
   mandatory-content preservation, deterministic truncation, and
   `CONTEXT_BUDGET_EXCEEDED` behavior.
3. Implement fixed section ordering, untrusted-data delimiters, and correction
   envelope rendering that cannot mutate packet constraints.
4. Persist one immutable packet and retrieval ranks/reasons per processing run.
5. Add packet unit/integration/evaluation tests for complete, truncated, and
   impossible-budget cases.

## Boundaries

- Do not call Ollama, validate a candidate, or expose prompt text to UI logs.
- Do not add tokenizer services, streaming, embeddings, compression models, or
  automatic context summaries.

## Verification

- Run packet-builder unit and temporary-SQLite integration tests.
- Demonstrate every AT-009 assertion and injection-boundary fixture.
- Run all current tests and syntax/import validation.

## Exit criteria

- Packets are immutable/versioned and retain required evidence.
- Hard constraints and original text are never silently dropped.
- All verification is green.
