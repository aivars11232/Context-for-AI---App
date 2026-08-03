# TASK-0006 — Versioned Conversation State

Status: In progress; TASK-0005 complete and D-014 TASK-0006 scope reconciled

## Goal

Implement deterministic, versioned conversation-state transitions with one
source of truth for the active project.

## Sources

- `docs/contracts/DomainAndDecisionRules.md`
- `DATABASE_SCHEMA.md`
- `REQUIREMENTS.md` FR-003 and NFR-008

## Required work

1. Implement state snapshots and transitions for project selection, topic stack,
   active task, previous task, task status, and expected output type.
2. Enforce that `conversations.project_id` is the sole persisted active project.
3. Implement high-confidence topic/task transitions, `CONTINUE`/`CORRECT`
   semantics, ten-item stack behavior, and compare-and-swap versioning.
4. Add deterministic unit and temporary-SQLite integration tests, including
   project switches, topic-stack overflow, version conflict, and concurrent-run
   busy behavior.

## Boundaries

- Do not parse natural language beyond passing prepared interpretation results.
- Do not resolve references, retrieve memory, call a model, or build packets.
- Do not introduce a second active-project field or autonomous task completion.

## D-014 TASK-0006 reconciliation

This section is the authoritative reconciliation for the TASK-0006 portion of
D-014. It is subordinate to the canonical sources above and does not resolve
any TASK-0007 or later portion of D-014.

### Public application seam and prepared inputs

TASK-0006 exposes four presentation-facing use cases:

1. The existing `SelectProject.execute(SelectProjectInput)` contract selects,
   switches, or clears the project association for an existing conversation.
2. `ApplyConversationStateTransition.execute(...)` accepts optional typed
   `PreparedTopicTransition`, `PreparedTaskTransition`, and
   `PreparedOutputTransition` values. Each prepared value contains canonical
   IDs/enums and a `UnitScore`; it contains no source text and performs no
   parsing or interpretation.
3. `TransitionTaskStatus.execute(...)` performs one named explicit task-status
   operation.
4. `ArchiveProject.execute(...)` performs the explicit project archive
   operation needed by the state assertions of AT-003.

All state-mutating inputs carry `conversation_id` and
`expected_state_version`. Public outputs return the resulting immutable
`ConversationState` and the directly changed `Conversation`,
`ConversationTask`, or `Project` where applicable. These four use cases are the
public TASK-0006 seam for its AT-003 state assertions. Creation of projects,
conversations, topics, and tasks is fixture/setup behavior for TASK-0006, not a
new use case owned by this task. Context-packet equality remains owned by the
later packet/pipeline work and is not implemented here.

### Deterministic transition ownership

- A new conversation state is created deterministically at version `0`, with
  null topic/task/output fields and an empty topic stack. TASK-0006 provides the
  dependency-free constructor, but does not add a conversation-creation use
  case.
- Only a prepared proposal with canonical `HIGH` confidence (`>= 0.80`) may
  change topic, task, or expected output. Lower-confidence proposals retain the
  corresponding prior state.
- A high-confidence topic moves its existing ID to the top (the final tuple
  position), or appends it when absent. The oldest item (the first tuple
  position) is removed when the result would exceed ten IDs.
- A high-confidence task selects an existing non-terminal task owned by the
  conversation. An `OPEN` selected task becomes `IN_PROGRESS`; the replaced
  active task remains non-terminal and becomes `previous_task_id`. Re-selecting
  the active task is a no-op.
- A prepared non-control intent sets its supplied canonical text output type.
  `UNSUPPORTED`, clarification, and controlled-failure results do not update
  expected output state.
- `CONTINUE` accepts no topic/task proposal, retains active and previous task,
  and preserves a non-null expected output type; a null expected output becomes
  `TEXT_ANSWER`.
- `CORRECT` has the same TASK-0006 state effect as `CONTINUE`. It does not
  persist a correction constraint; that behavior remains assigned to later
  constraint processing.
- Completing or cancelling the active task atomically moves it to
  `previous_task_id`, clears `active_task_id`, increments state once, and then
  applies the terminal task status in the same transaction. Reopening sets the
  status to `OPEN` without activating it. Selecting a task is the only
  TASK-0006 operation that performs `OPEN -> IN_PROGRESS`.
- A project selection changes only `conversations.project_id` and touches the
  versioned state once. Topic, task, previous-task, output, and stack fields are
  conversation-scoped and are preserved across a project switch. Re-selecting
  the same project is a no-op. Only an existing `ACTIVE` project may be selected.
- Project archival belongs to TASK-0006 only for the explicit AT-003 lifecycle
  operation. It preserves associated conversations and state and is rejected
  while that project has a non-terminal run. Project creation is not owned by
  TASK-0006.

Every semantic state change increments `version` by exactly one. A repeated
input whose complete semantic effect is already present returns the current
snapshot without a write or version increment. Multi-field prepared input is
one atomic transition and one increment. State writes use compare-and-swap; a
first stale/read-race conflict rolls back any collaborator writes, reloads the
latest snapshot, and replays the deterministic transition once. A second
conflict raises `ConcurrencyConflictError` and leaves no partial mutation.

TASK-0006 does not own message admission or application-level `BusyError`
mapping because that requires later orchestration. It preserves and tests the
existing `ProcessingRunRepository.get_non_terminal()` behavior and SQLite
single-global-non-terminal-run constraint; a competing repository write remains
a typed `PersistenceError` at this boundary.

`conversations.project_id` remains the sole persisted active-project source of
truth. `conversation_states` must not gain an active-project field, and no
application snapshot may persist a duplicate value.

### Authoritative file ownership

- Pure state construction and transition rules:
  `src/context_for_ai/domain/state_transitions.py`
- Typed application inputs, outputs, and protocols:
  `src/context_for_ai/application/contracts.py`
- Concrete TASK-0006 application use cases:
  `src/context_for_ai/application/conversation_state.py`
- Public exports and composition fields:
  `src/context_for_ai/application/__init__.py` and
  `src/context_for_ai/bootstrap/contracts.py`
- Pure transition tests:
  `tests/unit/domain/test_state_transitions.py`
- Application/CAS unit tests:
  `tests/unit/application/test_conversation_state.py`
- Temporary-SQLite and AT-003 state integration tests:
  `tests/integration/test_conversation_state.py`

The existing repository ports, SQLite repositories, schema, and migrations are
reused unchanged unless a focused TASK-0006 test demonstrates a direct defect.

## Verification

- Run state-transition unit tests and repository integration tests.
- Prove AT-003 state assertions through the public state/use-case seam.
- Run all current tests and syntax/import validation.

## Exit criteria

- State transitions match the canonical rules and are recoverable/versioned.
- No project/state duplicate source of truth exists.
- All verification is green.
