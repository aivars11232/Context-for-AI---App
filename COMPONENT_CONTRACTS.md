# Context for AI — Component Contracts

Detailed contracts are stored under `docs/contracts/`. Together with those
documents, this index is authoritative for component ownership after the root
scope, requirements, architecture, and schema documents.

| Component | Owns | Must not own |
|---|---|---|
| ProcessUserMessage | Idempotent pipeline orchestration and lifecycle transitions | Context rules, SQL, provider-specific calls |
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
| TraceLogger | Redacted structured stage trace events | Raw message/prompt/response logging, domain policy decisions |
| Repository implementations | Persistence mechanics | Domain policy decisions |
| Presentation layer | Display and user actions | Context intelligence rules |
