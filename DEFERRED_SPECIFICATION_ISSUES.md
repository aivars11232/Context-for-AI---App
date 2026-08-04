# Deferred Specification Issues

## Status and use

This register records specification work intentionally deferred by the bounded
documentation repair pass authorized on 2026-08-02. It does not change MVP scope,
authorize implementation, or override the source-of-truth order in
`SPECIFICATION_GOVERNANCE.md`.

Each item must be reconciled in documentation before implementation begins for
its assigned task. The assignments identify the owning delivery task; they do
not make a later task executable until its dependencies and acceptance criteria
also agree.

## Deferred issues

| ID | Deferred specification issue | Assigned task(s) |
|---|---|---|
| D-001 | Define exhaustive reference-mention phrases, overlap precedence, scan direction, and immutable mention-ordinal extraction. | `TASK-0008` |
| D-002 | Define qualifier capture templates, normalization, and exact emitted `MUST_*` predicate formats for `only`, `exactly`, modals, prohibition, preservation, substitution, prior-reference, and sequential language. | `TASK-0007` |
| D-003 | Define same-target normalization, hard-rule opposition, conflict grouping, non-hard current `PREFERRED`/`OPTIONAL` priority, and source sequencing for non-message constraints. | `TASK-0007` |
| D-004 | Complete processing/model-request/correction integrity rules: legal timestamps, `INITIAL`/attempt-0 and `REVISION`/attempt-1-or-2 pairing, same-run correction links, and repository enforcement. | `TASK-0005`, `TASK-0014` |
| D-005 | Reconcile restart recovery with the foreground UI controller: specify how an already accepted run resumes without becoming a prohibited background worker. | `TASK-0014`, `TASK-0015` |
| D-006 | Resolved for the provider-independent contract below: `ModelGateway` returns typed values, application/repository code persists lifecycle state, and live/recovery token ownership is explicit. TASK-0012 must preserve this contract at the Ollama transport boundary. | `TASK-0011`, `TASK-0012` |
| D-007 | Update `docs/diagrams/SEQUENCES.md` for duplicate-key and Busy branches, clarification persistence, `PENDING` claim, context-stage state update, and recovery. | `TASK-0014` |
| D-008 | Resolved for TASK-0010 below: the fixed prompt-policy/schema versions, versioning rules, complete packet/aggregate shapes, rendering grammar, evidence, retrieval, budgeting, omission, and typed-overflow contracts are authoritative. | `TASK-0010` |
| D-009 | Define evaluation-case and evaluation-run JSON shapes, category taxonomy, fixture linkage, expected observables, and repository/use-case boundary; alternatively defer runtime evaluation persistence consistently. | `TASK-0005`, `TASK-0018` |
| D-010 | Add exact acceptance assertions for required trace-event names, correlation fields, and redaction rather than merely claiming combined coverage. | `TASK-0014` |
| D-011 | Reconcile local-Ollama opt-in semantics in `TASK-0012` and `TASK-0018`: no flag skips; flag present makes invalid daemon/model/configuration a failed opt-in test. | `TASK-0018` |
| D-012 | Move full AT-012 ownership from `TASK-0013` to `TASK-0014`; keep Task 0013 limited to validator/correction-controller behavior. | `TASK-0013`, `TASK-0014` |
| D-013 | The TASK-0009 portion is resolved below: history is inspectable only and there is no restore operation. Remaining work must keep Task 0015 to responsiveness portions of AT-013 and Task 0017 to UI/presentation portions of manual memory control. | `TASK-0015`, `TASK-0017` |
| D-014 | Align detailed task scopes with the repaired contracts: Task 0002 enums/types; Task 0003 clarification/retrieval ports; Task 0004 schema additions/indexes; Task 0005 repositories/recovery; Task 0006 lifecycle; Tasks 0007–0010 deterministic contracts; Tasks 0011–0018 provider, pipeline, UI, and smoke criteria. | `TASK-0002` through `TASK-0018` |
| D-015 | Reconcile roadmap/backlog/implementation-plan wording with the global single-run admission rule, recovery matrix, clarification persistence, and task-stage acceptance ownership. | `TASK-0014` |

### TASK-0002 reconciliation

The `TASK-0002` portion of D-014 is resolved. Its scope is the dependency-free
canonical enums, value objects, immutable domain representations, typed domain
errors, and structural priority/lifecycle policies named by
`tasks/TASK-0002-DOMAIN-PRIMITIVES-AND-POLICIES.md` and the canonical contracts.
It does not include application ports, persistence, context parsing or decision
pipelines, provider integration, orchestration, or UI behavior.

### TASK-0003 reconciliation

The `TASK-0003` portion of D-014 is resolved. Its repository-port scope
explicitly includes the one-record clarification operations on
`ClarificationRepository` and the retrieval-result/retrieval-exclusion
operations on `ContextPacketRepository`. It defines inward contracts only; the
deterministic builders/retriever, repository implementations, pipeline
orchestration, and UI behavior remain assigned to their later tasks. D-014
remains unresolved for `TASK-0004`, `TASK-0005`, and `TASK-0007` through
`TASK-0018`.

### TASK-0005 reconciliation

The `TASK-0005` repository-enforcement portion of D-004 is resolved by the
canonical lifecycle invariants in `docs/contracts/Persistence.md`. Repositories
enforce processing-run and model-request timestamp states, `INITIAL`/attempt-0
and `REVISION`/attempt-1-or-2 pairing, same-run consecutive correction lineage,
and passed-validation assistant-message links. D-004 remains unresolved for
`TASK-0014`, which owns application orchestration and recovery use of those
repository guarantees.

### TASK-0006 reconciliation

The `TASK-0006` portion of D-014 is resolved by the authoritative reconciliation
in `tasks/TASK-0006-VERSIONED-CONVERSATION-STATE.md`. TASK-0006 owns the
dependency-free conversation-state transitions and the public use cases for
project selection, prepared topic/task/output state changes, explicit task
status changes, and project archival required by AT-003 state assertions. It
uses `conversations.project_id` as the sole persisted active-project value,
reuses the existing compare-and-swap and transaction ports, retries one
deterministic state transition after a conflict, and does not own project or
conversation creation.

The historical `Conversation State Manager.txt` material is explicitly
non-authoritative: its project duplicate, file/version, step, application,
decision, and unresolved-question fields are not TASK-0006 state. Message admission and `BusyError` mapping, correction-constraint persistence,
interpretation, packet construction, orchestration, recovery, and UI remain
assigned to their later tasks. D-014 remains unresolved for `TASK-0009` through
`TASK-0018`.

### TASK-0007 reconciliation

D-002 is resolved by the canonical source-preserving normalization, qualifier
capture, evidence, and exact predicate-format rules in
`docs/contracts/DomainAndDecisionRules.md`. D-003 is resolved there by the
canonical target-key, lexical opposition, source-recency, soft/hard,
override-evidence, conflict-group, conditional, and `ASSUMED` rules.

The `TASK-0007` portion of D-014 is resolved by the immutable public request and
result contracts in `docs/contracts/ContextEngine.md` and the bounded delivery
contract in
`tasks/TASK-0007-DETERMINISTIC-INTERPRETATION-AND-CONSTRAINTS.md`. An explicit
request to write a text prompt is canonically `EDIT_TEXT`/`TEXT_ANSWER`; it does
not add an intent/output enum or authorize image generation or an external
action.

The historical Context Interpreter taxonomy and Instruction and Constraint
Manager priority descriptions are non-authoritative for TASK-0007. The
canonical intent/output taxonomy, numeric bands, conditional/assumed behavior,
and conflict rules named above replace those historical descriptions. Reference
resolution, retrieval, packets, providers, orchestration, persistence, and UI
remain assigned to their existing later tasks.

### TASK-0008 reconciliation

D-001 is resolved by the exhaustive fixed/deictic/file form table, exact scoped
registry-name matching, TASK-0007 seed-mention merge, source-preserving
normalization, overlap precedence, left-to-right scan, and final contiguous
ordinal rules in `docs/contracts/DomainAndDecisionRules.md` and
`docs/contracts/ContextEngine.md`.

The `TASK-0008` portion of D-014 is resolved by the canonical registry identity,
ownership, lifecycle, provenance, explicit named-item grammar, candidate
ranking, status/confidence, materiality, evidence JSON, and pure
`ReferenceDecision` contracts. `DATABASE_SCHEMA.md` defines their persistence
semantics without a new migration. AT-006 now fixes the active-project outcome;
AT-007 separates TASK-0008 ambiguity/blocking evidence from later
orchestration, terminalization, provider-prevention integration, and UI
presentation. The bounded delivery contract is
`tasks/TASK-0008-ENTITY-REGISTRY-AND-REFERENCE-RESOLUTION.md`.

No model, semantic inference, file ingestion/indexing, memory, context-packet,
pipeline, or UI behavior is added to TASK-0008. After the TASK-0010
reconciliation below, D-014 remains unresolved for `TASK-0011` through
`TASK-0018`.

### TASK-0009 reconciliation

The TASK-0009 portions of D-013 and D-014 are resolved. TASK-0008 specification
reconciliation is complete at HEAD `8432241`, but TASK-0008 implementation is
not a runtime dependency of TASK-0009. TASK-0009 consumes no entity-registry,
reference-extraction, resolution, or `ReferenceDecision` output and may proceed
independently after its own implementation approval. It neither implements nor
claims TASK-0008 behavior; later pipeline composition owns integration order.

TASK-0009 owns explicit create, edit, get/inspect, stored-status list, and
soft-delete use cases; atomic source/revision persistence; computed effective
status; pure deterministic retrieval; and retrieval-result/exclusion
persistence assertions. History is inspectable only. There is no restore,
automatic creation/edit/merge/rewrite/cleanup/expiry/deletion, background
mutation, or model-based memory decision.

`docs/contracts/DomainAndDecisionRules.md` now fixes the complete Unicode
normalization, decimal precision, inclusive threshold, total ordering,
zero-based rank, reason formatting, exclusion precedence/details,
`memory-revision-v1`, effective status, scope, and retrieval-only duplicate
rules. `docs/contracts/ContextEngine.md` fixes the `MemoryManager` and pure
`ContextRetriever` ownership; `DATABASE_SCHEMA.md` maps those decisions to the
existing columns without a migration. The canonical formula replaces the
illustrative historical retrieval formulas, and the text-only/no-autonomous-
mutation boundary supersedes the obsolete historical correction example.

AT-008 and AT-014 now separate TASK-0009 component/use-case and persistence
assertions from later orchestration, packet construction, UI/presentation,
trace-event, and provider integration assertions. Exact trace-event contracts
remain assigned to D-010. The bounded delivery contract is
`tasks/TASK-0009-MANUAL-MEMORY-LIFECYCLE-AND-DETERMINISTIC-RETRIEVAL.md`.

D-013 remains open only for its TASK-0015/TASK-0017 portions. After the
TASK-0010 reconciliation below, D-014 remains unresolved for `TASK-0011`
through `TASK-0018`. No later-task issue is resolved by this section.

### TASK-0010 reconciliation

D-008 and the TASK-0010 portion of D-014 are resolved by the complete immutable
packet, prompt-rendering, and public component contracts in
`docs/contracts/ContextPacket.md`; the bounded delivery contract in
`tasks/TASK-0010-IMMUTABLE-CONTEXT-PACKET-AND-PROMPT-RENDERING.md`; and the
direct component and narrow persistence assertions in AT-009.

TASK-0010 consumes already-computed interpretation, reference, constraint, and
retrieval decisions through an explicit provider-independent
`ContextPacketBuildRequest`. It owns the recursively immutable
`mvp-context-packet-v1` aggregate, `mvp-prompt-policy-v1` grammar,
`mvp-correction-envelope-v1` render input, canonical JSON,
`conservative_utf8_v1`, deterministic whole-item budgeting/omission evidence,
typed initial/correction budget outcomes, and its two atomic initial
context-stage persistence outcomes.

The reconciliation does not assign interpretation, reference resolution,
constraint resolution, retrieval selection, provider/model calls, response
validation, correction control/persistence, later pipeline orchestration,
trace-event integration, or UI behavior to TASK-0010. After the TASK-0011
reconciliation below, D-014 remains unresolved for `TASK-0012` through
`TASK-0018`; no later-task issue is resolved here.

### TASK-0011 reconciliation

D-006 and the TASK-0011 portion of D-014 are resolved by the exact
`PromptRenderResult` handoff in `docs/contracts/ContextPacket.md`, the exhaustive
returned-value and safe-mapping contract in `docs/contracts/ModelGateway.md`,
the application-owned mapping in `docs/contracts/ProcessUserMessage.md`, the
bounded component/integration split in AT-010, and the delivery contract in
`tasks/TASK-0011-MODEL-GATEWAY-AND-DETERMINISTIC-MOCK-PROVIDER.md`.

The gateway returns one immutable `GenerationOutcome`; expected provider
failures are typed values rather than exceptions. The gateway and provider
adapters never persist lifecycle state. The Model Gateway contract fixes the
diagnostic code, safe message, request/run status, canonical failure code, and
no-response persistence expectation for every failure variant.

The foreground request owner owns a monotonic thread-safe token; the gateway
only observes it. Cancellation wins when it is observable at the same terminal
checkpoint as timeout or another outcome. Tokens are not persisted or inferred
after restart. If existing recovery policy permits a not-yet-sent call, its
application initiator supplies a fresh token; this does not define recovery
scheduling or presentation. An uncertain durable `IN_FLIGHT` request is never
repeated.

TASK-0011 owns the deterministic test adapter, test composition, correlation
preservation, safe persistence inputs, import isolation, cancellation, and
complete-buffering component assertions. It does not own Ollama transport,
production composition, lifecycle persistence, application trace events,
response validation, broader pipeline orchestration, QML, or UI behavior.

TASK-0011 is specification-ready but remains implementation-blocked until the
TASK-0010 implementation and exit criteria pass. This reconciliation does not
resolve any separate TASK-0012-or-later specification issue.

## Historical planning reconciliation

These supporting documents require a status-note or canonical-pointer repair,
not implementation of their historical proposals. The task assignment identifies
the related MVP delivery area.

| Planning area | Deferred contradiction or ambiguity | Assigned task(s) |
|---|---|---|
| Evaluation and Debugging System | Prior-conversation fixture claim; PostgreSQL/noncanonical tables; duplicated backend/API tree; validate-then-display workflow without pass/correction branches; automatic correction-memory wording. | `TASK-0014`, `TASK-0018` |
| Conversation State Manager | Historical fields such as file/version, rejected approaches, and unresolved questions presented as active state. | `TASK-0006` |
| Instruction and Constraint Manager | Historical priority order conflicts with canonical bands and lacks conditional/assumed semantics. | `TASK-0007` |
| Context Interpreter | Unqualified historical intent taxonomy. | `TASK-0007` |
| Context Retrieval Engine and Engineering Retrieval Engine | Illustrative formulas conflict with the canonical deterministic scoring formula. | `TASK-0009` |
| Memory System | Obsolete correction example implies image generation may be allowed. | `TASK-0009` |
| Critical Relationships | Direct project-to-task/project-state model conflicts with conversation-scoped tasks and conversation state. | `TASK-0004` |
| Main Use Cases | Historical `UpdateProjectState` use case conflicts with the canonical conversation-state model. | `TASK-0014` |
| UI Modules, User Interface, and Presentation Layer | `ProjectStateView`, plural models, rule locking, project-file, and unsupported project-data promises conflict with MVP scope. | `TASK-0015`, `TASK-0016`, `TASK-0017` |
| Response Validator | Historical hallucination/subjective checks are presented as MVP behavior. | `TASK-0013` |
| MVP Engineering Boundary | “Unrestricted background agents” is weaker than the MVP exclusion of all background workers. | `TASK-0015` |

## Completion rule

An assigned task must not start implementation while its applicable deferred
items remain unresolved. This register is intentionally finite: it supersedes no
root contract and should be deleted only after every row is resolved or formally
reclassified as post-MVP in the authoritative documents.
