# Context for AI — Canonical MVP Database Schema

## Status and database boundary

This is the single authoritative logical schema for the MVP. SQLite is the only
database. The local MVP is single-operator, so it has no `users` table. Every
ID is UUID text, every timestamp is UTC ISO-8601 text, foreign keys are enabled
for every connection, and all JSON columns contain valid JSON.

No table name is a SQLite keyword. In particular, the former `references` table
is replaced by `reference_resolutions`.

## Shared rules

- `created_at` and `updated_at` are non-null unless a table explicitly has only
  an immutable creation time.
- Enumerated values use the canonical values in
  `docs/contracts/DomainAndDecisionRules.md`; migrations add SQLite `CHECK`
  constraints for them.
- User-facing history is append-only where stated. Project archiving and memory
  deletion are state changes, not physical deletion. Conversations and messages
  are not deletable MVP operations.
- All foreign keys use `ON DELETE RESTRICT` unless this document states
  otherwise. The application must surface a typed error rather than cascading
  deletion of user data.
- `schema_migrations` records ordered, transactional migrations. A migration
  cannot be edited after it has been applied; its checksum must match.

## Schema migration ledger

### `schema_migrations`

- `version` integer primary key
- `checksum` non-null text
- `applied_at` non-null

## Conversation and state

### `projects`

- `id` primary key
- `name` non-null text
- `description` nullable text
- `status` non-null `ProjectStatus`
- `created_at`, `updated_at` non-null

### `conversations`

- `id` primary key
- `project_id` nullable foreign key to `projects.id`
- `title` nullable text
- `created_at`, `updated_at` non-null

`conversations.project_id` is the sole persisted active-project value. A null
value means the conversation is unscoped. There is no duplicate
`conversation_states.active_project_id` column.

### `topics`

- `id` primary key
- `conversation_id` non-null foreign key to `conversations.id`
- `label` non-null text
- `normalized_label` non-null text
- `created_at`, `updated_at` non-null
- unique `(conversation_id, normalized_label)`

### `tasks`

- `id` primary key
- `conversation_id` non-null foreign key to `conversations.id`
- `topic_id` nullable foreign key to `topics.id`
- `title` non-null text
- `status` non-null `TaskStatus`
- `created_at`, `updated_at` non-null

### `conversation_states`

- `conversation_id` primary key and foreign key to `conversations.id`
- `active_topic_id` nullable foreign key to `topics.id`
- `active_task_id` nullable foreign key to `tasks.id`
- `previous_task_id` nullable foreign key to `tasks.id`
- `expected_output_type` nullable `OutputType`
- `topic_stack_json` non-null JSON array of topic IDs, default `[]`
- `version` non-null integer, starting at `0`
- `updated_at` non-null

The application validates that all topic/task IDs belong to the same
conversation. State updates use compare-and-swap on `version`.

### `messages`

- `id` primary key
- `conversation_id` non-null foreign key to `conversations.id`
- `role` non-null `MessageRole`
- `original_text` non-null text
- `created_at` non-null
- `sequence_number` non-null integer
- unique `(conversation_id, sequence_number)`

`original_text` is immutable. A final assistant message is linked from
`model_responses.assistant_message_id`; a candidate response has no assistant
message until validation passes. For a linked accepted response, the assistant
message has role `ASSISTANT`, belongs to the run's conversation, and its
`original_text` UTF-8 bytes equal `model_responses.response_text` UTF-8 bytes
exactly. The application checks this before the terminal write and the
repository link operation enforces it again.

## Entities, references, and constraints

### `named_items`

- `id` primary key
- `conversation_id` non-null foreign key to `conversations.id`
- `project_id` nullable foreign key to `projects.id`
- `display_name` non-null text
- `normalized_name` non-null text
- `source_message_id` nullable foreign key to `messages.id`
- `created_at`, `updated_at` non-null
- unique `(conversation_id, normalized_name)`

A named item is created only by the explicit registration/declaration contract
in `DomainAndDecisionRules.md`. A null `source_message_id` means the explicit UI
registration operation; it never means model-inferred extraction.
Display and normalized names, declaration grammar, conversation/project
ownership, and duplicate rejection follow that contract. The named-item row and
its registry row are inserted atomically and carry the same source value.

### `entity_registry`

- `id` primary key
- `entity_type` non-null `EntityType`
- `native_id` non-null text
- `project_id` nullable foreign key to `projects.id`
- `display_name` non-null text
- `normalized_name` non-null text
- `source_message_id` nullable foreign key to `messages.id`
- `is_active` non-null integer boolean
- `created_at`, `updated_at` non-null
- unique `(entity_type, native_id)`

Project, topic, task, and explicit named-item records each receive an entity
registry row. `native_id` identifies the canonical project/topic/task/named-item
row. Repository validation in the same transaction enforces: `PROJECT` points
to `projects`, `TOPIC` to `topics`, `TASK` to `tasks`, and `NAMED_ITEM` to
`named_items`; the registry `project_id` must agree with the owning row when it
has one. SQLite cannot express this polymorphic foreign key, so the migration
adds repository-level invariant tests. No model-inferred entities are stored.

The registry UUID, `entity_type`, `native_id`, `created_at`, and
`source_message_id` are immutable. `PROJECT.project_id` equals its `native_id`;
topic/task project ownership follows their conversation; named-item ownership
matches its owner row. Owner names, conversation project changes, project
archiving, and task terminal/reopen transitions update the affected registry
display name, normalized name, project ID, and activity atomically under the
rules in `DomainAndDecisionRules.md`.

For every entity type, a non-null `source_message_id` is the immutable `USER`
message used by an explicit creation operation. It is null for an explicit UI
creation without message evidence. Topic, task, and named-item sources belong to
their owning conversation; the registry is the canonical project/topic/task
source because those owner tables have no source column. These are
repository-level polymorphic/provenance invariants and require no additional
schema column.

### `reference_resolutions`

- `id` primary key
- `processing_run_id` non-null foreign key to `processing_runs.id`
- `message_id` non-null foreign key to `messages.id`
- `mention_ordinal` non-null integer starting at `0`
- `surface_text` non-null text
- `status` non-null `ReferenceStatus`
- `resolved_entity_id` nullable foreign key to `entity_registry.id`
- `source_message_id` nullable foreign key to `messages.id`
- `confidence` non-null real in `[0, 1]`
- `candidate_evidence_json` non-null JSON array
- `created_at` non-null
- unique `(processing_run_id, mention_ordinal)`

`resolved_entity_id` is non-null only for `RESOLVED`. One row exists for every
final TASK-0008 mention and none is synthesized when there is no mention.
`message_id` is always the current user message; `source_message_id` follows the
winning/unique-evidence/null/non-applicable rules in
`DomainAndDecisionRules.md`. Ambiguous and unresolved results preserve evidence
and remain inspectable by later presentation code.

`candidate_evidence_json` is a non-empty ordered array. Each object contains
exactly `rank`, `entity_id`, `entity_type`, `display_name`, `normalized_name`,
`score`, `rank_reason`, `entity_source_message_id`, `evidence_message_id`,
`evidence_message_sequence`, `prior_mention_ordinal`, and `is_active`. Null
entity fields plus `NO_CANDIDATE`, `FILE_CONTEXT_UNSUPPORTED`, or
`DECLARATION_TARGET` record explicit non-candidate evidence. Repository
validation enforces the status-specific entity/source/confidence invariants and
the evidence object shape. These logical requirements use the existing JSON
column and do not require a TASK-0008 migration.

### `constraints`

- `id` primary key
- `processing_run_id` non-null foreign key to `processing_runs.id`
- `message_id` non-null foreign key to `messages.id`
- `ordinal` non-null integer starting at `0`
- `constraint_type` non-null `ConstraintType`
- `underlying_constraint_type` nullable `ConstraintType`, restricted to
  `REQUIRED`, `FORBIDDEN`, or `PRESERVE`
- `scope` non-null `ConstraintScope`
- `normalized_rule` non-null text
- `priority` non-null integer
- `source_kind` non-null `ConstraintSourceKind`
- `source_text` non-null text
- `confidence` non-null real in `[0, 1]`
- `resolution_status` non-null `ConstraintResolutionStatus`
- `conflict_group_id` nullable text
- `condition_json` nullable JSON object
- `condition_evaluation` nullable `ConditionEvaluation`
- `created_at` non-null
- unique `(processing_run_id, ordinal)`

`underlying_constraint_type`, `condition_json`, and `condition_evaluation` are
non-null exactly when `constraint_type` is `CONDITIONAL`; otherwise they are
null. A condition JSON object follows `mvp-condition-v1` and contains
`grammar_version`, `kind`, `expected_value`, and `evaluation`. `source_text`
is the immutable source evidence for the normalized predicate.

## Memory and provenance

### `memories`

- `id` primary key
- `conversation_id` nullable foreign key to `conversations.id`
- `project_id` nullable foreign key to `projects.id`
- `memory_type` non-null `MemoryType`
- `scope` non-null `MemoryScope`
- `status` non-null stored `MemoryStatus` (`ACTIVE` or `DELETED` only)
- `content` non-null text
- `keywords_json` non-null JSON array
- `topic_terms_json` non-null JSON array
- `importance` non-null real in `[0, 1]`
- `confidence` non-null real in `[0, 1]`
- `expires_at` nullable
- `created_at`, `updated_at` non-null
- `deleted_at` nullable

The application validates scope ownership: conversation-scoped records require
`conversation_id`; project-scoped records require `project_id`; global records
require neither. A record must have at least one source row. `DELETED` requires
non-null `deleted_at`; `ACTIVE` requires null `deleted_at`. Expiry is a computed
effective retrieval status, never a stored automatic lifecycle mutation. A
deleted row is retained for inspection and cannot be edited or restored.

### `memory_sources`

- `id` primary key
- `memory_id` non-null foreign key to `memories.id`
- `source_kind` non-null `MemorySourceKind`
- `source_message_id` nullable foreign key to `messages.id`
- `description` non-null text
- `created_at` non-null

`USER_MESSAGE` requires `source_message_id`; manual entries use
`MANUAL_ENTRY` and a non-empty user-entered description. TASK-0009 manual create
uses `MANUAL_ENTRY`; manual edit and soft delete use `USER_EDIT`. Each successful
manual mutation inserts exactly one source and its corresponding revision in
the same transaction.

### `memory_revisions`

- `id` primary key
- `memory_id` non-null foreign key to `memories.id`
- `revision_number` non-null integer
- `operation` non-null `MemoryRevisionOperation`
- `content_snapshot` non-null text
- `metadata_json` non-null JSON object
- `performed_by` non-null `LocalActor`, always `LOCAL_USER` for memory changes
- `created_at` non-null
- unique `(memory_id, revision_number)`

Expiry is evaluated at retrieval time and creates no automatic revision or
deletion. The MVP has no automatic merge; user edits/deletes resolve duplicates.
`content_snapshot` and the exact `memory-revision-v1` metadata object defined in
`docs/contracts/DomainAndDecisionRules.md` form a complete historical snapshot.
Its `source_id` is the UUID of the source inserted by the same operation. Create
starts at revision `1`; edit and soft-delete revisions are consecutive. These
are repository/application invariants over the existing columns and require no
TASK-0009 schema migration.

## Processing, packets, retrieval, and model lineage

### `processing_runs`

- `id` primary key
- `conversation_id` non-null foreign key to `conversations.id`
- `user_message_id` non-null unique foreign key to `messages.id`
- `idempotency_key` non-null text
- `status` non-null `ProcessingRunStatus`
- `state_version_at_start` non-null integer
- `configuration_fingerprint` non-null text
- `started_at` non-null
- `completed_at` nullable
- unique `(conversation_id, idempotency_key)`

`state_version_at_start` equals the conversation-state version committed by the
acceptance transaction after any explicit project selection, or the unchanged
current version when no selection changes it. It is immutable even when the
joined context transaction later commits a derived state version.

### `context_packets`

- `id` primary key
- `processing_run_id` non-null unique foreign key to `processing_runs.id`
- `message_id` non-null foreign key to `messages.id`
- `packet_json` non-null JSON object
- `schema_version` non-null text
- `prompt_policy_version` non-null text
- `configuration_fingerprint` non-null text
- `created_at` non-null

Packets are immutable. Revision calls use the same packet plus a separately
persisted correction envelope; they never mutate packet JSON.

### `retrieval_results`

- `id` primary key
- `context_packet_id` non-null foreign key to `context_packets.id`
- `memory_id` non-null foreign key to `memories.id`
- `rank` non-null integer
- `score` non-null real in `[0, 1]`
- `reasons_json` non-null JSON array
- `created_at` non-null
- unique `(context_packet_id, rank)`
- unique `(context_packet_id, memory_id)`

Ranks are contiguous and zero-based after threshold filtering, canonical sort,
retrieval-only duplicate collapse, and limit application. `reasons_json` is the
exact seven-string ordered factor array defined in
`docs/contracts/DomainAndDecisionRules.md`. `score` is the canonical 28-digit
decimal decision value represented by the existing SQLite real column, and
`created_at` equals retrieval `evaluated_at`.

### `retrieval_exclusions`

- `id` primary key
- `context_packet_id` non-null foreign key to `context_packets.id`
- `memory_id` non-null foreign key to `memories.id`
- `exclusion_reason` non-null `RetrievalExclusionReason`
- `computed_score` nullable real in `[0, 1]`
- `details_json` non-null JSON object
- `created_at` non-null
- unique `(context_packet_id, memory_id, exclusion_reason)`

This audit table records every considered-but-unselected memory. It is not a
memory mutation and does not expose raw memory content to logs. Every distinct considered memory appears exactly once
in either `retrieval_results` or
`retrieval_exclusions`. TASK-0009 writes one primary exclusion per unselected
memory using the canonical precedence. `computed_score` is null for
`SCOPE_MISMATCH`, `DELETED`, and `EXPIRED`, and is the canonical score for
`SCORE_BELOW_THRESHOLD`, `DUPLICATE_CONTENT`, and `LIMIT_EXCEEDED`.
`details_json` has exactly the reason-specific keys defined in
`docs/contracts/DomainAndDecisionRules.md`; it contains no raw or normalized
memory content. These are logical persistence rules over the existing table and
require no TASK-0009 schema migration.

### `model_requests`

- `id` primary key
- `processing_run_id` non-null foreign key to `processing_runs.id`
- `context_packet_id` non-null foreign key to `context_packets.id`
- `purpose` non-null `ModelRequestPurpose`
- `attempt_number` non-null integer (`0`, `1`, or `2`)
- `provider` non-null `ProviderKind`, `OLLAMA` in MVP
- `model_name` non-null text
- `status` non-null `ModelRequestStatus`
- `rendered_prompt` non-null text
- `request_json` non-null JSON object
- `started_at` nullable
- `completed_at` nullable
- `error_code` nullable text
- `safe_error_message` nullable text
- unique `(processing_run_id, attempt_number)`

`request_json` is the closed `mvp-model-request-v1` projection in
`docs/contracts/Persistence.md`. Its correlation, settings, and rendering
values must agree with the row, immutable packet, rendered prompt handoff, and
the adjacent correction row where applicable. It contains neither prompt text
nor a duplicate correction envelope.

### `model_responses`

- `id` primary key
- `model_request_id` non-null unique foreign key to `model_requests.id`
- `response_text` non-null text
- `metadata_json` non-null JSON object
- `assistant_message_id` nullable unique foreign key to `messages.id`
- `created_at` non-null

An accepted response has exactly one `assistant_message_id`. Invalid candidates
have no assistant message and remain available only in trace/validation views.
`metadata_json` is the closed `mvp-completed-generation-v1` projection in
`docs/contracts/Persistence.md`, including exact integral elapsed microseconds,
nullable token usage, normalized allowed provider metadata, and correlation
that agrees with the request/response lineage.

### `validation_results`

- `id` primary key
- `model_response_id` non-null unique foreign key to `model_responses.id`
- `status` non-null `ValidationStatus`
- `score` non-null real in `[0, 1]`
- `violations_json` non-null JSON array
- `evidence_json` non-null JSON array
- `created_at` non-null

### `correction_attempts`

- `id` primary key
- `processing_run_id` non-null foreign key to `processing_runs.id`
- `attempt_number` non-null integer constrained to `1` or `2`
- `prior_model_response_id` non-null foreign key to `model_responses.id`
- `revised_model_request_id` non-null foreign key to `model_requests.id`
- `reason_json` non-null JSON array
- `created_at` non-null
- unique `(processing_run_id, attempt_number)`

### `clarification_requests`

- `id` primary key
- `processing_run_id` non-null unique foreign key to `processing_runs.id`
- `reason_code` non-null `ClarificationReason`
- `question_text` non-null text
- `details_json` non-null JSON object
- `created_at` non-null

This is the sole durable clarification payload. A `NEEDS_CLARIFICATION` run has
exactly one row, no model request, and no `pipeline_failures` row. Repeating the
same idempotency key returns this exact row rather than creating a second
question.

### `pipeline_failures`

- `id` primary key
- `processing_run_id` non-null foreign key to `processing_runs.id`
- `stage` non-null `PipelineStage`
- `error_code` non-null `FailureCode`
- `safe_message` non-null text
- `details_json` non-null JSON object
- `is_terminal` non-null integer boolean
- `created_at` non-null

Terminal failures include context construction, provider transport, validation
exhaustion, cancellation, recovery, and persistence failures. Clarification is
not a failure. `CONTEXT_CONSTRUCTION_FAILED` is a canonical `FailureCode` stored
in this existing text column and requires no table/column migration. A
controlled failure is never represented as an assistant model message. The
repository enforces exactly one `is_terminal=true` row for a
`CONTROLLED_FAILURE`, `FAILED`, or `CANCELLED` run and none for `SUCCEEDED` or
`NEEDS_CLARIFICATION`; this is a logical invariant over existing columns, not a
new schema index.

## Settings and evaluation

### `settings`

- `key` primary key
- `value_json` non-null JSON value
- `updated_at` non-null

This table contains only the three non-secret presentation keys listed in
`docs/contracts/ConfigurationAndLogging.md`. YAML remains the source of truth
for model, storage, security, validation, context, and logging configuration.

### `evaluation_cases`

- `id` primary key
- `name` non-null unique text
- `category` non-null text
- `case_json` non-null JSON object
- `enabled` non-null integer boolean
- `created_at`, `updated_at` non-null

### `evaluation_runs`

- `id` primary key
- `evaluation_case_id` non-null foreign key to `evaluation_cases.id`
- `fixture_version` non-null text
- `provider_mode` non-null `EvaluationProviderMode`
- `result_json` non-null JSON object
- `passed` non-null integer boolean
- `created_at` non-null

## Required indexes

- `messages(conversation_id, sequence_number)`
- `topics(conversation_id, normalized_label)`
- `tasks(conversation_id, status)`
- `entity_registry(normalized_name, is_active)`
- `reference_resolutions(processing_run_id, mention_ordinal)`
- `constraints(processing_run_id, priority, ordinal)`
- `memories(project_id, status)` and `memories(conversation_id, status)`
- `memory_revisions(memory_id, revision_number)`
- `processing_runs(conversation_id, status)`
- partial unique index on a constant for `processing_runs` where `status IN`
  (`PERSISTED`, `CONTEXT_READY`, `GENERATING`, `REVISING`) to enforce one
  global non-terminal foreground run
- `model_requests(processing_run_id, attempt_number)`
- `validation_results(model_response_id)`
- `clarification_requests(processing_run_id)`
- `pipeline_failures(processing_run_id, created_at)`

## Migration and recovery rules

Each schema change is one numbered migration with a test for an upgrade from
the immediately preceding schema. Migrations run in a SQLite transaction,
create a backup/export recovery instruction before destructive transformations,
and must preserve immutable messages, packet snapshots, model lineage, memory
revisions, and terminal failures. Downgrades are not automatic; a failed
migration rolls back its transaction and leaves the prior ledger version.
