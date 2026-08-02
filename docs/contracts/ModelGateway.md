# Model Gateway Contract

## Responsibility

Expose an inward-facing, provider-independent, buffered text-generation port.
The application calls the port; infrastructure provides `OllamaModelProvider`
and the deterministic `MockModelProvider` used by tests.

## Input

- configured local model name
- fully rendered packet or correction prompt
- deterministic generation settings from validated YAML
- trace identifiers: processing run, packet, request, attempt number
- cancellation token owned by the foreground UI request

## Output

Exactly one complete outcome:

- `CompletedGeneration`: complete response text, provider metadata, elapsed
  duration, and token metadata when available; or
- typed transport failure: unavailable, model-not-found, timeout, cancellation,
  or invalid-provider-response.

Partial output is kept only inside the provider until completion. It is not sent
to QML, persisted as a candidate, or validated.

## MVP transport policy

- Only the configured local Ollama endpoint and one selected model are allowed.
- Each call uses `model.request_timeout_seconds`. On expiry, cancel/close the
  request, persist `TIMED_OUT`, and return `ModelTimeoutError`.
- A user cancellation is checked before the call and while waiting. It produces
  `CANCELLED` and `ModelCancelledError`.
- There is no automatic retry, provider fallback, model routing, streaming,
  cloud provider, tool call, or action execution. A transport failure consumes
  no revision attempt and terminates the run safely.
- The gateway never interprets intent, retrieves memory, mutates a packet,
  validates content, or retries without an explicit future caller policy.

## Required implementations

- `MockModelProvider` returns deterministic complete outcomes from fixtures.
- `OllamaModelProvider` is the sole MVP runtime implementation.

## Errors

`ProviderUnavailableError`, `ModelNotFoundError`, `ModelTimeoutError`,
`ModelCancelledError`, and `InvalidProviderResponseError` include a safe public
message and a non-secret diagnostic code. The application translates them into
processing-run terminal states.
