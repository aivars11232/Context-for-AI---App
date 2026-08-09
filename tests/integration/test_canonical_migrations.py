"""Integration coverage for the complete TASK-0004 SQLite migration boundary."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from context_for_ai.infrastructure.database import (
    MIGRATIONS,
    Migration,
    MigrationApplicationError,
    MigrationChecksumError,
    MigrationOrderError,
    apply_migrations,
    connect_database,
    initialize_migration_ledger,
)


TIMESTAMP = "2026-08-02T12:00:00Z"
PROJECT_ID = "00000000-0000-4000-8000-000000000001"
CONVERSATION_ID = "00000000-0000-4000-8000-000000000002"
SECOND_CONVERSATION_ID = "00000000-0000-4000-8000-000000000003"
MESSAGE_ID = "00000000-0000-4000-8000-000000000004"
SECOND_MESSAGE_ID = "00000000-0000-4000-8000-000000000005"
RUN_ID = "00000000-0000-4000-8000-000000000006"
SECOND_RUN_ID = "00000000-0000-4000-8000-000000000007"
TERMINAL_RUN_ID = "00000000-0000-4000-8000-000000000008"
IDEMPOTENCY_KEY = "00000000-0000-4000-8000-000000000009"
SECOND_IDEMPOTENCY_KEY = "00000000-0000-4000-8000-00000000000a"
TERMINAL_IDEMPOTENCY_KEY = "00000000-0000-4000-8000-00000000000b"
OLD_FAILURE_ID = "00000000-0000-4000-8000-00000000000c"
NEW_FAILURE_ID = "00000000-0000-4000-8000-00000000000e"
INVALID_FAILURE_ID = "00000000-0000-4000-8000-00000000000f"
ORPHAN_FAILURE_ID = "00000000-0000-4000-8000-000000000010"
V1_CHECKSUM = "efc7f72d38daab138e4f8a1a9cbaaae8816195ec4265246a03b00bf1884aaf6e"
V1_FAILURE_CODES = (
    "CONTEXT_BUDGET_EXCEEDED",
    "PERSISTENCE_ERROR",
    "CONCURRENCY_CONFLICT",
    "PROCESS_RESTARTED",
    "CONFIGURATION_CHANGED",
    "PROVIDER_UNAVAILABLE",
    "MODEL_NOT_FOUND",
    "MODEL_TIMEOUT",
    "MODEL_CANCELLED",
    "INVALID_PROVIDER_RESPONSE",
    "VALIDATION_EXHAUSTED",
    "CONFIGURATION_INVALID",
    "CANCELLED_BY_USER",
)


EXPECTED_COLUMNS = {
    "schema_migrations": ("version", "checksum", "applied_at"),
    "projects": ("id", "name", "description", "status", "created_at", "updated_at"),
    "conversations": ("id", "project_id", "title", "created_at", "updated_at"),
    "topics": (
        "id",
        "conversation_id",
        "label",
        "normalized_label",
        "created_at",
        "updated_at",
    ),
    "tasks": (
        "id",
        "conversation_id",
        "topic_id",
        "title",
        "status",
        "created_at",
        "updated_at",
    ),
    "conversation_states": (
        "conversation_id",
        "active_topic_id",
        "active_task_id",
        "previous_task_id",
        "expected_output_type",
        "topic_stack_json",
        "version",
        "updated_at",
    ),
    "messages": (
        "id",
        "conversation_id",
        "role",
        "original_text",
        "created_at",
        "sequence_number",
    ),
    "named_items": (
        "id",
        "conversation_id",
        "project_id",
        "display_name",
        "normalized_name",
        "source_message_id",
        "created_at",
        "updated_at",
    ),
    "entity_registry": (
        "id",
        "entity_type",
        "native_id",
        "project_id",
        "display_name",
        "normalized_name",
        "source_message_id",
        "is_active",
        "created_at",
        "updated_at",
    ),
    "reference_resolutions": (
        "id",
        "processing_run_id",
        "message_id",
        "mention_ordinal",
        "surface_text",
        "status",
        "resolved_entity_id",
        "source_message_id",
        "confidence",
        "candidate_evidence_json",
        "created_at",
    ),
    "constraints": (
        "id",
        "processing_run_id",
        "message_id",
        "ordinal",
        "constraint_type",
        "underlying_constraint_type",
        "scope",
        "normalized_rule",
        "priority",
        "source_kind",
        "source_text",
        "confidence",
        "resolution_status",
        "conflict_group_id",
        "condition_json",
        "condition_evaluation",
        "created_at",
    ),
    "memories": (
        "id",
        "conversation_id",
        "project_id",
        "memory_type",
        "scope",
        "status",
        "content",
        "keywords_json",
        "topic_terms_json",
        "importance",
        "confidence",
        "expires_at",
        "created_at",
        "updated_at",
        "deleted_at",
    ),
    "memory_sources": (
        "id",
        "memory_id",
        "source_kind",
        "source_message_id",
        "description",
        "created_at",
    ),
    "memory_revisions": (
        "id",
        "memory_id",
        "revision_number",
        "operation",
        "content_snapshot",
        "metadata_json",
        "performed_by",
        "created_at",
    ),
    "processing_runs": (
        "id",
        "conversation_id",
        "user_message_id",
        "idempotency_key",
        "status",
        "state_version_at_start",
        "configuration_fingerprint",
        "started_at",
        "completed_at",
    ),
    "context_packets": (
        "id",
        "processing_run_id",
        "message_id",
        "packet_json",
        "schema_version",
        "prompt_policy_version",
        "configuration_fingerprint",
        "created_at",
    ),
    "retrieval_results": (
        "id",
        "context_packet_id",
        "memory_id",
        "rank",
        "score",
        "reasons_json",
        "created_at",
    ),
    "retrieval_exclusions": (
        "id",
        "context_packet_id",
        "memory_id",
        "exclusion_reason",
        "computed_score",
        "details_json",
        "created_at",
    ),
    "model_requests": (
        "id",
        "processing_run_id",
        "context_packet_id",
        "purpose",
        "attempt_number",
        "provider",
        "model_name",
        "status",
        "rendered_prompt",
        "request_json",
        "started_at",
        "completed_at",
        "error_code",
        "safe_error_message",
    ),
    "model_responses": (
        "id",
        "model_request_id",
        "response_text",
        "metadata_json",
        "assistant_message_id",
        "created_at",
    ),
    "validation_results": (
        "id",
        "model_response_id",
        "status",
        "score",
        "violations_json",
        "evidence_json",
        "created_at",
    ),
    "correction_attempts": (
        "id",
        "processing_run_id",
        "attempt_number",
        "prior_model_response_id",
        "revised_model_request_id",
        "reason_json",
        "created_at",
    ),
    "clarification_requests": (
        "id",
        "processing_run_id",
        "reason_code",
        "question_text",
        "details_json",
        "created_at",
    ),
    "pipeline_failures": (
        "id",
        "processing_run_id",
        "stage",
        "error_code",
        "safe_message",
        "details_json",
        "is_terminal",
        "created_at",
    ),
    "settings": ("key", "value_json", "updated_at"),
    "evaluation_cases": (
        "id",
        "name",
        "category",
        "case_json",
        "enabled",
        "created_at",
        "updated_at",
    ),
    "evaluation_runs": (
        "id",
        "evaluation_case_id",
        "fixture_version",
        "provider_mode",
        "result_json",
        "passed",
        "created_at",
    ),
}

INTEGER_COLUMNS = {
    ("schema_migrations", "version"),
    ("conversation_states", "version"),
    ("messages", "sequence_number"),
    ("entity_registry", "is_active"),
    ("reference_resolutions", "mention_ordinal"),
    ("constraints", "ordinal"),
    ("constraints", "priority"),
    ("memory_revisions", "revision_number"),
    ("processing_runs", "state_version_at_start"),
    ("retrieval_results", "rank"),
    ("model_requests", "attempt_number"),
    ("correction_attempts", "attempt_number"),
    ("pipeline_failures", "is_terminal"),
    ("evaluation_cases", "enabled"),
    ("evaluation_runs", "passed"),
}

REAL_COLUMNS = {
    ("reference_resolutions", "confidence"),
    ("constraints", "confidence"),
    ("memories", "importance"),
    ("memories", "confidence"),
    ("retrieval_results", "score"),
    ("retrieval_exclusions", "computed_score"),
    ("validation_results", "score"),
}

EXPECTED_EXPLICIT_INDEXES = {
    "idx_messages_conversation_sequence",
    "idx_topics_conversation_normalized_label",
    "idx_tasks_conversation_status",
    "idx_entity_registry_normalized_name_active",
    "idx_reference_resolutions_run_mention",
    "idx_constraints_run_priority_ordinal",
    "idx_memories_project_status",
    "idx_memories_conversation_status",
    "idx_memory_revisions_memory_revision",
    "idx_processing_runs_conversation_status",
    "uq_processing_runs_single_foreground",
    "idx_model_requests_run_attempt",
    "idx_validation_results_response",
    "idx_clarification_requests_run",
    "idx_pipeline_failures_run_created",
}

EXPECTED_INDEX_COLUMNS = {
    "idx_messages_conversation_sequence": ("conversation_id", "sequence_number"),
    "idx_topics_conversation_normalized_label": (
        "conversation_id",
        "normalized_label",
    ),
    "idx_tasks_conversation_status": ("conversation_id", "status"),
    "idx_entity_registry_normalized_name_active": ("normalized_name", "is_active"),
    "idx_reference_resolutions_run_mention": ("processing_run_id", "mention_ordinal"),
    "idx_constraints_run_priority_ordinal": (
        "processing_run_id",
        "priority",
        "ordinal",
    ),
    "idx_memories_project_status": ("project_id", "status"),
    "idx_memories_conversation_status": ("conversation_id", "status"),
    "idx_memory_revisions_memory_revision": ("memory_id", "revision_number"),
    "idx_processing_runs_conversation_status": ("conversation_id", "status"),
    "uq_processing_runs_single_foreground": (None,),
    "idx_model_requests_run_attempt": ("processing_run_id", "attempt_number"),
    "idx_validation_results_response": ("model_response_id",),
    "idx_clarification_requests_run": ("processing_run_id",),
    "idx_pipeline_failures_run_created": ("processing_run_id", "created_at"),
}

EXPECTED_FOREIGN_KEYS = {
    "conversations": {("project_id", "projects", "id")},
    "topics": {("conversation_id", "conversations", "id")},
    "tasks": {
        ("conversation_id", "conversations", "id"),
        ("topic_id", "topics", "id"),
    },
    "conversation_states": {
        ("conversation_id", "conversations", "id"),
        ("active_topic_id", "topics", "id"),
        ("active_task_id", "tasks", "id"),
        ("previous_task_id", "tasks", "id"),
    },
    "messages": {("conversation_id", "conversations", "id")},
    "named_items": {
        ("conversation_id", "conversations", "id"),
        ("project_id", "projects", "id"),
        ("source_message_id", "messages", "id"),
    },
    "entity_registry": {
        ("project_id", "projects", "id"),
        ("source_message_id", "messages", "id"),
    },
    "reference_resolutions": {
        ("processing_run_id", "processing_runs", "id"),
        ("message_id", "messages", "id"),
        ("resolved_entity_id", "entity_registry", "id"),
        ("source_message_id", "messages", "id"),
    },
    "constraints": {
        ("processing_run_id", "processing_runs", "id"),
        ("message_id", "messages", "id"),
    },
    "memories": {
        ("conversation_id", "conversations", "id"),
        ("project_id", "projects", "id"),
    },
    "memory_sources": {
        ("memory_id", "memories", "id"),
        ("source_message_id", "messages", "id"),
    },
    "memory_revisions": {("memory_id", "memories", "id")},
    "processing_runs": {
        ("conversation_id", "conversations", "id"),
        ("user_message_id", "messages", "id"),
    },
    "context_packets": {
        ("processing_run_id", "processing_runs", "id"),
        ("message_id", "messages", "id"),
    },
    "retrieval_results": {
        ("context_packet_id", "context_packets", "id"),
        ("memory_id", "memories", "id"),
    },
    "retrieval_exclusions": {
        ("context_packet_id", "context_packets", "id"),
        ("memory_id", "memories", "id"),
    },
    "model_requests": {
        ("processing_run_id", "processing_runs", "id"),
        ("context_packet_id", "context_packets", "id"),
    },
    "model_responses": {
        ("model_request_id", "model_requests", "id"),
        ("assistant_message_id", "messages", "id"),
    },
    "validation_results": {("model_response_id", "model_responses", "id")},
    "correction_attempts": {
        ("processing_run_id", "processing_runs", "id"),
        ("prior_model_response_id", "model_responses", "id"),
        ("revised_model_request_id", "model_requests", "id"),
    },
    "clarification_requests": {("processing_run_id", "processing_runs", "id")},
    "pipeline_failures": {("processing_run_id", "processing_runs", "id")},
    "evaluation_runs": {("evaluation_case_id", "evaluation_cases", "id")},
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    }


def _insert_conversation_and_message(
    connection: sqlite3.Connection,
    *,
    conversation_id: str,
    message_id: str,
    sequence_number: int,
) -> None:
    connection.execute(
        """
        INSERT INTO conversations (id, project_id, title, created_at, updated_at)
        VALUES (?, NULL, NULL, ?, ?)
        """,
        (conversation_id, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO messages (
            id, conversation_id, role, original_text, created_at, sequence_number
        ) VALUES (?, ?, 'USER', 'message', ?, ?)
        """,
        (message_id, conversation_id, TIMESTAMP, sequence_number),
    )


def _insert_pipeline_failure(
    connection: sqlite3.Connection,
    *,
    failure_id: str,
    processing_run_id: str = RUN_ID,
    error_code: str,
) -> None:
    connection.execute(
        """
        INSERT INTO pipeline_failures (
            id, processing_run_id, stage, error_code, safe_message,
            details_json, is_terminal, created_at
        ) VALUES (?, ?, 'CONTEXT', ?, 'safe message', '{"component":"PACKET_BUILD"}', 1, ?)
        """,
        (failure_id, processing_run_id, error_code, TIMESTAMP),
    )


def _pipeline_failure_index_metadata(
    connection: sqlite3.Connection,
) -> dict[str, tuple[object, ...]]:
    return {
        str(row[1]): (
            row[2],
            row[3],
            row[4],
            tuple(
                index_row[2]
                for index_row in connection.execute(f"PRAGMA index_info({row[1]})")
            ),
        )
        for row in connection.execute("PRAGMA index_list(pipeline_failures)")
    }


def test_fresh_apply_and_reapply_are_exact_and_idempotent(tmp_path: Path) -> None:
    database_path = apply_migrations(tmp_path / "fresh.sqlite3")

    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO settings (key, value_json, updated_at)
            VALUES ('ui.theme', '"SYSTEM"', ?)
            """,
            (TIMESTAMP,),
        )
        schema_before = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
        ledger_before = connection.execute(
            "SELECT version, checksum, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        settings_before = connection.execute(
            "SELECT key, value_json, updated_at FROM settings"
        ).fetchall()

    assert apply_migrations(database_path) == database_path

    with connect_database(database_path) as connection:
        schema_after = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
            ORDER BY type, name
            """
        ).fetchall()
        ledger_after = connection.execute(
            "SELECT version, checksum, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        settings_after = connection.execute(
            "SELECT key, value_json, updated_at FROM settings"
        ).fetchall()
        ledger_counts = connection.execute(
            "SELECT version, count(*) FROM schema_migrations GROUP BY version"
        ).fetchall()

    assert schema_after == schema_before
    assert settings_after == settings_before
    assert ledger_after == ledger_before
    assert MIGRATIONS[0].checksum == V1_CHECKSUM
    assert [row[:2] for row in ledger_after] == [
        (migration.version, migration.checksum) for migration in MIGRATIONS
    ]
    assert ledger_counts == [(migration.version, 1) for migration in MIGRATIONS]


def test_version_zero_ledger_upgrades_to_the_complete_canonical_schema(
    tmp_path: Path,
) -> None:
    database_path = initialize_migration_ledger(tmp_path / "upgrade.sqlite3")
    with connect_database(database_path) as connection:
        assert _table_names(connection) == {"schema_migrations"}
        assert connection.execute("SELECT * FROM schema_migrations").fetchall() == []

    apply_migrations(database_path)

    with connect_database(database_path) as connection:
        assert _table_names(connection) == set(EXPECTED_COLUMNS)
        assert connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall() == [
            (migration.version, migration.checksum) for migration in MIGRATIONS
        ]


def test_version_one_upgrade_widens_only_pipeline_failure_error_code(
    tmp_path: Path,
) -> None:
    database_path = apply_migrations(
        tmp_path / "upgrade-v1.sqlite3",
        migrations=MIGRATIONS[:1],
    )

    with connect_database(database_path) as connection:
        assert MIGRATIONS[0].checksum == V1_CHECKSUM
        assert connection.execute(
            "SELECT version, checksum FROM schema_migrations"
        ).fetchall() == [(1, V1_CHECKSUM)]
        _insert_conversation_and_message(
            connection,
            conversation_id=CONVERSATION_ID,
            message_id=MESSAGE_ID,
            sequence_number=0,
        )
        connection.execute(
            """
            INSERT INTO processing_runs (
                id, conversation_id, user_message_id, idempotency_key, status,
                state_version_at_start, configuration_fingerprint, started_at, completed_at
            ) VALUES (?, ?, ?, ?, 'CONTROLLED_FAILURE', 0, 'fingerprint', ?, ?)
            """,
            (
                RUN_ID,
                CONVERSATION_ID,
                MESSAGE_ID,
                IDEMPOTENCY_KEY,
                TIMESTAMP,
                TIMESTAMP,
            ),
        )
        connection.execute(
            """
            INSERT INTO settings (key, value_json, updated_at)
            VALUES ('ui.theme', '"DARK"', ?)
            """,
            (TIMESTAMP,),
        )
        _insert_pipeline_failure(
            connection,
            failure_id=OLD_FAILURE_ID,
            error_code="PERSISTENCE_ERROR",
        )
        columns_before = connection.execute(
            "PRAGMA table_info(pipeline_failures)"
        ).fetchall()
        foreign_keys_before = connection.execute(
            "PRAGMA foreign_key_list(pipeline_failures)"
        ).fetchall()
        indexes_before = _pipeline_failure_index_metadata(connection)
        explicit_index_sql_before = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_pipeline_failures_run_created'
            """
        ).fetchone()
        failure_rows_before = connection.execute(
            "SELECT * FROM pipeline_failures ORDER BY id"
        ).fetchall()
        settings_before = connection.execute(
            "SELECT * FROM settings ORDER BY key"
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            _insert_pipeline_failure(
                connection,
                failure_id=NEW_FAILURE_ID,
                error_code="CONTEXT_CONSTRUCTION_FAILED",
            )
        assert connection.execute(
            "SELECT count(*) FROM pipeline_failures"
        ).fetchone() == (1,)

    apply_migrations(database_path)

    with connect_database(database_path) as connection:
        assert connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall() == [
            (migration.version, migration.checksum) for migration in MIGRATIONS
        ]
        assert connection.execute(
            "PRAGMA table_info(pipeline_failures)"
        ).fetchall() == columns_before
        assert connection.execute(
            "PRAGMA foreign_key_list(pipeline_failures)"
        ).fetchall() == foreign_keys_before
        assert _pipeline_failure_index_metadata(connection) == indexes_before
        assert connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_pipeline_failures_run_created'
            """
        ).fetchone() == explicit_index_sql_before
        assert connection.execute(
            "SELECT * FROM pipeline_failures ORDER BY id"
        ).fetchall() == failure_rows_before
        assert connection.execute(
            "SELECT * FROM settings ORDER BY key"
        ).fetchall() == settings_before
        assert "pipeline_failures_v2" not in _table_names(connection)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        for identifier_number, error_code in enumerate(V1_FAILURE_CODES, start=0x20):
            _insert_pipeline_failure(
                connection,
                failure_id=(
                    f"00000000-0000-4000-8000-{identifier_number:012x}"
                ),
                error_code=error_code,
            )
        _insert_pipeline_failure(
            connection,
            failure_id=NEW_FAILURE_ID,
            error_code="CONTEXT_CONSTRUCTION_FAILED",
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_pipeline_failure(
                connection,
                failure_id=INVALID_FAILURE_ID,
                error_code="NOT_A_FAILURE_CODE",
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_pipeline_failure(
                connection,
                failure_id=ORPHAN_FAILURE_ID,
                processing_run_id=SECOND_RUN_ID,
                error_code="CONTEXT_CONSTRUCTION_FAILED",
            )
        assert connection.execute(
            "SELECT error_code FROM pipeline_failures ORDER BY id"
        ).fetchall() == [
            ("PERSISTENCE_ERROR",),
            ("CONTEXT_CONSTRUCTION_FAILED",),
            *((error_code,) for error_code in V1_FAILURE_CODES),
        ]


def test_schema_has_exact_columns_types_indexes_and_restrictive_foreign_keys(
    tmp_path: Path,
) -> None:
    database_path = apply_migrations(tmp_path / "shape.sqlite3")

    with connect_database(database_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert _table_names(connection) == set(EXPECTED_COLUMNS)
        assert "references" not in _table_names(connection)
        connection.execute("SELECT * FROM reference_resolutions").fetchall()

        non_table_objects = connection.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('view', 'trigger')"
        ).fetchall()
        assert non_table_objects == []

        for table_name, expected_columns in EXPECTED_COLUMNS.items():
            table_info = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            assert tuple(row[1] for row in table_info) == expected_columns
            for row in table_info:
                column_name = row[1]
                expected_type = (
                    "INTEGER"
                    if (table_name, column_name) in INTEGER_COLUMNS
                    else "REAL"
                    if (table_name, column_name) in REAL_COLUMNS
                    else "TEXT"
                )
                assert row[2] == expected_type

            foreign_key_rows = connection.execute(
                f"PRAGMA foreign_key_list({table_name})"
            ).fetchall()
            actual_foreign_keys = {(row[3], row[2], row[4]) for row in foreign_key_rows}
            assert actual_foreign_keys == EXPECTED_FOREIGN_KEYS.get(table_name, set())
            assert {row[6] for row in foreign_key_rows} <= {"RESTRICT"}

        explicit_index_rows = connection.execute(
            """
            SELECT name, sql
            FROM sqlite_master
            WHERE type = 'index' AND sql IS NOT NULL
            ORDER BY name
            """
        ).fetchall()
        assert {row[0] for row in explicit_index_rows} == EXPECTED_EXPLICIT_INDEXES
        for index_name, expected_columns in EXPECTED_INDEX_COLUMNS.items():
            index_columns = connection.execute(
                f"PRAGMA index_info({index_name})"
            ).fetchall()
            assert tuple(row[2] for row in index_columns) == expected_columns

        processing_run_indexes = {
            row[1]: (row[2], row[4])
            for row in connection.execute("PRAGMA index_list(processing_runs)")
        }
        assert processing_run_indexes["uq_processing_runs_single_foreground"] == (1, 1)
        foreground_index_sql = dict(explicit_index_rows)[
            "uq_processing_runs_single_foreground"
        ]
        for status in ("PERSISTED", "CONTEXT_READY", "GENERATING", "REVISING"):
            assert status in foreground_index_sql


def test_documented_checks_foreign_keys_and_global_run_guard_reject_invalid_rows(
    tmp_path: Path,
) -> None:
    database_path = apply_migrations(tmp_path / "constraints.sqlite3")

    with connect_database(database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO projects (id, name, status, created_at, updated_at)
                VALUES (?, 'invalid status', 'UNKNOWN', ?, ?)
                """,
                (PROJECT_ID, TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO projects (id, name, status, created_at, updated_at)
                VALUES ('not-a-uuid', 'invalid id', 'ACTIVE', ?, ?)
                """,
                (TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO projects (id, name, status, created_at, updated_at)
                VALUES (?, 'invalid time', 'ACTIVE', 'not-a-time', ?)
                """,
                (PROJECT_ID, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO conversations (id, project_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (CONVERSATION_ID, PROJECT_ID, TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO evaluation_cases (
                    id, name, category, case_json, enabled, created_at, updated_at
                ) VALUES (?, 'bad json', 'category', '[]', 1, ?, ?)
                """,
                (RUN_ID, TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO evaluation_cases (
                    id, name, category, case_json, enabled, created_at, updated_at
                ) VALUES (?, 'bad boolean', 'category', '{}', 2, ?, ?)
                """,
                (RUN_ID, TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memories (
                    id, conversation_id, project_id, memory_type, scope, status,
                    content, keywords_json, topic_terms_json, importance, confidence,
                    expires_at, created_at, updated_at, deleted_at
                ) VALUES (?, NULL, NULL, 'PROJECT_FACT', 'GLOBAL', 'ACTIVE',
                          'content', '[]', '[]', 1.1, 1.0, NULL, ?, ?, NULL)
                """,
                (RUN_ID, TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memories (
                    id, conversation_id, project_id, memory_type, scope, status,
                    content, keywords_json, topic_terms_json, importance, confidence,
                    expires_at, created_at, updated_at, deleted_at
                ) VALUES (?, NULL, NULL, 'PROJECT_FACT', 'GLOBAL', 'DELETED',
                          'content', '[]', '[]', 1.0, 1.0, NULL, ?, ?, NULL)
                """,
                (RUN_ID, TIMESTAMP, TIMESTAMP),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES ('model.name', '"forbidden"', ?)
                """,
                (TIMESTAMP,),
            )

        connection.execute(
            """
            INSERT INTO projects (id, name, status, created_at, updated_at)
            VALUES (?, 'project', 'ACTIVE', ?, ?)
            """,
            (PROJECT_ID, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """
            INSERT INTO conversations (id, project_id, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (CONVERSATION_ID, PROJECT_ID, TIMESTAMP, TIMESTAMP),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM projects WHERE id = ?", (PROJECT_ID,))

        connection.execute("DELETE FROM conversations WHERE id = ?", (CONVERSATION_ID,))
        _insert_conversation_and_message(
            connection,
            conversation_id=CONVERSATION_ID,
            message_id=MESSAGE_ID,
            sequence_number=0,
        )
        _insert_conversation_and_message(
            connection,
            conversation_id=SECOND_CONVERSATION_ID,
            message_id=SECOND_MESSAGE_ID,
            sequence_number=0,
        )
        connection.execute(
            """
            INSERT INTO processing_runs (
                id, conversation_id, user_message_id, idempotency_key, status,
                state_version_at_start, configuration_fingerprint, started_at, completed_at
            ) VALUES (?, ?, ?, ?, 'PERSISTED', 0, 'fingerprint', ?, NULL)
            """,
            (RUN_ID, CONVERSATION_ID, MESSAGE_ID, IDEMPOTENCY_KEY, TIMESTAMP),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO reference_resolutions (
                    id, processing_run_id, message_id, mention_ordinal, surface_text,
                    status, resolved_entity_id, source_message_id, confidence,
                    candidate_evidence_json, created_at
                ) VALUES (?, ?, ?, 0, 'it', 'RESOLVED', NULL, NULL, 1.0, '[]', ?)
                """,
                (
                    "00000000-0000-4000-8000-00000000000c",
                    RUN_ID,
                    MESSAGE_ID,
                    TIMESTAMP,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO constraints (
                    id, processing_run_id, message_id, ordinal, constraint_type,
                    underlying_constraint_type, scope, normalized_rule, priority,
                    source_kind, source_text, confidence, resolution_status,
                    conflict_group_id, condition_json, condition_evaluation, created_at
                ) VALUES (?, ?, ?, 0, 'CONDITIONAL', NULL, 'CURRENT_RESPONSE',
                          'MUST_TEST', 900, 'CURRENT_MESSAGE', 'if test', 1.0,
                          'ACTIVE', NULL, NULL, NULL, ?)
                """,
                (
                    "00000000-0000-4000-8000-00000000000d",
                    RUN_ID,
                    MESSAGE_ID,
                    TIMESTAMP,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO processing_runs (
                    id, conversation_id, user_message_id, idempotency_key, status,
                    state_version_at_start, configuration_fingerprint, started_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, 'GENERATING', 0, 'fingerprint', ?, NULL)
                """,
                (
                    SECOND_RUN_ID,
                    SECOND_CONVERSATION_ID,
                    SECOND_MESSAGE_ID,
                    SECOND_IDEMPOTENCY_KEY,
                    TIMESTAMP,
                ),
            )
        connection.execute(
            """
            INSERT INTO processing_runs (
                id, conversation_id, user_message_id, idempotency_key, status,
                state_version_at_start, configuration_fingerprint, started_at, completed_at
            ) VALUES (?, ?, ?, ?, 'SUCCEEDED', 0, 'fingerprint', ?, ?)
            """,
            (
                TERMINAL_RUN_ID,
                SECOND_CONVERSATION_ID,
                SECOND_MESSAGE_ID,
                TERMINAL_IDEMPOTENCY_KEY,
                TIMESTAMP,
                TIMESTAMP,
            ),
        )


def test_failed_migration_rolls_back_schema_and_ledger_version(tmp_path: Path) -> None:
    database_path = apply_migrations(tmp_path / "rollback.sqlite3")
    failing_migration = Migration(
        version=len(MIGRATIONS) + 1,
        name="forced_failure",
        statements=(
            "CREATE TABLE should_roll_back (id INTEGER PRIMARY KEY)",
            "CREATE TABLE invalid_sql (",
        ),
    )

    with pytest.raises(MigrationApplicationError):
        apply_migrations(database_path, migrations=(*MIGRATIONS, failing_migration))

    with connect_database(database_path) as connection:
        assert "should_roll_back" not in _table_names(connection)
        assert connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall() == [
            (migration.version, migration.checksum) for migration in MIGRATIONS
        ]


def test_checksum_and_order_validation_reject_mutated_history(tmp_path: Path) -> None:
    checksum_database = apply_migrations(tmp_path / "checksum.sqlite3")
    with connect_database(checksum_database) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1"
        )

    with pytest.raises(MigrationChecksumError):
        apply_migrations(checksum_database)

    out_of_order = Migration(
        version=2,
        name="not_version_one",
        statements=("CREATE TABLE never_applied (id INTEGER PRIMARY KEY)",),
    )
    with pytest.raises(MigrationOrderError):
        apply_migrations(tmp_path / "order.sqlite3", migrations=(out_of_order,))
    assert not (tmp_path / "order.sqlite3").exists()
