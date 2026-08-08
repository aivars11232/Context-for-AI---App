# Context for AI — Component Contracts

Detailed contracts are stored under `docs/contracts/`. Together with those
documents, this index is authoritative for component ownership after the root
scope, requirements, architecture, and schema documents.

| Component | Owns | Must not own |
|---|---|---|
| PrepareApplicationShell | One pre-QML recovery preflight and deterministic initial-conversation selection/first-run creation | Recovery classification/resumption, UI state, worker creation, polling |
| ProcessUserMessage | Idempotent pipeline orchestration and lifecycle transitions | Context rules, SQL, provider-specific calls |
| RecoverProcessingRun | One-shot foreground startup recovery of the sole global non-terminal run | Polling, queues, daemon work, uncertain-call retry |
| InspectContext | One-snapshot selection and safe historical aggregation of the latest accepted run for one conversation | Writes, current-state substitution, decision re-execution, raw/open DTO exposure |
| LoadInitialUiPreferences | One pre-QML validation/default read of all three permitted SQLite preferences, returning only startup theme/context values | Writes, conversation selection, raw last-conversation UUID presentation, configuration/YAML override, Qt calls |
| InspectMemories | One-evaluated-at stored-status query and closed complete memory/provenance/revision projection | Writes, expiry mutation, automatic lifecycle action, raw persistence DTO exposure |
| CreateMemoryWithGuidance | Creation validation, same-scope/owner normalized advisory comparison, and an explicitly authorized independent create | Merge/replace/delete of a candidate, automatic mutation, presentation confirmation |
| Memory presentation mutation adapters | Expected-revision edit/soft-delete orchestration and one post-commit redacted trace event | Domain lifecycle reinvention, QML trace emission, restore, automatic retry |
| InspectProjects | One-snapshot active/archived/current-association safe project projection | Selection/archive writes, inferred eligibility authority, raw IDs in presentation |
| Project presentation mutation adapters | Safe versioned select/clear and guarded archive orchestration over existing project use cases | Domain transition reinvention, archive cascade, raw project/state DTO exposure |
| InspectValidationHistory | Same latest-run target as `InspectContext` and every ordered safe request/validation/correction/failure projection | Prompt/candidate/provider/raw-validation exposure, writes, selected-run UI |
| InspectManualSettings | Validated defaults plus the closed safe configuration/origin/fingerprint view | YAML/source dump, path/endpoint/secret exposure, writes |
| UpdateManualSettings | Atomic update of changed directly editable UI preferences | Last-conversation ownership, YAML/configuration edits, GUI/theme calls |
| ConversationStateManager | Deterministic active-state transitions | Model calls, UI rendering |
| InterpretationEngine | Intent, topic, qualifier, output-type interpretation | Persistence, response generation |
| ReferenceResolver | Mention-to-entity resolution | Memory mutation, model generation |
| ConstraintEngine | Constraint extraction, normalization, priority, conflict detection | UI, provider calls |
| ContextRetriever | Deterministic selection and scoring of relevant memories | Memory creation, model calls |
| ContextPacketBuilder | Immutable structured packet assembly | Retrieval decisions, provider calls |
| ClarificationBuilder | One deterministic safe question and durable payload from a canonical clarification reason | Model calls, free-form question generation |
| ModelGateway | Inward-facing buffered text-generation interface | Context interpretation, SQL, routing, streaming, retries |
| ResponseValidator | Deterministic validation report | Response persistence, unbounded retry |
| CorrectionController | Maximum-two revision control and controlled exhaustion | Infinite loops, hidden requirement changes |
| MemoryManager | Explicit-user-operation, provenance-preserving memory CRUD | Silent autonomous creation, rewriting, merging, or deletion |
| ConversationProjectManager | Explicit conversation/project/named-item lifecycle operations | Hidden active-project state or automatic entity extraction |
| ConfigurationLoader | Validated local YAML configuration and precedence | UI settings overrides, remote configuration, secret logging |
| TraceLogger | `emit(TraceEvent)` for redacted structured stage/recovery events | Alternate ambient-correlation APIs, raw message/prompt/response logging, domain policy decisions |
| TransactionBoundary | One connection-local re-entrant transaction whose nested users join the outer commit/rollback | Cross-thread contexts, independent nested commits, provider calls inside a transaction |
| Repository implementations | Persistence mechanics | Domain policy decisions |
| ShellApplicationScopeFactory | Calling-thread construction and same-thread disposal of startup, foreground, inspection, and manual-operation application scopes and their separate SQLite graphs | Shared/cross-thread connections, queues, service location from QML |
| IdempotencyKeyFactory | One caller-owned UUID for each controller-accepted submission | Run admission, persistence, duplicate classification, recovery IDs |
| StartupErrorPresenter | One safe stderr presentation and, for interactive desktop mode, one entry-point-owned native non-QML modal | Raw diagnostics, QML fallback, recovery-result presentation |
| ForegroundRunController | Private execution role of `ShellFacade`: one ephemeral worker/token, duplicate suppression, cancellation/shutdown, queued terminal handoff | A second public controller/state store, application decisions, SQL, provider calls, trace-derived progress, force termination |
| InspectionQueryController | Private execution role of `ShellFacade`: one finite read-only worker, generation matching, one coalesced refresh, queued safe-result handoff | A second public controller/state store, a queue/poller/persistent worker, processing-run admission, shared SQLite objects |
| ManualOperationsController | Private execution role of `ShellFacade`: at most one finite TASK-0017 operation, one replaceable coalesced read route, confirmations, generation matching, queued safe-result handoff | A second public controller/state store, presentation-side mutation queue/retry, poller/persistent worker, shared SQLite objects, application/domain decisions |
| ShellFacade | The one entry-point-owned GUI QObject, closed GUI/page state, safe result projection, and exact post-TASK-0017 `{CHAT, CONTEXT_INSPECTION, MEMORY, PROJECTS, VALIDATION_HISTORY, SETTINGS}` route set | QML-owned lifetime, raw application DTO branching in QML, diagnostics, deferred-page placeholders |
| Presentation layer | Display and explicit user actions through application interfaces | Context intelligence rules, SQL, provider/Ollama access |

The exact TASK-0015 interfaces, state machine, startup/error behavior, scope
lifetime, responsiveness, result projection, route ownership, and QML packaging
rules are normative in `docs/contracts/PresentationShell.md`.

The TASK-0016 inspection target, safe result algebra, availability, worker and
refresh semantics, accessibility, and extension to the shell are normative in
`docs/contracts/ContextInspection.md`.

The TASK-0017 route/page algebras, finite operation scope, safe memory/project/
validation/settings models, mutation/trace/confirmation behavior,
configuration/theme boundary, accessibility, and additive shell integration are
normative in `docs/contracts/ManualOperationsUI.md`.
