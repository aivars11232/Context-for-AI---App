# TASK-0016 — Context Inspection UI

Status: Specification reconciled; implementation blocked by TASK-0015 implementation and exit criteria

## Goal

Implement the required context-inspection view using persisted, observable data
from application use cases.

## Sources

- `REQUIREMENTS.md` FR-015
- `MVP_SCOPE.md`
- `ACCEPTANCE_TESTS.md` AT-013
- `ARCHITECTURE.md`
- `COMPONENT_CONTRACTS.md`
- `docs/contracts/ContextInspection.md` (normative detailed contract)
- `docs/contracts/PresentationShell.md`
- `docs/contracts/Persistence.md`

## Required work

1. Implement the closed `InspectContext` request/result/view algebra in
   `ContextInspection.md`, including latest-run target selection, historical
   semantics, deterministic ordering/formatting, field availability, strict
   safe projection, and whole-load failure behavior.
2. Extend the existing shell to the exact `{CHAT, CONTEXT_INSPECTION}` route set
   without changing the initial `CHAT` route or TASK-0015 chat behavior. Keep the
   existing `ShellFacade` as the sole QML-facing QObject/state owner.
3. Add the finite read-only inspection scope/worker, queued immutable delivery,
   generation matching, single coalesced refresh, and asynchronous joint
   shutdown behavior. Keep every SQLite object on the inspection thread and
   separate from the foreground scope.
4. Implement every contracted page state, transition, refresh/invalidation
   trigger, stale-data rule, safe field/list model, and exact availability text.
5. Implement the native Qt accessibility IDs, names, roles, list/scalar
   templates, state text, and polite revision-driven announcements.
6. Add the deterministic application, persistence, facade, offscreen QML,
   responsiveness, threading, redaction-sentinel, and accessibility coverage in
   the TASK-0016 portion of AT-013.

## Boundaries

- Do not add file context, embeddings, vector search, provider configuration,
  automatic memory edits, or direct SQL/model calls in UI.
- Do not turn inspection into a local HTTP API.
- Do not add a database migration: use the existing durable projections and the
  contract's explicit availability semantics.
- Do not expose rendered prompts, invalid candidates, provider metadata, unsafe
  details, raw validation structures, hidden IDs, or persistence/domain objects.
- Do not create a second public facade/controller, generic queue, persistent
  worker, polling/trace refresh, shared SQLite connection, or force termination.

## Verification

- Run focused `InspectContext` target/aggregation/availability/redaction tests
  against isolated deterministic SQLite fixtures.
- Run facade/worker tests proving coalescing, stale-result rejection, queued GUI
  delivery, GUI responsiveness, same-thread connection ownership, coexistence
  with foreground processing, and shutdown cleanup.
- Run packaged offscreen-QML and Qt accessibility-interface tests for every
  AT-013 field, page state, accessible identity, and exact announcement.
- Run application-startup validation and the complete then-current non-live
  suite; no live Ollama daemon, screen reader, KDE service, or KWin rule is a
  prerequisite.

## Exit criteria

- The user can inspect every required context decision and safe final status.
- Every unavailable historical field is explicit; no current-state inference or
  unsafe value reaches QML/accessibility output.
- Inspection remains responsive, uses only application-facing safe data, and
  preserves all TASK-0015 shell behavior.
- Every deterministic invariant in `ContextInspection.md` and both ownership
  portions of AT-013 are green.
