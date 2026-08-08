# TASK-0018 — Local Ollama Smoke Acceptance

Specification status: Reconciled; G18-01, G18-02, and G18-03 are closed.

Implementation/acceptance status: Blocked by TASK-0017 and its prerequisite
chain. AT-016 has not been implemented or executed by this reconciliation.

## Goal

Implement, run, and record the sole explicitly opted-in live-model acceptance
criterion after the complete deterministic and UI acceptance chain is green.

## Authoritative sources

- `ACCEPTANCE_TESTS.md` AT-016 — canonical detailed fixture, oracle, execution,
  artifact, and retention contract
- `docs/contracts/OllamaAdapter.md`
- `docs/contracts/ModelGateway.md`
- `docs/contracts/ConfigurationAndLogging.md`
- `docs/contracts/DomainAndDecisionRules.md`
- `docs/contracts/ContextPacket.md`
- `docs/contracts/ResponseValidation.md`
- `docs/contracts/ProcessUserMessage.md`
- `docs/contracts/Persistence.md`
- `docs/contracts/PresentationShell.md`
- `DEFINITION_OF_DONE.md`

## Closed specification gates

| Gate | Closed decision |
|---|---|
| G18-01 | AT-016 owns an independent six-file synthetic fixture at `tests/fixtures/at_016_local_ollama_smoke/`, version `at-016-local-ollama-smoke-v1`. AT-016 fixes the fixture deltas, empty initial state, exact user message, deterministic interpretation/packet expectations, normal validation predicate, private bounded sentinel assertion, and zero-revision one-generation oracle in `ACCEPTANCE_TESTS.md`. |
| G18-02 | The testing/evaluation harness owns one standalone local JSON artifact per exact-opt-in execution. The artifact is not an `evaluation_cases`/`evaluation_runs` record and is not owned by production code, SQLite, QML, or routine logging. Runtime evaluation persistence remains deferred consistently under D-009. |
| G18-03 | AT-016 closes the artifact field/schema version, safe failure vocabulary, canonical serialization, authoritative gateway timing projection, bounded OS metadata source, prohibited content, atomic unique publication, local-only handling, and operator-managed retention. No database schema or migration is required. |

The D-011 behavior is preserved: default execution excludes live tests; an
explicitly selected AT-016 with no opt-in flag is the sole environment-absence
skip; a present non-`1` flag fails; exact `1` requires the model-name override;
and every other configuration, preflight, execution, assertion, or evidence
failure fails rather than skipping.

## Canonical acceptance shape

- The fixture is an independent copy of complete fixture version
  `mvp-config-fixture-v2`, with only the exact deltas listed in AT-016. Its
  exact message is `Exactly answer CONTEXT_FOR_AI_SMOKE_OK.` and its correction
  limit is zero.
- The normal production validator must pass the derived
  `MUST_EXACTLY:ANSWER_CONTEXT_FOR_AI_SMOKE_OK` rule. The acceptance harness
  separately requires one identifier-bounded, case-sensitive sentinel
  occurrence in the privately buffered candidate. Candidate prose is otherwise
  not fixed, and no content is emitted as evidence.
- The complete real local composition performs one provider generation, durable
  lifecycle/lineage/trace work, and the QML-visible accepted-result assertion.
  No pull, alias discovery, cloud fallback, retry generation, or correction is
  part of the smoke.
- Each exact-opt-in execution attempts one closed
  `at-016-evidence-v1` artifact under `data/acceptance/at-016/`. The document
  contains only the allowlisted prerequisite statuses, result/failure code,
  fixture/schema identifiers, configuration/model/provider evidence, gateway
  elapsed microseconds, bounded OS triplet, timestamp, and fixed limitations
  defined in AT-016.
- The normal Definition-of-Done completion report references the artifact and
  prerequisite results. It does not replace, broaden, or duplicate the artifact
  schema.

## Required implementation work

1. After TASK-0017 is implemented with green exit criteria, add only the
   versioned AT-016 fixture, marked live acceptance harness, and testing-layer
   artifact writer/validator specified by AT-016.
2. Cover `data/acceptance/` with repository ignore rules before any live AT-016
   execution. Never commit, append to, overwrite, or automatically delete an
   evidence artifact.
3. Preserve the exact `CONTEXT_FOR_AI_RUN_OLLAMA` and
   `CONTEXT_FOR_AI__MODEL__NAME` gate behavior above; keep the base URL as the
   existing optional, validated numeric-loopback override.
4. Reuse the production composition, Ollama transport, response validation,
   persistence, lineage, trace, redaction, facade, and packaged QML path without
   adding a TASK-0018 production feature or weakening an assertion to obtain a
   live pass.
5. Record the final prerequisite commands/results and safe artifact reference
   in the normal completion report.

## Boundaries

- No application behavior, public API, QML surface, provider contract, normal
  validation behavior, correction behavior, routine log schema, or trace schema
  change is assigned.
- No `evaluation_cases` or `evaluation_runs` shape, repository, use case, row,
  schema migration, or general evaluation framework is assigned.
- No cloud fallback, model routing, streaming, model pull, alias discovery,
  external service, background processing, or non-loopback endpoint is allowed.
- No fixture prompt, sentinel, candidate/response/assistant text, provider
  payload, endpoint, secret, environment value, hostname, username, or
  machine-unique identifier may enter the standalone artifact or routine
  diagnostics.
- No application change may be made merely to make a live model pass, and MVP
  completion may not be claimed while a prerequisite or deterministic
  acceptance criterion is failing.

## Implementation verification

- Run the complete default/non-live suite and establish every AT-001 through
  AT-015 prerequisite in its required environment before starting AT-016.
- Verify absent, invalid, and exact-`1` opt-in branches, including the rule that
  only absent opt-in on explicit selection skips and writes no artifact.
- Run the explicitly selected AT-016 once against the named installed local
  model and verify the one-generation pipeline, persistence/lineage, trace and
  redaction assertions, QML result, and closed standalone artifact.
- Re-read the published JSON, validate its exact schema/canonical encoding and
  prohibited-content rules, confirm that no evaluation row was created, and
  reference the unique local artifact from the completion report.

## Exit criteria

Specification readiness is complete now: G18-01 through G18-03 have no
remaining ambiguity. Implementation readiness remains prerequisite-blocked
until TASK-0017 is implemented with green exit criteria.

After that dependency clears, TASK-0018 is complete only when the complete
default/non-live and AT-001-through-AT-015 prerequisites are green, one
exact-opt-in AT-016 execution passes against the named local model, its valid
standalone artifact is retained locally and referenced by the completion
report, and no code or runtime behavior outside this task boundary was added.
