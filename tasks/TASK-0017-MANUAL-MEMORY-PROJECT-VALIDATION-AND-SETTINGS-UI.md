# TASK-0017 — Manual Memory, Project, Validation, and Settings UI

Specification status: Reconciled; all TASK-0017 specification gates are closed.

Implementation status: Blocked by TASK-0016 and its prerequisite chain. No
TASK-0017 implementation is complete or authorized by this status distinction.

## Goal

Expose the four remaining bounded MVP manual-operation areas through the one
existing shell facade and presentation-safe application use cases, without
weakening memory, archive, validation-before-display, configuration, threading,
or persistence safety.

## Authoritative sources

- `MVP_SCOPE.md`
- `REQUIREMENTS.md` FR-003 and FR-014 through FR-018, plus NFR-008
- `ARCHITECTURE.md`
- `docs/contracts/ManualOperationsUI.md` — canonical detailed TASK-0017 contract
- `docs/contracts/PresentationShell.md`
- `docs/contracts/ContextInspection.md`
- `docs/contracts/DomainAndDecisionRules.md`
- `docs/contracts/ContextEngine.md`
- `docs/contracts/ConfigurationAndLogging.md`
- `docs/contracts/Persistence.md`
- `ACCEPTANCE_TESTS.md` AT-013 and complete AT-014

## Closed specification gates

| Gate | Closed decision |
|---|---|
| G17-01 | Add exactly `MEMORY`, `PROJECTS`, `VALIDATION_HISTORY`, and `SETTINGS` to the same `ShellFacade`; all page states/navigation/accessibility are closed. |
| G17-02 | One finite shared TASK-0017 operation worker/scope at a time, same-thread SQLite, one latest read coalescing value, suppressed mutations, queued immutable delivery, stale rejection, and asynchronous disposal. |
| G17-M01 | All-local stored-status memory inspection with Active default, computed Expired, complete safe provenance/revisions, deterministic order/selection, and no inspection write. |
| G17-M02 | Closed create/edit/delete forms/results, exact soft-delete confirmation, expected-revision guard, post-success selection, and application-owned post-commit trace. |
| G17-M03 | Advisory creation-time same-scope/owner normalized duplicate guidance with Return/Create separate actions and no merge behavior/control. |
| G17-P01 | Safe active/archived project lists, versioned select/clear including existing bounded CAS retry, confirmed guarded archive, preservation, archived current association, and cross-page invalidation. |
| G17-V01 | Same latest-run target as TASK-0016, ordered full safe attempt/correction/failure history, and zero prompt/candidate/provider/raw-ID exposure. |
| G17-S01 | `SYSTEM`/`true`/null defaults; only theme/context directly editable; last-conversation UUID remains later conversation-selection ownership. |
| G17-S02 | Closed read-only configuration allowlist, per-field origin enum/label, complete 64-character fingerprint, and source/value redaction. |
| G17-S03 | Atomic settings persistence, immediate Qt `QStyleHints` color-scheme/context navigation apply, no normal restart, no YAML/KDE/KWin/style change. |
| G17-A01 | Deterministic fixed-fixture application/integration/offscreen/accessibility/startup/packaging/full-suite oracles in AT-014 with AT-013 regression. |

## Required implementation work

1. Implement only the routes, facade roles, page states/actions/models,
   application adapters/scopes, and packaged QML defined by
   `docs/contracts/ManualOperationsUI.md`.
2. Reuse existing memory/project/validation/settings/domain/repository use cases
   and rules; add only the presentation-safe aggregation/orchestration seams
   explicitly required by that contract.
3. Implement the bounded startup preference read, immutable configuration-origin
   metadata, Qt-native theme application, and post-commit manual-memory trace
   integration exactly at their owning boundaries.
4. Add the named deterministic TASK-0017 component/integration/offscreen tests
   needed to satisfy complete AT-014 and re-run both existing AT-013 passes.

## Boundaries

- No automatic memory extraction/creation/merge/rewrite/cleanup/expiry deletion,
  restore, hard delete, or merge button.
- No project creation or conversation-management UI in this task; no archive
  cascade or silent association clear.
- No prompt/candidate/response/provider/raw validation/failure/internal-ID
  presentation.
- No YAML/source configuration editing, model/storage/security/logging override,
  endpoint/model/credential/proxy/cloud control, or full configuration dump.
- No Qt Quick Controls style switching, KDE/Breeze/KWin integration, or native
  screen-reader test dependency.
- No API, queue, poller, persistent/background worker, daemon, detached task,
  timer refresh, cross-thread SQLite object, forced termination, or future-page
  placeholder.
- No database schema or migration change is assigned; the existing schema is
  sufficient.

## Implementation verification

- Run the complete TASK-0009 component and TASK-0017 application/integration/UI
  ownership portions of AT-014.
- Re-run both unchanged ownership portions of AT-013.
- Run source-checkout and installed-package QML/startup checks, native Qt
  accessibility/announcement tests, and the complete current non-live suite.
- Demonstrate GUI responsiveness, same-thread connection lifecycle, queued-only
  delivery, stale/mismatched rejection, asynchronous shutdown, safe redaction,
  archive preservation, settings/YAML boundaries, and exact memory trace events.

## Exit criteria

Specification readiness is complete now: no TASK-0017 specification gate
remains. Implementation readiness remains prerequisite-blocked until TASK-0016
is implemented with green exit criteria.

After that dependency clears, TASK-0017 is implementation-complete only when
all required work agrees with the canonical documents, complete AT-014 and both
AT-013 passes are green, the full current non-live suite passes, and no code or
runtime behavior outside this task's boundary was introduced.
