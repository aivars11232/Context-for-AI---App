# Ollama Adapter Contract

## Authority and prerequisite

This contract defines the sole MVP Ollama infrastructure adapter. It implements
the final provider-independent `ModelGateway` contract without adding or changing
any public gateway type.

TASK-0012 implementation must not begin until TASK-0011's exit criteria and the
TASK-0011 component assertions in AT-010 pass. TASK-0012 consumes the resulting
`GenerationRequest`, `GenerationSettings`, `CancellationToken`,
`GenerationOutcome`, five typed failure values, fixed safe diagnostics,
cancellation precedence, and complete-buffering contract exactly as implemented.
It must not duplicate or revise those TASK-0011 decisions.

If this document and `ModelGateway.md` ever disagree about the inward port,
`ModelGateway.md` is authoritative. This document owns only the outward Ollama
adapter behavior.

## Responsibility and ownership

The adapter owns:

- direct Ollama HTTP communication through the validated loopback endpoint;
- the ordered health, local-only, and model-existence checks;
- request-private response-body buffering and protocol-envelope validation;
- propagation of the shared timeout and cancellation token into transport work;
- translation of transport and Ollama observations into the existing canonical
  `GenerationOutcome` values; and
- normalization of the allowlisted metadata used to construct one
  `CompletedGeneration`.

The adapter does not own configuration discovery or YAML parsing, prompt
rendering, persistence, request/run lifecycle mutation, trace emission, QML/UI
publication, semantic response validation, correction, application lifecycle
orchestration, or daemon lifecycle management. The lifecycle table in
`ModelGateway.md` remains later application behavior; the adapter only returns a
typed outcome.

TASK-0012 proves complete-output-only behavior at the gateway boundary. It does
not import or exercise persistence, response validation, correction, application
pipeline, presentation, or QML components.

## Validated handoff and one bound model

`ConfigurationAndLogging.md` is authoritative for parsing and validating
`model.provider`, `model.base_url`, `model.name`, and generation settings. The
configuration loader performs no network request. After complete validation, an
outer composition boundary may construct one adapter with the immutable
normalized endpoint and one normalized model identity. The adapter must not read
YAML, `.env`, `OLLAMA_HOST`, proxy variables, netrc, cookie stores, or ambient
credentials.

Model-reference normalization uses the exact narrow grammar in
`ConfigurationAndLogging.md`: split on `/` with no empty segment; allow no
whitespace or control character; allow `:` only once and only in the final
segment, with non-empty model and tag portions; and append `:latest` when that
colon is absent. `model_tag` is the explicit or inserted suffix. Normalization
does not trim, case-fold, expand a registry or namespace, resolve an alias, or
select another model. Comparisons are case-sensitive after this one
transformation.

`GenerationRequest.model_name` must normalize to the adapter-bound model before
any network work begins. A mismatch is the malformed-caller/programming-invariant
case already permitted by `ModelGateway.md`; it is not a typed provider result
and must not become routing. `/api/show` and `/api/generate` both receive the one
normalized bound identity.

The terminal generation envelope's `model` value must normalize to the same
identity. Any other value is `InvalidProviderResponseFailure`. No existence
result or model alias is cached. If the model disappears after a successful
existence check, `/api/generate` HTTP 404 returns `ModelNotFoundFailure` without
retry, pull, substitution, or fallback.

## Local-only execution invariant

A loopback Ollama daemon can otherwise use daemon-owned cloud authentication, so
a loopback URL and absence of an application API key are not sufficient proof of
local inference. The MVP therefore requires all of these controls:

1. The adapter receives only the validated numeric-loopback HTTP endpoint.
2. Each connected peer address is verified as loopback before request data is
   sent. DNS names, proxies, redirects, tunnels, and response-supplied locations
   are not eligible transports.
3. Redirect following, environment/system proxies, netrc, cookies, and ambient
   authentication are disabled. The adapter sends no `Authorization`,
   `Proxy-Authorization`, API-key, or `Cookie` header.
4. Before every prompt-bearing request, the daemon must attest its native cloud
   policy through the uncached `/api/status` check below.
5. Both the model-details and generation envelopes must have absent, null, or
   empty-string `remote_model` and `remote_host` fields. Non-empty strings are
   remote markers. Every other non-null JSON type is malformed and follows the
   preflight or terminal-envelope mapping below.
6. The adapter calls no pull, push, sign-in, cloud, web-search, web-fetch,
   OpenAI-compatible, or provider-discovery endpoint.

The separately installed Ollama daemon must be started with its native cloud
disable setting, currently `OLLAMA_NO_CLOUD=1` or
`disable_ollama_cloud: true`, and restarted when that setting changes. The
application does not set or manage daemon configuration. It verifies the
daemon-reported result before sending each prompt.

The supported Ollama capability is `GET /api/status` returning the cloud status
shape below. This capability is known from Ollama v0.16.2 onward, although Ollama
labels the corresponding client method experimental. Runtime support is proved by
the response, never inferred from the version string. Endpoint absence or schema
drift is therefore an availability risk, never a data-egress fallback: the
adapter fails closed and sends no prompt. It must not substitute a version guess,
daemon-log inspection, model-name heuristic, or operator assertion for the
status response.

The local host and the separately installed Ollama daemon are trusted runtime
dependencies under the existing MVP threat model. The checks prove the route and
the daemon's reported native cloud policy; they are not cryptographic attestation
against a malicious process already controlling loopback.

Official compatibility basis:

- [Ollama cloud-disable configuration](https://docs.ollama.com/faq)
- [Ollama v0.16.2 status route and handler](https://github.com/ollama/ollama/blob/v0.16.2/server/routes.go)
- [Ollama v0.16.2 status response type](https://github.com/ollama/ollama/blob/v0.16.2/api/types.go)

## Per-invocation checks and ordering

Adapter construction is side-effect free and performs no readiness request.
Every non-pre-cancelled `generate` call performs this exact uncached sequence:

1. `GET /api/version` — daemon health;
2. `GET /api/status` — local-only attestation;
3. `POST /api/show` — exact configured-model existence and locality; and
4. `POST /api/generate` — the only prompt-bearing request.

Cancellation is checked before each operation, whenever a transport wait or body
read resumes, and immediately before a terminal outcome is published. A failure
at any step stops the sequence; no later request is sent. The first observable
failure in this order determines the typed result, subject to cancellation and
deadline precedence.

Health succeeds only for HTTP 200 with a JSON media type and a complete body
containing exactly one JSON object with no trailing non-whitespace data.
`version` must be a non-empty, non-whitespace string. The exact validated string
is retained; trimming cannot make it valid. Unknown health fields are ignored.
Subject to cancellation and timeout precedence, every other health observation
returns `ProviderUnavailableFailure`.

Local-only attestation succeeds only for HTTP 200 with a JSON media type and
one complete object with no trailing non-whitespace data containing:

```text
cloud: {
  disabled: true,
  source: "env" | "config" | "both"
}
```

Subject to the cancellation, deadline, and HTTP 408/504 rules below, every
failure to obtain that exact attestation returns `ProviderUnavailableFailure`.
This includes a missing endpoint, any other status, malformed JSON, missing or
null fields, wrong types, `disabled: false`, `source: "none"`, and an empty or
unknown source. None of these cases sends the prompt. `/api/status` is the
local-safety capability gate, so its unavailable, incompatible, malformed, and
negative states intentionally share one fail-closed outcome. Unknown additional
fields are ignored and never retained.

The model check is `POST /api/show` with semantic JSON exactly equivalent to:

```text
{
  "model": <normalized bound model>,
  "verbose": false
}
```

HTTP 200 with a JSON media type and one complete JSON object with no trailing
non-whitespace data proves that the exact requested identity exists at that
checkpoint. `remote_model` and `remote_host` may each be absent, null, or the
empty string. A non-empty string means there is no eligible local instance of the
configured model and returns `ModelNotFoundFailure`; any other JSON type makes
the preflight malformed and returns `ProviderUnavailableFailure`. Subject to
cancellation, timeout, show-404, and valid-remote-marker precedence, every other
malformed or unsuccessful show observation is also
`ProviderUnavailableFailure`. Other unknown show fields are ignored and never
retained.

No successful check is cached across gateway invocations. A separate readiness
probe may repeat the checks in later composition work, but it can never replace
the per-generation sequence defined here.

## Generation wire contract

The adapter uses only `POST /api/generate`. It sends a JSON media type and accepts
a JSON media type; ordinary media-type parameters are allowed. The request is
semantically exactly:

```text
{
  "model": <normalized bound model>,
  "prompt": GenerationRequest.rendered_prompt,
  "stream": false,
  "raw": true,
  "think": false,
  "truncate": false,
  "shift": false,
  "options": {
    "num_ctx": GenerationSettings.context_window_tokens,
    "temperature": GenerationSettings.temperature
  }
}
```

`prompt` decodes to the caller's rendered prompt unchanged. `raw: true` prevents
Ollama from applying another prompt template. `truncate: false` and
`shift: false` prohibit the provider from silently dropping or shifting the
already budgeted prompt. The exact decimal temperature is encoded as a
value-equivalent JSON number, not a string or binary-float artifact.

No system prompt, template, suffix, context, format, image, tool, thinking level,
logprob, debug, conversation, cloud, credential, or provider-routing field is
sent. `stream: false` is mandatory because Ollama streaming is otherwise the
default. There is no streaming code path or fallback endpoint.

Official wire basis:

- [Ollama generate API](https://docs.ollama.com/api/generate)
- [Ollama streaming behavior](https://docs.ollama.com/api/streaming)

## Complete terminal envelope and buffering

Generation succeeds only when all of these are true:

- the status is HTTP 200 and the media type is JSON;
- the complete body contains exactly one JSON object and no trailing
  non-whitespace data;
- `model` is a non-empty string matching the normalized bound identity;
- `response` is a non-empty, non-whitespace string;
- `done` is the boolean `true`;
- `remote_model` and `remote_host` are absent, null, or the empty string;
- `thinking` is absent, null, or the empty string;
- `tool_calls`, `logprobs`, and `context` are absent, null, or an empty array; and
- `error`, `image`, and `_debug_info` are absent or null.

For `remote_model`, `remote_host`, and `thinking`, every non-empty string or wrong
JSON type invalidates the envelope. For `tool_calls`, `logprobs`, and `context`,
every non-empty array or wrong JSON type invalidates it. Any non-null `error`,
`image`, or `_debug_info` value invalidates it; provider error text and image
content are discarded with the private body and never retained or logged.

`done_reason` may be absent, null, or a string. Missing, null, or the empty string
normalizes to null; a non-empty string is retained exactly. A present field with
any other JSON type invalidates the envelope. Unknown fields are ignored and
never copied wholesale.

`CompletedGeneration.response_text` is the exact decoded `response` string; it is
not trimmed or normalized. JSON/HTTP body fragmentation is transport behavior,
not provider streaming. The complete body remains private to the adapter until
the single terminal envelope has been read, decoded, validated, and converted to
one `CompletedGeneration`.

The port exposes no chunk callback or partial result. If the body is held,
incomplete, malformed, cancelled, timed out, or interrupted, `generate` has not
returned content. The adapter closes the pending transport and discards its
entire private body buffer before returning a content-free failure.

## Timeout and cancellation

One absolute deadline from a monotonic clock begins immediately after the entry
cancellation check. It covers health, local-only attestation, model existence,
generation, complete body reads, JSON decoding, envelope validation, and the
final pre-publication cancellation check. Every operation receives only the
remaining budget from `GenerationSettings.request_timeout_seconds`; no stage
gets a new timeout. If no budget remains before a stage, that stage is not
started and the adapter returns `ModelTimeoutFailure`.

The transport wait must remain cancellation-aware while connecting, waiting for
headers, and reading a body. Every response body is closed before any outcome
returns, including ordinary non-200 and malformed-response paths. A non-200 body
is not parsed, retained, drained into an application buffer, or logged. On
timeout or observed cancellation, the adapter aborts the active exchange, closes
its response/body and request-scoped connection, prevents reuse of an unread
connection, discards all buffered content, and waits until no request-scoped
transport work can publish content before returning. No transport work may
continue after the terminal outcome.

Cancellation wins if cancellation and timeout, completion, or another provider
condition become observable at the same checkpoint. A terminal value already
returned is final. Worker-thread force termination, a persistent adapter worker,
queue, independently scheduled background activity, retry, and fallback are
prohibited. Any request-scoped cancellation activity exists only within this
synchronous call and must terminate before `generate` returns.

## Canonical failure translation

The adapter returns only the failure values and exact safe diagnostics already
defined by `ModelGateway.md`. Provider bodies, exception text, status text,
headers, endpoints, and remote host values never cross the port or enter routine
logs.

| Observation | Existing gateway outcome |
|---|---|
| Cancellation observed at any checkpoint | `ModelCancelledFailure` |
| Shared deadline expires at any stage | `ModelTimeoutFailure` |
| HTTP 408 or 504 at any stage | `ModelTimeoutFailure` |
| Any unavailable, non-200, incomplete, or malformed `/api/version` health response | `ProviderUnavailableFailure` |
| `/api/status` does not return the exact cloud-disabled attestation | `ProviderUnavailableFailure` |
| `/api/show` HTTP 404 or valid non-empty remote marker | `ModelNotFoundFailure` |
| Any other unavailable, non-200, incomplete, or malformed `/api/show` response | `ProviderUnavailableFailure` |
| Generation connection/reset/protocol failure before a usable HTTP status | `ProviderUnavailableFailure` |
| `/api/generate` HTTP 404 | `ModelNotFoundFailure` |
| Any other non-200 generation status, including 3xx, 401/403, 429, and 5xx | `ProviderUnavailableFailure` |
| Incomplete, truncated, trailing, or malformed HTTP-200 generation body/envelope | `InvalidProviderResponseFailure` |
| Terminal generation reports the wrong model | `InvalidProviderResponseFailure` |
| Non-terminal, remote-marked, tool/thinking-bearing, or empty generation | `InvalidProviderResponseFailure` |

Cancellation and the shared local deadline are checked before applying an HTTP
classification at the same checkpoint. There is no automatic retry. An
unclassified transport/provider exception follows the existing safe default and
returns `ProviderUnavailableFailure`.

Preflight checks establish provider eligibility and therefore fail unavailable,
except the model-not-found observations above. Only a nominal HTTP-200 generation
response crosses the final TASK-0011 invalid-response boundary; failure to read
and validate its one complete terminal object is
`InvalidProviderResponseFailure`.

## Allowed success metadata

`CompletedGeneration.elapsed` is monotonic wall duration from the start of the
whole gateway attempt through the successful final cancellation/deadline
checkpoint immediately before publication, including all three preflight checks
and envelope validation. Ollama's `total_duration` is not used as `elapsed`.

`provider_metadata` is recursively immutable and has exactly these keys:

```text
{
  "provider": "ollama",
  "provider_version": <validated /api/version string>,
  "model_identity": <normalized bound model>,
  "model_tag": <explicit tag>,
  "cloud_disable_source": "env" | "config" | "both",
  "done_reason": <string or null>,
  "total_duration_ns": <non-negative integer or null>,
  "load_duration_ns": <non-negative integer or null>,
  "prompt_eval_duration_ns": <non-negative integer or null>,
  "eval_duration_ns": <non-negative integer or null>
}
```

For optional provider fields, absent and JSON null become null. A present duration
with the wrong type, including boolean, or a negative value invalidates the
otherwise successful envelope.

Token usage maps independently:

- `prompt_eval_count` becomes `TokenUsage.prompt_tokens` when present as a
  non-negative integer, otherwise null;
- `eval_count` becomes `TokenUsage.generated_tokens` under the same rule;
- `total_tokens` is their sum only when both are known, otherwise null; and
- `token_usage` itself is null only when both provider count fields are absent or
  null.

A present count with a wrong type, including boolean, or a negative value
invalidates the envelope. Token counts are not duplicated in
`provider_metadata`.

Unknown fields, `created_at`, raw status/show/generation objects, prompt and
response content, partial content, thinking, context arrays, logprobs, tool calls,
headers, endpoints, remote hosts/models, exceptions, cookies, authorization data,
and secrets are never retained in metadata or routine logs.

## Composition and test boundaries

TASK-0012 does not implement the complete production composition root or change
full application/QML orchestration. A later outer production composition root
constructs the adapter from the already validated endpoint and bound model
identity and injects it into `SystemPorts.model_gateway`. Domain, context-engine,
application, presentation, and QML code never import the concrete adapter or
Ollama transport.

Required default-suite adapter tests construct the real adapter through one test
composition fixture with a controlled transport double and validated fixture
configuration. They use no daemon and prove request ordering, no caching,
loopback and no-redirect/no-proxy behavior, payload/envelope mapping, local-only
failure, model disappearance and mismatch, HTTP translation, shared timeout,
cancellation-driven closure, metadata normalization, and private buffering of a
held partial body. Broader application and pipeline tests continue to inject the
TASK-0011 deterministic mock.

The isolated live-test definitions and fixture are part of TASK-0012's required
test surface, but executing them against a daemon is optional. Every test that
contacts a live Ollama daemon is marked `ollama`. The project's central pytest
configuration—not a developer convention—makes the normal/default selection
exclude that marker. When live tests are selected:

- absent `CONTEXT_FOR_AI_RUN_OLLAMA` skips the marked test and reports environment
  absence, never a pass;
- a present value other than exactly `1` is an invalid opt-in and fails;
- exact value `1` runs all preflight and adapter assertions; and
- invalid configuration, a non-local endpoint, failed cloud-disable attestation,
  unavailable daemon, missing model, timeout, malformed response, or any failed
  assertion is a failure, never a dynamic skip.

The live fixture loads an isolated complete six-file configuration through the
normal loader. Endpoint and model changes may use only the existing validated
`CONTEXT_FOR_AI__MODEL__BASE_URL` and `CONTEXT_FOR_AI__MODEL__NAME` overrides.
`CONTEXT_FOR_AI_RUN_OLLAMA` enables execution only and supplies no endpoint,
model, credential, or provider value. The fixture does not accept a cloud URL,
credential, raw environment endpoint, fallback, or provider substitution.
Marked live adapter transport test execution exercises only this component
contract; it does not run or satisfy AT-016's later complete-pipeline
acceptance. Absence of opt-in live evidence does not block TASK-0012 because the
controlled-transport suite is required. Once opted in, a failing live test must
be reported as a failure.
