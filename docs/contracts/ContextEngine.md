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
surface text, normalized phrase, source rule ID (the existing field is named
`qualifier_rule_id`), and original offsets. The ordinal emitted here is local to
the immutable TASK-0007 mention sequence.

`InterpretationDecision` contains the existing `RequestInterpretation`, rule-set
version, deterministically ordered intent candidates, optional topic label,
optional task title, ordered unresolved reference mentions, and at most one
clarification reason/details object. A different-intent top tie or no match
returns `UNSUPPORTED`/`CLARIFICATION`. A same-intent tie selects the
lexicographically smaller rule ID. The engine does not mutate state; its
high-confidence labels/output are proposals for the existing TASK-0006 seam.
The interpreter does not inspect registry rows or extract registry-dependent
names and deictic forms. Its `same as before` output is seed evidence for the
TASK-0008 extractor.

## ReferenceMentionExtractor

This TASK-0008 component accepts the immutable user message, TASK-0007 seed
mentions, and the scoped active/inactive entity-registry candidates. It validates
each seed against the message, copies its evidence without mutating it, adds only
the fixed forms and exact complete registry names in
`DomainAndDecisionRules.md`, applies the canonical overlap rules, and returns one
new immutable source-ordered mention sequence with final contiguous ordinals.
`the app` in AT-006 is added here; it is not a qualifier and does not change
TASK-0007 intent or qualifier behavior.

The extractor performs no candidate scoring, status selection, persistence,
state mutation, named-item creation, model call, or semantic inference. An empty
final sequence is valid and creates no reference outcome.

## ReferenceResolver

`ReferenceResolutionRequest` contains the processing-run ID, immutable current
user message, ordered prior recent messages, immutable state, final extracted
mentions, scoped active/inactive registry entities, prior `RESOLVED` outcomes
for those recent messages, and evaluated-at UTC time. Recent messages are in
ascending sequence order; prior outcomes link to them by `message_id`, so the
resolver combines the message's immutable sequence with the outcome's mention
ordinal for tracked-entity recency. The resolver is constructed with an
`IdGenerator`; it never reads a repository or clock directly.

`ReferenceCandidateEvidence` exposes the exact fixed evidence fields and order
defined in `DomainAndDecisionRules.md`. `ReferenceDecision` contains one ordered
`ReferenceOutcome` per final mention, optional reference clarification
reason/details, and `blocks_generation`. The flag is true exactly when the
lowest-ordinal material outcome is `AMBIGUOUS` or `UNRESOLVED`; its clarification
data uses that mention. `NOT_APPLICABLE` is retained but is non-material.

The resolver returns immutable results without side effects. TASK-0008
application code may persist the complete outcome tuple through the existing
`ReferenceResolutionRepository` in one transaction. The reference decision does
not persist a clarification, change a processing-run status, inspect or create a
model request, construct a context packet, or produce a UI result. Those are
later orchestration/presentation responsibilities.

TASK-0007 implements neither TASK-0008 component. A `same as before` qualifier
still ends at its local ordered `ReferenceMention`; final mention merge, recent
message/prior-outcome search, candidate ranking, `ReferenceStatus`, reuse, and
reference-stage clarification are TASK-0008 responsibilities.

Entity registration is separate application behavior. It creates an owner and
registry row atomically through inward repository/transaction contracts; neither
the extractor nor resolver writes registry state.

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

## MemoryManager

TASK-0009 owns application use cases for explicit create, edit, get, stored-
status list, and soft-delete operations. The manager receives only inward
`MemoryRepository`, `TransactionBoundary`, `Clock`, and `IdGenerator` ports.
Create, edit, and delete each use one clock reading and atomically write one
source plus one consecutive `memory-revision-v1` revision. Get/list return the
complete memory, ordered sources, ordered revisions, evaluated-at time, and the
computed `MemoryEffectiveStatus` defined in `DomainAndDecisionRules.md`.

The manager rejects edit, repeated delete, and restore attempts for a deleted
memory. It performs no automatic creation, extraction, merge, rewrite, cleanup,
expiry mutation, or background operation. Presentation invokes these use cases
later; UI rendering, pipeline orchestration, and trace-event emission are not
TASK-0009 `MemoryManager` behavior.

TASK-0017 consumes that complete application output only through the closed
projection in `ManualOperationsUI.md`. Its adapter reads one `evaluated_at` for
the entire stored-status query, preserves the repository's memory/source/
revision ordering, computes `MemoryEffectiveStatus`, resolves safe owner/source
labels, and strips internal IDs before QML. Edit/soft-delete adapters compare the
selected greatest revision inside their outer transaction, then invoke the same
canonical manager operation; they do not add a restore path or a second memory
lifecycle implementation.

`CreateMemoryWithGuidance` uses the canonical normalized-content function only
for the creation-time same-scope/owner advisory rule in
`DomainAndDecisionRules.md`. It is not part of `ContextRetriever`, does not
score/collapse retrieval candidates, and never merges or changes an existing
memory. TASK-0017 application integration, not `MemoryManager` or QML, emits the
one canonical redacted memory trace event after a successful commit.

## TASK-0017 validation-history projection

`InspectValidationHistory` is a read-only application projector, not a new
validator. It targets the same latest accepted run selected by
`ContextInspection.md`, validates ordered request/response/validation/correction
lineage from repository ports, and returns only the closed safe history in
`ManualOperationsUI.md`. It does not invoke `ResponseValidator` or
`CorrectionController`, reconstruct a prompt, expose any candidate/provider/raw
validation value, or write/trace a decision.

## ContextRetriever

`RetrievalRequest` contains processing-run, source-message, conversation,
optional project, and caller-supplied context-packet IDs; exact request text;
optional active-topic label; a tuple of distinct considered memories that may
include scope mismatches, deleted records, and expired records; validated
threshold/limit values; and one injected-clock `evaluated_at` value. The caller
reads the clock once. The retriever is constructed with an `IdGenerator`; it
does not read a repository, clock, configuration file, or packet.

`RetrievalDecision` partitions every considered memory ID exactly once between
ordered `RetrievalResult` selections and ordered `RetrievalExclusion` evidence.
It contains the highest selected score as confidence, or null for no selection.
Normalization, decimal arithmetic, eligibility, exclusion precedence, score,
threshold, sort, retrieval-only duplicate collapse, limit, zero-based rank,
reason strings, evidence shapes, and timestamps follow the complete canonical
rules in `DomainAndDecisionRules.md`.

The retriever is pure: it never creates, merges, rewrites, deletes, or otherwise
mutates a memory. TASK-0009 persistence tests may attach its already-computed
results/exclusions to a caller-supplied existing context-packet fixture through
the existing `ContextPacketRepository`; the retriever does not construct that packet
or orchestrate persistence. Packet construction, pipeline integration,
UI/presentation, trace events, and provider interaction remain later work.

## ContextPacketBuilder

Input: exact message, interpretation, state, references, constraints, retrieved
memories, confidence, response policy, and token configuration. Output: one
immutable `mvp-context-packet-v2` or a context-budget failure before generation.

TASK-0007 does not construct a `ContextPacket`. AT-004 and its component-owned
part of AT-005 are demonstrated through `InterpretationDecision`,
`ConstraintDecision`, and `ResponsePolicy` only.
