# TASK-0011 — Model Gateway and Deterministic Mock Provider

Status: Specification reconciled; implementation blocked until TASK-0010 exit
criteria pass

## Goal

Implement the inward-facing buffered generation port and deterministic outward
test adapter needed for non-live gateway and pipeline tests, without adding an
Ollama transport, persistence orchestration, response validation, or UI
behavior.

## Sources

- `docs/contracts/ModelGateway.md`
- `docs/contracts/ContextPacket.md` (`PromptRenderResult` handoff only)
- `docs/contracts/ProcessUserMessage.md` (outcome-mapping ownership only)
- `docs/contracts/Persistence.md` (existing lifecycle ownership/invariants only)
- `ARCHITECTURE.md`
- `ACCEPTANCE_TESTS.md` AT-010 TASK-0011 component pass

## Reconciled TASK-0011 contract

### TASK-0010 dependency and handoff

TASK-0011 consumes no packet builder, renderer, context policy, or
`ContextBudgetExceeded` behavior. The successful producer object is exactly
TASK-0010's `PromptRenderResult`. The application caller constructs one
`GenerationRequest` by copying `rendered_prompt` byte-for-byte and
`context_packet_id` unchanged. Attempt `0` is the initial render; correction
attempt `1` or `2` comes from the already-validated caller-held
`CorrectionEnvelope`.

The gateway receives only the prompt string and provider-independent request
fields. It receives neither `ContextPacket` nor `PromptRenderResult`, and it
never parses, normalizes, mutates, or re-renders the prompt. A
`ContextBudgetExceeded` outcome never calls the gateway.

Direct TASK-0011 tests may construct a fixed `GenerationRequest` compatible with
that handoff; they do not implement or substitute for TASK-0010. Execution of
this task remains blocked until TASK-0010's implementation and exit criteria are
complete.

### Gateway request and returned outcomes

The public gateway request is the immutable `GenerationRequest` defined by the
Model Gateway contract: configured model name, exact rendered prompt, validated
`GenerationSettings`, processing-run ID, packet ID, request ID, and attempt
number. Those four correlation values are caller-owned and are never allocated
or changed by the gateway.

`ModelGateway.generate` returns exactly one immutable value:

```text
GenerationOutcome =
    CompletedGeneration
  | ProviderUnavailableFailure
  | ModelNotFoundFailure
  | ModelTimeoutFailure
  | ModelCancelledFailure
  | InvalidProviderResponseFailure
```

The five failure variants are returned results, not exceptions. Expected
provider conditions never escape as provider-specific exceptions. Invalid
caller/programmer invariants and invalid test fixtures remain exceptional and
are not transport outcomes.

The existing preliminary `ProviderUnavailableError`, `ModelNotFoundError`,
`ModelTimeoutError`, `ModelCancelledError`, and
`InvalidProviderResponseError` exception-shaped port vocabulary is superseded
by this returned-value contract and must not remain as a second public failure
path.

### Safe failure mapping and persistence ownership

The exact diagnostic code, safe message, request status, run status, canonical
`FailureCode`, and absence-of-response rules are the authoritative table in
`docs/contracts/ModelGateway.md`. In summary:

- provider unavailable, model not found, and invalid provider response map to
  request `FAILED` and run `FAILED`;
- timeout maps to request `TIMED_OUT` and run `FAILED`;
- gateway-observed cancellation maps to request `CANCELLED`, run `CANCELLED`,
  and `MODEL_CANCELLED`; and
- `CANCELLED_BY_USER` is reserved for cancellation completed before a request
  enters the gateway.

The fixed messages and codes belong to the failure result types. Fixtures and
providers cannot replace them with raw error text. An unclassified provider or
transport exception before a valid complete response normalizes to
`ProviderUnavailableFailure`.

TASK-0011 defines and tests the typed persistence inputs and mapping only. The
gateway and mock perform no database operation. Application orchestration later
owns terminal request/run updates, `SafeFailure` creation, candidate persistence,
and validation under the existing transaction contract.

### Deterministic `MockModelProvider`

`MockModelProvider` is a test/evaluation-layer adapter, not production
infrastructure. Its implementation belongs in
`tests/fixtures/model_gateway.py`; versioned synthetic data belongs under
`tests/fixtures/mock_model_provider/`. It is injected through `ModelGateway` and
does not add `MOCK` to runtime provider configuration or `ProviderKind`.

The mock consumes an immutable ordered `mock-model-provider-v1` script. Each
step contains an exact expected `GenerationRequest`, an `IMMEDIATE` or `HELD`
checkpoint, and one explicitly supplied terminal success or non-cancellation
failure. Script selection is only by zero-based call order; exact request
matching is an assertion after selection and never routing.

The required scripted outcomes are complete success, provider unavailable,
model not found (the task's “unavailable model”), timeout, and invalid provider
response. Cancellation is token-driven rather than an artificial fixture
failure: pre-call cancellation consumes no step; cancellation after reserving a
held step consumes that step and wins before its terminal outcome.

Repeated calls consume successive steps with no implicit repeat, retry, cycle,
fallback, prompt selection, or model selection. Malformed fixtures, mismatched
requests, and exhaustion are deterministic fixture errors, not gateway
outcomes. The mock exposes an immutable ordered call snapshot containing exact
requests and returned outcomes and never retains the mutable token.

Success fixtures explicitly provide the complete text, recursively immutable
safe metadata, exact elapsed duration, and exact token usage or null. The mock
never measures or infers those values and uses no clock, randomness, network,
configuration discovery, persistence, trace logger, response validator, QML
object, or real sleep.

### Cancellation and complete buffering

The foreground request owner owns the concrete monotonic thread-safe token; the
gateway observes but never resets it. Tests own a deterministic test token. The
token is Qt-independent and ephemeral, and cancellation never force-terminates
a worker.

Cancellation is checked on gateway entry, whenever a wait/checkpoint resumes,
and immediately before a terminal outcome becomes observable. If cancellation
and timeout or another outcome are observable at the same checkpoint,
cancellation wins. A returned terminal outcome is final.

A held mock step is the component-level buffering oracle. While held, the call
has not returned, the mock has no terminal call record, and the consumer has no
response text or result. Release produces exactly one complete result; failure
or cancellation produces exactly one typed failure with no response/partial
text. The public port additionally exposes no content callback, iterator,
generator, signal, progress-text payload, or partial result. A structural
no-`stream` assertion alone is insufficient.

### AT-010 and composition ownership

TASK-0011 owns only the AT-010 component pass:

- deterministic gateway success/failure values and safe mappings;
- pre-call and held-checkpoint cancellation precedence;
- complete-output-only behavior at the gateway boundary;
- exact preservation of request correlation and persistence-input fields;
- immutable mock call observations and deterministic script behavior;
- test composition injecting the mock through `SystemPorts.model_gateway`; and
- static absolute/relative import isolation proving domain/application code has
  no concrete provider import, context-engine code has no gateway dependency,
  and presentation/QML depends only on application use-case interfaces.

TASK-0011 does not persist model requests/responses/failures, emit application
trace events, validate a candidate, implement a pipeline, construct QML output,
or test UI behavior. Those integrated AT-010 assertions are not TASK-0011 exit
criteria.

TASK-0011 does not finish the production composition root. Tests construct the
mock at their outer composition boundary. TASK-0012 remains responsible for the
Ollama transport adapter and its later construction at the production
composition boundary using the same inward port. There is no runtime provider
registry, per-request selection, routing, or fallback.

## Required work

1. Reconcile the existing port implementation to the exact immutable request,
   completed result, five typed returned failure results, exhaustive
   `GenerationOutcome`, cancellation token, correlation, and safe-message/code
   contracts above.
2. Implement the testing-layer `MockModelProvider`, immutable script/step/call
   records, deterministic held checkpoint, fixed success metadata, request
   matching, consumption, repetition, and exhaustion behavior.
3. Preserve the existing `SystemPorts.model_gateway` injection seam and add only
   mock test composition; do not complete production composition.
4. Strengthen static import checks to cover absolute and relative imports and
   prove the exact domain/application/context-engine/presentation boundaries
   above.
5. Add deterministic component/contract tests for the complete AT-010
   TASK-0011 pass, including non-tautological buffering and cancellation
   assertions.

## Boundaries

- Do not implement or import the TASK-0010 builder/renderer; consume only its
  documented successful handoff shape.
- Do not implement the Ollama transport or a production provider placeholder.
- Do not stream partial text, retry transport, route/fallback models, call tools,
  use cloud providers, or execute actions.
- Do not persist lifecycle state, emit application trace events, validate
  response content, implement broader pipeline orchestration, or change QML/UI
  behavior.
- Do not add a runtime mock provider kind, provider registry, configuration
  selector, or test-only branch to production code.

## Verification

- Exercise every `GenerationOutcome` variant with fixed immutable inputs and
  exact safe mapping assertions.
- Prove script matching, ordered consumption, repeated calls, exhaustion,
  immutable call records, fixed metadata/token values, and fresh-instance
  determinism.
- Prove pre-call cancellation does not consume a step and held-checkpoint
  cancellation consumes the reserved step and wins over its terminal outcome.
- Hold a successful step to prove no result/text is observable before release,
  then assert one byte-exact complete result; assert every failure exposes zero
  partial/complete text.
- Verify all request correlation and persistence-input values are preserved
  without performing persistence or trace emission.
- Run focused gateway/mock/import-boundary tests, all current tests, and
  syntax/import validation.

## Exit criteria

- TASK-0010's implementation and exit criteria have passed before TASK-0011
  implementation starts.
- The public gateway has one exhaustive returned-value contract with no parallel
  expected-failure exception path.
- Safe codes/messages and lifecycle mappings exactly match the Model Gateway
  contract, and provider-originated raw details cannot cross the port.
- Mock generation is deterministic, complete-output-only, outward of the port,
  and covers every required success/failure/cancellation outcome.
- Cancellation and full buffering pass the deterministic held-checkpoint
  assertions without sleeps or forced thread termination.
- Test composition and import isolation preserve the existing dependency
  direction; no Ollama implementation exists in this task.
- Every TASK-0011 component assertion in AT-010 and all implementation
  verification are green.
