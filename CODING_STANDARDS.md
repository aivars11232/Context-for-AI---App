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

- Follow `docs/contracts/ConfigurationAndLogging.md` for required structured
  fields, event names, redaction, retention, and traceability.
- Never log API keys, authentication tokens, original message text, rendered
  prompts, model responses, raw memory content, or complete configuration.
- Preserve traceability from a user message through context construction, model
  calls, validation, correction, failures, and manual memory changes.

## Configuration

- Keep environment-specific values outside source code and follow the six-file
  YAML schema and precedence contract.
- Provide only the explicit defaults defined by that contract.
- Validate configuration before QML startup and fail clearly with a typed,
  redacted error on invalid configuration.

## Documentation

- Public interfaces require concise docstrings describing responsibility, inputs, outputs, and raised errors.
- Comments explain non-obvious reasoning, not obvious syntax.
- Update architecture and contract documentation when behavior or boundaries change.

## Testing

- Tests must verify observable behavior.
- Unit tests must not require Ollama or a persistent user database.
- Integration tests must use temporary isolated storage.
- Live Ollama tests must be marked `ollama`, opt-in, and required only for
  TASK-0018 / AT-016 after all deterministic acceptance criteria are green.
- A failing test blocks further implementation.
