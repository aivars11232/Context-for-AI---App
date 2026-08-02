# Model Gateway Contract

## Responsibility
Expose provider-independent text generation.

## Input
- model name
- rendered request
- generation settings
- trace identifiers

## Output
- response text
- provider metadata
- timing and token metadata when available

## Required implementations
- MockModelProvider for deterministic tests
- OllamaModelProvider for local runtime

## Never does
Interpret user intent, retrieve memory, alter context packets, validate content, or retry without caller instruction.

## Errors
ProviderUnavailableError, ModelNotFoundError, ModelTimeoutError, InvalidProviderResponseError.
