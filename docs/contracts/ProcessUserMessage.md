# ProcessUserMessage Contract

## Responsibility

Coordinate one idempotent user-message pipeline and return exactly one of:
accepted assistant text, a clarification result, a typed controlled failure, an
existing in-progress result, or a pre-acceptance busy result.

## Input

- `conversation_id`
- exact user text
- `idempotency_key` UUID supplied by the UI
- optional explicit `project_id` selection

## Output

- `result_kind`: `FINAL`, `EXISTING_RUN`, or `BUSY`
- for `FINAL`/`EXISTING_RUN`, `processing_run_id`, persisted `user_message_id`,
  and any canonical `ProcessingRunStatus`; `EXISTING_RUN` may be `PERSISTED`,
  `CONTEXT_READY`, `GENERATING`, or `REVISING`
- for `BUSY`, `active_processing_run_id`, its non-terminal status, and typed
  `BusyError`; it has no new `user_message_id`
- optional final assistant message ID and text only when `SUCCEEDED`
- context packet ID when construction succeeded
- final validation result when a candidate response exists
- current state snapshot and either safe failure details or the one persisted
  clarification request ID/question

## Required sequence

1. Deduplicate the input by `(conversation_id, idempotency_key)`; an existing
   key returns `EXISTING_RUN` unchanged. For a new key, reject a global active
   run as `BUSY` before acceptance and before message persistence.
2. In the acceptance transaction for an accepted submission, persist exact text
   before any derived work, create a `PERSISTED` run, and apply a user-selected
   project change.
3. Run deterministic interpretation, reference, constraint, state, retrieval,
   and packet construction. Persist results in the context transaction.
4. Return `NEEDS_CLARIFICATION` before generation for material ambiguity,
   unsupported intent, an unsupported condition, material assumption, or a
   hard-constraint conflict. Persist exactly one deterministic clarification
   request and no `pipeline_failures` row for this outcome.
5. Start one provider request in a short transaction, then call the gateway
   outside a database transaction. Receive exactly one typed
   `GenerationOutcome`; expected transport failures are returned values, not
   exceptions.
6. Persist and validate every received candidate using only the immutable
   packet's validation snapshot. A valid candidate is linked to one assistant
   message and ends the run successfully.
7. On validation failure, pass the unchanged packet, failed-candidate lineage,
   and exact failed report to the pure correction controller. The packet's
   `response_policy.correction_limit` is the sole revision-limit authority.
   Each returned envelope names the immediately failed response, carries only
   typed violations, and produces the next consecutive attempt. No caller
   supplies a second maximum or mutates the packet.
8. When the controller returns `CorrectionExhausted`, persist the exact
   `VALIDATION/VALIDATION_EXHAUSTED` safe failure and terminal
   `CONTROLLED_FAILURE` transition defined in `ResponseValidation.md` and
   `Persistence.md`. On provider failure, cancellation, context-budget failure,
   or persistence failure, follow the corresponding terminal/best-effort
   persistence contract. Never expose an invalid candidate as final output.

## Dependencies

Repository ports, deterministic context components, model-gateway port,
response validator, correction controller, clock/ID ports, and transaction
boundary.

## TASK-0013/TASK-0014 ownership boundary

TASK-0013 defines and verifies the pure validator, typed validation reports,
score/warning behavior, pure correction-envelope/controller decisions, and the
bounded repository projections for validation, correction attempts, and
exhaustion. Its fixtures may supply already-persisted lineage objects and do not
execute this complete sequence.

TASK-0014 owns this use case's complete lifecycle: provider invocation,
candidate/request/terminal transaction coordination, repeated validation and
correction decisions, final assistant linkage, safe UI result, recovery entry,
and complete AT-012 execution. This split does not move repository or
transaction ownership into the validator or controller.

## Never does

Direct SQL, provider-specific HTTP, UI work, model routing, hidden requirement
inference, automatic memory mutation, or an unbounded/automatic retry.

## Error and gateway-outcome contract

The use case maps non-gateway failures to typed application outcomes:
`ConfigurationError`, `PersistenceError`, `ConcurrencyConflictError`,
`BusyError`, `ContextConstructionError`, `ClarificationRequired`,
`ContextBudgetExceededError`, and `ValidationExhaustedError`.

`ValidationExhaustedError` is an application return only after the exact
`SafeFailure` has been durably projected when persistence is available. It is
not stored in `pipeline_failures`, and it never contains candidate text.

Expected gateway conditions do not join that exception list. The gateway
returns `CompletedGeneration` or one of
`ProviderUnavailableFailure`, `ModelNotFoundFailure`,
`ModelTimeoutFailure`, `ModelCancelledFailure`, and
`InvalidProviderResponseFailure`. The application maps each returned failure
exactly according to the status/code/message/persistence table in
`docs/contracts/ModelGateway.md`; it does not inspect provider exceptions or
invent a message. Terminal failures write `pipeline_failures` with the safe
message and request correlation fields when persistence is available.
Clarification and pre-acceptance busy are not failures.
