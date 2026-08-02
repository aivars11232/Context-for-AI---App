# Context Engine Contracts

All MVP context components are deterministic and rule-based. Their canonical
enums, scoring, ambiguity, state, constraint, and retrieval rules are defined
in `DomainAndDecisionRules.md`; packet shape is defined in `ContextPacket.md`.
No MVP component is model-backed.

## InterpretationEngine

Input: immutable user message and state snapshot. Output: one `IntentType`,
expected `OutputType`, qualifiers with matched evidence, proposed topic/task,
confidence, and `NEEDS_CLARIFICATION` when rules require it.

## ReferenceResolver

Input: message, ordered recent messages, state, and entity registry. Output:
one persisted `ReferenceStatus` result per mention, candidate evidence, source
message, entity ID when resolved, and confidence.

## ConstraintEngine

Input: message, interpretation, state, resolved references, and eligible
stored rules. Output: normalized typed constraints, priority outcomes, and
explicit conflict groups. A hard conflict returns clarification before a model
call.

## ContextRetriever

Input: message, state, project, topic, eligible memories, injected clock, and
retrieval limits. Output: ordered selected memories with score/rank/reasons and
recorded exclusions. It does not create, merge, or mutate memory.

## ContextPacketBuilder

Input: exact message, interpretation, state, references, constraints, retrieved
memories, confidence, response policy, and token configuration. Output: one
immutable `mvp-context-packet-v1` or a context-budget failure before generation.
