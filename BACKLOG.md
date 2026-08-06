# Context for AI — MVP Backlog

Tasks are strictly ordered. A task becomes `Ready` only when all predecessors
are `Done` and their documented verification is green.

TASK-0014 owns global (not per-conversation) message admission, the separate
one-shot foreground recovery entry, AT-002 through the public use case, full
AT-012 orchestration, and AT-015. TASK-0013 retains only its documented
validator/correction component portion of AT-012.

| Task | Title | Depends on | Status |
|---|---|---|---|
| TASK-0001 | Repository foundation | None | Ready |
| TASK-0002 | Canonical domain primitives and policies | TASK-0001 | Blocked |
| TASK-0003 | Inward ports and composition contracts | TASK-0002 | Blocked |
| TASK-0004 | Canonical SQLite migrations | TASK-0003 | Blocked |
| TASK-0005 | SQLite repositories and lifecycle persistence | TASK-0004 | Blocked |
| TASK-0006 | Versioned conversation state | TASK-0005 | Blocked |
| TASK-0007 | Deterministic interpretation and constraints | TASK-0006 | Blocked |
| TASK-0008 | Entity registry and reference resolution | TASK-0007 | Blocked |
| TASK-0009 | Manual memory lifecycle and deterministic retrieval | TASK-0008 | Blocked |
| TASK-0010 | Immutable context packet and prompt rendering | TASK-0009 | Blocked |
| TASK-0011 | Model gateway and deterministic mock provider | TASK-0010 | Blocked |
| TASK-0012 | Buffered local Ollama provider | TASK-0011 | Blocked |
| TASK-0013 | Deterministic validation and bounded correction | TASK-0012 | Blocked |
| TASK-0014 | Complete idempotent backend pipeline | TASK-0013 | Blocked |
| TASK-0015 | Responsive PySide6/QML application shell | TASK-0014 | Blocked |
| TASK-0016 | Context inspection UI | TASK-0015 | Blocked |
| TASK-0017 | Manual memory, project, validation, and settings UI | TASK-0016 | Blocked |
| TASK-0018 | Local Ollama smoke acceptance | TASK-0017 | Blocked |
