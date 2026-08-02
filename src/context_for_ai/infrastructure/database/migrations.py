"""Ordered, transactional migrations for the canonical MVP SQLite schema."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3

from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.infrastructure.database.connection import connect_database
from context_for_ai.infrastructure.database.migration_ledger import (
    initialize_migration_ledger,
)


class MigrationError(PersistenceError):
    """Base class for a canonical schema-migration failure."""


class MigrationOrderError(MigrationError):
    """Raised when migration definitions or ledger rows are not an ordered prefix."""


class MigrationChecksumError(MigrationError):
    """Raised when an applied migration no longer matches its immutable definition."""


class MigrationApplicationError(MigrationError):
    """Raised after a migration fails and its transaction is rolled back."""


def _uuid_check(expression: str) -> str:
    """Return a SQLite expression accepting canonical lowercase UUID text."""

    return f"""
        typeof({expression}) = 'text'
        AND length({expression}) = 36
        AND substr({expression}, 9, 1) = '-'
        AND substr({expression}, 14, 1) = '-'
        AND substr({expression}, 19, 1) = '-'
        AND substr({expression}, 24, 1) = '-'
        AND length(replace({expression}, '-', '')) = 32
        AND replace({expression}, '-', '') NOT GLOB '*[^0-9a-f]*'
        AND lower({expression}) = {expression}
    """.strip()


def _utc_timestamp_check(expression: str) -> str:
    """Return a SQLite expression accepting non-empty UTC ISO-8601 text."""

    return f"""
        typeof({expression}) = 'text'
        AND datetime({expression}) IS NOT NULL
        AND (
            substr({expression}, -1) = 'Z'
            OR substr({expression}, -6) = '+00:00'
        )
    """.strip()


def _json_array_check(expression: str) -> str:
    """Return a non-throwing SQLite check for a valid JSON array."""

    return f"""
        CASE
            WHEN json_valid({expression})
            THEN json_type({expression}) = 'array'
            ELSE 0
        END
    """.strip()


def _json_object_check(expression: str) -> str:
    """Return a non-throwing SQLite check for a valid JSON object."""

    return f"""
        CASE
            WHEN json_valid({expression})
            THEN json_type({expression}) = 'object'
            ELSE 0
        END
    """.strip()


@dataclass(frozen=True, slots=True)
class Migration:
    """One immutable numbered migration and its deterministic checksum."""

    version: int
    name: str
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or self.version < 1:
            raise ValueError("Migration versions must be positive integers.")
        if not self.name.strip():
            raise ValueError("Migration names must be non-empty.")
        if not self.statements or any(not statement.strip() for statement in self.statements):
            raise ValueError("Migrations must contain non-empty SQL statements.")

    @property
    def checksum(self) -> str:
        """Return the stable SHA-256 checksum for all immutable migration content."""

        payload = "\n\0\n".join(
            (str(self.version), self.name, *(statement.strip() for statement in self.statements))
        )
        return sha256(payload.encode("utf-8")).hexdigest()


_CANONICAL_SCHEMA_STATEMENTS = (
    f"""
    CREATE TABLE projects (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        name TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'ARCHIVED')),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")})
    )
    """,
    f"""
    CREATE TABLE conversations (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        project_id TEXT CHECK (project_id IS NULL OR ({_uuid_check("project_id")})),
        title TEXT,
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")}),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE topics (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        conversation_id TEXT NOT NULL CHECK ({_uuid_check("conversation_id")}),
        label TEXT NOT NULL,
        normalized_label TEXT NOT NULL,
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")}),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE RESTRICT,
        UNIQUE (conversation_id, normalized_label)
    )
    """,
    f"""
    CREATE TABLE tasks (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        conversation_id TEXT NOT NULL CHECK ({_uuid_check("conversation_id")}),
        topic_id TEXT CHECK (topic_id IS NULL OR ({_uuid_check("topic_id")})),
        title TEXT NOT NULL,
        status TEXT NOT NULL
            CHECK (status IN ('OPEN', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")}),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE RESTRICT,
        FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE conversation_states (
        conversation_id TEXT NOT NULL PRIMARY KEY
            CHECK ({_uuid_check("conversation_id")}),
        active_topic_id TEXT
            CHECK (active_topic_id IS NULL OR ({_uuid_check("active_topic_id")})),
        active_task_id TEXT
            CHECK (active_task_id IS NULL OR ({_uuid_check("active_task_id")})),
        previous_task_id TEXT
            CHECK (previous_task_id IS NULL OR ({_uuid_check("previous_task_id")})),
        expected_output_type TEXT CHECK (
            expected_output_type IS NULL OR expected_output_type IN (
                'TEXT_ANSWER', 'TEXT_EXPLANATION', 'TEXT_DESCRIPTION', 'TEXT_PLAN',
                'TEXT_ANALYSIS', 'TEXT_CODE', 'TEXT_COMPARISON', 'CLARIFICATION',
                'CONTROLLED_FAILURE'
            )
        ),
        topic_stack_json TEXT NOT NULL DEFAULT '[]'
            CHECK ({_json_array_check("topic_stack_json")}),
        version INTEGER NOT NULL DEFAULT 0
            CHECK (typeof(version) = 'integer' AND version >= 0),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")}),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE RESTRICT,
        FOREIGN KEY (active_topic_id) REFERENCES topics(id) ON DELETE RESTRICT,
        FOREIGN KEY (active_task_id) REFERENCES tasks(id) ON DELETE RESTRICT,
        FOREIGN KEY (previous_task_id) REFERENCES tasks(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE messages (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        conversation_id TEXT NOT NULL CHECK ({_uuid_check("conversation_id")}),
        role TEXT NOT NULL CHECK (role IN ('USER', 'ASSISTANT', 'SYSTEM')),
        original_text TEXT NOT NULL,
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        sequence_number INTEGER NOT NULL
            CHECK (typeof(sequence_number) = 'integer' AND sequence_number >= 0),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE RESTRICT,
        UNIQUE (conversation_id, sequence_number)
    )
    """,
    f"""
    CREATE TABLE named_items (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        conversation_id TEXT NOT NULL CHECK ({_uuid_check("conversation_id")}),
        project_id TEXT CHECK (project_id IS NULL OR ({_uuid_check("project_id")})),
        display_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL,
        source_message_id TEXT
            CHECK (source_message_id IS NULL OR ({_uuid_check("source_message_id")})),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")}),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE RESTRICT,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT,
        FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE RESTRICT,
        UNIQUE (conversation_id, normalized_name)
    )
    """,
    f"""
    CREATE TABLE entity_registry (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        entity_type TEXT NOT NULL
            CHECK (entity_type IN ('PROJECT', 'TOPIC', 'TASK', 'NAMED_ITEM')),
        native_id TEXT NOT NULL CHECK ({_uuid_check("native_id")}),
        project_id TEXT CHECK (project_id IS NULL OR ({_uuid_check("project_id")})),
        display_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL,
        source_message_id TEXT
            CHECK (source_message_id IS NULL OR ({_uuid_check("source_message_id")})),
        is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")}),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT,
        FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE RESTRICT,
        UNIQUE (entity_type, native_id)
    )
    """,
    f"""
    CREATE TABLE processing_runs (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        conversation_id TEXT NOT NULL CHECK ({_uuid_check("conversation_id")}),
        user_message_id TEXT NOT NULL UNIQUE CHECK ({_uuid_check("user_message_id")}),
        idempotency_key TEXT NOT NULL CHECK ({_uuid_check("idempotency_key")}),
        status TEXT NOT NULL CHECK (status IN (
            'PERSISTED', 'CONTEXT_READY', 'GENERATING', 'REVISING', 'SUCCEEDED',
            'NEEDS_CLARIFICATION', 'CONTROLLED_FAILURE', 'FAILED', 'CANCELLED'
        )),
        state_version_at_start INTEGER NOT NULL
            CHECK (typeof(state_version_at_start) = 'integer' AND state_version_at_start >= 0),
        configuration_fingerprint TEXT NOT NULL,
        started_at TEXT NOT NULL CHECK ({_utc_timestamp_check("started_at")}),
        completed_at TEXT CHECK (
            completed_at IS NULL OR ({_utc_timestamp_check("completed_at")})
        ),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE RESTRICT,
        FOREIGN KEY (user_message_id) REFERENCES messages(id) ON DELETE RESTRICT,
        UNIQUE (conversation_id, idempotency_key)
    )
    """,
    f"""
    CREATE TABLE reference_resolutions (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        processing_run_id TEXT NOT NULL CHECK ({_uuid_check("processing_run_id")}),
        message_id TEXT NOT NULL CHECK ({_uuid_check("message_id")}),
        mention_ordinal INTEGER NOT NULL
            CHECK (typeof(mention_ordinal) = 'integer' AND mention_ordinal >= 0),
        surface_text TEXT NOT NULL,
        status TEXT NOT NULL
            CHECK (status IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED', 'NOT_APPLICABLE')),
        resolved_entity_id TEXT CHECK (
            resolved_entity_id IS NULL OR ({_uuid_check("resolved_entity_id")})
        ),
        source_message_id TEXT CHECK (
            source_message_id IS NULL OR ({_uuid_check("source_message_id")})
        ),
        confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
        candidate_evidence_json TEXT NOT NULL
            CHECK ({_json_array_check("candidate_evidence_json")}),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        CHECK (
            (status = 'RESOLVED' AND resolved_entity_id IS NOT NULL)
            OR (status <> 'RESOLVED' AND resolved_entity_id IS NULL)
        ),
        FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE RESTRICT,
        FOREIGN KEY (resolved_entity_id) REFERENCES entity_registry(id) ON DELETE RESTRICT,
        FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE RESTRICT,
        UNIQUE (processing_run_id, mention_ordinal)
    )
    """,
    f"""
    CREATE TABLE constraints (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        processing_run_id TEXT NOT NULL CHECK ({_uuid_check("processing_run_id")}),
        message_id TEXT NOT NULL CHECK ({_uuid_check("message_id")}),
        ordinal INTEGER NOT NULL CHECK (typeof(ordinal) = 'integer' AND ordinal >= 0),
        constraint_type TEXT NOT NULL CHECK (constraint_type IN (
            'REQUIRED', 'FORBIDDEN', 'PRESERVE', 'PREFERRED', 'OPTIONAL',
            'CONDITIONAL', 'ASSUMED'
        )),
        underlying_constraint_type TEXT CHECK (
            underlying_constraint_type IS NULL
            OR underlying_constraint_type IN ('REQUIRED', 'FORBIDDEN', 'PRESERVE')
        ),
        scope TEXT NOT NULL
            CHECK (scope IN ('CURRENT_RESPONSE', 'CONVERSATION', 'PROJECT', 'GLOBAL')),
        normalized_rule TEXT NOT NULL,
        priority INTEGER NOT NULL CHECK (typeof(priority) = 'integer'),
        source_kind TEXT NOT NULL CHECK (source_kind IN (
            'CURRENT_MESSAGE', 'TASK_POLICY', 'CORRECTION_MEMORY', 'PREFERENCE_MEMORY',
            'RETRIEVED_MEMORY', 'ASSUMPTION', 'DERIVED_OUTPUT_POLICY'
        )),
        source_text TEXT NOT NULL,
        confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
        resolution_status TEXT NOT NULL
            CHECK (resolution_status IN ('ACTIVE', 'INACTIVE', 'OVERRIDDEN', 'CONFLICTING')),
        conflict_group_id TEXT,
        condition_json TEXT CHECK (
            condition_json IS NULL OR ({_json_object_check("condition_json")})
        ),
        condition_evaluation TEXT CHECK (
            condition_evaluation IS NULL
            OR condition_evaluation IN ('TRUE', 'FALSE', 'UNSUPPORTED')
        ),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        CHECK (
            (
                constraint_type = 'CONDITIONAL'
                AND underlying_constraint_type IS NOT NULL
                AND condition_json IS NOT NULL
                AND condition_evaluation IS NOT NULL
            )
            OR (
                constraint_type <> 'CONDITIONAL'
                AND underlying_constraint_type IS NULL
                AND condition_json IS NULL
                AND condition_evaluation IS NULL
            )
        ),
        FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE RESTRICT,
        UNIQUE (processing_run_id, ordinal)
    )
    """,
    f"""
    CREATE TABLE memories (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        conversation_id TEXT CHECK (
            conversation_id IS NULL OR ({_uuid_check("conversation_id")})
        ),
        project_id TEXT CHECK (project_id IS NULL OR ({_uuid_check("project_id")})),
        memory_type TEXT NOT NULL CHECK (memory_type IN (
            'PROJECT_FACT', 'USER_PREFERENCE', 'CORRECTION_RULE',
            'TECHNICAL_ENVIRONMENT', 'ARCHIVED_SUMMARY'
        )),
        scope TEXT NOT NULL CHECK (scope IN ('CONVERSATION', 'PROJECT', 'GLOBAL')),
        status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'DELETED')),
        content TEXT NOT NULL,
        keywords_json TEXT NOT NULL CHECK ({_json_array_check("keywords_json")}),
        topic_terms_json TEXT NOT NULL CHECK ({_json_array_check("topic_terms_json")}),
        importance REAL NOT NULL CHECK (importance >= 0.0 AND importance <= 1.0),
        confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
        expires_at TEXT CHECK (expires_at IS NULL OR ({_utc_timestamp_check("expires_at")})),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")}),
        deleted_at TEXT CHECK (deleted_at IS NULL OR ({_utc_timestamp_check("deleted_at")})),
        CHECK (
            (status = 'ACTIVE' AND deleted_at IS NULL)
            OR (status = 'DELETED' AND deleted_at IS NOT NULL)
        ),
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE RESTRICT,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE memory_sources (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        memory_id TEXT NOT NULL CHECK ({_uuid_check("memory_id")}),
        source_kind TEXT NOT NULL
            CHECK (source_kind IN ('USER_MESSAGE', 'MANUAL_ENTRY', 'USER_EDIT')),
        source_message_id TEXT CHECK (
            source_message_id IS NULL OR ({_uuid_check("source_message_id")})
        ),
        description TEXT NOT NULL,
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        CHECK (source_kind <> 'USER_MESSAGE' OR source_message_id IS NOT NULL),
        CHECK (source_kind <> 'MANUAL_ENTRY' OR length(trim(description)) > 0),
        FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
        FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE memory_revisions (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        memory_id TEXT NOT NULL CHECK ({_uuid_check("memory_id")}),
        revision_number INTEGER NOT NULL CHECK (typeof(revision_number) = 'integer'),
        operation TEXT NOT NULL CHECK (operation IN ('CREATE', 'EDIT', 'SOFT_DELETE')),
        content_snapshot TEXT NOT NULL,
        metadata_json TEXT NOT NULL CHECK ({_json_object_check("metadata_json")}),
        performed_by TEXT NOT NULL CHECK (performed_by = 'LOCAL_USER'),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
        UNIQUE (memory_id, revision_number)
    )
    """,
    f"""
    CREATE TABLE context_packets (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        processing_run_id TEXT NOT NULL UNIQUE CHECK ({_uuid_check("processing_run_id")}),
        message_id TEXT NOT NULL CHECK ({_uuid_check("message_id")}),
        packet_json TEXT NOT NULL CHECK ({_json_object_check("packet_json")}),
        schema_version TEXT NOT NULL,
        prompt_policy_version TEXT NOT NULL,
        configuration_fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE retrieval_results (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        context_packet_id TEXT NOT NULL CHECK ({_uuid_check("context_packet_id")}),
        memory_id TEXT NOT NULL CHECK ({_uuid_check("memory_id")}),
        rank INTEGER NOT NULL CHECK (typeof(rank) = 'integer'),
        score REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
        reasons_json TEXT NOT NULL CHECK ({_json_array_check("reasons_json")}),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (context_packet_id) REFERENCES context_packets(id) ON DELETE RESTRICT,
        FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
        UNIQUE (context_packet_id, rank),
        UNIQUE (context_packet_id, memory_id)
    )
    """,
    f"""
    CREATE TABLE retrieval_exclusions (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        context_packet_id TEXT NOT NULL CHECK ({_uuid_check("context_packet_id")}),
        memory_id TEXT NOT NULL CHECK ({_uuid_check("memory_id")}),
        exclusion_reason TEXT NOT NULL CHECK (exclusion_reason IN (
            'SCOPE_MISMATCH', 'DELETED', 'EXPIRED', 'SCORE_BELOW_THRESHOLD',
            'DUPLICATE_CONTENT', 'LIMIT_EXCEEDED'
        )),
        computed_score REAL CHECK (
            computed_score IS NULL OR (computed_score >= 0.0 AND computed_score <= 1.0)
        ),
        details_json TEXT NOT NULL CHECK ({_json_object_check("details_json")}),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (context_packet_id) REFERENCES context_packets(id) ON DELETE RESTRICT,
        FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE RESTRICT,
        UNIQUE (context_packet_id, memory_id, exclusion_reason)
    )
    """,
    f"""
    CREATE TABLE model_requests (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        processing_run_id TEXT NOT NULL CHECK ({_uuid_check("processing_run_id")}),
        context_packet_id TEXT NOT NULL CHECK ({_uuid_check("context_packet_id")}),
        purpose TEXT NOT NULL CHECK (purpose IN ('INITIAL', 'REVISION')),
        attempt_number INTEGER NOT NULL
            CHECK (typeof(attempt_number) = 'integer' AND attempt_number IN (0, 1, 2)),
        provider TEXT NOT NULL CHECK (provider = 'OLLAMA'),
        model_name TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN (
            'PENDING', 'IN_FLIGHT', 'SUCCEEDED', 'TIMED_OUT', 'CANCELLED', 'FAILED'
        )),
        rendered_prompt TEXT NOT NULL,
        request_json TEXT NOT NULL CHECK ({_json_object_check("request_json")}),
        started_at TEXT CHECK (started_at IS NULL OR ({_utc_timestamp_check("started_at")})),
        completed_at TEXT CHECK (
            completed_at IS NULL OR ({_utc_timestamp_check("completed_at")})
        ),
        error_code TEXT,
        safe_error_message TEXT,
        FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (context_packet_id) REFERENCES context_packets(id) ON DELETE RESTRICT,
        UNIQUE (processing_run_id, attempt_number)
    )
    """,
    f"""
    CREATE TABLE model_responses (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        model_request_id TEXT NOT NULL UNIQUE CHECK ({_uuid_check("model_request_id")}),
        response_text TEXT NOT NULL,
        metadata_json TEXT NOT NULL CHECK ({_json_object_check("metadata_json")}),
        assistant_message_id TEXT UNIQUE CHECK (
            assistant_message_id IS NULL OR ({_uuid_check("assistant_message_id")})
        ),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (model_request_id) REFERENCES model_requests(id) ON DELETE RESTRICT,
        FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE validation_results (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        model_response_id TEXT NOT NULL UNIQUE CHECK ({_uuid_check("model_response_id")}),
        status TEXT NOT NULL CHECK (status IN ('PASSED', 'FAILED', 'NOT_RUN')),
        score REAL NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
        violations_json TEXT NOT NULL CHECK ({_json_array_check("violations_json")}),
        evidence_json TEXT NOT NULL CHECK ({_json_array_check("evidence_json")}),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (model_response_id) REFERENCES model_responses(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE correction_attempts (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        processing_run_id TEXT NOT NULL CHECK ({_uuid_check("processing_run_id")}),
        attempt_number INTEGER NOT NULL
            CHECK (typeof(attempt_number) = 'integer' AND attempt_number IN (1, 2)),
        prior_model_response_id TEXT NOT NULL
            CHECK ({_uuid_check("prior_model_response_id")}),
        revised_model_request_id TEXT NOT NULL
            CHECK ({_uuid_check("revised_model_request_id")}),
        reason_json TEXT NOT NULL CHECK ({_json_array_check("reason_json")}),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id) ON DELETE RESTRICT,
        FOREIGN KEY (prior_model_response_id) REFERENCES model_responses(id) ON DELETE RESTRICT,
        FOREIGN KEY (revised_model_request_id) REFERENCES model_requests(id) ON DELETE RESTRICT,
        UNIQUE (processing_run_id, attempt_number)
    )
    """,
    f"""
    CREATE TABLE clarification_requests (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        processing_run_id TEXT NOT NULL UNIQUE CHECK ({_uuid_check("processing_run_id")}),
        reason_code TEXT NOT NULL CHECK (reason_code IN (
            'AMBIGUOUS_REFERENCE', 'UNRESOLVED_REFERENCE',
            'LOW_CONFIDENCE_INTERPRETATION', 'HARD_CONSTRAINT_CONFLICT',
            'UNSUPPORTED_INTENT', 'UNSUPPORTED_CONDITION', 'MATERIAL_ASSUMPTION'
        )),
        question_text TEXT NOT NULL,
        details_json TEXT NOT NULL CHECK ({_json_object_check("details_json")}),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE pipeline_failures (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        processing_run_id TEXT NOT NULL CHECK ({_uuid_check("processing_run_id")}),
        stage TEXT NOT NULL CHECK (stage IN (
            'ACCEPTANCE', 'CONTEXT', 'REQUEST', 'TRANSPORT', 'VALIDATION', 'CORRECTION',
            'TERMINALIZATION', 'RECOVERY', 'MEMORY'
        )),
        error_code TEXT NOT NULL CHECK (error_code IN (
            'CONTEXT_BUDGET_EXCEEDED', 'PERSISTENCE_ERROR', 'CONCURRENCY_CONFLICT',
            'PROCESS_RESTARTED', 'CONFIGURATION_CHANGED', 'PROVIDER_UNAVAILABLE',
            'MODEL_NOT_FOUND', 'MODEL_TIMEOUT', 'MODEL_CANCELLED',
            'INVALID_PROVIDER_RESPONSE', 'VALIDATION_EXHAUSTED',
            'CONFIGURATION_INVALID', 'CANCELLED_BY_USER'
        )),
        safe_message TEXT NOT NULL,
        details_json TEXT NOT NULL CHECK ({_json_object_check("details_json")}),
        is_terminal INTEGER NOT NULL CHECK (is_terminal IN (0, 1)),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (processing_run_id) REFERENCES processing_runs(id) ON DELETE RESTRICT
    )
    """,
    f"""
    CREATE TABLE settings (
        key TEXT NOT NULL PRIMARY KEY CHECK (key IN (
            'ui.theme', 'ui.context_panel_visible', 'ui.last_selected_conversation_id'
        )),
        value_json TEXT NOT NULL CHECK (json_valid(value_json)),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")}),
        CHECK (
            CASE
                WHEN NOT json_valid(value_json) THEN 0
                WHEN key = 'ui.theme' THEN
                    json_type(value_json) = 'text'
                    AND json_extract(value_json, '$') IN ('SYSTEM', 'LIGHT', 'DARK')
                WHEN key = 'ui.context_panel_visible' THEN
                    json_type(value_json) IN ('true', 'false')
                WHEN key = 'ui.last_selected_conversation_id' THEN
                    json_type(value_json) = 'null'
                    OR (
                        json_type(value_json) = 'text'
                        AND ({_uuid_check("json_extract(value_json, '$')")})
                    )
                ELSE 0
            END
        )
    )
    """,
    f"""
    CREATE TABLE evaluation_cases (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        name TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL,
        case_json TEXT NOT NULL CHECK ({_json_object_check("case_json")}),
        enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        updated_at TEXT NOT NULL CHECK ({_utc_timestamp_check("updated_at")})
    )
    """,
    f"""
    CREATE TABLE evaluation_runs (
        id TEXT NOT NULL PRIMARY KEY CHECK ({_uuid_check("id")}),
        evaluation_case_id TEXT NOT NULL CHECK ({_uuid_check("evaluation_case_id")}),
        fixture_version TEXT NOT NULL,
        provider_mode TEXT NOT NULL CHECK (provider_mode IN ('MOCK', 'OLLAMA')),
        result_json TEXT NOT NULL CHECK ({_json_object_check("result_json")}),
        passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
        created_at TEXT NOT NULL CHECK ({_utc_timestamp_check("created_at")}),
        FOREIGN KEY (evaluation_case_id) REFERENCES evaluation_cases(id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE INDEX idx_messages_conversation_sequence
        ON messages (conversation_id, sequence_number)
    """,
    """
    CREATE INDEX idx_topics_conversation_normalized_label
        ON topics (conversation_id, normalized_label)
    """,
    """
    CREATE INDEX idx_tasks_conversation_status
        ON tasks (conversation_id, status)
    """,
    """
    CREATE INDEX idx_entity_registry_normalized_name_active
        ON entity_registry (normalized_name, is_active)
    """,
    """
    CREATE INDEX idx_reference_resolutions_run_mention
        ON reference_resolutions (processing_run_id, mention_ordinal)
    """,
    """
    CREATE INDEX idx_constraints_run_priority_ordinal
        ON constraints (processing_run_id, priority, ordinal)
    """,
    """
    CREATE INDEX idx_memories_project_status
        ON memories (project_id, status)
    """,
    """
    CREATE INDEX idx_memories_conversation_status
        ON memories (conversation_id, status)
    """,
    """
    CREATE INDEX idx_memory_revisions_memory_revision
        ON memory_revisions (memory_id, revision_number)
    """,
    """
    CREATE INDEX idx_processing_runs_conversation_status
        ON processing_runs (conversation_id, status)
    """,
    """
    CREATE UNIQUE INDEX uq_processing_runs_single_foreground
        ON processing_runs ((1))
        WHERE status IN ('PERSISTED', 'CONTEXT_READY', 'GENERATING', 'REVISING')
    """,
    """
    CREATE INDEX idx_model_requests_run_attempt
        ON model_requests (processing_run_id, attempt_number)
    """,
    """
    CREATE INDEX idx_validation_results_response
        ON validation_results (model_response_id)
    """,
    """
    CREATE INDEX idx_clarification_requests_run
        ON clarification_requests (processing_run_id)
    """,
    """
    CREATE INDEX idx_pipeline_failures_run_created
        ON pipeline_failures (processing_run_id, created_at)
    """,
)


MIGRATIONS = (
    Migration(
        version=1,
        name="canonical_mvp_schema",
        statements=_CANONICAL_SCHEMA_STATEMENTS,
    ),
)


def _validate_migration_order(migrations: tuple[Migration, ...]) -> None:
    versions = tuple(migration.version for migration in migrations)
    expected_versions = tuple(range(1, len(migrations) + 1))
    if versions != expected_versions:
        raise MigrationOrderError(
            "Canonical migrations must be ordered, contiguous, and start at version 1."
        )


def _read_and_validate_ledger(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...],
) -> tuple[int, ...]:
    ledger_columns = tuple(
        row[1] for row in connection.execute("PRAGMA table_info(schema_migrations)")
    )
    if ledger_columns != ("version", "checksum", "applied_at"):
        raise MigrationOrderError("The schema_migrations ledger has an unexpected shape.")

    ledger_rows = connection.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied_versions = tuple(row[0] for row in ledger_rows)
    migration_versions = tuple(migration.version for migration in migrations)
    if applied_versions != migration_versions[: len(applied_versions)]:
        raise MigrationOrderError(
            "Applied migration versions must be an ordered prefix of canonical migrations."
        )

    migrations_by_version = {migration.version: migration for migration in migrations}
    for version, stored_checksum in ledger_rows:
        expected_checksum = migrations_by_version[version].checksum
        if stored_checksum != expected_checksum:
            raise MigrationChecksumError(
                f"Applied migration {version} checksum does not match its definition."
            )
    return applied_versions


def _applied_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def apply_migrations(
    database_path: Path,
    *,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> Path:
    """Apply all pending migrations transactionally and validate prior checksums.

    The existing ledger-only bootstrap is version zero. Each migration is
    committed with its ledger row in one explicit transaction. A failed
    statement rolls back the complete migration and leaves the prior version
    intact. Reapplying an unchanged sequence is a no-op.
    """

    migration_sequence = tuple(migrations)
    _validate_migration_order(migration_sequence)
    try:
        resolved_path = initialize_migration_ledger(database_path)
        connection = connect_database(resolved_path)
    except PersistenceError as error:
        raise MigrationApplicationError("SQLite migration setup failed.") from error

    connection.isolation_level = None
    try:
        applied_versions = _read_and_validate_ledger(connection, migration_sequence)
        for migration in migration_sequence[len(applied_versions) :]:
            try:
                connection.execute("BEGIN IMMEDIATE")
                for statement in migration.statements:
                    connection.execute(statement)
                foreign_key_violations = connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                if foreign_key_violations:
                    raise sqlite3.IntegrityError(
                        "Migration introduced foreign-key violations."
                    )
                connection.execute(
                    """
                    INSERT INTO schema_migrations (version, checksum, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (migration.version, migration.checksum, _applied_at()),
                )
                connection.commit()
            except sqlite3.Error as error:
                if connection.in_transaction:
                    connection.rollback()
                raise MigrationApplicationError(
                    f"Migration {migration.version} ({migration.name}) failed; "
                    "its transaction was rolled back."
                ) from error
    finally:
        connection.close()
    return resolved_path
