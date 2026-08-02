# Context Packet Contract

## Status

This document defines the immutable `context_packet` schema version
`mvp-context-packet-v1`. It is a data contract, not an unstructured transcript.
Packets are stored unchanged in `context_packets.packet_json`.

## Required top-level shape

```text
{
  schema_version: "mvp-context-packet-v1",
  trace: { processing_run_id, conversation_id, user_message_id, state_version, configuration_fingerprint },
  request: { original_text, intent, intent_rule_id, expected_output_type, qualifiers, confidence },
  active_state: { project_id, topic_id, task_id, previous_task_id, topic_stack },
  references: [ { mention_ordinal, surface_text, status, entity_id, source_message_id, confidence, evidence } ],
  constraints: [ { ordinal, id, type, underlying_type, scope, normalized_rule, priority, source_kind, source_evidence, confidence, status, conflict_group_id, condition } ],
  retrieval: [ { memory_id, content, score, rank, reasons, scope, confidence } ],
  confidence: { interpretation, references, retrieval, overall },
  response_policy: { output_type, validate_before_display, text_only, no_actions, correction_limit },
  rendering: { prompt_policy_version, token_estimator, token_budget, included_sections, omitted_sections }
}
```

All IDs are UUID strings; `active_state` IDs and a non-resolved reference's
`entity_id`/`source_message_id` may be null only where the state/reference
contract permits it. `original_text` is the exact stored Unicode string.
`confidence` values are numeric `[0,1]` or null only for a non-applicable
reference/retrieval aggregate. Every qualifier has `{kind, rule_id,
matched_text}`. Every constraint has the canonical enum values plus source
message/memory/state identifiers in `source_evidence`; `underlying_type` and
`condition` are null unless `type` is `CONDITIONAL`. A conditional object is the
persisted `{grammar_version, kind, expected_value, evaluation}` shape.

Every persisted packet contains the exact original request, its response policy,
all active hard constraints (including true conditionals with an underlying hard
predicate), and all `OVERRIDDEN`/`CONFLICTING` constraint evidence. A false
conditional may be omitted only after its evidence is recorded. Collections have
deterministic order: constraints by priority descending then immutable `ordinal`
ascending; references by immutable `mention_ordinal` ascending; retrieval by
rank ascending. A run has one immutable packet only when the builder succeeds.
`CONTEXT_READY`, `GENERATING`, `REVISING`, and every generation-derived terminal
run have exactly one packet. A pre-packet clarification or context-budget failure
has zero packets; a clarification after successful construction retains one.

## Response policy

`response_policy` is always:

```text
{
  output_type: <canonical OutputType>,
  validate_before_display: true,
  text_only: true,
  no_actions: true,
  streaming: false,
  correction_limit: <validated validation.max_revisions>,
  model_generation_limit: 1 + correction_limit,
  absolute_model_generation_cap: 3
}
```

The policy does not permit a provider, retrieved memory, or user text to change
the model-call limit or execute an action.

## Token estimation and budget

- The MVP uses `conservative_utf8_v1`: estimated tokens equal
  `ceil(utf8_byte_length / 3)`, with a minimum of one token for non-empty text.
  This estimator ID is persisted in the packet and is deterministic without a
  model call.
- `effective_prompt_budget` is the smaller of
  `context.maximum_prompt_tokens` and
  `model.context_window_tokens - context.reserved_response_tokens`.
- The renderer first reserves protocol text, exact original request, active
  state, all active `REQUIRED`, `FORBIDDEN`, and `PRESERVE` constraints, true
  conditional hard predicates, and conflict/override evidence. It never
  truncates those sections.
- If the minimum mandatory content exceeds the effective budget, the run ends
  before generation with `CONTEXT_BUDGET_EXCEEDED` and a controlled failure.
- Otherwise include, in order: resolved references, inactive conditional rules,
  high-priority preferences, retrieval results by rank, optional rules, and
  assumed rules. Drop from the end of that order until within budget. Each
  `rendering.omitted_sections` item is
  `{section, reason, item_ids, estimated_tokens}` where `section` is one of
  `REFERENCES`, `CONSTRAINTS`, or `RETRIEVAL`, `reason` is `TOKEN_BUDGET` or
  `INACTIVE_CONDITION`, `item_ids` are deterministic source IDs, and
  `estimated_tokens` is a non-negative integer. `included_sections` uses the
  same section enum and is in render order.

## Rendering and injection boundary

The renderer emits fixed protocol sections in this order: response policy,
exact user request, active state, references, constraints, retrieved memory,
and correction envelope when applicable. Original text, references, and memory
content are delimited as untrusted data. Only response-policy and constraint
sections are instructions. Retrieved text that resembles an instruction is
quoted data and cannot override the fixed policy.

## Revision envelope

A correction call preserves the original packet. Its separate envelope contains
the failed candidate identifier, typed validation violations, and the fixed
instruction to satisfy the unchanged response policy. It cannot weaken,
remove, or reinterpret a packet constraint.
