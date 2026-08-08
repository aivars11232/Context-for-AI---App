# TASK-0015 — Responsive PySide6/QML Application Shell

Status: Specification reconciled; execution blocked until TASK-0014 exit
criteria and final public interfaces are implemented and green.

## Goal

Implement the minimum desktop shell that presents the complete use case without
blocking the QML UI thread.

## Sources

- `ARCHITECTURE.md`
- `COMPONENT_CONTRACTS.md`
- `docs/contracts/ProcessUserMessage.md`
- `docs/contracts/Persistence.md`
- `docs/contracts/ConfigurationAndLogging.md`
- `docs/contracts/PresentationShell.md`
- `REQUIREMENTS.md` NFR-008
- `ACCEPTANCE_TESTS.md` AT-001 and AT-013

## Required work

1. Deliver only the contracted `CHAT` shell, exact-text chat input/output,
   startup/preflight/first-conversation flow, non-QML startup errors, and the
   closed `ShellFacade` state machine in `PresentationShell.md`.
2. Consume the final TASK-0014 `ProcessUserMessage` and
   `RecoverProcessingRun` interfaces unchanged through worker-owned application
   scopes, with one ephemeral foreground execution at a time.
3. Satisfy the exact progress, cancellation, duplicate suppression, safe-result
   projection, queued delivery, SQLite-thread ownership, late-signal, shutdown,
   and disposal contracts.
4. Package/load the root and every nested QML asset through the canonical
   package-resource boundary.
5. Provide the TASK-0015-owned AT-001 shell/startup-error assertions and AT-013
   shell-responsiveness assertions. Full AT-013 page acceptance remains with its
   later owner.

## Boundaries

- No API server, persistent worker, streaming tokens, provider routing, or
  direct QML-to-SQL/Ollama call.
- No direct QML application-DTO branching, trace-derived progress, queue,
  polling, forced thread termination, or cross-thread SQLite object.
- Do not register, display, or create placeholders for detailed context, memory,
  project, conversation-management, validation, or settings pages until their
  later owners.
- Do not redesign the TASK-0014 result algebra, transaction order, cancellation
  checkpoints, or recovery matrix.

## Verification

- Run the offscreen UI assertions and complete mock-provider pipeline tests
  required by the owning contracts.
- Demonstrate the TASK-0015 AT-001 startup/error/packaging portion and AT-013
  responsiveness portion without claiming the deferred context page.
- Run all then-current tests, application-startup validation, and installed-
  package QML loading validation.

## Exit criteria

- A pending model request cannot freeze the QML event loop.
- UI displays only validated final text or safe typed outcomes.
- No-recovery startup and invalid/duplicate actions start no foreground worker.
- Every foreground SQLite connection and repository stays on its one worker
  thread and closes before immutable terminal delivery.
- Shutdown/cancellation never blocks the GUI thread or force-terminates work.
- All verification is green.
