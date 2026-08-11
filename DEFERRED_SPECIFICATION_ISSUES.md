# Deferred Specification Issues

## Status and use

This register records specification work intentionally deferred by the bounded
documentation repair pass authorized on 2026-08-02 and the bounded semantic-
alignment reconciliation authorized on 2026-08-11. It does not change MVP
scope, perform implementation, or override the source-of-truth order in
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
| D-004 | Resolved: repository enforcement remains TASK-0005 ownership; TASK-0014 now fixes application transaction ordering, closed request/response projections, adjacent correction reconstruction, timestamps, and recovery use of those guards. | `TASK-0005`, `TASK-0014` |
| D-005 | Resolved as a cross-layer contract: startup invokes one finite `RecoverProcessingRun` foreground execution before admission, with a fresh owned token and no queue, polling, daemon, or detached work. Later presentation wiring remains TASK-0015 delivery, not an open TASK-0014 specification decision. | `TASK-0014`, `TASK-0015` |
| D-006 | Resolved for the provider-independent contract below: `ModelGateway` returns typed values, application/repository code persists lifecycle state, and live/recovery token ownership is explicit. TASK-0012 must preserve this contract at the Ollama transport boundary. | `TASK-0011`, `TASK-0012` |
| D-007 | Resolved: `docs/diagrams/SEQUENCES.md` now shows duplicate/existing, global Busy, clarification, joined context/state CAS, `PENDING` claim, bounded generation/correction, and one-shot recovery branches. | `TASK-0014` |
| D-008 | Resolved for TASK-0010 below: packet schema v2, current prompt policy v2, historical v1 compatibility, versioning rules, complete packet/aggregate shapes, rendering grammar, semantic projections, evidence, retrieval, budgeting, omission, and typed-overflow contracts are authoritative. The aligned implementation repair remains pending under D-016. | `TASK-0010` |
| D-009 | The TASK-0018 portion is resolved: AT-016 uses one closed standalone local JSON artifact owned by its testing/evaluation harness and creates no runtime evaluation row. General evaluation-case/evaluation-run shapes, taxonomy, repositories, use cases, and runtime persistence retain their deferred status. | `TASK-0005`, `TASK-0018` |
| D-010 | Resolved: `ConfigurationAndLogging.md` fixes event/stage/correlation/error/order semantics and AT-014/AT-015 contain exact owning assertions, including recovery and redaction. | `TASK-0014` |
| D-011 | Reconcile local-Ollama opt-in semantics in `TASK-0012` and `TASK-0018`: no flag skips; flag present makes invalid daemon/model/configuration a failed opt-in test. | `TASK-0018` |
| D-012 | Resolved: TASK-0013 retains pure validator/correction and bounded preconstructed repository evidence; TASK-0014 owns complete provider-facing AT-012 orchestration. | `TASK-0013`, `TASK-0014` |
| D-013 | The TASK-0009 and TASK-0017 portions are resolved below: history is inspectable only, no restore exists, and `ManualOperationsUI.md` fixes the complete manual-memory presentation/trace/acceptance contract. Any separate TASK-0015 portion retains its existing status. | `TASK-0015`, `TASK-0017` |
| D-014 | The TASK-0014, TASK-0016, and TASK-0017 portions are resolved below by their canonical public-result, transaction, inspection/manual-operation, safety, trace, and acceptance contracts. Portions assigned to other delivery tasks retain their existing status. | `TASK-0002` through `TASK-0018` |
| D-015 | Resolved for TASK-0014: roadmap, backlog, and implementation-plan wording now agrees on global admission, one-shot recovery, clarification persistence, and AT-002/full-AT-012/AT-015 ownership. | `TASK-0014` |
| D-016 | Resolved in documentation: canonical `normalized_rule` was not translated into deterministic validator-equivalent trusted model semantics, while AT-016 imposed an undisclosed raw candidate sentinel. Current prompt policy v2 now renders closed semantic projections; the raw fixture identifier is not an output oracle; TASK-0013 remains unchanged; historical v1 rows remain truthful without migration. TASK-0010 implementation and later TASK-0018 harness repair are still pending. | `TASK-0010`, `TASK-0013`, `TASK-0018` |

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
and passed-validation assistant-message links. The remaining TASK-0014
application/recovery portion is resolved by the TASK-0014 reconciliation below.

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
are now fixed by the resolved D-010 reconciliation below. The bounded delivery contract is
`tasks/TASK-0009-MANUAL-MEMORY-LIFECYCLE-AND-DETERMINISTIC-RETRIEVAL.md`.

D-013 remains open here only for its later TASK-0015/TASK-0017 portions; the
TASK-0017 portion is resolved solely by the dedicated reconciliation below.
After the TASK-0010 reconciliation below, D-014 remains unresolved here for its
later delivery portions. No later-task issue is resolved by this section.

### TASK-0010 reconciliation

D-008 and the TASK-0010 portion of D-014 are resolved by the complete immutable
packet, prompt-rendering, and public component contracts in
`docs/contracts/ContextPacket.md`; the bounded delivery contract in
`tasks/TASK-0010-IMMUTABLE-CONTEXT-PACKET-AND-PROMPT-RENDERING.md`; and the
direct component and narrow persistence assertions in AT-009.

TASK-0010 consumes already-computed interpretation, reference, constraint, and
retrieval decisions through an explicit provider-independent
`ContextPacketBuildRequest`. It owns the recursively immutable
`mvp-context-packet-v2` aggregate, current `mvp-prompt-policy-v2` grammar,
historical v1 read/render dispatch, `mvp-correction-envelope-v1` render input,
canonical JSON, deterministic canonical-rule and validation-semantic
projections, `conservative_utf8_v1`, deterministic whole-item budgeting/
omission evidence, typed initial/correction budget outcomes, and its two atomic
initial context-stage persistence outcomes.

The reconciliation does not assign interpretation, reference resolution,
constraint resolution, retrieval selection, provider/model calls, response
validation, correction control/persistence, later pipeline orchestration,
trace-event integration, or UI behavior to TASK-0010. After the TASK-0011
reconciliation below, D-014 remains unresolved for `TASK-0012` through
`TASK-0018`; no later-task issue is resolved here.

This section records specification ownership only. The repository implementation
at the start of the 2026-08-11 reconciliation still emitted v1 bytes and did not
produce the semantic projections. The bounded TASK-0010 repair and revised
AT-009 evidence in D-016 remain required before TASK-0018 may continue; no code
or test repair occurred in that documentation-only pass.

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

### TASK-0014 reconciliation

The TASK-0014 portions of D-004, D-005, D-007, D-010, D-012, D-014, and D-015
are resolved by the bounded specification reconciliation recorded in:

- `docs/contracts/ProcessUserMessage.md` for the exact admission order,
  exhaustive public result algebra, cancellation entry/checkpoints, and the
  separate empty-request foreground recovery use case;
- `docs/contracts/Persistence.md` for re-entrant transaction joining, atomic
  context ownership, closed durable request/response and interpretation
  projections, assistant byte lineage, the complete recovery matrix, and exact
  safe failures;
- `docs/contracts/DomainAndDecisionRules.md`, `ContextPacket.md`,
  `ModelGateway.md`, `DATABASE_SCHEMA.md`, and `ARCHITECTURE.md` for the one new
  context-failure code, legal accepted cancellation, joined packet-stage
  semantics, gateway/recovery handoff, logical schema guards, and one-shot
  foreground composition;
- `docs/contracts/ConfigurationAndLogging.md` and
  `docs/diagrams/SEQUENCES.md` for the canonical trace port/matrix/order and
  repaired lifecycle/recovery flows; and
- `ACCEPTANCE_TESTS.md`, the TASK-0014 delivery contract, and the three planning
  summaries for AT-002, full AT-012, and AT-015 ownership.

Admission always performs same-key lookup before the global active-run check,
then persists acceptance only when both branches permit it. An acceptance
rollback returns an unpersisted persistence result and never recreates foreign-
key lineage. Context packet persistence joins one outer transaction; a false
state CAS rolls all context writes back. Recovery is invoked once before new
submissions, continues only provably not-yet-sent work, and terminalizes an
uncertain call without retry.

No TASK-0014 specification gate remains. Its implementation is still an ordered
execution dependency on completed, green TASK-0013 exit criteria; that is not a
specification ambiguity. This section does not resolve or implement any
TASK-0015-or-later presentation/smoke work, and it does not change predecessor
component ownership.

For TASK-0014, the historical “Evaluation and Debugging System” and “Main Use
Cases” proposals are non-authoritative. Their PostgreSQL/API, automatic
correction-memory, validate-then-display, prior-conversation fixture, and
`UpdateProjectState` descriptions do not supplement the canonical SQLite,
validate-before-display, no-automatic-memory, and conversation-state contracts
listed above. No historical planning file may add a TASK-0014 behavior or gate.

### TASK-0016 reconciliation

The TASK-0016 portion of D-014 is resolved by
`docs/contracts/ContextInspection.md`, the additive extension in
`docs/contracts/PresentationShell.md`, the read-only ownership in
`docs/contracts/Persistence.md`, the component/architecture boundaries, and the
deterministic context-page portion of AT-013.

The canonical inspection target is the latest accepted run for the shell's
current conversation, selected by linked user-message sequence. The page exposes
only its closed historical safe projection with explicit field availability,
uses one additive route on the existing facade, and performs one finite
worker-thread-owned snapshot per load with queued/stale-safe delivery. Its
complete states, refresh rules, native Qt accessibility oracle, and redaction
allowlist are fixed by that contract. The existing schema is sufficient and no
migration is assigned to TASK-0016.

For TASK-0016, the historical “UI Modules,” “User Interface,” and “Presentation
Layer” proposals are non-authoritative. Their `ProjectStateView`, plural model,
rule-locking, project-file/project-data, direct backend/API, and generic
background-work descriptions neither supplement nor override
`ContextInspection.md`. No historical planning file may add a TASK-0016 field,
route, state, worker, persistence requirement, or verification gate.

No TASK-0016 specification gate remains. Implementation remains ordered behind
completed, green TASK-0015 exit criteria; that dependency is not a specification
ambiguity. D-014 remains open for every other delivery-task portion not already
resolved elsewhere in this register.

### TASK-0017 reconciliation

The TASK-0017 portions of D-013 and D-014 are resolved by
`docs/contracts/ManualOperationsUI.md`, its additive shell/context integration,
the aligned domain/context/configuration/persistence boundaries, and the
complete TASK-0017 portion of AT-014.

The canonical contract fixes exactly four additive routes on the existing
facade, one finite shared manual-operation scope/worker, complete safe memory/
project/full-validation/settings projections, explicit confirmations and stale
guards, advisory creation-time duplicate guidance, archive preservation,
candidate/configuration redaction, permitted preference defaults/ownership,
per-field configuration origin/full fingerprint, Qt-native theme application,
post-commit memory trace ownership, accessibility, and deterministic
verification. The existing schema is sufficient and no migration is assigned.

For TASK-0017, the historical “UI Modules,” “User Interface,” and “Presentation
Layer” proposals are non-authoritative. Their `ProjectStateView`, plural-model,
rule-locking, project-file/project-data, generic background-work, raw backend/API,
theme/KDE, memory automation, or unrestricted validation/configuration ideas
neither supplement nor override `ManualOperationsUI.md`. No historical planning
file may add a TASK-0017 field, route, state, worker, mutation, persistence
requirement, or verification gate.

No TASK-0017 specification gate remains. Implementation is still ordered behind
completed, green TASK-0016 exit criteria and its prerequisite chain; that block
is not a specification ambiguity. D-013/D-014 retain every unrelated delivery-
task portion not already resolved elsewhere in this register.

### TASK-0018 gate reconciliation

G18-01, G18-02, and G18-03 are closed by the complete AT-016 contract in
`ACCEPTANCE_TESTS.md` and the aligned
`tasks/TASK-0018-LOCAL-OLLAMA-SMOKE-ACCEPTANCE.md` task sheet.

The fixture is one independent, versioned copy of the established complete
six-file configuration with closed deltas, an empty initial state, one exact
message, deterministic pre-provider expectations, the existing normalized
validation predicate and exact production evidence assertion, and zero
revisions. The uppercase source literal remains a private fixture identifier,
not a candidate-output predicate. The fixture therefore permits one provider
generation and defines a structural production-validation oracle without
fixing or publishing the model's surrounding prose.

The TASK-0018 portion of D-009 is resolved by one standalone
`at-016-evidence-v1` local JSON artifact per exact-opt-in execution. Its owner,
allowlisted fields, safe failure codes, canonical serialization, authoritative
gateway timing projection, bounded OS source, prohibited content, unique atomic
publication, and operator-managed retention are closed. It creates no
`evaluation_cases` or `evaluation_runs` row and requires no database schema,
migration, repository, use case, application, QML, routine-log, or trace-schema
change. The remaining general evaluation framework described by D-009 stays
deferred.

The existing D-011 behavior is neither rewritten nor reopened: the default
suite excludes live tests; explicitly selecting AT-016 without the opt-in flag
is the sole skip; a present non-`1` flag fails; exact `1` requires the model-name
override; and every other opted-in failure fails. This bounded reconciliation
does not alter D-014 or any unrelated deferred-task portion.

Specification closure does not execute AT-016 or clear its delivery order.
TASK-0018 implementation and live acceptance remain blocked until the D-016
TASK-0010 prompt-policy-v2 repair, revised AT-009, TASK-0017, and their
prerequisite chains are implemented with green exit criteria. TASK-0018 then
updates only its testing/evaluation harness to consume v2 and the production
validation evidence; it does not own the production repair.

### TASK-0010 / TASK-0013 / TASK-0018 semantic alignment

D-016 records the gap found after the original task specifications had each
been implemented against their own contracts: v1 rendered canonical
`normalized_rule` as a trusted field but did not define or render its
validator-equivalent model meaning, while TASK-0013 correctly split canonical
predicate atoms at underscores and AT-016 separately required a raw
case-sensitive fixture identifier from the candidate. A compliant prompt and a
compliant validator could therefore disagree without either violating its own
then-current task contract.

The documentation decision is now closed:

- `normalized_rule` remains the canonical machine/audit representation;
- new packets use `mvp-prompt-policy-v2`, rendering both that canonical value
  and one exact semantic instruction derived from the canonical grammar;
- the trusted validation-semantics block exposes only pass-critical topic,
  output-shape, action-marker, and active-preserve semantics;
- persisted v1 packets and model requests keep their identifiers and bytes and
  render only through v1; the existing generic text/JSON storage needs no
  schema or data migration;
- TASK-0013 candidate normalization, predicate parsing, `MUST_EXACTLY`, report,
  score, and correction behavior do not change; and
- the uppercase AT-016 fixture identifier is source/evidence only. AT-016
  asserts the normal passed `REQUIRED_CONSTRAINT` evidence and has no private
  output predicate or `SMOKE_SENTINEL_MISMATCH` code.

This was documentation reconciliation only. Production still requires the
bounded TASK-0010 v2 implementation/test repair, and the uncommitted TASK-0018
testing/evaluation work must later replace its v1/raw-sentinel expectations
after that prerequisite is green. AT-016 has not been run, TASK-0018 is not
complete, and no implementation result is claimed here.

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
| UI Modules, User Interface, and Presentation Layer | Its TASK-0016 context-page proposals are superseded by `ContextInspection.md`; its TASK-0017 memory/project/validation/settings proposals are superseded by `ManualOperationsUI.md`. `ProjectStateView`, plural models, rule locking, project-file, unsupported project-data, raw backend/API, and generic background-work promises remain non-authoritative. | `TASK-0015`, `TASK-0016`, `TASK-0017` |
| Response Validator | Historical hallucination/subjective checks are presented as MVP behavior. | `TASK-0013` |
| MVP Engineering Boundary | “Unrestricted background agents” is weaker than the MVP exclusion of all background workers. | `TASK-0015` |

## Completion rule

An assigned task must not start implementation while its applicable deferred
items remain unresolved. This register is intentionally finite: it supersedes no
root contract and should be deleted only after every row is resolved or formally
reclassified as post-MVP in the authoritative documents.
