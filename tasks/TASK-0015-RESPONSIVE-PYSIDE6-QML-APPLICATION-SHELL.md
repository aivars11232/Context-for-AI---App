# TASK-0015 — Responsive PySide6/QML Application Shell

Status: Blocked by TASK-0014

## Goal

Implement the minimum desktop shell that presents the complete use case without
blocking the QML UI thread.

## Sources

- `ARCHITECTURE.md`
- `docs/contracts/ProcessUserMessage.md`
- `REQUIREMENTS.md` NFR-008
- `ACCEPTANCE_TESTS.md` AT-001 and AT-013

## Required work

1. Implement QML application shell, chat input/output, navigation, startup
   error display, and application-use-case view models/controllers.
2. Dispatch a bounded foreground request task outside the QML UI thread and
   implement progress, cancellation, duplicate-submit disablement, and typed
   success/clarification/failure presentation.
3. Wire only application interfaces; keep QML free of context, SQL, and Ollama
   logic.
4. Add offscreen QML/UI tests for startup, responsive pending state,
   cancellation, duplicate submit, and safe terminal-status display.

## Boundaries

- No API server, persistent worker, streaming tokens, provider routing, or
  direct QML-to-SQL/Ollama call.
- Do not implement detailed context/memory/project/validation pages until later
  tasks.

## Verification

- Run offscreen UI tests and complete mock-provider pipeline tests.
- Demonstrate AT-001 startup and AT-013 responsiveness assertions.
- Run all current tests and application-startup validation.

## Exit criteria

- A pending model request cannot freeze the QML event loop.
- UI displays only validated final text or safe typed outcomes.
- All verification is green.
