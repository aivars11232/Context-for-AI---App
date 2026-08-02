# ProcessUserMessage Contract

## Responsibility
Coordinate one complete user-message pipeline and return a final result.

## Input
- conversation ID
- exact user text
- optional active project ID

## Output
- persisted user message ID
- final assistant response or controlled failure
- context packet ID
- validation result
- updated state snapshot

## Dependencies
Repository interfaces, context components, model gateway, validator, correction controller, transaction boundary.

## Never does
Direct SQL, provider-specific HTTP, UI work, or hidden requirement inference.

## Errors
ConfigurationError, PersistenceError, ContextConstructionError, ModelProviderError, ValidationExhaustedError.
