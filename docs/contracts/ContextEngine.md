# Context Engine Contracts

## InterpretationEngine
Input: message plus state snapshot. Output: intent, topic, qualifiers, expected output type, confidence.

## ReferenceResolver
Input: message, recent messages, tracked entities. Output: resolutions with source and confidence.

## ConstraintEngine
Input: message, interpretation, active state. Output: normalized prioritized constraints and conflicts.

## ContextRetriever
Input: message, state, project, retrieval limits. Output: ordered memories with scores and reasons.

## ContextPacketBuilder
Input: exact message, interpretation, state, references, constraints, retrieved memories, response policy. Output: immutable versioned context packet.

Each component is deterministic in MVP unless explicitly passed a model-backed implementation in a later phase.
