# Context for AI — Executable Acceptance Criteria

## Test harness rules

- Every deterministic acceptance case uses fixed UUIDs, an injected UTC clock,
  an isolated temporary SQLite database, fixture YAML, and `MockModelProvider`.
- A case asserts observable data, UI state, or returned result; it does not only
  assert that a mock method was called.
- Fixture files are versioned, synthetic, and free of prior private
  conversations. The fixture version is persisted in evaluation results.
- Live Ollama is excluded from the default test command and has one explicit
  opt-in criterion, AT-016.
- The implementation must map each ID below to a named pytest test or evaluation
  fixture. A test may cover multiple IDs only when its assertions identify each
  ID independently.

## Deterministic MVP acceptance tests

### AT-001 Application startup and configuration

**Fixture:** a complete valid six-file YAML configuration, including intent,
qualifier, output-shape, preserve-verb, and action-marker rules, and an isolated
data directory. **Action:** bootstrap the application using the QML offscreen
test platform. **Pass:** configuration validates, the migration bootstrap ledger
initializes an empty database (canonical schema migrations are accepted in
AT-002/Task 0004), the QML root window is created, and no unhandled
import/configuration error occurs. Repeat with one invalid key/range/rule-table
violation per fixture; each run must fail before QML creation with a typed
`ConfigurationError` naming the file/key.

### AT-002 Exact user-message persistence

**Fixture:** a conversation and text containing whitespace, Unicode, and a
newline. **Action:** submit it with an idempotency key, then reload it. **Pass:**
the stored `messages.original_text` is byte-for-byte equal to the input and the
`processing_runs` row exists before a mock provider is invoked.

### AT-003 State tracking and transition

**Fixture:** no project/conversation, then one created active project, one
created conversation, topic, task, and state version. **Action:** select the
project, submit a high-confidence continuation and then an explicit new task,
complete the task, and archive the project after the terminal run. **Pass:** the
first retains the task; the second moves the old task to `previous_task_id`,
updates state once, increments version, and packet state equals persisted state;
the named task-status transitions are legal; archive preserves its conversations
and makes the project unavailable for new selection.

### AT-004 Qualifier and constraint handling

**Fixture:** `Remove only the blue line and do not change anything else.`
**Action:** interpret and extract constraints. **Pass:** it creates a current
`REQUIRED` normalized target `remove blue line`, a current `PRESERVE` rule for
unspecified content, and a `FORBIDDEN` rule for additional changes, all at
priority `1000` with source evidence. No unrelated constraint is inferred.

### AT-005 Output-type protection

**Fixture:** prior design context and `Do not generate anything; give me a
description.` **Action:** interpret and build a packet. **Pass:** expected
output is `TEXT_DESCRIPTION`, response policy is text-only/no-actions, and the
packet contains a forbidden image/action rule. This test verifies policy only;
the MVP does not invoke an image generator.

### AT-006 Reference resolution

**Fixture:** an entity-registry row for project `Context for AI`, an active
project, a source message ID that introduced it, and one explicit named-item
declaration. **Action:** submit `correct the app structure` and register the
named item through the canonical declaration/UI operation. **Pass:** `the app`
becomes one
`reference_resolutions` row with `RESOLVED`, the entity ID, source message ID,
confidence `>= 0.80`, immutable mention ordinal, and ranked candidate evidence;
the named item has an owning `named_items` row and no model-inferred registry
entry exists.

### AT-007 Ambiguous reference clarification

**Fixture:** two equally ranked named entities matching `the app`. **Action:**
resolve the mention. **Pass:** outcome is `AMBIGUOUS`, no model request exists,
the run becomes `NEEDS_CLARIFICATION`, exactly one `clarification_requests` row
uses the canonical template/evidence, and the UI result contains that one safe
clarification question.

### AT-008 Deterministic context retrieval

**Fixture:** active-project, different-project, conversation, global,
expired, deleted, and duplicate memories with known dates/importance/keywords.
**Action:** retrieve for a Context for AI message using the fixed clock.
**Pass:** only eligible non-expired/non-deleted memories above threshold are
selected; cross-project records are excluded; exact duplicates collapse only in
the retrieval result; ranks, scores, and reasons exactly follow the canonical
formula and tie-break order.

### AT-009 Context-packet completeness and truncation

**Fixture:** a message, state, references, hard/optional/conditional constraints,
memories, and a small configured token budget. **Action:** build a packet.
**Pass:** it has schema version `mvp-context-packet-v1`, all required top-level
fields/types, exact original text, all active hard/true-conditional constraints,
conflict/override evidence, immutable reference/constraint order, deterministic
omission records, and no omitted mandatory content. A budget smaller than
mandatory content produces `CONTEXT_BUDGET_EXCEEDED` before any model request or
packet row.

### AT-010 Model abstraction and buffering

**Fixture:** `MockModelProvider` yielding one complete result and a static
import-boundary check. **Action:** run a packet through the gateway. **Pass:**
application/domain modules do not import the Ollama implementation; only the
composition root wires it; the UI receives no partial output; the persisted
request/response contains trace IDs and completion status.

### AT-011 Response validation

**Fixture:** a packet with one required phrase, one forbidden phrase, one
preservation predicate, active topic, and text output type. **Action:** validate
separate passing and failing candidates. **Pass:** each failed candidate has the
expected typed violation, deterministic evidence, and score; each configured
output shape, action marker, preserve verb, and true conditional predicate
follows its documented grammar; preferred, optional, assumed, and repetition
rules are warnings only; no model call occurs during validation.

### AT-012 Bounded correction and controlled exhaustion

**Fixture:** mock responses that fail a hard validation rule, parameterized with
`validation.max_revisions` values `0`, `1`, and `2`. **Action:** run the full
correction flow. **Pass:** it makes exactly one, two, or three model requests
respectively with consecutive attempts beginning at `0`; it creates exactly the
matching number of correction rows; all candidates and reports persist; exhausted
runs are `CONTROLLED_FAILURE`; no assistant message links an invalid response;
UI gets a safe failure rather than candidate text.

### AT-013 Context inspection UI

**Fixture:** one processed mock-provider message containing state, intent,
references, constraints, retrieval, confidence, and validation data. **Action:**
open the context-inspection page. **Pass:** it visibly presents every FR-015
field, including reference status/evidence, retrieval scores/reasons, confidence,
validation status, and any controlled failure or clarification. The QML UI stays
responsive while a pending foreground request is cancelled; the worker-owned
SQLite connection is not accessed from the GUI thread, and its queued terminal
signal is the only UI state mutation path.

### AT-014 Manual memory lifecycle

**Fixture:** a manual memory create, edit, duplicate candidate, expiry timestamp,
and delete request. **Action:** perform explicit UI/use-case operations. **Pass:**
each mutation creates a source and immutable revision; duplicate records are not
automatically merged; expiry computes `EXPIRED` for retrieval while stored status
remains `ACTIVE`; delete writes a `DELETED` tombstone; provenance/history remain
inspectable; matching redacted `memory_*` trace events carry memory/revision IDs
and no raw content.

### AT-015 Complete mock-provider pipeline, idempotency, and recovery

**Fixture:** valid configuration, an isolated database, fixed clock, and a
passing mock response. **Action:** submit once, repeat the same idempotency key,
attempt a concurrent second key, and simulate restart at each non-terminal run
state. **Pass:** the first submission persists every required stage and one
linked assistant message; duplicate submission returns the same run (including
an in-progress status); a fresh concurrent submission gets a pre-acceptance
typed busy result; restart recovery exercises every matrix row, including
pending, in-flight, persisted validated candidate, correction preparation, and
changed configuration fingerprint, without duplicating an uncertain model call.
Its applicable trace events carry correlation IDs and contain no raw request,
packet, response, memory, or secret content; the combined assertions in
AT-007, AT-012, AT-014, and AT-015 cover every required trace event name.

### AT-016 Local Ollama smoke acceptance

This is the only live-model acceptance criterion. It is marked `ollama` and is
skipped only when `CONTEXT_FOR_AI_RUN_OLLAMA=1` is absent. When that flag is
present, every preflight condition below is executed and a missing/invalid
condition fails the opt-in test:

1. The fixture configuration uses loopback Ollama, `temperature: 0.0`, timeout
   `60`, and a named installed model supplied through
   `CONTEXT_FOR_AI__MODEL__NAME`.
2. The test records `ollama show <model>` output or equivalent model metadata,
   configuration fingerprint, Ollama version, OS, and elapsed time as an
   artifact without recording message/prompt/response content in logs.
3. The deterministic fixture asks for the exact text token
   `CONTEXT_FOR_AI_SMOKE_OK`; packet constraints require that token.

**Action:** run the complete one-process pipeline against local Ollama.
**Pass:** health check succeeds, one buffered response arrives within timeout,
validation passes the token constraint, every lifecycle/trace record persists,
and the QML UI displays the linked accepted assistant text. A missing daemon,
model, timeout, or token mismatch is a failed opt-in acceptance result—not a
silently skipped pass.

## Requirement traceability

| Requirement area | Acceptance IDs |
|---|---|
| Configuration, startup, local runtime | AT-001, AT-016 |
| Exact persistence, state, entity/reference | AT-002–AT-007, AT-015 |
| Constraints, retrieval, packet | AT-004–AT-009 |
| Gateway, validation, correction | AT-010–AT-012, AT-016 |
| UI and manual memory safety | AT-013–AT-014 |
| Transaction, idempotency, recovery, traceability | AT-002, AT-012, AT-015–AT-016 |
