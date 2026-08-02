# Context for AI — Coding Standards

## Python

- Target Python 3.12 or newer.
- Use explicit type annotations for public functions, methods, and data models.
- Prefer dataclasses or focused domain classes over unstructured dictionaries in domain and application code.
- Keep functions small and single-purpose.
- Avoid global mutable state.
- Use `pathlib.Path` for filesystem paths.
- Use UTC-aware timestamps internally.
- Do not catch broad `Exception` unless re-raising a typed application error with preserved cause.

## Naming

- Packages and modules: `snake_case`.
- Classes and enums: `PascalCase`.
- Functions, methods, and variables: `snake_case`.
- Constants: `UPPER_SNAKE_CASE`.
- Test files: `test_<component>.py`.
- Test functions: `test_<observable_behavior>`.

## Dependencies

- Domain code must not import PySide6, SQLite adapters, Ollama clients, QML, or infrastructure implementations.
- Application code depends on domain interfaces, not concrete adapters.
- Infrastructure implements interfaces declared inward of it.
- UI invokes application use cases; it does not implement context logic.

## Errors

- Define typed domain, application, configuration, persistence, and model-provider errors.
- Never silently ignore a failed pipeline stage.
- Error messages must identify the failed stage without exposing secrets.

## Logging

- Use structured logging fields where practical: conversation ID, message ID, stage, attempt number, and error type.
- Never log API keys, authentication tokens, or complete secret-bearing configuration.
- Preserve traceability from a user message through context construction, model calls, validation, and persistence.

## Configuration

- Keep environment-specific values outside source code.
- Provide safe defaults only where requirements define them.
- Validate configuration at startup and fail clearly on invalid values.

## Documentation

- Public interfaces require concise docstrings describing responsibility, inputs, outputs, and raised errors.
- Comments explain non-obvious reasoning, not obvious syntax.
- Update architecture and contract documentation when behavior or boundaries change.

## Testing

- Tests must verify observable behavior.
- Unit tests must not require Ollama or a persistent user database.
- Integration tests must use temporary isolated storage.
- Live Ollama tests must be marked and optional until Stage 13.
- A failing test blocks further implementation.
