# ADR-001 — Modular Monolith

Status: Accepted

Context for AI needs strong internal boundaries but does not require distributed deployment for its MVP.

Decision: Build one repository and one local application with presentation, application, domain, context intelligence, infrastructure, and testing boundaries.

Consequences: Simpler deployment and debugging; boundaries must be enforced through imports and interfaces. Microservices are excluded from MVP.
