# TASK-0012 — Buffered Local Ollama Provider

Status: Specification reconciled; implementation blocked until TASK-0011 exit
criteria and the TASK-0011 component assertions in AT-010 pass

## Goal

Implement the sole MVP runtime provider: a fully buffered, fail-closed local-only
Ollama infrastructure adapter behind the final TASK-0011 gateway port.

## Sources

- `docs/contracts/ModelGateway.md`
- `docs/contracts/OllamaAdapter.md`
- `docs/contracts/ConfigurationAndLogging.md`
- `ARCHITECTURE.md`
- `REQUIREMENTS.md` FR-011, NFR-001, and NFR-003
- `ACCEPTANCE_TESTS.md` AT-010 TASK-0012 component extension
- `MVP_SCOPE.md`

## TASK-0011 prerequisite and handoff

TASK-0012 implementation must not begin until every TASK-0011 exit criterion and
the TASK-0011 component assertions in AT-010 pass. The prerequisite is the
implemented final gateway contract, not merely the existence of TASK-0011
specification text.

TASK-0012 consumes `GenerationRequest`, `GenerationSettings`,
`CancellationToken`, `GenerationOutcome`, the five canonical failure variants,
their fixed safe diagnostics, cancellation precedence, complete buffering, and
the application-owned lifecycle mapping exactly as defined by
`ModelGateway.md`. It must not redefine, extend, or duplicate that vocabulary,
the correlation set, the deterministic mock, or TASK-0011 implementation
decisions.

## Reconciled TASK-0012 contract

### Local-only execution

Static configuration accepts only the direct numeric-loopback HTTP endpoint, one
local model identity, and no API-key, authorization, proxy, cloud-provider,
fallback, or bypass field. The separately installed Ollama daemon must use its
native cloud-disable setting.

Before every prompt-bearing request, the adapter performs the uncached
`/api/version`, `/api/status`, and exact-model `/api/show` sequence in
`OllamaAdapter.md`. Generation proceeds only when the daemon is healthy,
`cloud.disabled` is exactly true with an approved native source, and the model
details have no remote marker. Missing or incompatible status capability fails
closed; there is no log, version, name-heuristic, or operator-assertion fallback.
Redirects, proxies, ambient authentication, non-loopback peers, model pull,
sign-in, and cloud/provider endpoints are prohibited.

### Health and model checks

Construction performs no network request. Health, local-only, and exact-model
checks run in the fixed order above for every non-pre-cancelled gateway call and
are never cached across calls. The first failed check stops the sequence and no
later request is sent.

The adapter is bound to the one normalized configured model. It normalizes only
an omitted tag to `:latest`, never resolves an alias or selects a model. A caller
model mismatch is the existing pre-network programming-invariant case. A show or
generate 404 is `ModelNotFoundFailure`; model disappearance after a successful
show is therefore handled by the generation 404 without retry. A terminal model
mismatch is `InvalidProviderResponseFailure`.

### Wire, buffering, timeout, cancellation, and metadata

Only the four native endpoints and exact request/envelope rules in
`OllamaAdapter.md` are permitted. `/api/generate` receives the rendered prompt
unchanged with `stream: false`, `raw: true`, `think: false`, `truncate: false`,
`shift: false`, and only the configured context-window and temperature options.
No streaming, tool, image, provider conversation, routing, or cloud field exists.

One monotonic absolute deadline covers all three preflight checks, generation,
complete body reads, envelope validation, and final cancellation observation.
Stages receive only the remaining budget. Cancellation is propagated while the
transport waits and wins over a simultaneous timeout or provider outcome. On
timeout or cancellation the request-scoped transport is aborted and closed, all
private buffered content is discarded, and no transport work continues after
the returned failure.

The adapter exposes content only through one complete `CompletedGeneration`.
Transport body fragments are private and are never gateway streaming. Timeout,
cancellation, failure, a non-terminal envelope, remote marker, model mismatch,
thinking/tool output, or malformed response exposes no partial or complete text.

Success returns only the exact normalized metadata allowlist and token mapping in
`OllamaAdapter.md`. Elapsed time comes from the adapter's monotonic whole-call
measurement, not an Ollama duration. Prompts, responses, partial content, raw
provider objects or exceptions, endpoints, headers, cookies, remote hosts,
authorization data, and secrets are never retained in metadata or routine logs.

### Ownership and composition

The adapter owns transport communication, ordered runtime checks, request-private
buffering, protocol-envelope validation, timeout/cancellation propagation,
provider error translation, metadata normalization, and construction of the
existing gateway outcome.

It owns no YAML discovery, persistence, application trace emission, request/run
lifecycle mutation, UI publication, prompt rendering, semantic response
validation, correction, application lifecycle orchestration, or Ollama daemon
lifecycle. It returns typed outcomes only; later application orchestration owns
the authoritative request/run mapping in `ModelGateway.md`.

TASK-0012 supplies the infrastructure adapter and test construction fixtures. It
does not finish or modify the complete production composition root. A later outer
production boundary constructs the adapter from the already validated immutable
endpoint and bound model identity and injects it into
`SystemPorts.model_gateway`. Per-call settings remain in `GenerationRequest`.
Domain, context-engine, application, presentation, and QML code do not import
Ollama infrastructure.

### Test separation

Required default-suite component tests construct the real adapter with validated
fixture configuration and a controlled transport. They require no daemon and
prove the complete AT-010 TASK-0012 extension, including a held partial HTTP body
that exposes no content before one terminal complete result. Broader application
and complete-pipeline tests continue to use the TASK-0011 deterministic mock.

The isolated marked test definitions and fixture are required TASK-0012 test
surface; contacting a live daemon is optional. Only those live tests are marked
`ollama`, and the default pytest selection excludes them. When explicitly
selected, an absent `CONTEXT_FOR_AI_RUN_OLLAMA` skips as environment absence; a
present value other than exactly `1` fails as an invalid opt-in; exact `1`
executes every preflight and assertion. Once opted in, invalid configuration,
non-local transport, cloud-disable failure, unavailable daemon, missing model,
timeout, malformed response, or assertion failure is a failure and may not
dynamically skip.

Marked live adapter test execution exercises only the adapter transport
contract. It does not run or satisfy AT-016's later full-pipeline acceptance and
does not import persistence, validation, correction, application-pipeline,
presentation, or QML components.

## Required work

1. Reconcile the existing model configuration implementation to the exact static
   validation and immutable handoff in `ConfigurationAndLogging.md`, without
   performing network I/O in the loader.
2. Implement the infrastructure Ollama adapter against the unchanged final
   TASK-0011 port and every normative local-only, wire, timeout, cancellation,
   buffering, failure, and metadata rule in `OllamaAdapter.md`.
3. Translate provider observations into the canonical returned
   `GenerationOutcome` values without retry. Do not map or persist request/run
   lifecycle state in the adapter.
4. Add the required default-suite controlled-transport component coverage and
   keep broader gateway/application tests on the deterministic mock.
5. Add isolated optional live transport tests under the exact marker and opt-in
   rules above, without expanding them into complete-pipeline acceptance.

## Boundaries

- Only one configured local Ollama model is permitted.
- No FastAPI, cloud URL or execution, API key, provider fallback, model routing,
  streaming, tools, image generation, provider pull, persistent adapter worker,
  queue, or background orchestration.
- Any request-scoped transport cancellation activity exists only inside the
  synchronous gateway invocation, is not independently scheduled work, and must
  terminate before `generate` returns.
- Do not implement full pipeline orchestration, persistence integration,
  semantic validation, correction, presentation, or QML behavior here.
- Do not implement or modify the complete production composition root.

## Verification

- Confirm the TASK-0011 prerequisite and component assertions are green before
  starting TASK-0012 implementation.
- Run the required controlled-transport adapter tests in the default suite and
  all existing mock-provider gateway/import-boundary tests.
- Prove that the default test command excludes `ollama` and performs no live
  daemon discovery or connection.
- Run optional marked live transport tests only under the explicit opt-in rules;
  record environment absence as a skip, never a pass.
- Run all current tests and syntax/import validation.

## Exit criteria

- The TASK-0011 implementation prerequisite is satisfied and its final gateway
  contract remains unchanged.
- Static configuration and runtime attestation fail closed against non-local or
  cloud execution before any prompt-bearing request.
- The adapter obeys the exact ordered checks, one-model wire contract, shared
  timeout, cancellation closure, complete-buffer-only rule, canonical failure
  translation, and metadata allowlist.
- Required daemon-free component coverage is green and the default suite remains
  independent of Ollama.
- Optional live test absence is reported accurately; any opted-in failure is not
  hidden or converted to a skip.
- Ownership/import boundaries remain intact and no production composition root,
  pipeline, persistence, validation, correction, or UI behavior is implemented.
- All required verification is green.
