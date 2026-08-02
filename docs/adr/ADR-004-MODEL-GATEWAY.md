# ADR-004 — Provider-Independent Model Gateway

Status: Accepted

Decision: Application code calls a model gateway interface. Ollama is one infrastructure implementation; a deterministic mock is required for tests.

Consequences: Domain and application logic remain provider-independent. Ollama-specific behavior must not leak across the boundary.
