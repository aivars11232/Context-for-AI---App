# Context for AI — MVP Database Schema

SQLite is the only MVP database. IDs are text UUIDs unless otherwise stated. Timestamps are UTC ISO-8601 text. Foreign-key enforcement must be enabled.

## projects

- `id` primary key
- `name` non-null
- `description` nullable
- `status` non-null
- `created_at` non-null
- `updated_at` non-null

## conversations

- `id` primary key
- `project_id` nullable foreign key to `projects.id`
- `title` nullable
- `created_at` non-null
- `updated_at` non-null

## messages

- `id` primary key
- `conversation_id` non-null foreign key
- `role` non-null: user, assistant, system, tool
- `original_text` non-null
- `created_at` non-null
- `sequence_number` non-null integer
- unique `(conversation_id, sequence_number)`

## conversation_states

- `conversation_id` primary key and foreign key
- `active_project_id` nullable foreign key
- `active_topic` nullable
- `active_task` nullable
- `previous_task` nullable
- `expected_output_type` nullable
- `topic_stack_json` non-null default `[]`
- `version` non-null integer
- `updated_at` non-null

## references

- `id` primary key
- `message_id` non-null foreign key
- `surface_text` non-null
- `resolved_entity_type` nullable
- `resolved_entity_id` nullable
- `source_message_id` nullable foreign key
- `confidence` non-null real between 0 and 1
- `created_at` non-null

## constraints

- `id` primary key
- `message_id` non-null foreign key
- `constraint_type` non-null
- `normalized_rule` non-null
- `priority` non-null integer
- `scope` non-null
- `source_text` non-null
- `confidence` non-null real between 0 and 1
- `created_at` non-null

## memories

- `id` primary key
- `project_id` nullable foreign key
- `source_message_id` nullable foreign key
- `memory_type` non-null
- `scope` non-null
- `content` non-null
- `keywords_json` non-null default `[]`
- `importance` non-null real between 0 and 1
- `confidence` non-null real between 0 and 1
- `expires_at` nullable
- `created_at` non-null
- `updated_at` non-null

## context_packets

- `id` primary key
- `message_id` non-null foreign key
- `packet_json` non-null
- `schema_version` non-null
- `created_at` non-null

## model_requests

- `id` primary key
- `context_packet_id` non-null foreign key
- `provider` non-null
- `model_name` non-null
- `attempt_number` non-null integer
- `request_json` non-null
- `created_at` non-null

## model_responses

- `id` primary key
- `model_request_id` non-null foreign key
- `response_text` non-null
- `metadata_json` non-null default `{}`
- `created_at` non-null

## validation_results

- `id` primary key
- `model_response_id` non-null foreign key
- `passed` non-null integer boolean
- `score` nullable real
- `violations_json` non-null default `[]`
- `created_at` non-null

## correction_attempts

- `id` primary key
- `original_model_response_id` non-null foreign key
- `revised_model_request_id` non-null foreign key
- `attempt_number` non-null integer constrained to 1 or 2
- `reason_json` non-null
- `created_at` non-null

## settings

- `key` primary key
- `value_json` non-null
- `updated_at` non-null

## evaluation_cases

- `id` primary key
- `name` non-null unique
- `category` non-null
- `case_json` non-null
- `enabled` non-null integer boolean
- `created_at` non-null
- `updated_at` non-null

## Required indexes

- messages by `(conversation_id, sequence_number)`
- memories by `project_id`
- constraints by `message_id`
- references by `message_id`
- context packets by `message_id`
- model requests by `context_packet_id`
- validation results by `model_response_id`

Schema changes require numbered migrations and integration tests.
