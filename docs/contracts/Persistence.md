# Persistence Contracts

## Boundary

`DATABASE_SCHEMA.md` is the canonical logical schema. Repositories expose
domain objects and typed operations; domain, context-intelligence, and
application code must not depend on SQLite rows or SQL strings.

## Required repositories

- `ProjectRepository`
- `ConversationRepository`
- `TopicRepository`
- `TaskRepository`
- `ConversationStateRepository`
- `MessageRepository`
- `EntityRepository`
- `ReferenceResolutionRepository`
- `ConstraintRepository`
- `MemoryRepository` (including sources and revisions)
- `ProcessingRunRepository`
- `ContextPacketRepository` (including retrieval results and retrieval exclusions)
- `ModelCallRepository` (requests, responses, corrections, failures)
- `ValidationRepository`
- `ClarificationRepository`
- `SettingsRepository`
- `EvaluationRepository`

## Transaction boundaries

No SQLite transaction is held during an Ollama call. `ProcessUserMessage` uses
these short transactions:

1. **Acceptance transaction:** first look up `(conversation_id,
   idempotency_key)`. An existing key returns its stored run without mutation.
   A new key checks the global non-terminal-run index; if occupied, it returns
   `BusyError` before persisting a message or run. Otherwise persist the
   immutable user message, create a `PERSISTED` run, apply an explicit project
   change, and commit. The partial unique index is the race-safe final guard.
2. **Context transaction:** persist deterministic interpretation, reference,
   constraint, state, and retrieval decisions. If clarification is required,
   persist exactly one deterministic `clarification_requests` row and terminal
   `NEEDS_CLARIFICATION` status in this transaction; a packet is optional only
   when the builder already succeeded. If the mandatory packet budget fails,
   persist `CONTEXT_BUDGET_EXCEEDED` and terminal `CONTROLLED_FAILURE`. Otherwise
   persist the immutable packet and move the run to `CONTEXT_READY`; commit.
3. **Request preparation and claim transactions:** create a `PENDING` request
   (and, for a revision, its correction row) while moving the run to
   `GENERATING` or `REVISING`; commit. In a second short transaction claim that
   request by changing it to `IN_FLIGHT`; commit before the provider call.
4. **Candidate transaction:** persist the provider result and `SUCCEEDED`
   request status, then deterministically validate the complete candidate and
   persist its validation report in the same transaction. A transport outcome
   instead persists the terminal request status, a failure record, and terminal
   run status in one transaction.
5. **Terminal transaction:** on a pass, create the linked assistant message and
   mark the run `SUCCEEDED`; deterministic state was already committed with the
   packet, so this transaction does not perform a second state update. On
   exhausted validation, cancel,
   or a recovery-determined failure, persist `pipeline_failures` and a terminal
   run status. Memory records are not automatically changed by this pipeline.

## Idempotency, recovery, and concurrency

- The UI supplies one UUID `idempotency_key` per submit. Repeating that key for
  the same conversation returns the existing run (including a non-terminal
  status) and never creates another user message or model request.
- The application has at most one global non-terminal foreground run. A new key
  while it exists is rejected before acceptance with `BusyError` containing the
  active run ID/status and no new user-message ID; it is not queued in a
  background worker.
- State writes compare the expected `conversation_states.version`; a conflict
  reloads state and reruns only deterministic context construction once. A
  second conflict becomes a typed `ConcurrencyConflictError`.
- Restart recovery finds the one possible non-terminal run and first compares
  its stored configuration fingerprint with the current normalized fingerprint.
  A mismatch becomes terminal `FAILED` with `CONFIGURATION_CHANGED`; recovery
  never rebuilds a packet or calls a model under changed rules. With a matching
  fingerprint it follows this complete matrix:

  | Durable state | Recovery action |
  |---|---|
  | `PERSISTED` with no packet/request | Re-run deterministic context construction once. |
  | `CONTEXT_READY` with no request | Create/claim the initial `PENDING` request and continue. |
  | `GENERATING` or `REVISING` with `PENDING` request | Claim and make that not-yet-sent request. |
  | `GENERATING` or `REVISING` with `IN_FLIGHT` request | Terminalize `FAILED/PROCESS_RESTARTED`; delivery cannot be proved. |
  | Non-terminal run with `SUCCEEDED` request, response, and passing validation but no assistant link | Repeat the idempotent terminal transaction only. |
  | Non-terminal run with failed validation and revisions remaining but no next request | Create exactly one next correction request/row, then claim it. |
  | Non-terminal run with failed validation at the configured limit | Terminalize `CONTROLLED_FAILURE/VALIDATION_EXHAUSTED`. |
  | Non-terminal run with terminal failed/timed-out/cancelled request | Terminalize the matching safe failure without another provider call. |

  Any impossible combination (for example two requests for one attempt or a
  response without its request) is terminalized as `FAILED/PERSISTENCE_ERROR`
  and retained for diagnosis. The system never automatically repeats an
  uncertain model call.
- Repository operations return typed persistence/concurrency errors. If a
  mandatory write rolls back, the application returns `PersistenceError` without
  showing candidate text, then makes one best-effort fresh transaction to record
  `FAILED/PERSISTENCE_ERROR`. If that transaction also fails, no claim of a
  persisted failure is made; recovery retries terminalization on the next
  startup. This is the only safe behavior when the database is unavailable.

## Lifecycle invariants

- One run has one user message and zero or one immutable packet. A successful
  packet is required before any model request; `CONTEXT_READY` and later
  generation states have exactly one packet.
- Attempt `0` is the initial generation; attempts `1` and `2` are the only
  possible revisions. A unique database constraint enforces this.
- A successful response has exactly one validation result and one linked
  assistant message. Failed candidates have a validation result when text was
  received and no assistant message.
- A controlled failure has no final assistant candidate. The UI renders its
  safe system status rather than model text.
- Manual memory operations write source and revision rows in the same
  transaction. Soft deletion preserves all provenance and revisions.
