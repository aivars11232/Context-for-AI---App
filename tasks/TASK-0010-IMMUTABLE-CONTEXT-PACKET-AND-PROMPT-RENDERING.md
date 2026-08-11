# TASK-0010 — Immutable Context Packet and Prompt Rendering

Status: Semantic-alignment specification reconciled; prompt-policy-v2
implementation repair pending

## Goal

Implement the formal immutable context-packet aggregate, deterministic prompt
budgeting and rendering, and the narrow context-stage persistence boundary
defined by `docs/contracts/ContextPacket.md`.

## Sources

- `docs/contracts/ContextPacket.md`
- `docs/contracts/DomainAndDecisionRules.md`
- `docs/contracts/Persistence.md`
- `REQUIREMENTS.md` FR-010 and the FR-012 compatibility boundary
- `DATABASE_SCHEMA.md`
- `ACCEPTANCE_TESTS.md` AT-009

## Reconciled TASK-0010 contract

TASK-0010 consumes the already-computed TASK-0007 interpretation and constraint
decisions, TASK-0008 reference outcomes, and TASK-0009 retrieval decision. It
does not call or reimplement those components. A successful build permits only
`RESOLVED`/`NOT_APPLICABLE` reference outcomes, no active material `ASSUMED`
constraint, and no `CONFLICTING` constraint. Outcomes that require
clarification or conflict handling stop before packet construction.

The public provider-independent seams are exactly:

- `ContextPacketBuilder.build(ContextPacketBuildRequest)` returning
  `ContextPacketBuildResult`;
- `ContextPacketBuildResult = ContextPacketBuildSuccess |
  ContextBudgetExceeded`;
- `PromptRenderer.render(PromptRenderRequest)` returning
  `PromptRenderOutcome`; and
- `PromptRenderOutcome = PromptRenderResult | ContextBudgetExceeded`; and
- `ContextPacketStage.execute(ContextPacketBuildRequest)` returning the same
  `ContextPacketBuildResult` after its applicable initial transaction commits.

`ContextPacketBuildRequest` contains the preallocated context-packet ID, run,
message, exact versioned state/project snapshot, already-computed decisions,
one immutable packet-lineage companion per constraint, selected immutable memory
snapshots, the immutable active-topic snapshot, the normalized validation-
configuration snapshot, scalar budget inputs, and one caller-supplied creation
time read from the injected clock. It contains no provider, model,
gateway, repository, UI object, clock, or caller-selected policy/version value.
The packet ID is allocated before retrieval and is the same ID already carried
by TASK-0009 result and exclusion rows. The lineage companions supply only the
source IDs/state version and resolution links absent from TASK-0007 evidence;
the builder joins and validates them without repository lookup or decision
mutation.

A successful result contains one `ContextPacketRecord` aggregate and its
initial `PromptRenderResult`. The aggregate consists of the immutable outer
packet plus rank-ordered retrieval results and retrieval exclusions ordered by
canonical memory UUID. Selected memory snapshots are complete packet payload;
exclusions remain aggregate audit evidence outside `packet_json`. Retrieval
confidence is copied unchanged from the TASK-0009 decision. Packet identity and
`created_at` remain outer-record fields. Packet construction and render
projection never mutate an upstream result, state snapshot, memory snapshot, or
the completed packet.

The component-owned versions are fixed at:

- packet schema `mvp-context-packet-v2`;
- current prompt policy `mvp-prompt-policy-v2`;
- historical read/render prompt policy `mvp-prompt-policy-v1`;
- correction envelope `mvp-correction-envelope-v1`; and
- estimator `conservative_utf8_v1`.

New packet construction always selects v2. Prompt rendering uses its exact
preamble, semantic-policy line, ordered `@@CFA/...@@` section markers, trust
classifications, canonical JSON rules, and correction blocks in the
ContextPacket contract. Every trusted constraint renders both canonical
`normalized_rule` and the exact deterministic `semantic_instruction` derived
from its parsed rule; the closed validation-semantics block communicates only
the topic, output-shape, action-marker, and active-preserve inputs needed by the
unchanged production validator. Source text and other untrusted evidence never
participate in either trusted projection, and no free-form paraphrasing is
permitted.

A stored v1 packet remains readable/renderable only through the exact v1
grammar and can never be upgraded or rendered as v2. New callers cannot select
v1. User/reference/constraint-evidence/retrieval/correction data remains
serialized as data and cannot create a trusted instruction boundary. Canonical
JSON accepts exact decimals and rejects binary floating-point input rather than
converting it implicitly. Before packet construction, the builder maps only
TASK-0008 candidate-evidence scores in the fixed canonical five-value domain to
their exact decimal values and validates the score/reason pairing; this is a
representation projection, not reranking. Rendered prompt text is returned
only to its in-process caller and is neither persisted nor logged by TASK-0010.

The effective prompt budget and estimate are computed exactly as specified in
the contract. Mandatory content includes full protocol framing, response
policy, validation semantics, original request, active state, active hard/true-
conditional constraints with their semantic instructions, and override
evidence groups. Optional items begin fully included and are tail-pruned as
whole items in this fixed order: resolved references, inactive-conditional
evidence, active `PREFERRED` constraints, selected retrieval by rank, then
active `OPTIONAL` constraints. A retained soft constraint keeps its canonical
and semantic projections together. Each removal rerenders the complete prompt;
there is no splitting, reordering, rewriting, summarizing, or backfill.
Omission records identify the projection and stable whole-item keys. Render
omission never deletes packet evidence.

A correction envelope must name the same packet and have an attempt number
within that packet's correction limit. A correction render starts from the
initial retained optional prefix, appends the fixed envelope, and can only prune
further. Its result reports final included sections and only the additional
correction-local token omissions; initial omissions remain in packet rendering
metadata. Correction rendering cannot mutate packet bytes. Correction budget
overflow returns `ContextBudgetExceeded(phase=CORRECTION)` with no prompt and
performs no persistence or run transition in TASK-0010.

The narrow `ContextPacketStage` application seam owns two atomic initial
outcomes:

- On success, persist exactly one `ContextPacketRecord` and transition the run
  from `PERSISTED` to `CONTEXT_READY` in the same transaction.
- On initial mandatory-budget overflow, allocate one failure ID, persist exactly
  the specified terminal `SafeFailure` with that ID, the processing-run ID,
  `stage=CONTEXT`, and `error_code=CONTEXT_BUDGET_EXCEEDED`; transition the run
  from `PERSISTED` to `CONTROLLED_FAILURE` in the same transaction; and write no
  packet, retrieval, model, validation, correction, or assistant row.

Expected budget overflow is the typed `ContextBudgetExceeded` result, not an
exception. Invalid lineage, malformed upstream decisions, fingerprint
mismatch, inconsistent selected-memory input, and other contract violations
are programmer/configuration errors and must not be converted into that result.

## Required work

1. Change the current construction constant to v2 while accepting stored v1
   and v2 packet-policy identities through explicit version dispatch. Retain
   packet schema v2 and every existing immutable packet field.
2. Implement the pure canonical-rule-to-semantic-instruction mapping and the
   closed validation-semantics projection exactly as contracted. Reject a
   malformed/unsupported canonical form rather than reparsing source evidence.
3. Implement the exact v2 renderer bytes and make semantic bytes participate in
   `conservative_utf8_v1`, mandatory budgeting, full-rerender tail pruning,
   omission accounting, and correction rendering. Retain the exact v1 renderer
   only for historical packets and reject cross-version or unknown dispatch.
4. Preserve the existing `ContextPacketBuilder` and `ContextPacketStage`
   boundaries and atomic outcomes. New packets record v2; no packet update,
   historical rewrite, provider call, or schema migration is added.
5. Update direct builder/renderer and temporary-SQLite fixtures to demonstrate
   every revised AT-009 assertion, including exact v2 bytes and historical v1
   compatibility.

## Boundaries

- Do not interpret messages, resolve references/constraints, select memories,
  rerank retrieval, or call TASK-0007 through TASK-0009 components.
- Do not call a model/provider, validate candidate output, control correction
  attempts, create model/validation/correction/assistant rows, or orchestrate
  later processing-run states.
- Do not change TASK-0013 candidate normalization, predicate parsing, matching,
  violation, warning, score, or correction-control behavior.
- Do not read provider settings beyond the scalar budget values already in the
  build request; do not add model-name, base-URL, temperature, gateway, or
  tokenizer-service coupling.
- Do not expose or persist rendered prompts in the UI, logs, database, events,
  or diagnostics.
- Do not add streaming, embeddings, compression models, automatic context
  summaries, lossy evidence projection, or configurable rendering grammar.
- Do not implement any TASK-0011-or-later behavior.

## Verification

- Exercise the public builder and renderer seams directly with fixed immutable
  fixtures; no provider mock or broader pipeline service is required.
- Cover complete, optional-tail-pruned, initial impossible-budget, correction,
  correction-overflow, delimiter-injection, and repeated-render determinism
  cases, including every semantic template, validation-semantics shape, exact
  estimator vectors, and byte-for-byte v2 prompt assertions.
- Prove a historical v1 packet renders only exact v1 bytes and remains
  unchanged; prove new-build v1 selection, cross-version rendering, and unknown
  versions are rejected.
- Verify packet evidence remains complete and unchanged across render omission
  and correction attempts; verify cross-packet/out-of-limit correction input is
  rejected and correction results report only additional omissions.
- Use temporary SQLite to prove the success and initial-overflow writes and run
  transitions are atomic, including induced rollback.
- Run all current tests plus syntax/import validation during implementation.

## Exit criteria

- `REQUIREMENTS.md`, `ContextPacket.md`, TASK-0010, AT-009, persistence, and the
  deferred register agree on the public seams, semantic projections, versions,
  grammar, estimator, pruning, overflow, and historical behavior.
- D-008 and the TASK-0010 portion of D-014 are resolved without assigning
  provider, validator, correction-controller, or later orchestration work to
  this task.
- Packets are immutable and versioned, retain complete required evidence, and
  are persisted only by the specified atomic success path.
- Original request text, active hard constraints, true conditional hard
  constraints, and override evidence are never silently dropped.
- Every new trusted prompt exposes the pass-critical production semantics, and
  no validator or TASK-0018-specific exception is introduced.
- Every AT-009 assertion passes and all implementation verification is green.
