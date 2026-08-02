# Context for AI — Acceptance Tests

## AT-001 Application startup
Given the required dependencies and configuration are present, when the application starts, then the main QML window opens without import, database, or configuration errors.

## AT-002 Message persistence
Given an active conversation, when the user submits a message, then the exact original text is stored in SQLite and can be read back unchanged.

## AT-003 Active-state tracking
Given an active project and topic, when the user continues the task, then the context packet contains the correct project, topic, task, and expected output type.

## AT-004 Qualifier handling
Given the message `Remove only the blue line and do not change anything else`, when constraints are extracted, then `remove blue line` is REQUIRED and all other content is represented by PRESERVE or FORBIDDEN constraints.

## AT-005 Output-type protection
Given prior image-design context and the message `Do not generate anything; give me a description`, when the message is interpreted, then the expected output type is text and image generation is FORBIDDEN.

## AT-006 Reference resolution
Given the previous active entity is `Context for AI`, when the user says `correct the app structure`, then `the app` resolves to `Context for AI` with its source message recorded.

## AT-007 Context retrieval
Given memories from several projects, when a message concerns Context for AI, then project-relevant memories are retrieved and unrelated project memories are excluded.

## AT-008 Context-packet completeness
Given a valid message, when context construction completes, then the packet includes original text, intent, active state, references, constraints, retrieved memory, confidence, and response policy.

## AT-009 Model abstraction
Given a configured mock provider, when the application requests a response, then the pipeline uses the model gateway without importing the Ollama implementation into domain or application code.

## AT-010 Response validation
Given a response that violates a FORBIDDEN constraint, when validation runs, then the response is rejected and the violation is recorded.

## AT-011 Bounded correction
Given repeated invalid model responses, when correction is attempted, then no more than two revision attempts occur and the pipeline returns a controlled failure result.

## AT-012 Context inspection
Given a processed message, when the user opens the context panel, then the UI displays the interpreted intent, active state, resolved references, extracted constraints, retrieved memories, and validation status.

## AT-013 Memory provenance
Given a memory is stored, when it is inspected, then its source, scope, confidence, creation time, and update time are available.

## AT-014 Complete pipeline
Given a configured local Ollama model, when the user submits a message, then the application persists the message, constructs context, calls Ollama, validates the response, persists the result, updates state, and displays the final response.
