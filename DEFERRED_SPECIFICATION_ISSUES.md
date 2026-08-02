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
| D-006 | Correct `ModelGateway` ownership so it returns typed timeout/cancellation outcomes while application/repository code persists lifecycle state; define cancellation ownership during recovery. | `TASK-0011`, `TASK-0012` |
| D-007 | Update `docs/diagrams/SEQUENCES.md` for duplicate-key and Busy branches, clarification persistence, `PENDING` claim, context-stage state update, and recovery. | `TASK-0014` |
| D-008 | Define the fixed `prompt_policy_version`, versioning rule, and remaining nested context-packet evidence/retrieval/token-budget shapes. | `TASK-0010` |
| D-009 | Define evaluation-case and evaluation-run JSON shapes, category taxonomy, fixture linkage, expected observables, and repository/use-case boundary; alternatively defer runtime evaluation persistence consistently. | `TASK-0005`, `TASK-0018` |
| D-010 | Add exact acceptance assertions for required trace-event names, correlation fields, and redaction rather than merely claiming combined coverage. | `TASK-0014` |
| D-011 | Reconcile local-Ollama opt-in semantics in `TASK-0012` and `TASK-0018`: no flag skips; flag present makes invalid daemon/model/configuration a failed opt-in test. | `TASK-0018` |
| D-012 | Move full AT-012 ownership from `TASK-0013` to `TASK-0014`; keep Task 0013 limited to validator/correction-controller behavior. | `TASK-0013`, `TASK-0014` |
| D-013 | Narrow premature acceptance claims: Task 0009 may cover retrieval portions of AT-014 only; Task 0015 may cover responsiveness portions of AT-013 only; define whether memory history is inspectable only or supports an explicit restore operation. | `TASK-0009`, `TASK-0015`, `TASK-0017` |
| D-014 | Align detailed task scopes with the repaired contracts: Task 0002 enums/types; Task 0003 clarification/retrieval ports; Task 0004 schema additions/indexes; Task 0005 repositories/recovery; Task 0006 lifecycle; Tasks 0007–0010 deterministic contracts; Tasks 0011–0018 provider, pipeline, UI, and smoke criteria. | `TASK-0002` through `TASK-0018` |
| D-015 | Reconcile roadmap/backlog/implementation-plan wording with the global single-run admission rule, recovery matrix, clarification persistence, and task-stage acceptance ownership. | `TASK-0014` |

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
