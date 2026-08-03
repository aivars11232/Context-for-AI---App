# Context Engine Contracts

All MVP context components are deterministic and rule-based. Their canonical
enums, scoring, ambiguity, state, constraint, and retrieval rules are defined
in `DomainAndDecisionRules.md`; packet shape is defined in `ContextPacket.md`.
No MVP component is model-backed.

## InterpretationEngine

`InterpretationRequest` contains the processing-run ID, immutable user message,
immutable conversation-state snapshot, and evaluated-at UTC time. The engine is
constructed with validated `ContextSettings`; it never reads YAML directly.

`MatchedRuleEvidence` contains rule ID, exact matched source text, normalized
phrase, original half-open start/end offsets, and rule priority.
`IntentCandidate` combines one intent, its permitted/default output, and matched
evidence. Existing `QualifierMatch` carries the same source evidence plus its
normalized captures. `ReferenceMention` contains only mention ordinal, exact
surface text, normalized phrase, qualifier rule ID, and original offsets.

`InterpretationDecision` contains the existing `RequestInterpretation`, rule-set
version, deterministically ordered intent candidates, optional topic label,
optional task title, ordered unresolved reference mentions, and at most one
clarification reason/details object. A different-intent top tie or no match
returns `UNSUPPORTED`/`CLARIFICATION`. A same-intent tie selects the
lexicographically smaller rule ID. The engine does not mutate state; its
high-confidence labels/output are proposals for the existing TASK-0006 seam.

## ReferenceResolver

Input: message, ordered recent messages, state, and entity registry. Output:
one persisted `ReferenceStatus` result per mention, candidate evidence, source
message, entity ID when resolved, and confidence.

TASK-0007 does not implement this component. A `same as before` qualifier ends
at an ordered `ReferenceMention`; recent-message/entity search, candidate
ranking, `ReferenceStatus`, reuse, and reference-stage clarification remain a
TASK-0008 responsibility.

## ConstraintEngine

`ConstraintEvaluationRequest` contains the immutable message, state,
`InterpretationDecision`, caller-supplied reference outcomes (empty in
TASK-0007), eligible caller-supplied constraints with source evidence, optional
normalized active-project name, and evaluated-at UTC time. The engine may use
injected `Clock` and `IdGenerator` ports; it must not call a repository.

`ConstraintSourceEvidence` contains the constraint ID, normalized target key,
contributing rule IDs and exact source texts, optional source-message sequence,
immutable source UTC time, and the deterministic comparison tuple.
`ConstraintConflictGroup` contains the deterministic group ID, target key, and
ordered opposing constraint IDs. `ResponsePolicy` contains expected output
type, `text_only=True`, `actions_allowed=False`, and the rule-set version.

`ConstraintDecision` contains every normalized `Constraint`, source evidence,
explicit conflict groups, the fixed response policy, and at most one
clarification reason/details object. It retains inactive, overridden, assumed,
and conflicting results. Precedence inside the TASK-0007 boundary is an
interpretation block, unsupported condition, hard conflict, then material
assumption. No provider-facing result is produced when a reason is present.

The engine emits the fixed `MUST_NOT_EXECUTE:IMAGE_OR_ACTION` derived policy for
every accepted text interpretation. It parses only `mvp-condition-v1`, applies
canonical priority/recency rules, and performs only canonical lexical
opposition. It does not persist constraints or clarification data.

## ContextRetriever

Input: message, state, project, topic, eligible memories, injected clock, and
retrieval limits. Output: ordered selected memories with score/rank/reasons and
recorded exclusions. It does not create, merge, or mutate memory.

## ContextPacketBuilder

Input: exact message, interpretation, state, references, constraints, retrieved
memories, confidence, response policy, and token configuration. Output: one
immutable `mvp-context-packet-v1` or a context-budget failure before generation.

TASK-0007 does not construct a `ContextPacket`. AT-004 and its component-owned
part of AT-005 are demonstrated through `InterpretationDecision`,
`ConstraintDecision`, and `ResponsePolicy` only.
