# Model Gateway Contract

## Responsibility and ownership

`ModelGateway` is the inward-facing, provider-independent, fully buffered
text-generation port used by application orchestration. Its public vocabulary
belongs with the existing inward domain/application ports. Outward provider
adapters implement the port; neither the port nor an adapter persists lifecycle
state, emits application trace events, validates response content, or mutates a
context packet.

The application calls the gateway outside a database transaction and maps its
one returned outcome to later persistence and orchestration. Expected provider
and transport conditions are returned as typed values, never raised as expected
control-flow exceptions.

## TASK-0010 handoff

TASK-0010 produces exactly one successful prompt handoff object:
`PromptRenderResult`. The application caller constructs `GenerationRequest` by:

- copying `PromptRenderResult.rendered_prompt` byte-for-byte into
  `rendered_prompt`;
- copying `PromptRenderResult.context_packet_id` unchanged into
  `context_packet_id`;
- using attempt `0` for `render_kind=INITIAL`; and
- for `render_kind=CORRECTION`, using the attempt number already validated in
  the caller-held `CorrectionEnvelope`, which must be `1` or `2`.

The gateway receives the prompt string, not `ContextPacket`,
`PromptRenderResult`, rendering metadata, or a renderer. It treats initial and
correction prompts as opaque text and must not trim, normalize, prefix, suffix,
parse, reinterpret, or re-render them. `ContextBudgetExceeded` contains no
prompt and must never cause a gateway invocation.

This is a contract dependency. TASK-0011 fixtures may construct an exact
`GenerationRequest` directly; they do not implement or substitute for the
TASK-0010 builder or renderer.

## Public request

```text
GenerationSettings {
  context_window_tokens: integer >= 1024,
  request_timeout_seconds: integer 1..300,
  temperature: exact decimal 0.0..2.0
}

GenerationRequest {
  model_name: non-empty string,
  rendered_prompt: non-empty string copied verbatim from PromptRenderResult,
  settings: GenerationSettings,
  processing_run_id: uuid,
  context_packet_id: uuid,
  model_request_id: uuid,
  attempt_number: 0 | 1 | 2
}
```

The model name and generation settings come from the validated local YAML
configuration. `processing_run_id`, `context_packet_id`, `model_request_id`, and
`attempt_number` are the complete gateway correlation set; there is no separate
provider-owned trace ID. The gateway neither allocates nor changes them.

## Public outcome algebra

`ModelGateway.generate(request, cancellation_token)` returns exactly one member
of this exhaustive provider-independent sum:

```text
GenerationOutcome =
    CompletedGeneration
  | ProviderUnavailableFailure
  | ModelNotFoundFailure
  | ModelTimeoutFailure
  | ModelCancelledFailure
  | InvalidProviderResponseFailure

GenerationFailure =
    ProviderUnavailableFailure
  | ModelNotFoundFailure
  | ModelTimeoutFailure
  | ModelCancelledFailure
  | InvalidProviderResponseFailure
```

Every member is an immutable result value. The five failure variants are not
exceptions. A caller branches only on the returned type; no provider-specific
exception, status, payload, or message crosses the port.

Only malformed caller input, a violated programming invariant, or an invalid
test fixture may raise. Every provider-originated connectivity, timeout,
cancellation, model-availability, or response-envelope failure is normalized to
one of the five result variants. An unclassified provider/transport exception
before a valid complete response is safely normalized to
`ProviderUnavailableFailure`.

### Completed generation

```text
CompletedGeneration {
  response_text: non-empty, non-whitespace complete string,
  provider_metadata: recursively immutable JSON object,
  elapsed: non-negative duration,
  token_usage: TokenUsage or null
}

TokenUsage {
  prompt_tokens: non-negative integer or null,
  generated_tokens: non-negative integer or null,
  total_tokens: non-negative integer or null
}
```

Provider metadata contains only normalized non-content fields safe for later
persistence. It must not contain prompt text, response text, partial text, raw
exceptions, request/response headers, authorization data, endpoint URLs, or
configuration secrets. Token metadata is optional because a provider may not
report it.

`InvalidProviderResponseFailure` is transport/protocol validation only. It
means the provider returned no terminal complete response, a missing/null/
non-string response field, an empty or whitespace-only response, or a malformed
completion envelope. It does not inspect topic, intent, constraints, output
shape, or any other response-content rule.

Every live provider call is bounded by
`GenerationSettings.request_timeout_seconds`. If that deadline expires, the
adapter cancels/closes its pending transport work before returning
`ModelTimeoutFailure`. The mock's scripted timeout represents that terminal
observation immediately or at a held checkpoint; it never waits for wall-clock
expiry. Timeout never causes an automatic retry.

### Failure values and safe mapping

Each failure type owns the exact diagnostic code and safe public message shown
below. They are constants, not fixture/provider-supplied text.

| Gateway outcome | Diagnostic code | Exact safe public message | `ModelRequestStatus` | Terminal `ProcessingRunStatus` | Persisted `FailureCode` |
|---|---|---|---|---|---|
| `ProviderUnavailableFailure` | `PROVIDER_UNAVAILABLE` | `The local model provider is unavailable.` | `FAILED` | `FAILED` | `PROVIDER_UNAVAILABLE` |
| `ModelNotFoundFailure` | `MODEL_NOT_FOUND` | `The configured local model is unavailable.` | `FAILED` | `FAILED` | `MODEL_NOT_FOUND` |
| `ModelTimeoutFailure` | `MODEL_TIMEOUT` | `The local model request timed out.` | `TIMED_OUT` | `FAILED` | `MODEL_TIMEOUT` |
| `ModelCancelledFailure` | `MODEL_CANCELLED` | `The local model request was cancelled.` | `CANCELLED` | `CANCELLED` | `MODEL_CANCELLED` |
| `InvalidProviderResponseFailure` | `INVALID_PROVIDER_RESPONSE` | `The local model provider returned an invalid response.` | `FAILED` | `FAILED` | `INVALID_PROVIDER_RESPONSE` |

`MODEL_CANCELLED` is reserved for cancellation observed by the gateway for an
already claimed request. `CANCELLED_BY_USER` remains the application failure
code for cancellation completed before any request enters the gateway.

The mapping is authoritative for later application persistence, but persistence
is not gateway or TASK-0011 component behavior. For a returned failure, the
application owns one post-call transaction that:

- changes the existing `IN_FLIGHT` request to the mapped terminal request
  status;
- sets `completed_at`, `error_code` to the diagnostic code, and
  `safe_error_message` to the exact message;
- creates one terminal `SafeFailure` with `stage=TRANSPORT`, the mapped
  `FailureCode`, the same message, and exact safe details
  `{attempt_number, context_packet_id, diagnostic_code, model_request_id}`;
- changes the run to the mapped terminal run status; and
- creates no `ModelResponse`, validation, correction, or assistant-message row.

For `CompletedGeneration`, the application later supplies the exact response
text, provider metadata, elapsed duration, and token usage as candidate
persistence inputs, marks the request `SUCCEEDED`, and performs the existing
atomic candidate/validation contract. The gateway does not mark the processing
run `SUCCEEDED`. TASK-0011 proves the typed inputs and mapping; it does not
perform either persistence path.

No raw provider exception text or type name, prompt/response content, partial
text, headers, endpoint, or provider payload may appear in a failure value,
request error field, `SafeFailure`, or routine log. A transport failure creates
no automatic retry or next correction request.

## Cancellation semantics

```text
CancellationToken {
  is_cancelled() -> bool
}
```

The foreground request owner creates and owns the concrete cancellation token.
Only that owner may move it monotonically from not-cancelled to cancelled. The
token is thread-safe, idempotent, visible across the foreground/UI and provider
worker threads, independent of Qt, and never persisted. The gateway may only
observe it and must never reset it.

The gateway checks cancellation:

1. on entry, before reserving or starting provider work;
2. whenever a provider wait/checkpoint resumes; and
3. immediately before making any terminal provider outcome observable.

If cancellation and timeout or another scripted/provider outcome are observable
at the same checkpoint, cancellation wins. A terminal outcome already returned
is final; later cancellation has no retroactive effect. Cancellation returns
`ModelCancelledFailure` and never response or partial text. Worker-thread force
termination is prohibited.

The token is ephemeral recovery state. Process restart does not reconstruct or
infer cancellation from the missing old token. If the existing recovery policy
permits a not-yet-sent request to enter the gateway, the application component
initiating that call supplies a fresh initially non-cancelled token. This
contract does not decide when or how recovered foreground work is scheduled or
presented. A durably `IN_FLIGHT` request is not called again, and a durably
terminal cancelled request is terminalized without another provider call, as
specified by the persistence recovery matrix.

## Complete buffering

The only content-bearing observation at the gateway boundary is one returned
`CompletedGeneration` containing the entire response. Before that return, no
response text is observable outside the adapter. Failure variants contain no
response-text or partial-text field.

The port exposes no iterator, generator, async generator, chunk/text callback,
signal, progress payload containing provider text, partial-result object, or
provider buffer. Internal chunks may exist only inside a future transport
adapter and are discarded on failure.

TASK-0011 buffering verification must use a content-free deterministic hold
checkpoint. While held, the call has not returned, the mock has published no
terminal call record, and the consumer has observed zero response text or
result. Releasing a successful step produces exactly one result with the exact
complete fixture string. Cancellation or failure produces exactly one typed
failure and zero response text. Merely asserting that no `stream` method exists
is necessary but not sufficient.

## Deterministic `MockModelProvider`

`MockModelProvider` is an outward test adapter owned by the testing/evaluation
layer. Its implementation belongs in `tests/fixtures/model_gateway.py`, not the
production `context_for_ai` package. Versioned synthetic fixture data belongs
under `tests/fixtures/mock_model_provider/`. The mock is not a runtime provider
kind, configuration value, provider registry entry, or fallback.

The mock consumes this immutable ordered script:

```text
MockModelScript {
  schema_version: "mock-model-provider-v1",
  steps: tuple[MockGenerationStep, ...]
}

MockGenerationStep {
  expected_request: GenerationRequest,
  checkpoint: IMMEDIATE | HELD,
  terminal_outcome:
      CompletedGeneration
    | ProviderUnavailableFailure
    | ModelNotFoundFailure
    | ModelTimeoutFailure
    | InvalidProviderResponseFailure
}

MockCallRecord {
  ordinal: non-negative integer,
  script_step_index: non-negative integer or null,
  request: GenerationRequest,
  outcome: GenerationOutcome
}
```

Cancellation is token-driven rather than an artificial terminal script entry.
A `HELD` step publishes a content-free test checkpoint, reserves that step, and
waits for an explicit test-controlled release. On release it checks cancellation
before exposing the scripted terminal outcome. This proves cancellation during
waiting without a wall-clock sleep, polling race, retry loop, or network access.
The mock exposes a thread-safe checkpoint controller with two test operations:
`wait_until_held(step_index, bounded_test_timeout)` and
`release(step_index)`. The timeout only bounds a failed test; it never selects a
gateway outcome. The controller exposes no prompt, response, or partial text.

Script rules are:

1. A pre-cancelled invocation returns `ModelCancelledFailure`, consumes no
   script step, and records one call with `script_step_index=null`.
2. Otherwise the next zero-based unconsumed step is selected solely by script
   order. Exact value equality with `expected_request` is then asserted; request
   matching is an oracle, never routing or outcome selection.
3. A matching step is reserved exactly once. If cancellation wins after
   reservation, that step is consumed and the call records
   `ModelCancelledFailure`; otherwise it records the scripted terminal outcome.
4. Repeated invocations consume successive steps. There is no implicit repeat,
   cycle, fallback, retry, prompt match, or model-based selection.
5. A request mismatch, malformed fixture, or script exhaustion is a deterministic
   test-fixture error, not a `GenerationOutcome`; it consumes no unmatched step
   and adds no terminal call record.
6. Call records are exposed only as an immutable ordered snapshot. They retain
   the exact request and returned outcome and never retain the mutable token.
7. A successful fixture explicitly supplies exact response text, recursively
   immutable provider metadata, exact non-negative elapsed duration, and exact
   token usage or null. The mock does not infer or measure any value.

Given fresh equal scripts, equal requests, and equal cancellation/release
actions, two mock instances return value-equal outcomes and call-record
snapshots. The mock uses no network, system clock, randomness, configuration
discovery, persistence, trace logger, QML object, response validator, or real
sleep.

The required mock matrix covers complete success, provider unavailable, model
not found (the task's “unavailable model”), timeout, pre-call cancellation,
cancellation at a held checkpoint, and invalid provider response.

## Composition and import isolation

TASK-0011 uses only test composition: tests construct `MockModelProvider` and
inject it into the existing `SystemPorts.model_gateway` slot through one test
composition fixture. That fixture is the test process's composition root;
ordinary test bodies receive the inward port and do not construct adapters ad
hoc. TASK-0011 does not finish the production composition root and does not
change `main.py` runtime provider selection.

TASK-0012 remains responsible for the Ollama transport adapter and its later
production construction at the same outer composition boundary. No Ollama
client, transport, placeholder, provider factory, runtime router, or fallback is
part of TASK-0011.

Application orchestration depends only on the inward `ModelGateway` vocabulary,
which remains in the innermost port layer. Domain and application code import
neither the test mock nor an Ollama implementation. Context-engine code has no
gateway dependency. Presentation and QML import application use-case interfaces
only and import neither gateway vocabulary nor any provider implementation.
Only the test-composition fixture may import and construct the mock; only outer
production composition may later import and construct the Ollama adapter.
Static import checks must cover absolute and relative imports and prove these
package boundaries. TASK-0011 can prove the negative Ollama-import boundary but
cannot claim positive Ollama construction before that adapter exists.

## Prohibited behavior

The gateway and mock never interpret intent, retrieve memory, mutate a packet,
validate response content, persist data, emit application trace events, retry
transport, route/fallback models, stream output, call tools, execute actions,
use a cloud provider, or expose provider output to QML.
