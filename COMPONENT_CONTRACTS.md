# Context for AI — Component Contracts

Detailed contracts are stored under `docs/contracts/`. This index is authoritative for component ownership.

| Component | Owns | Must not own |
|---|---|---|
| ProcessUserMessage | Pipeline orchestration | Context rules, SQL, provider-specific calls |
| ConversationStateManager | Active state transitions | Model calls, UI rendering |
| InterpretationEngine | Intent, topic, qualifier, output-type interpretation | Persistence, response generation |
| ReferenceResolver | Mention-to-entity resolution | Memory mutation, model generation |
| ConstraintEngine | Constraint extraction, normalization, priority, conflict detection | UI, provider calls |
| ContextRetriever | Selection and scoring of relevant memories | Memory creation, model calls |
| ContextPacketBuilder | Immutable structured packet assembly | Retrieval decisions, provider calls |
| ModelGateway | Provider-independent generation interface | Context interpretation, SQL |
| ResponseValidator | Deterministic validation report | Response persistence, unbounded retry |
| CorrectionController | Maximum-two revision control | Infinite loops, hidden requirement changes |
| MemoryManager | Provenance-preserving memory CRUD | Silent autonomous rewriting |
| Repository implementations | Persistence mechanics | Domain policy decisions |
| Presentation layer | Display and user actions | Context intelligence rules |
