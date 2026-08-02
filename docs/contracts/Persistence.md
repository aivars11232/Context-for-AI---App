# Persistence Contracts

Repositories expose domain objects and typed operations. Application and domain code must not depend on SQL rows.

Required repositories:
- ProjectRepository
- ConversationRepository
- MessageRepository
- ConversationStateRepository
- MemoryRepository
- ContextPacketRepository
- ModelCallRepository
- ValidationRepository
- EvaluationRepository

All multi-stage message processing writes must use an explicit transaction strategy. Exact original user text must be recoverable unchanged.
