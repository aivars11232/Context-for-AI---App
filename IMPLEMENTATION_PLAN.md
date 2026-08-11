# Context for AI — Implementation Plan

Implement one numbered task at a time. Do not begin a task until every earlier
task's exit criteria and relevant acceptance criteria pass. The detailed task
files under `tasks/` are mandatory delivery contracts; this plan is their
ordered summary.

## Stage 1 — Repository foundation (`TASK-0001`)

Create the Python packaging, validated six-file YAML bootstrap, logging
bootstrap, minimal QML startup boundary, and isolated test layout. `pyproject.toml`
is the sole dependency-management source of truth; do not add `requirements.txt`.

**Exit:** AT-001 startup/configuration behavior passes with fixtures.

## Stage 2 — Domain and ports (`TASK-0002`, `TASK-0003`)

Implement canonical value objects, enums, entities, typed errors, deterministic
policies, and inward repository/model/clock ports without imports from Qt,
SQLite, or Ollama.

**Exit:** domain/port unit tests pass; import-boundary checks pass.

## Stage 3 — SQLite schema and repositories (`TASK-0004`, `TASK-0005`)

Implement numbered migrations for the canonical schema, all required repository
ports, transaction helpers, state-version checks, idempotency storage, lineage,
and memory revision/provenance persistence.

**Exit:** isolated SQLite migration/repository integration tests pass,
including data-preservation, lifecycle, and FK behavior.

## Stage 4 — Deterministic context intelligence (`TASK-0006`–`TASK-0010`)

Implement state transitions, interpretation/qualifiers/constraints, reference
resolution, memory retrieval, and immutable packet rendering using the
canonical rules only.

**Exit:** AT-003 through AT-009 pass with deterministic fixtures.

## Stage 5 — Controlled model flow (`TASK-0011`–`TASK-0013`)

Implement the mock gateway, bounded foreground provider port, local Ollama
adapter, deterministic validation, and correction controller. No streaming,
routing, fallback, cloud provider, or transport retry is permitted.

**Exit:** AT-010 and AT-011 plus TASK-0013's bounded component portion of AT-012
pass, and TASK-0012's controlled-transport adapter tests pass in the default
suite. Full provider-facing AT-012 orchestration remains Stage 6 ownership.
Live adapter transport test definitions are included, but their execution is
separately marked and opt-in; it does not exercise or satisfy AT-016's complete
local-Ollama pipeline acceptance.

## Stage 6 — Complete mock-provider pipeline (`TASK-0014`)

Implement `ProcessUserMessage` with the documented persistence ordering,
transactions, exhaustive typed results, global single-run admission, one-shot
foreground recovery, concurrency handling, safe failures, and state updates.

**Exit:** AT-002, full AT-012, AT-015, and applicable AT-003–AT-011 assertions
pass through the public submission/recovery use cases with the mock provider.

## Stage 7 — Desktop MVP (`TASK-0015`–`TASK-0017`)

Implement the QML shell, bounded foreground request presentation, context
inspection, and explicit manual memory/project/validation/settings views.

TASK-0015 owns only the `CHAT` shell, startup/error/first-conversation flow,
worker-scoped foreground execution, safe typed presentation, recursive QML
packaging, and the shell-responsiveness portion of AT-013 under
`docs/contracts/PresentationShell.md`. The detailed context-inspection page and
other named views remain with their later owners; TASK-0015 creates no
placeholder routes for them.

TASK-0016's specification is reconciled and implementation-ready in
`docs/contracts/ContextInspection.md`, but implementation remains blocked until
TASK-0015 is implemented and its exit criteria pass. TASK-0016 then owns the
read-only latest-run `InspectContext` projection, the additive
`CONTEXT_INSPECTION` route on the same facade, one separate finite inspection
scope/worker, closed page/refresh/error states, native Qt accessibility, and the
context-page portion of AT-013. It owns no schema migration, processing write,
generic worker queue, or placeholder for another page.

TASK-0017's specification is reconciled and implementation-ready in specification
terms in `docs/contracts/ManualOperationsUI.md`, but implementation remains
blocked until TASK-0016 is implemented and its exit criteria pass. TASK-0017
then owns exactly the additive `MEMORY`, `PROJECTS`, `VALIDATION_HISTORY`, and
`SETTINGS` routes on the same facade; one finite shared manual-operation scope/
worker; safe memory/project/full-validation/settings projections; explicit
confirmed mutations and post-commit memory trace integration; advisory duplicate
guidance; permitted preference defaults/updates; immutable configuration origin/
fingerprint inspection; Qt-native immediate color-scheme application; and the
TASK-0017 portion of AT-014. It adds no schema migration, YAML editor, KDE/KWin
dependency, worker queue, or automatic memory behavior.

**Exit:** both ownership portions of AT-013 and the complete TASK-0009 plus
TASK-0017 ownership portions of AT-014 pass; packaged startup/accessibility and
the current non-live suite remain green; no UI thread blocking, hidden automatic
memory mutation, unsafe candidate/configuration exposure, or archive data loss
remains.

## Stage 8 — Local Ollama acceptance (`TASK-0018`)

Before TASK-0018 implementation continues or any live call begins, complete one
bounded predecessor-correction gate after TASK-0017:

1. Reopen only TASK-0010's prompt-rendering implementation boundary. Make
   `mvp-prompt-policy-v2` current for new packets, add the exact deterministic
   trusted validation/constraint semantic projections and byte-level grammar,
   include those bytes in existing budgeting/correction behavior, and retain
   exact version-dispatched v1 reading/rendering for historical packets.
2. Preserve packet schema v2, the existing SQLite schema, historical packet and
   model-request rows, and all TASK-0013 candidate normalization, predicate,
   match, report, score, and correction behavior. No migration or validator
   workaround is part of this correction.
3. Make the revised AT-009 and affected non-live regression suite green. Only
   then update TASK-0018's testing/evaluation harness to expect v2 and replace
   its private raw-output sentinel with the exact production
   `REQUIRED_CONSTRAINT` evidence assertion in AT-016.

After that gate and the full deterministic/UI prerequisite chain are green, run
the opt-in, reproducible local-Ollama smoke acceptance against the configured
local model and record only the contracted non-secret environment/model
metadata. TASK-0018 remains test/evaluation-only and owns no production repair.

**Exit:** revised AT-009 and every non-live prerequisite are green, then AT-016
passes through one normal production-validator success with no private
candidate oracle. A failed or unavailable live environment is reported, not
ignored.
