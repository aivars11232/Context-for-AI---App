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
   outside a database transaction. Buffer a complete result.
6. Persist and validate every received candidate. A valid candidate is linked to
   one assistant message and ends the run successfully.
7. On validation failure, create at most two correction attempts. Revisions use
   the original immutable packet plus a violation envelope.
8. On exhaustion, provider failure, cancellation, context-budget failure, or
   persistence failure, follow the terminal/best-effort persistence contract.
   Never expose an invalid candidate as final output.

## Dependencies

Repository ports, deterministic context components, model-gateway port,
response validator, correction controller, clock/ID ports, and transaction
boundary.

## Never does

Direct SQL, provider-specific HTTP, UI work, model routing, hidden requirement
inference, automatic memory mutation, or an unbounded/automatic retry.

## Error contract

The use case maps infrastructure failures to typed application outcomes:
`ConfigurationError`, `PersistenceError`, `ConcurrencyConflictError`, `BusyError`,
`ContextConstructionError`, `ClarificationRequired`, `ProviderUnavailableError`,
`ModelNotFoundError`, `ModelTimeoutError`, `ModelCancelledError`,
`InvalidProviderResponseError`, `ContextBudgetExceededError`, and
`ValidationExhaustedError`. Terminal failures write `pipeline_failures` with a
safe user message and trace IDs when persistence is available; clarification and
pre-acceptance busy are not failures.
