"""SQLite adapters for the canonical inward persistence protocols."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import json
import sqlite3
from typing import Callable, TypeVar

from context_for_ai.context_engine.normalization import (
    find_phrase_matches,
    normalize_display_label,
    normalize_phrase,
    normalize_text,
)
from context_for_ai.domain.decisions import (
    Condition,
    Constraint,
    ContextPacket,
    ReferenceCandidateEvidence,
    ReferenceOutcome,
    RetrievalExclusion,
    RetrievalResult,
)
from context_for_ai.domain.entities import (
    Conversation,
    ConversationState,
    ConversationTask,
    Entity,
    Memory,
    MemoryRevision,
    MemorySource,
    Message,
    NamedItem,
    Project,
    Topic,
)
from context_for_ai.domain.enums import (
    ClarificationReason,
    ConditionEvaluation,
    ConditionKind,
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    EntityType,
    EvaluationProviderMode,
    FailureCode,
    LocalActor,
    MemoryRevisionOperation,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    OutputType,
    PipelineStage,
    ProcessingRunStatus,
    ProjectStatus,
    ProviderKind,
    ReferenceRankReason,
    ReferenceStatus,
    RetrievalExclusionReason,
    TaskStatus,
    ValidationStatus,
)
from context_for_ai.domain.errors import DomainError, LifecycleInvariantError
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
    CorrectionAttempt,
    ModelRequest,
    ModelResponse,
    ProcessingRun,
    SafeFailure,
    ValidationResult,
)
from context_for_ai.domain.policies import (
    NON_TERMINAL_PROCESSING_RUN_STATUSES,
    TERMINAL_PROCESSING_RUN_STATUSES,
    is_terminal_task,
    require_model_request_transition,
    require_processing_run_transition,
    require_project_transition,
    require_task_transition,
)
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.ports.records import (
    ContextPacketRecord,
    EvaluationCase,
    EvaluationRun,
    MemoryRecord,
    Setting,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    FrozenJsonValue,
    UnitScore,
    canonical_json,
    format_utc_timestamp,
    freeze_json,
    parse_utc_timestamp,
    parse_canonical_json_object,
)


_T = TypeVar("_T")
_RowMapper = Callable[[sqlite3.Row], _T]


def _rollback_owned(connection: sqlite3.Connection, owns_transaction: bool) -> None:
    if owns_transaction and connection.in_transaction:
        try:
            connection.rollback()
        except sqlite3.Error as error:
            raise PersistenceError("SQLite transaction rollback failed.") from error


@contextmanager
def _write_transaction(
    connection: sqlite3.Connection,
    operation: str,
) -> Iterator[None]:
    """Run one write atomically, joining an explicit outer transaction if present."""

    owns_transaction = not connection.in_transaction
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        yield
        if owns_transaction:
            connection.commit()
    except sqlite3.IntegrityError as error:
        _rollback_owned(connection, owns_transaction)
        raise PersistenceError(
            f"{operation} violated a SQLite integrity constraint."
        ) from error
    except sqlite3.Error as error:
        _rollback_owned(connection, owns_transaction)
        raise PersistenceError(f"{operation} failed in SQLite.") from error
    except BaseException:
        _rollback_owned(connection, owns_transaction)
        raise


class SQLiteTransactionBoundary:
    """Open short explicit SQLite transactions for multi-repository operations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    def transaction(self) -> AbstractContextManager[None]:
        return _write_transaction(self._connection, "SQLite transaction")


def _fetch_one(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...],
    operation: str,
) -> sqlite3.Row | None:
    try:
        return connection.execute(sql, parameters).fetchone()
    except sqlite3.Error as error:
        raise PersistenceError(f"{operation} failed in SQLite.") from error


def _fetch_all(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...],
    operation: str,
) -> tuple[sqlite3.Row, ...]:
    try:
        return tuple(connection.execute(sql, parameters).fetchall())
    except sqlite3.Error as error:
        raise PersistenceError(f"{operation} failed in SQLite.") from error


def _map_row(row: sqlite3.Row, mapper: _RowMapper[_T], record_name: str) -> _T:
    try:
        return mapper(row)
    except PersistenceError:
        raise
    except (DomainError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PersistenceError(
            f"Stored {record_name} could not be mapped to its domain record."
        ) from error


def _map_rows(
    rows: tuple[sqlite3.Row, ...],
    mapper: _RowMapper[_T],
    record_name: str,
) -> tuple[_T, ...]:
    return tuple(_map_row(row, mapper, record_name) for row in rows)


def _optional_id(value: object) -> DomainId | None:
    return None if value is None else DomainId(str(value))


def _optional_time(value: object) -> datetime | None:
    return None if value is None else parse_utc_timestamp(str(value))


def _thaw_json(value: FrozenJsonValue) -> object:
    if isinstance(value, FrozenJsonObject):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _encode_json(value: FrozenJsonValue) -> str:
    try:
        return json.dumps(
            _thaw_json(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise PersistenceError("A persistence JSON value could not be encoded.") from error


def _decode_json(value: object) -> FrozenJsonValue:
    try:
        return freeze_json(json.loads(str(value)))
    except (DomainError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PersistenceError("Stored JSON is not a valid immutable JSON value.") from error


def _decode_json_object(value: object) -> FrozenJsonObject:
    decoded = _decode_json(value)
    if not isinstance(decoded, FrozenJsonObject):
        raise PersistenceError("Stored JSON must be an object.")
    return decoded


def _encode_packet_json(value: FrozenJsonObject) -> str:
    try:
        return canonical_json(value)
    except DomainError as error:
        raise PersistenceError("Context packet JSON is not canonical.") from error


def _decode_packet_json(value: object) -> FrozenJsonObject:
    try:
        packet = _thaw_json(parse_canonical_json_object(str(value)))
        if not isinstance(packet, dict):
            raise PersistenceError("Stored context packet JSON must be an object.")

        def exact_decimal(raw: object) -> object:
            return Decimal(raw) if isinstance(raw, int) and not isinstance(raw, bool) else raw

        request = packet["request"]
        request["confidence"] = exact_decimal(request["confidence"])
        for reference in packet["references"]:
            reference["confidence"] = exact_decimal(reference["confidence"])
            for evidence in reference["evidence"]:
                evidence["score"] = exact_decimal(evidence["score"])
        for constraint in packet["constraints"]:
            constraint["confidence"] = exact_decimal(constraint["confidence"])
        for selected in packet["retrieval"]:
            selected["score"] = exact_decimal(selected["score"])
            selected["confidence"] = exact_decimal(selected["confidence"])
        confidence = packet["confidence"]
        for key in ("interpretation", "references", "retrieval", "overall"):
            confidence[key] = exact_decimal(confidence[key])
        return FrozenJsonObject(packet)
    except (DomainError, KeyError, TypeError) as error:
        raise PersistenceError("Stored context packet JSON is not canonical.") from error


def _decode_json_array(value: object) -> tuple[FrozenJsonValue, ...]:
    decoded = _decode_json(value)
    if not isinstance(decoded, tuple):
        raise PersistenceError("Stored JSON must be an array.")
    return decoded


def _decode_text_array(value: object) -> tuple[str, ...]:
    decoded = _decode_json_array(value)
    if any(not isinstance(item, str) for item in decoded):
        raise PersistenceError("Stored JSON array must contain only text values.")
    return tuple(item for item in decoded if isinstance(item, str))


def _decode_object_array(value: object) -> tuple[FrozenJsonObject, ...]:
    decoded = _decode_json_array(value)
    if any(not isinstance(item, FrozenJsonObject) for item in decoded):
        raise PersistenceError("Stored JSON array must contain only objects.")
    return tuple(item for item in decoded if isinstance(item, FrozenJsonObject))


def _project(row: sqlite3.Row) -> Project:
    return Project(
        DomainId(str(row["id"])),
        str(row["name"]),
        None if row["description"] is None else str(row["description"]),
        ProjectStatus(str(row["status"])),
        parse_utc_timestamp(str(row["created_at"])),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        DomainId(str(row["id"])),
        _optional_id(row["project_id"]),
        None if row["title"] is None else str(row["title"]),
        parse_utc_timestamp(str(row["created_at"])),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _topic(row: sqlite3.Row) -> Topic:
    return Topic(
        DomainId(str(row["id"])),
        DomainId(str(row["conversation_id"])),
        str(row["label"]),
        str(row["normalized_label"]),
        parse_utc_timestamp(str(row["created_at"])),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _task(row: sqlite3.Row) -> ConversationTask:
    return ConversationTask(
        DomainId(str(row["id"])),
        DomainId(str(row["conversation_id"])),
        _optional_id(row["topic_id"]),
        str(row["title"]),
        TaskStatus(str(row["status"])),
        parse_utc_timestamp(str(row["created_at"])),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _conversation_state(row: sqlite3.Row) -> ConversationState:
    topic_stack = _decode_text_array(row["topic_stack_json"])
    return ConversationState(
        DomainId(str(row["conversation_id"])),
        _optional_id(row["active_topic_id"]),
        _optional_id(row["active_task_id"]),
        _optional_id(row["previous_task_id"]),
        None
        if row["expected_output_type"] is None
        else OutputType(str(row["expected_output_type"])),
        tuple(DomainId(value) for value in topic_stack),
        int(row["version"]),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _message(row: sqlite3.Row) -> Message:
    return Message(
        DomainId(str(row["id"])),
        DomainId(str(row["conversation_id"])),
        MessageRole(str(row["role"])),
        str(row["original_text"]),
        parse_utc_timestamp(str(row["created_at"])),
        int(row["sequence_number"]),
    )


def _named_item(row: sqlite3.Row) -> NamedItem:
    return NamedItem(
        DomainId(str(row["id"])),
        DomainId(str(row["conversation_id"])),
        _optional_id(row["project_id"]),
        str(row["display_name"]),
        str(row["normalized_name"]),
        _optional_id(row["source_message_id"]),
        parse_utc_timestamp(str(row["created_at"])),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _entity(row: sqlite3.Row) -> Entity:
    return Entity(
        DomainId(str(row["id"])),
        EntityType(str(row["entity_type"])),
        DomainId(str(row["native_id"])),
        _optional_id(row["project_id"]),
        str(row["display_name"]),
        str(row["normalized_name"]),
        _optional_id(row["source_message_id"]),
        bool(row["is_active"]),
        parse_utc_timestamp(str(row["created_at"])),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _reference_outcome(row: sqlite3.Row) -> ReferenceOutcome:
    return ReferenceOutcome(
        DomainId(str(row["id"])),
        DomainId(str(row["processing_run_id"])),
        DomainId(str(row["message_id"])),
        int(row["mention_ordinal"]),
        str(row["surface_text"]),
        ReferenceStatus(str(row["status"])),
        _optional_id(row["resolved_entity_id"]),
        _optional_id(row["source_message_id"]),
        UnitScore(row["confidence"]),
        tuple(
            ReferenceCandidateEvidence.from_json_object(item)
            for item in _decode_object_array(row["candidate_evidence_json"])
        ),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _condition(row: sqlite3.Row) -> Condition | None:
    if row["condition_json"] is None:
        return None
    stored = _decode_json_object(row["condition_json"])
    condition = Condition(
        str(stored["grammar_version"]),
        ConditionKind(str(stored["kind"])),
        str(stored["expected_value"]),
        ConditionEvaluation(str(stored["evaluation"])),
    )
    if row["condition_evaluation"] != condition.evaluation.value:
        raise PersistenceError(
            "Stored condition evaluation disagrees with its JSON representation."
        )
    return condition


def _constraint(row: sqlite3.Row) -> Constraint:
    return Constraint(
        DomainId(str(row["id"])),
        DomainId(str(row["processing_run_id"])),
        DomainId(str(row["message_id"])),
        int(row["ordinal"]),
        ConstraintType(str(row["constraint_type"])),
        None
        if row["underlying_constraint_type"] is None
        else ConstraintType(str(row["underlying_constraint_type"])),
        ConstraintScope(str(row["scope"])),
        str(row["normalized_rule"]),
        int(row["priority"]),
        ConstraintSourceKind(str(row["source_kind"])),
        str(row["source_text"]),
        UnitScore(row["confidence"]),
        ConstraintResolutionStatus(str(row["resolution_status"])),
        None
        if row["conflict_group_id"] is None
        else str(row["conflict_group_id"]),
        _condition(row),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _memory(row: sqlite3.Row) -> Memory:
    return Memory(
        DomainId(str(row["id"])),
        _optional_id(row["conversation_id"]),
        _optional_id(row["project_id"]),
        MemoryType(str(row["memory_type"])),
        MemoryScope(str(row["scope"])),
        MemoryStatus(str(row["status"])),
        str(row["content"]),
        _decode_text_array(row["keywords_json"]),
        _decode_text_array(row["topic_terms_json"]),
        UnitScore(row["importance"]),
        UnitScore(row["confidence"]),
        _optional_time(row["expires_at"]),
        parse_utc_timestamp(str(row["created_at"])),
        parse_utc_timestamp(str(row["updated_at"])),
        _optional_time(row["deleted_at"]),
    )


def _memory_source(row: sqlite3.Row) -> MemorySource:
    return MemorySource(
        DomainId(str(row["id"])),
        DomainId(str(row["memory_id"])),
        MemorySourceKind(str(row["source_kind"])),
        _optional_id(row["source_message_id"]),
        str(row["description"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _memory_revision(row: sqlite3.Row) -> MemoryRevision:
    return MemoryRevision(
        DomainId(str(row["id"])),
        DomainId(str(row["memory_id"])),
        int(row["revision_number"]),
        MemoryRevisionOperation(str(row["operation"])),
        str(row["content_snapshot"]),
        _decode_json_object(row["metadata_json"]),
        LocalActor(str(row["performed_by"])),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _processing_run(row: sqlite3.Row) -> ProcessingRun:
    return ProcessingRun(
        DomainId(str(row["id"])),
        DomainId(str(row["conversation_id"])),
        DomainId(str(row["user_message_id"])),
        str(row["idempotency_key"]),
        ProcessingRunStatus(str(row["status"])),
        int(row["state_version_at_start"]),
        str(row["configuration_fingerprint"]),
        parse_utc_timestamp(str(row["started_at"])),
        _optional_time(row["completed_at"]),
    )


def _context_packet(row: sqlite3.Row) -> ContextPacket:
    return ContextPacket(
        DomainId(str(row["id"])),
        DomainId(str(row["processing_run_id"])),
        DomainId(str(row["message_id"])),
        _decode_packet_json(row["packet_json"]),
        str(row["schema_version"]),
        str(row["prompt_policy_version"]),
        str(row["configuration_fingerprint"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _retrieval_result(row: sqlite3.Row) -> RetrievalResult:
    return RetrievalResult(
        DomainId(str(row["id"])),
        DomainId(str(row["context_packet_id"])),
        DomainId(str(row["memory_id"])),
        int(row["rank"]),
        UnitScore(row["score"]),
        _decode_text_array(row["reasons_json"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _retrieval_exclusion(row: sqlite3.Row) -> RetrievalExclusion:
    return RetrievalExclusion(
        DomainId(str(row["id"])),
        DomainId(str(row["context_packet_id"])),
        DomainId(str(row["memory_id"])),
        RetrievalExclusionReason(str(row["exclusion_reason"])),
        None if row["computed_score"] is None else UnitScore(row["computed_score"]),
        _decode_json_object(row["details_json"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _model_request(row: sqlite3.Row) -> ModelRequest:
    return ModelRequest(
        DomainId(str(row["id"])),
        DomainId(str(row["processing_run_id"])),
        DomainId(str(row["context_packet_id"])),
        ModelRequestPurpose(str(row["purpose"])),
        int(row["attempt_number"]),
        ProviderKind(str(row["provider"])),
        str(row["model_name"]),
        ModelRequestStatus(str(row["status"])),
        str(row["rendered_prompt"]),
        _decode_json_object(row["request_json"]),
        _optional_time(row["started_at"]),
        _optional_time(row["completed_at"]),
        None if row["error_code"] is None else str(row["error_code"]),
        None
        if row["safe_error_message"] is None
        else str(row["safe_error_message"]),
    )


def _model_response(row: sqlite3.Row) -> ModelResponse:
    return ModelResponse(
        DomainId(str(row["id"])),
        DomainId(str(row["model_request_id"])),
        str(row["response_text"]),
        _decode_json_object(row["metadata_json"]),
        _optional_id(row["assistant_message_id"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _validation_result(row: sqlite3.Row) -> ValidationResult:
    return ValidationResult(
        DomainId(str(row["id"])),
        DomainId(str(row["model_response_id"])),
        ValidationStatus(str(row["status"])),
        UnitScore(row["score"]),
        _decode_object_array(row["violations_json"]),
        _decode_object_array(row["evidence_json"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _correction(row: sqlite3.Row) -> CorrectionAttempt:
    return CorrectionAttempt(
        DomainId(str(row["id"])),
        DomainId(str(row["processing_run_id"])),
        int(row["attempt_number"]),
        DomainId(str(row["prior_model_response_id"])),
        DomainId(str(row["revised_model_request_id"])),
        _decode_object_array(row["reason_json"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _clarification(row: sqlite3.Row) -> ClarificationRequest:
    return ClarificationRequest(
        DomainId(str(row["id"])),
        DomainId(str(row["processing_run_id"])),
        ClarificationReason(str(row["reason_code"])),
        str(row["question_text"]),
        _decode_json_object(row["details_json"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _safe_failure(row: sqlite3.Row) -> SafeFailure:
    return SafeFailure(
        DomainId(str(row["id"])),
        DomainId(str(row["processing_run_id"])),
        PipelineStage(str(row["stage"])),
        FailureCode(str(row["error_code"])),
        str(row["safe_message"]),
        _decode_json_object(row["details_json"]),
        bool(row["is_terminal"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


def _setting(row: sqlite3.Row) -> Setting:
    return Setting(
        str(row["key"]),
        _decode_json(row["value_json"]),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _evaluation_case(row: sqlite3.Row) -> EvaluationCase:
    return EvaluationCase(
        DomainId(str(row["id"])),
        str(row["name"]),
        str(row["category"]),
        _decode_json_object(row["case_json"]),
        bool(row["enabled"]),
        parse_utc_timestamp(str(row["created_at"])),
        parse_utc_timestamp(str(row["updated_at"])),
    )


def _evaluation_run(row: sqlite3.Row) -> EvaluationRun:
    return EvaluationRun(
        DomainId(str(row["id"])),
        DomainId(str(row["evaluation_case_id"])),
        str(row["fixture_version"]),
        EvaluationProviderMode(str(row["provider_mode"])),
        _decode_json_object(row["result_json"]),
        bool(row["passed"]),
        parse_utc_timestamp(str(row["created_at"])),
    )


class _SQLiteRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    def _one(
        self,
        sql: str,
        parameters: tuple[object, ...],
        mapper: _RowMapper[_T],
        record_name: str,
    ) -> _T | None:
        row = _fetch_one(self._connection, sql, parameters, f"Read {record_name}")
        return None if row is None else _map_row(row, mapper, record_name)

    def _all(
        self,
        sql: str,
        parameters: tuple[object, ...],
        mapper: _RowMapper[_T],
        record_name: str,
    ) -> tuple[_T, ...]:
        rows = _fetch_all(self._connection, sql, parameters, f"List {record_name}")
        return _map_rows(rows, mapper, record_name)

    def _write(self, operation: str) -> AbstractContextManager[None]:
        return _write_transaction(self._connection, operation)


def _require_existing(value: _T | None, record_name: str) -> _T:
    if value is None:
        raise PersistenceError(f"{record_name} does not exist.")
    return value


def _require_non_regressing_update(
    *, old_created_at: datetime, old_updated_at: datetime, new_created_at: datetime,
    new_updated_at: datetime, record_name: str,
) -> None:
    if new_created_at != old_created_at:
        raise LifecycleInvariantError(f"{record_name}.created_at is immutable.")
    if new_updated_at < old_updated_at:
        raise LifecycleInvariantError(f"{record_name}.updated_at cannot move backward.")


class SQLiteProjectRepository(_SQLiteRepository):
    def add(self, project: Project) -> None:
        with self._write("Add project"):
            self._connection.execute(
                """
                INSERT INTO projects (id, name, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(project.id), project.name, project.description,
                    project.status.value, format_utc_timestamp(project.created_at),
                    format_utc_timestamp(project.updated_at),
                ),
            )

    def get(self, project_id: DomainId) -> Project | None:
        return self._one(
            "SELECT * FROM projects WHERE id = ?", (str(project_id),), _project, "project"
        )

    def list_by_status(self, status: ProjectStatus) -> tuple[Project, ...]:
        return self._all(
            "SELECT * FROM projects WHERE status = ? ORDER BY created_at, id",
            (status.value,), _project, "projects",
        )

    def update(self, project: Project) -> None:
        with self._write("Update project"):
            current = _require_existing(self.get(project.id), "Project")
            _require_non_regressing_update(
                old_created_at=current.created_at,
                old_updated_at=current.updated_at,
                new_created_at=project.created_at,
                new_updated_at=project.updated_at,
                record_name="Project",
            )
            if current.status is not project.status:
                active_run = _fetch_one(
                    self._connection,
                    """
                    SELECT processing_runs.id
                    FROM processing_runs
                    JOIN conversations
                      ON conversations.id = processing_runs.conversation_id
                    WHERE conversations.project_id = ?
                      AND processing_runs.status IN (
                          'PERSISTED', 'CONTEXT_READY', 'GENERATING', 'REVISING'
                      )
                    LIMIT 1
                    """,
                    (str(project.id),),
                    "Check project archive guard",
                )
                require_project_transition(
                    current.status,
                    project.status,
                    has_non_terminal_run=active_run is not None,
                )
            cursor = self._connection.execute(
                """
                UPDATE projects
                SET name = ?, description = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    project.name, project.description, project.status.value,
                    format_utc_timestamp(project.updated_at), str(project.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Project update did not affect exactly one row.")
            self._connection.execute(
                """
                UPDATE entity_registry
                SET display_name = ?, normalized_name = ?, is_active = ?, updated_at = ?
                WHERE entity_type = 'PROJECT' AND native_id = ?
                """,
                (
                    project.name,
                    normalize_phrase(project.name),
                    int(project.status is ProjectStatus.ACTIVE),
                    format_utc_timestamp(project.updated_at),
                    str(project.id),
                ),
            )
            if project.status is ProjectStatus.ARCHIVED:
                self._connection.execute(
                    "UPDATE entity_registry SET is_active = 0, updated_at = ? WHERE project_id = ?",
                    (format_utc_timestamp(project.updated_at), str(project.id)),
                )


class SQLiteConversationRepository(_SQLiteRepository):
    def _require_active_project(self, project_id: DomainId | None) -> None:
        if project_id is None:
            return
        row = _fetch_one(
            self._connection,
            "SELECT status FROM projects WHERE id = ?",
            (str(project_id),),
            "Validate conversation project",
        )
        if row is None:
            raise PersistenceError("Conversation project does not exist.")
        if row["status"] != ProjectStatus.ACTIVE.value:
            raise LifecycleInvariantError(
                "A conversation may select only an ACTIVE project."
            )

    def add(self, conversation: Conversation) -> None:
        with self._write("Add conversation"):
            self._require_active_project(conversation.project_id)
            self._connection.execute(
                """
                INSERT INTO conversations (id, project_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(conversation.id),
                    None if conversation.project_id is None else str(conversation.project_id),
                    conversation.title,
                    format_utc_timestamp(conversation.created_at),
                    format_utc_timestamp(conversation.updated_at),
                ),
            )

    def get(self, conversation_id: DomainId) -> Conversation | None:
        return self._one(
            "SELECT * FROM conversations WHERE id = ?",
            (str(conversation_id),), _conversation, "conversation",
        )

    def list_for_project(
        self, project_id: DomainId | None
    ) -> tuple[Conversation, ...]:
        if project_id is None:
            sql = "SELECT * FROM conversations WHERE project_id IS NULL ORDER BY created_at, id"
            parameters: tuple[object, ...] = ()
        else:
            sql = "SELECT * FROM conversations WHERE project_id = ? ORDER BY created_at, id"
            parameters = (str(project_id),)
        return self._all(sql, parameters, _conversation, "conversations")

    def update(self, conversation: Conversation) -> None:
        with self._write("Update conversation"):
            current = _require_existing(self.get(conversation.id), "Conversation")
            _require_non_regressing_update(
                old_created_at=current.created_at,
                old_updated_at=current.updated_at,
                new_created_at=conversation.created_at,
                new_updated_at=conversation.updated_at,
                record_name="Conversation",
            )
            self._require_active_project(conversation.project_id)
            cursor = self._connection.execute(
                """
                UPDATE conversations
                SET project_id = ?, title = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    None if conversation.project_id is None else str(conversation.project_id),
                    conversation.title,
                    format_utc_timestamp(conversation.updated_at),
                    str(conversation.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Conversation update did not affect exactly one row.")
            if conversation.project_id != current.project_id:
                project_value = (
                    None
                    if conversation.project_id is None
                    else str(conversation.project_id)
                )
                updated_at = format_utc_timestamp(conversation.updated_at)
                self._connection.execute(
                    """
                    UPDATE entity_registry
                    SET project_id = ?, is_active = 1, updated_at = ?
                    WHERE entity_type = 'TOPIC'
                      AND native_id IN (
                          SELECT id FROM topics WHERE conversation_id = ?
                      )
                    """,
                    (project_value, updated_at, str(conversation.id)),
                )
                self._connection.execute(
                    """
                    UPDATE entity_registry
                    SET project_id = ?,
                        is_active = CASE
                            WHEN native_id IN (
                                SELECT id FROM tasks
                                WHERE conversation_id = ?
                                  AND status IN ('OPEN', 'IN_PROGRESS')
                            ) THEN 1 ELSE 0 END,
                        updated_at = ?
                    WHERE entity_type = 'TASK'
                      AND native_id IN (
                          SELECT id FROM tasks WHERE conversation_id = ?
                      )
                    """,
                    (
                        project_value,
                        str(conversation.id),
                        updated_at,
                        str(conversation.id),
                    ),
                )


class SQLiteTopicRepository(_SQLiteRepository):
    def add(self, topic: Topic) -> None:
        with self._write("Add topic"):
            self._connection.execute(
                """
                INSERT INTO topics (
                    id, conversation_id, label, normalized_label, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(topic.id), str(topic.conversation_id), topic.label,
                    topic.normalized_label, format_utc_timestamp(topic.created_at),
                    format_utc_timestamp(topic.updated_at),
                ),
            )

    def get(self, topic_id: DomainId) -> Topic | None:
        return self._one(
            "SELECT * FROM topics WHERE id = ?", (str(topic_id),), _topic, "topic"
        )

    def get_by_normalized_label(
        self, conversation_id: DomainId, normalized_label: str
    ) -> Topic | None:
        return self._one(
            """
            SELECT * FROM topics
            WHERE conversation_id = ? AND normalized_label = ?
            """,
            (str(conversation_id), normalized_label), _topic, "topic",
        )

    def list_for_conversation(
        self, conversation_id: DomainId
    ) -> tuple[Topic, ...]:
        return self._all(
            "SELECT * FROM topics WHERE conversation_id = ? ORDER BY created_at, id",
            (str(conversation_id),), _topic, "topics",
        )

    def update(self, topic: Topic) -> None:
        with self._write("Update topic"):
            current = _require_existing(self.get(topic.id), "Topic")
            if topic.conversation_id != current.conversation_id:
                raise LifecycleInvariantError("Topic.conversation_id is immutable.")
            _require_non_regressing_update(
                old_created_at=current.created_at,
                old_updated_at=current.updated_at,
                new_created_at=topic.created_at,
                new_updated_at=topic.updated_at,
                record_name="Topic",
            )
            cursor = self._connection.execute(
                """
                UPDATE topics
                SET label = ?, normalized_label = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    topic.label, topic.normalized_label,
                    format_utc_timestamp(topic.updated_at), str(topic.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Topic update did not affect exactly one row.")
            self._connection.execute(
                """
                UPDATE entity_registry
                SET display_name = ?, normalized_name = ?, updated_at = ?
                WHERE entity_type = 'TOPIC' AND native_id = ?
                """,
                (
                    topic.label,
                    topic.normalized_label,
                    format_utc_timestamp(topic.updated_at),
                    str(topic.id),
                ),
            )


class SQLiteTaskRepository(_SQLiteRepository):
    def _require_topic_ownership(self, task: ConversationTask) -> None:
        if task.topic_id is None:
            return
        row = _fetch_one(
            self._connection,
            "SELECT conversation_id FROM topics WHERE id = ?",
            (str(task.topic_id),),
            "Validate task topic",
        )
        if row is None or row["conversation_id"] != str(task.conversation_id):
            raise LifecycleInvariantError(
                "A task topic must belong to the task conversation."
            )

    def add(self, task: ConversationTask) -> None:
        with self._write("Add task"):
            self._require_topic_ownership(task)
            self._connection.execute(
                """
                INSERT INTO tasks (
                    id, conversation_id, topic_id, title, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(task.id), str(task.conversation_id),
                    None if task.topic_id is None else str(task.topic_id),
                    task.title, task.status.value,
                    format_utc_timestamp(task.created_at),
                    format_utc_timestamp(task.updated_at),
                ),
            )

    def get(self, task_id: DomainId) -> ConversationTask | None:
        return self._one(
            "SELECT * FROM tasks WHERE id = ?", (str(task_id),), _task, "task"
        )

    def list_for_conversation(
        self, conversation_id: DomainId
    ) -> tuple[ConversationTask, ...]:
        return self._all(
            "SELECT * FROM tasks WHERE conversation_id = ? ORDER BY created_at, id",
            (str(conversation_id),), _task, "tasks",
        )

    def update(self, task: ConversationTask) -> None:
        with self._write("Update task"):
            current = _require_existing(self.get(task.id), "Task")
            if task.conversation_id != current.conversation_id:
                raise LifecycleInvariantError("ConversationTask.conversation_id is immutable.")
            _require_non_regressing_update(
                old_created_at=current.created_at,
                old_updated_at=current.updated_at,
                new_created_at=task.created_at,
                new_updated_at=task.updated_at,
                record_name="ConversationTask",
            )
            self._require_topic_ownership(task)
            if current.status is not task.status:
                require_task_transition(current.status, task.status)
            if is_terminal_task(task.status):
                state_row = _fetch_one(
                    self._connection,
                    """
                    SELECT conversation_id FROM conversation_states
                    WHERE active_task_id = ?
                    """,
                    (str(task.id),),
                    "Check active task terminal guard",
                )
                if state_row is not None:
                    raise LifecycleInvariantError(
                        "An active task must be cleared before it becomes terminal."
                    )
            cursor = self._connection.execute(
                """
                UPDATE tasks
                SET topic_id = ?, title = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    None if task.topic_id is None else str(task.topic_id),
                    task.title, task.status.value,
                    format_utc_timestamp(task.updated_at), str(task.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Task update did not affect exactly one row.")
            activity_row = _fetch_one(
                self._connection,
                """
                SELECT CASE WHEN (conversations.project_id IS NULL
                                       OR projects.status = 'ACTIVE')
                                      AND tasks.status IN ('OPEN', 'IN_PROGRESS')
                            THEN 1 ELSE 0 END AS expected_active
                FROM tasks
                JOIN conversations ON conversations.id = tasks.conversation_id
                LEFT JOIN projects ON projects.id = conversations.project_id
                WHERE tasks.id = ?
                """,
                (str(task.id),),
                "Read task entity activity",
            )
            if activity_row is None:
                raise PersistenceError("Updated task could not be reloaded.")
            self._connection.execute(
                """
                UPDATE entity_registry
                SET display_name = ?, normalized_name = ?, is_active = ?, updated_at = ?
                WHERE entity_type = 'TASK' AND native_id = ?
                """,
                (
                    task.title,
                    normalize_phrase(task.title),
                    int(bool(activity_row["expected_active"])),
                    format_utc_timestamp(task.updated_at),
                    str(task.id),
                ),
            )


class SQLiteConversationStateRepository(_SQLiteRepository):
    def _validate_references(self, state: ConversationState) -> None:
        topic_ids = tuple(
            dict.fromkeys(
                candidate
                for candidate in (state.active_topic_id, *state.topic_stack)
                if candidate is not None
            )
        )
        for topic_id in topic_ids:
            row = _fetch_one(
                self._connection,
                "SELECT conversation_id FROM topics WHERE id = ?",
                (str(topic_id),),
                "Validate conversation state topic",
            )
            if row is None or row["conversation_id"] != str(state.conversation_id):
                raise LifecycleInvariantError(
                    "Every state topic must belong to the state conversation."
                )
        for task_id, active in (
            (state.active_task_id, True),
            (state.previous_task_id, False),
        ):
            if task_id is None:
                continue
            row = _fetch_one(
                self._connection,
                "SELECT conversation_id, status FROM tasks WHERE id = ?",
                (str(task_id),),
                "Validate conversation state task",
            )
            if row is None or row["conversation_id"] != str(state.conversation_id):
                raise LifecycleInvariantError(
                    "Every state task must belong to the state conversation."
                )
            if active and TaskStatus(str(row["status"])) in (
                TaskStatus.COMPLETED,
                TaskStatus.CANCELLED,
            ):
                raise LifecycleInvariantError("An active task cannot be terminal.")

    def add(self, state: ConversationState) -> None:
        if state.version != 0:
            raise LifecycleInvariantError("A new conversation state must start at version 0.")
        with self._write("Add conversation state"):
            self._validate_references(state)
            self._connection.execute(
                """
                INSERT INTO conversation_states (
                    conversation_id, active_topic_id, active_task_id, previous_task_id,
                    expected_output_type, topic_stack_json, version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(state.conversation_id),
                    None if state.active_topic_id is None else str(state.active_topic_id),
                    None if state.active_task_id is None else str(state.active_task_id),
                    None if state.previous_task_id is None else str(state.previous_task_id),
                    None
                    if state.expected_output_type is None
                    else state.expected_output_type.value,
                    _encode_json(tuple(str(item) for item in state.topic_stack)),
                    state.version,
                    format_utc_timestamp(state.updated_at),
                ),
            )

    def get(self, conversation_id: DomainId) -> ConversationState | None:
        return self._one(
            "SELECT * FROM conversation_states WHERE conversation_id = ?",
            (str(conversation_id),), _conversation_state, "conversation state",
        )

    def compare_and_swap(
        self, *, expected_version: int, state: ConversationState
    ) -> bool:
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 0
        ):
            raise LifecycleInvariantError("expected_version must be non-negative.")
        if state.version != expected_version + 1:
            raise LifecycleInvariantError(
                "A compare-and-swap state must increment version exactly once."
            )
        with self._write("Compare and swap conversation state"):
            self._validate_references(state)
            current = self.get(state.conversation_id)
            if current is not None and state.updated_at < current.updated_at:
                raise LifecycleInvariantError(
                    "ConversationState.updated_at cannot move backward."
                )
            cursor = self._connection.execute(
                """
                UPDATE conversation_states
                SET active_topic_id = ?, active_task_id = ?, previous_task_id = ?,
                    expected_output_type = ?, topic_stack_json = ?, version = ?,
                    updated_at = ?
                WHERE conversation_id = ? AND version = ?
                """,
                (
                    None if state.active_topic_id is None else str(state.active_topic_id),
                    None if state.active_task_id is None else str(state.active_task_id),
                    None if state.previous_task_id is None else str(state.previous_task_id),
                    None
                    if state.expected_output_type is None
                    else state.expected_output_type.value,
                    _encode_json(tuple(str(item) for item in state.topic_stack)),
                    state.version,
                    format_utc_timestamp(state.updated_at),
                    str(state.conversation_id),
                    expected_version,
                ),
            )
            return cursor.rowcount == 1


class SQLiteMessageRepository(_SQLiteRepository):
    def add(self, message: Message) -> None:
        with self._write("Add immutable message"):
            self._connection.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, original_text, created_at, sequence_number
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(message.id), str(message.conversation_id), message.role.value,
                    message.original_text, format_utc_timestamp(message.created_at),
                    message.sequence_number,
                ),
            )

    def get(self, message_id: DomainId) -> Message | None:
        return self._one(
            "SELECT * FROM messages WHERE id = ?", (str(message_id),), _message, "message"
        )

    def list_for_conversation(
        self, conversation_id: DomainId, *, limit: int | None = None
    ) -> tuple[Message, ...]:
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        ):
            raise LifecycleInvariantError("Message limit must be non-negative or null.")
        if limit == 0:
            return ()
        if limit is None:
            sql = """
                SELECT * FROM messages
                WHERE conversation_id = ?
                ORDER BY sequence_number, id
            """
            parameters: tuple[object, ...] = (str(conversation_id),)
        else:
            sql = """
                SELECT * FROM (
                    SELECT * FROM messages
                    WHERE conversation_id = ?
                    ORDER BY sequence_number DESC, id DESC
                    LIMIT ?
                ) ORDER BY sequence_number, id
            """
            parameters = (str(conversation_id), limit)
        return self._all(sql, parameters, _message, "messages")

    def next_sequence_number(self, conversation_id: DomainId) -> int:
        row = _fetch_one(
            self._connection,
            """
            SELECT COALESCE(MAX(sequence_number), -1) + 1 AS next_sequence
            FROM messages WHERE conversation_id = ?
            """,
            (str(conversation_id),),
            "Read next message sequence",
        )
        if row is None:
            raise PersistenceError("Next message sequence query returned no row.")
        return int(row["next_sequence"])


class SQLiteEntityRepository(_SQLiteRepository):
    def _validate_source_message(
        self,
        source_message_id: DomainId | None,
        *,
        conversation_id: DomainId | None,
    ) -> None:
        if source_message_id is None:
            return
        row = _fetch_one(
            self._connection,
            "SELECT conversation_id, role FROM messages WHERE id = ?",
            (str(source_message_id),),
            "Validate entity source message",
        )
        if row is None:
            raise PersistenceError("Entity source message does not exist.")
        if row["role"] != MessageRole.USER.value:
            raise LifecycleInvariantError("Entity source message must have USER role.")
        if conversation_id is not None and row["conversation_id"] != str(
            conversation_id
        ):
            raise LifecycleInvariantError(
                "Entity source message must belong to its owning conversation."
            )

    def _validate_named_item_record(self, named_item: NamedItem) -> None:
        conversation = _fetch_one(
            self._connection,
            "SELECT id FROM conversations WHERE id = ?",
            (str(named_item.conversation_id),),
            "Validate named-item conversation",
        )
        if conversation is None:
            raise PersistenceError("Named-item conversation does not exist.")
        if named_item.project_id is not None:
            project = _fetch_one(
                self._connection,
                "SELECT id FROM projects WHERE id = ?",
                (str(named_item.project_id),),
                "Validate named-item project",
            )
            if project is None:
                raise PersistenceError("Named-item project does not exist.")
        if (
            normalize_display_label(named_item.display_name) != named_item.display_name
            or normalize_phrase(named_item.display_name) != named_item.normalized_name
        ):
            raise LifecycleInvariantError(
                "Named-item display and normalized names must be canonical."
            )
        self._validate_source_message(
            named_item.source_message_id,
            conversation_id=named_item.conversation_id,
        )

    def _validate_owner(self, entity: Entity) -> None:
        if entity.entity_type is EntityType.PROJECT:
            row = _fetch_one(
                self._connection,
                "SELECT name, status FROM projects WHERE id = ?",
                (str(entity.native_id),),
                "Validate project entity owner",
            )
            if row is None:
                raise PersistenceError("Project entity owner does not exist.")
            if entity.project_id != entity.native_id:
                raise LifecycleInvariantError(
                    "A project entity project_id must equal its native project ID."
                )
            expected_active = row["status"] == ProjectStatus.ACTIVE.value
            expected_display = str(row["name"])
            expected_normalized = normalize_phrase(expected_display)
            source_conversation_id = None
        elif entity.entity_type is EntityType.TOPIC:
            row = _fetch_one(
                self._connection,
                """
                SELECT topics.label, topics.normalized_label,
                       topics.conversation_id, conversations.project_id,
                       CASE WHEN conversations.project_id IS NULL
                                  OR projects.status = 'ACTIVE'
                            THEN 1 ELSE 0 END AS expected_active
                FROM topics
                JOIN conversations ON conversations.id = topics.conversation_id
                LEFT JOIN projects ON projects.id = conversations.project_id
                WHERE topics.id = ?
                """,
                (str(entity.native_id),),
                "Validate topic entity owner",
            )
            if row is None:
                raise PersistenceError("Topic entity owner does not exist.")
            if entity.project_id != _optional_id(row["project_id"]):
                raise LifecycleInvariantError(
                    "Topic entity project_id must match its conversation project."
                )
            expected_active = bool(row["expected_active"])
            expected_display = str(row["label"])
            expected_normalized = str(row["normalized_label"])
            source_conversation_id = DomainId(str(row["conversation_id"]))
        elif entity.entity_type is EntityType.TASK:
            row = _fetch_one(
                self._connection,
                """
                SELECT tasks.title, tasks.conversation_id,
                       conversations.project_id, tasks.status,
                       CASE WHEN (conversations.project_id IS NULL
                                       OR projects.status = 'ACTIVE')
                                      AND tasks.status IN ('OPEN', 'IN_PROGRESS')
                            THEN 1 ELSE 0 END AS expected_active
                FROM tasks
                JOIN conversations ON conversations.id = tasks.conversation_id
                LEFT JOIN projects ON projects.id = conversations.project_id
                WHERE tasks.id = ?
                """,
                (str(entity.native_id),),
                "Validate task entity owner",
            )
            if row is None:
                raise PersistenceError("Task entity owner does not exist.")
            if entity.project_id != _optional_id(row["project_id"]):
                raise LifecycleInvariantError(
                    "Task entity project_id must match its conversation project."
                )
            expected_active = bool(row["expected_active"])
            expected_display = str(row["title"])
            expected_normalized = normalize_phrase(expected_display)
            source_conversation_id = DomainId(str(row["conversation_id"]))
        else:
            row = _fetch_one(
                self._connection,
                """
                SELECT named_items.conversation_id, named_items.project_id,
                       named_items.display_name, named_items.normalized_name,
                       named_items.source_message_id,
                       CASE WHEN named_items.project_id IS NULL
                                  OR projects.status = 'ACTIVE'
                            THEN 1 ELSE 0 END AS expected_active
                FROM named_items
                LEFT JOIN projects ON projects.id = named_items.project_id
                WHERE named_items.id = ?
                """,
                (str(entity.native_id),),
                "Validate named-item entity owner",
            )
            if row is None:
                raise PersistenceError("Named-item entity owner does not exist.")
            if entity.project_id != _optional_id(row["project_id"]):
                raise LifecycleInvariantError(
                    "Named-item entity project_id must match its owner."
                )
            expected_active = bool(row["expected_active"])
            expected_display = str(row["display_name"])
            expected_normalized = str(row["normalized_name"])
            source_conversation_id = DomainId(str(row["conversation_id"]))
            if entity.source_message_id != _optional_id(row["source_message_id"]):
                raise LifecycleInvariantError(
                    "Named-item entity source must match its owner."
                )
        if (
            entity.display_name != expected_display
            or entity.normalized_name != expected_normalized
        ):
            raise LifecycleInvariantError(
                "Entity display and normalized names must mirror their owner."
            )
        if entity.is_active is not expected_active:
            raise LifecycleInvariantError(
                "Entity activity must mirror its owning lifecycle."
            )
        self._validate_source_message(
            entity.source_message_id,
            conversation_id=source_conversation_id,
        )

    def _insert_entity(self, entity: Entity) -> None:
        if entity.id == entity.native_id:
            raise LifecycleInvariantError(
                "Entity registry ID must be distinct from its native owner ID."
            )
        self._validate_owner(entity)
        self._connection.execute(
            """
            INSERT INTO entity_registry (
                id, entity_type, native_id, project_id, display_name,
                normalized_name, source_message_id, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(entity.id), entity.entity_type.value, str(entity.native_id),
                None if entity.project_id is None else str(entity.project_id),
                entity.display_name, entity.normalized_name,
                None
                if entity.source_message_id is None
                else str(entity.source_message_id),
                int(entity.is_active), format_utc_timestamp(entity.created_at),
                format_utc_timestamp(entity.updated_at),
            ),
        )

    def add(self, entity: Entity) -> None:
        with self._write("Add entity"):
            self._insert_entity(entity)

    def add_named_item(self, named_item: NamedItem, entity: Entity) -> None:
        if entity.entity_type is not EntityType.NAMED_ITEM or entity.native_id != named_item.id:
            raise LifecycleInvariantError(
                "A named-item entity must point to the supplied named item."
            )
        with self._write("Add named item and entity"):
            self._validate_named_item_record(named_item)
            self._connection.execute(
                """
                INSERT INTO named_items (
                    id, conversation_id, project_id, display_name, normalized_name,
                    source_message_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(named_item.id), str(named_item.conversation_id),
                    None if named_item.project_id is None else str(named_item.project_id),
                    named_item.display_name, named_item.normalized_name,
                    None
                    if named_item.source_message_id is None
                    else str(named_item.source_message_id),
                    format_utc_timestamp(named_item.created_at),
                    format_utc_timestamp(named_item.updated_at),
                ),
            )
            self._insert_entity(entity)

    def update_named_item(self, named_item: NamedItem, entity: Entity) -> None:
        if entity.entity_type is not EntityType.NAMED_ITEM or entity.native_id != named_item.id:
            raise LifecycleInvariantError(
                "A named-item entity must point to the supplied named item."
            )
        with self._write("Update named item and entity"):
            current_owner = _require_existing(
                self.get_named_item(named_item.id),
                "Named item",
            )
            current_entity = _require_existing(self.get(entity.id), "Entity")
            if (
                named_item.conversation_id != current_owner.conversation_id
                or named_item.project_id != current_owner.project_id
                or named_item.source_message_id != current_owner.source_message_id
            ):
                raise LifecycleInvariantError(
                    "Named-item conversation, project, and source are immutable."
                )
            if (
                entity.entity_type is not current_entity.entity_type
                or entity.native_id != current_entity.native_id
                or entity.source_message_id != current_entity.source_message_id
            ):
                raise LifecycleInvariantError(
                    "Named-item registry identity and source are immutable."
                )
            _require_non_regressing_update(
                old_created_at=current_owner.created_at,
                old_updated_at=current_owner.updated_at,
                new_created_at=named_item.created_at,
                new_updated_at=named_item.updated_at,
                record_name="NamedItem",
            )
            _require_non_regressing_update(
                old_created_at=current_entity.created_at,
                old_updated_at=current_entity.updated_at,
                new_created_at=entity.created_at,
                new_updated_at=entity.updated_at,
                record_name="Entity",
            )
            if (
                entity.display_name != named_item.display_name
                or entity.normalized_name != named_item.normalized_name
                or entity.project_id != named_item.project_id
                or entity.updated_at != named_item.updated_at
            ):
                raise LifecycleInvariantError(
                    "Named-item owner and registry mutable fields must stay synchronized."
                )
            self._validate_named_item_record(named_item)
            cursor = self._connection.execute(
                """
                UPDATE named_items
                SET display_name = ?, normalized_name = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    named_item.display_name,
                    named_item.normalized_name,
                    format_utc_timestamp(named_item.updated_at),
                    str(named_item.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError(
                    "Named-item update did not affect exactly one owner row."
                )
            self._validate_owner(entity)
            cursor = self._connection.execute(
                """
                UPDATE entity_registry
                SET project_id = ?, display_name = ?, normalized_name = ?,
                    is_active = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    None if entity.project_id is None else str(entity.project_id),
                    entity.display_name,
                    entity.normalized_name,
                    int(entity.is_active),
                    format_utc_timestamp(entity.updated_at),
                    str(entity.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError(
                    "Named-item update did not affect exactly one registry row."
                )

    def get(self, entity_id: DomainId) -> Entity | None:
        return self._one(
            "SELECT * FROM entity_registry WHERE id = ?",
            (str(entity_id),), _entity, "entity",
        )

    def get_named_item(self, named_item_id: DomainId) -> NamedItem | None:
        return self._one(
            "SELECT * FROM named_items WHERE id = ?",
            (str(named_item_id),), _named_item, "named item",
        )

    def list_reference_candidates(
        self, *, conversation_id: DomainId, project_id: DomainId | None
    ) -> tuple[Entity, ...]:
        return self._all(
            """
            SELECT entity_registry.*
            FROM entity_registry
            WHERE (
                (entity_type = 'PROJECT' AND native_id = ?)
                OR (entity_type = 'TOPIC' AND EXISTS (
                    SELECT 1 FROM topics
                    WHERE topics.id = entity_registry.native_id
                      AND topics.conversation_id = ?
                ))
                OR (entity_type = 'TASK' AND EXISTS (
                    SELECT 1 FROM tasks
                    WHERE tasks.id = entity_registry.native_id
                      AND tasks.conversation_id = ?
                ))
                OR (entity_type = 'NAMED_ITEM' AND EXISTS (
                    SELECT 1 FROM named_items
                    WHERE named_items.id = entity_registry.native_id
                      AND named_items.conversation_id = ?
                      AND (
                          named_items.project_id IS NULL
                          OR named_items.project_id = ?
                      )
                ))
            )
            ORDER BY normalized_name, entity_type, id
            """,
            (
                None if project_id is None else str(project_id),
                str(conversation_id),
                str(conversation_id),
                str(conversation_id),
                None if project_id is None else str(project_id),
            ),
            _entity,
            "reference candidate entities",
        )

    def update(self, entity: Entity) -> None:
        with self._write("Update entity"):
            current = _require_existing(self.get(entity.id), "Entity")
            if (
                entity.entity_type is not current.entity_type
                or entity.native_id != current.native_id
                or entity.source_message_id != current.source_message_id
            ):
                raise LifecycleInvariantError(
                    "Entity type, native_id, and source_message_id are immutable."
                )
            _require_non_regressing_update(
                old_created_at=current.created_at,
                old_updated_at=current.updated_at,
                new_created_at=entity.created_at,
                new_updated_at=entity.updated_at,
                record_name="Entity",
            )
            self._validate_owner(entity)
            cursor = self._connection.execute(
                """
                UPDATE entity_registry
                SET project_id = ?, display_name = ?, normalized_name = ?,
                    is_active = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    None if entity.project_id is None else str(entity.project_id),
                    entity.display_name, entity.normalized_name,
                    int(entity.is_active), format_utc_timestamp(entity.updated_at),
                    str(entity.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Entity update did not affect exactly one row.")


class SQLiteReferenceResolutionRepository(_SQLiteRepository):
    def _validate_complete_tuple(
        self,
        outcomes: tuple[ReferenceOutcome, ...],
    ) -> None:
        if any(not isinstance(outcome, ReferenceOutcome) for outcome in outcomes):
            raise LifecycleInvariantError(
                "Reference persistence requires typed outcomes."
            )
        if [outcome.mention_ordinal for outcome in outcomes] != list(
            range(len(outcomes))
        ):
            raise LifecycleInvariantError(
                "Reference persistence requires one complete contiguous outcome tuple."
            )
        if len({outcome.id for outcome in outcomes}) != len(outcomes):
            raise LifecycleInvariantError("Reference outcome IDs must be distinct.")
        if outcomes and (
            len({outcome.processing_run_id for outcome in outcomes}) != 1
            or len({outcome.message_id for outcome in outcomes}) != 1
        ):
            raise LifecycleInvariantError(
                "Reference outcomes must share one run and current message."
            )

    def _current_context(self, outcome: ReferenceOutcome) -> sqlite3.Row:
        row = _fetch_one(
            self._connection,
            """
            SELECT processing_runs.user_message_id,
                   processing_runs.conversation_id,
                   messages.role,
                   messages.sequence_number,
                   conversations.project_id
            FROM processing_runs
            JOIN messages ON messages.id = processing_runs.user_message_id
            JOIN conversations ON conversations.id = processing_runs.conversation_id
            WHERE processing_runs.id = ?
            """,
            (str(outcome.processing_run_id),),
            "Validate reference resolution run",
        )
        if row is None or row["user_message_id"] != str(outcome.message_id):
            raise LifecycleInvariantError(
                "Reference outcome message must be the run user message."
            )
        if row["role"] != MessageRole.USER.value:
            raise LifecycleInvariantError(
                "Reference outcome current message must have USER role."
            )
        return row

    def _validate_candidate_scope(
        self,
        entity: Entity,
        *,
        conversation_id: str,
        project_id: object,
    ) -> None:
        if entity.entity_type is EntityType.PROJECT:
            if project_id is None or str(entity.native_id) != str(project_id):
                raise LifecycleInvariantError(
                    "Project reference evidence is outside the current scope."
                )
            return
        if entity.entity_type is EntityType.TOPIC:
            table = "topics"
        elif entity.entity_type is EntityType.TASK:
            table = "tasks"
        else:
            row = _fetch_one(
                self._connection,
                """
                SELECT conversation_id, project_id
                FROM named_items WHERE id = ?
                """,
                (str(entity.native_id),),
                "Validate named-item reference scope",
            )
            if row is None or row["conversation_id"] != conversation_id:
                raise LifecycleInvariantError(
                    "Named-item reference evidence is outside the conversation."
                )
            if row["project_id"] is not None and row["project_id"] != project_id:
                raise LifecycleInvariantError(
                    "Named-item reference evidence is outside the current project."
                )
            return
        row = _fetch_one(
            self._connection,
            f"SELECT conversation_id FROM {table} WHERE id = ?",
            (str(entity.native_id),),
            "Validate owner reference scope",
        )
        if row is None or row["conversation_id"] != conversation_id:
            raise LifecycleInvariantError(
                "Topic/task reference evidence is outside the conversation."
            )

    def _validate_evidence(
        self,
        outcome: ReferenceOutcome,
        context: sqlite3.Row,
    ) -> None:
        conversation_id = str(context["conversation_id"])
        current_sequence = int(context["sequence_number"])
        for evidence in outcome.candidate_evidence:
            if evidence.entity_id is None:
                continue
            row = _fetch_one(
                self._connection,
                "SELECT * FROM entity_registry WHERE id = ?",
                (str(evidence.entity_id),),
                "Validate reference evidence entity",
            )
            if row is None:
                raise LifecycleInvariantError(
                    "Reference evidence entity does not exist."
                )
            stored = _map_row(row, _entity, "reference evidence entity")
            if (
                stored.entity_type is not evidence.entity_type
                or stored.display_name != evidence.display_name
                or stored.normalized_name != evidence.normalized_name
                or stored.source_message_id != evidence.entity_source_message_id
                or stored.is_active is not evidence.is_active
            ):
                raise LifecycleInvariantError(
                    "Reference evidence must exactly match its stored entity snapshot."
                )
            self._validate_candidate_scope(
                stored,
                conversation_id=conversation_id,
                project_id=context["project_id"],
            )

            if evidence.evidence_message_id is None:
                continue
            message = _fetch_one(
                self._connection,
                "SELECT conversation_id, original_text, sequence_number FROM messages WHERE id = ?",
                (str(evidence.evidence_message_id),),
                "Validate reference evidence message",
            )
            if message is None:
                raise LifecycleInvariantError(
                    "Reference evidence message does not exist."
                )
            if int(message["sequence_number"]) != evidence.evidence_message_sequence:
                raise LifecycleInvariantError(
                    "Reference evidence message sequence does not match storage."
                )
            if evidence.rank_reason is ReferenceRankReason.EXACT_NAME:
                if evidence.evidence_message_id != outcome.message_id:
                    raise LifecycleInvariantError(
                        "Exact-name evidence must use the current message."
                    )
            else:
                if (
                    message["conversation_id"] != conversation_id
                    or int(message["sequence_number"]) >= current_sequence
                ):
                    raise LifecycleInvariantError(
                        "Prior reference evidence must precede the current message in its conversation."
                    )
            if evidence.rank_reason in {
                ReferenceRankReason.EXACT_NAME,
                ReferenceRankReason.SOURCE_MESSAGE,
            } and not find_phrase_matches(
                normalize_text(str(message["original_text"])),
                stored.normalized_name,
            ):
                raise LifecycleInvariantError(
                    "Reference name evidence must occur word-bounded in its evidence message."
                )
            if evidence.rank_reason is ReferenceRankReason.RECENT_TRACKED:
                tracked = _fetch_one(
                    self._connection,
                    """
                    SELECT id FROM reference_resolutions
                    WHERE message_id = ? AND mention_ordinal = ?
                      AND status = 'RESOLVED' AND resolved_entity_id = ?
                    LIMIT 1
                    """,
                    (
                        str(evidence.evidence_message_id),
                        evidence.prior_mention_ordinal,
                        str(stored.id),
                    ),
                    "Validate tracked reference evidence",
                )
                if tracked is None:
                    raise LifecycleInvariantError(
                        "Tracked reference evidence must link a prior RESOLVED outcome."
                    )

        if outcome.source_message_id is not None:
            source = _fetch_one(
                self._connection,
                "SELECT id FROM messages WHERE id = ?",
                (str(outcome.source_message_id),),
                "Validate reference outcome source",
            )
            if source is None:
                raise LifecycleInvariantError(
                    "Reference outcome source message does not exist."
                )

    def add_all(self, outcomes: tuple[ReferenceOutcome, ...]) -> None:
        frozen = tuple(outcomes)
        self._validate_complete_tuple(frozen)
        if not frozen:
            return
        with self._write("Add reference resolutions"):
            contexts = tuple(self._current_context(outcome) for outcome in frozen)
            for outcome, context in zip(frozen, contexts, strict=True):
                self._validate_evidence(outcome, context)
            for outcome in frozen:
                self._connection.execute(
                    """
                    INSERT INTO reference_resolutions (
                        id, processing_run_id, message_id, mention_ordinal, surface_text,
                        status, resolved_entity_id, source_message_id, confidence,
                        candidate_evidence_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(outcome.id), str(outcome.processing_run_id),
                        str(outcome.message_id), outcome.mention_ordinal,
                        outcome.surface_text, outcome.status.value,
                        None
                        if outcome.resolved_entity_id is None
                        else str(outcome.resolved_entity_id),
                        None
                        if outcome.source_message_id is None
                        else str(outcome.source_message_id),
                        float(outcome.confidence.value),
                        _encode_json(
                            tuple(
                                item.to_json_object()
                                for item in outcome.candidate_evidence
                            )
                        ),
                        format_utc_timestamp(outcome.created_at),
                    ),
                )

    def list_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[ReferenceOutcome, ...]:
        return self._all(
            """
            SELECT * FROM reference_resolutions
            WHERE processing_run_id = ?
            ORDER BY mention_ordinal, id
            """,
            (str(processing_run_id),), _reference_outcome, "reference resolutions",
        )

    def list_resolved_for_messages(
        self,
        message_ids: tuple[DomainId, ...],
    ) -> tuple[ReferenceOutcome, ...]:
        frozen = tuple(message_ids)
        if len(set(frozen)) != len(frozen):
            raise LifecycleInvariantError(
                "Resolved-reference message IDs must be distinct."
            )
        if not frozen:
            return ()
        placeholders = ", ".join("?" for _ in frozen)
        outcomes = self._all(
            f"""
            SELECT * FROM reference_resolutions
            WHERE status = 'RESOLVED' AND message_id IN ({placeholders})
            """,
            tuple(str(message_id) for message_id in frozen),
            _reference_outcome,
            "resolved references for messages",
        )
        order = {message_id: index for index, message_id in enumerate(frozen)}
        return tuple(
            sorted(
                outcomes,
                key=lambda outcome: (
                    order[outcome.message_id],
                    outcome.mention_ordinal,
                    str(outcome.id),
                ),
            )
        )


class SQLiteConstraintRepository(_SQLiteRepository):
    def add_all(self, constraints: tuple[Constraint, ...]) -> None:
        frozen = tuple(constraints)
        with self._write("Add constraints"):
            for constraint in frozen:
                run = _fetch_one(
                    self._connection,
                    "SELECT user_message_id FROM processing_runs WHERE id = ?",
                    (str(constraint.processing_run_id),),
                    "Validate constraint run",
                )
                if run is None or run["user_message_id"] != str(constraint.message_id):
                    raise LifecycleInvariantError(
                        "Constraint message must be the run user message."
                    )
                condition_json = None
                condition_evaluation = None
                if constraint.condition is not None:
                    condition_json = _encode_json(
                        FrozenJsonObject(
                            {
                                "grammar_version": constraint.condition.grammar_version,
                                "kind": constraint.condition.kind.value,
                                "expected_value": constraint.condition.expected_value,
                                "evaluation": constraint.condition.evaluation.value,
                            }
                        )
                    )
                    condition_evaluation = constraint.condition.evaluation.value
                self._connection.execute(
                    """
                    INSERT INTO constraints (
                        id, processing_run_id, message_id, ordinal, constraint_type,
                        underlying_constraint_type, scope, normalized_rule, priority,
                        source_kind, source_text, confidence, resolution_status,
                        conflict_group_id, condition_json, condition_evaluation, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(constraint.id), str(constraint.processing_run_id),
                        str(constraint.message_id), constraint.ordinal,
                        constraint.constraint_type.value,
                        None
                        if constraint.underlying_constraint_type is None
                        else constraint.underlying_constraint_type.value,
                        constraint.scope.value, constraint.normalized_rule,
                        constraint.priority, constraint.source_kind.value,
                        constraint.source_text, float(constraint.confidence.value),
                        constraint.resolution_status.value,
                        constraint.conflict_group_id, condition_json,
                        condition_evaluation,
                        format_utc_timestamp(constraint.created_at),
                    ),
                )

    def list_for_run(self, processing_run_id: DomainId) -> tuple[Constraint, ...]:
        return self._all(
            """
            SELECT * FROM constraints
            WHERE processing_run_id = ?
            ORDER BY priority DESC, ordinal, id
            """,
            (str(processing_run_id),), _constraint, "constraints",
        )


class SQLiteMemoryRepository(_SQLiteRepository):
    def _insert_memory(self, memory: Memory) -> None:
        self._connection.execute(
            """
            INSERT INTO memories (
                id, conversation_id, project_id, memory_type, scope, status, content,
                keywords_json, topic_terms_json, importance, confidence, expires_at,
                created_at, updated_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(memory.id),
                None if memory.conversation_id is None else str(memory.conversation_id),
                None if memory.project_id is None else str(memory.project_id),
                memory.memory_type.value, memory.scope.value, memory.status.value,
                memory.content, _encode_json(memory.keywords),
                _encode_json(memory.topic_terms), float(memory.importance.value),
                float(memory.confidence.value),
                None
                if memory.expires_at is None
                else format_utc_timestamp(memory.expires_at),
                format_utc_timestamp(memory.created_at),
                format_utc_timestamp(memory.updated_at),
                None
                if memory.deleted_at is None
                else format_utc_timestamp(memory.deleted_at),
            ),
        )

    def _insert_source(self, source: MemorySource) -> None:
        self._connection.execute(
            """
            INSERT INTO memory_sources (
                id, memory_id, source_kind, source_message_id, description, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(source.id), str(source.memory_id), source.source_kind.value,
                None
                if source.source_message_id is None
                else str(source.source_message_id),
                source.description, format_utc_timestamp(source.created_at),
            ),
        )

    def _insert_revision(self, revision: MemoryRevision) -> None:
        self._connection.execute(
            """
            INSERT INTO memory_revisions (
                id, memory_id, revision_number, operation, content_snapshot,
                metadata_json, performed_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(revision.id), str(revision.memory_id), revision.revision_number,
                revision.operation.value, revision.content_snapshot,
                _encode_json(revision.metadata), revision.performed_by.value,
                format_utc_timestamp(revision.created_at),
            ),
        )

    def add(
        self,
        memory: Memory,
        source: MemorySource,
        revision: MemoryRevision,
    ) -> None:
        MemoryRecord(memory, (source,), (revision,))
        with self._write("Add memory aggregate"):
            self._insert_memory(memory)
            self._insert_source(source)
            self._insert_revision(revision)

    def _record_for_memory(self, memory: Memory) -> MemoryRecord:
        sources = self._all(
            """
            SELECT * FROM memory_sources
            WHERE memory_id = ? ORDER BY created_at, id
            """,
            (str(memory.id),), _memory_source, "memory sources",
        )
        revisions = self._all(
            """
            SELECT * FROM memory_revisions
            WHERE memory_id = ? ORDER BY revision_number, id
            """,
            (str(memory.id),), _memory_revision, "memory revisions",
        )
        try:
            if not revisions:
                raise LifecycleInvariantError(
                    "Stored memory requires at least one revision."
                )
            importance = revisions[-1].metadata["importance"]
            confidence = revisions[-1].metadata["confidence"]
            if not isinstance(importance, str) or not isinstance(confidence, str):
                raise LifecycleInvariantError(
                    "Stored memory revision scores must be canonical strings."
                )
            exact_importance = UnitScore(importance)
            exact_confidence = UnitScore(confidence)
            if (
                UnitScore(float(exact_importance.value)) != memory.importance
                or UnitScore(float(exact_confidence.value)) != memory.confidence
            ):
                raise LifecycleInvariantError(
                    "Stored memory REAL scores disagree with final revision metadata."
                )
            exact_memory = replace(
                memory,
                importance=exact_importance,
                confidence=exact_confidence,
            )
            return MemoryRecord(exact_memory, sources, revisions)
        except (DomainError, KeyError, TypeError, ValueError) as error:
            raise PersistenceError("Stored memory aggregate is invalid.") from error

    def get(self, memory_id: DomainId) -> MemoryRecord | None:
        memory = self._one(
            "SELECT * FROM memories WHERE id = ?", (str(memory_id),), _memory, "memory"
        )
        return None if memory is None else self._record_for_memory(memory)

    def list_by_status(self, status: MemoryStatus) -> tuple[MemoryRecord, ...]:
        memories = self._all(
            "SELECT * FROM memories WHERE status = ? ORDER BY updated_at DESC, id",
            (status.value,), _memory, "memories",
        )
        return tuple(self._record_for_memory(memory) for memory in memories)

    def list_retrieval_candidates(self) -> tuple[MemoryRecord, ...]:
        memories = self._all(
            "SELECT * FROM memories ORDER BY id",
            (),
            _memory,
            "memory retrieval candidates",
        )
        return tuple(self._record_for_memory(memory) for memory in memories)

    def update_with_revision(
        self,
        memory: Memory,
        source: MemorySource,
        revision: MemoryRevision,
    ) -> None:
        with self._write("Update memory aggregate"):
            current_record = _require_existing(self.get(memory.id), "Memory")
            current = current_record.memory
            if current.status is MemoryStatus.DELETED:
                raise LifecycleInvariantError("A deleted memory cannot be changed or restored.")
            if (
                memory.created_at != current.created_at
                or memory.memory_type is not current.memory_type
                or memory.conversation_id != current.conversation_id
                or memory.project_id != current.project_id
                or memory.scope is not current.scope
            ):
                raise LifecycleInvariantError(
                    "Memory creation, type, ownership, and scope fields are immutable."
                )
            expected_operation = (
                MemoryRevisionOperation.SOFT_DELETE
                if memory.status is MemoryStatus.DELETED
                else MemoryRevisionOperation.EDIT
            )
            if revision.operation is not expected_operation:
                raise LifecycleInvariantError(
                    "Memory revision operation must match the lifecycle update."
                )
            prospective_sources = tuple(
                sorted(
                    (*current_record.sources, source),
                    key=lambda item: (item.created_at, str(item.id)),
                )
            )
            prospective_revisions = (*current_record.revisions, revision)
            MemoryRecord(memory, prospective_sources, prospective_revisions)
            cursor = self._connection.execute(
                """
                UPDATE memories
                SET status = ?, content = ?, keywords_json = ?,
                    topic_terms_json = ?, importance = ?, confidence = ?,
                    expires_at = ?, updated_at = ?, deleted_at = ?
                WHERE id = ?
                """,
                (
                    memory.status.value, memory.content,
                    _encode_json(memory.keywords), _encode_json(memory.topic_terms),
                    float(memory.importance.value), float(memory.confidence.value),
                    None
                    if memory.expires_at is None
                    else format_utc_timestamp(memory.expires_at),
                    format_utc_timestamp(memory.updated_at),
                    None
                    if memory.deleted_at is None
                    else format_utc_timestamp(memory.deleted_at),
                    str(memory.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Memory update did not affect exactly one row.")
            self._insert_source(source)
            self._insert_revision(revision)


def _validate_processing_run_timestamps(run: ProcessingRun) -> None:
    DomainId(run.idempotency_key)
    terminal = run.status in TERMINAL_PROCESSING_RUN_STATUSES
    if terminal and run.completed_at is None:
        raise LifecycleInvariantError("A terminal processing run requires completed_at.")
    if not terminal and run.completed_at is not None:
        raise LifecycleInvariantError("A non-terminal processing run requires null completed_at.")
    if run.completed_at is not None and run.completed_at < run.started_at:
        raise LifecycleInvariantError(
            "ProcessingRun.completed_at cannot precede started_at."
        )


class SQLiteProcessingRunRepository(_SQLiteRepository):
    def add(self, run: ProcessingRun) -> None:
        _validate_processing_run_timestamps(run)
        if run.status is not ProcessingRunStatus.PERSISTED:
            raise LifecycleInvariantError(
                "A new processing run must start in PERSISTED status."
            )
        with self._write("Add processing run"):
            message = _fetch_one(
                self._connection,
                "SELECT conversation_id, role FROM messages WHERE id = ?",
                (str(run.user_message_id),),
                "Validate processing run message",
            )
            if (
                message is None
                or message["conversation_id"] != str(run.conversation_id)
                or message["role"] != MessageRole.USER.value
            ):
                raise LifecycleInvariantError(
                    "A processing run requires its conversation's USER message."
                )
            existing = self.get_by_idempotency_key(
                conversation_id=run.conversation_id,
                idempotency_key=DomainId(run.idempotency_key),
            )
            if existing is not None:
                if existing == run:
                    return
                raise PersistenceError(
                    "The processing-run idempotency key already identifies another stored state."
                )
            self._connection.execute(
                """
                INSERT INTO processing_runs (
                    id, conversation_id, user_message_id, idempotency_key, status,
                    state_version_at_start, configuration_fingerprint,
                    started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.id), str(run.conversation_id), str(run.user_message_id),
                    run.idempotency_key, run.status.value, run.state_version_at_start,
                    run.configuration_fingerprint, format_utc_timestamp(run.started_at),
                    None
                    if run.completed_at is None
                    else format_utc_timestamp(run.completed_at),
                ),
            )

    def get(self, processing_run_id: DomainId) -> ProcessingRun | None:
        return self._one(
            "SELECT * FROM processing_runs WHERE id = ?",
            (str(processing_run_id),), _processing_run, "processing run",
        )

    def get_by_idempotency_key(
        self, *, conversation_id: DomainId, idempotency_key: DomainId
    ) -> ProcessingRun | None:
        return self._one(
            """
            SELECT * FROM processing_runs
            WHERE conversation_id = ? AND idempotency_key = ?
            """,
            (str(conversation_id), str(idempotency_key)),
            _processing_run,
            "processing run",
        )

    def get_non_terminal(self) -> ProcessingRun | None:
        placeholders = ", ".join("?" for _ in NON_TERMINAL_PROCESSING_RUN_STATUSES)
        statuses = tuple(
            status.value
            for status in sorted(
                NON_TERMINAL_PROCESSING_RUN_STATUSES,
                key=lambda candidate: candidate.value,
            )
        )
        return self._one(
            f"SELECT * FROM processing_runs WHERE status IN ({placeholders}) LIMIT 1",
            statuses,
            _processing_run,
            "non-terminal processing run",
        )

    def update(self, run: ProcessingRun) -> None:
        _validate_processing_run_timestamps(run)
        with self._write("Update processing run"):
            current = _require_existing(self.get(run.id), "Processing run")
            immutable_current = (
                current.conversation_id,
                current.user_message_id,
                current.idempotency_key,
                current.state_version_at_start,
                current.configuration_fingerprint,
                current.started_at,
            )
            immutable_new = (
                run.conversation_id,
                run.user_message_id,
                run.idempotency_key,
                run.state_version_at_start,
                run.configuration_fingerprint,
                run.started_at,
            )
            if immutable_new != immutable_current:
                raise LifecycleInvariantError(
                    "Processing run identity and acceptance fields are immutable."
                )
            if current == run:
                return
            require_processing_run_transition(current.status, run.status)
            cursor = self._connection.execute(
                """
                UPDATE processing_runs SET status = ?, completed_at = ? WHERE id = ?
                """,
                (
                    run.status.value,
                    None
                    if run.completed_at is None
                    else format_utc_timestamp(run.completed_at),
                    str(run.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Processing run update did not affect exactly one row.")


class SQLiteContextPacketRepository(_SQLiteRepository):
    def add(self, record: ContextPacketRecord) -> None:
        packet = record.packet
        with self._write("Add context packet aggregate"):
            run = _fetch_one(
                self._connection,
                """
                SELECT conversation_id, user_message_id, configuration_fingerprint, status
                FROM processing_runs WHERE id = ?
                """,
                (str(packet.processing_run_id),),
                "Validate context packet run",
            )
            if run is None or run["user_message_id"] != str(packet.message_id):
                raise LifecycleInvariantError(
                    "Context packet message must be the run user message."
                )
            if run["configuration_fingerprint"] != packet.configuration_fingerprint:
                raise LifecycleInvariantError(
                    "Context packet configuration fingerprint must match its run."
                )
            trace = packet.packet_json["trace"]
            if not isinstance(trace, FrozenJsonObject) or (
                run["conversation_id"] != trace["conversation_id"]
            ):
                raise LifecycleInvariantError(
                    "Context packet trace conversation must match its run."
                )
            if ProcessingRunStatus(str(run["status"])) not in (
                ProcessingRunStatus.PERSISTED,
                ProcessingRunStatus.CONTEXT_READY,
            ):
                raise LifecycleInvariantError(
                    "A context packet may be added only before model generation."
                )
            self._connection.execute(
                """
                INSERT INTO context_packets (
                    id, processing_run_id, message_id, packet_json, schema_version,
                    prompt_policy_version, configuration_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(packet.id), str(packet.processing_run_id), str(packet.message_id),
                    _encode_packet_json(packet.packet_json), packet.schema_version,
                    packet.prompt_policy_version, packet.configuration_fingerprint,
                    format_utc_timestamp(packet.created_at),
                ),
            )
            for result in record.retrieval_results:
                self._connection.execute(
                    """
                    INSERT INTO retrieval_results (
                        id, context_packet_id, memory_id, rank, score,
                        reasons_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(result.id), str(result.context_packet_id),
                        str(result.memory_id), result.rank, float(result.score.value),
                        _encode_json(result.reasons),
                        format_utc_timestamp(result.created_at),
                    ),
                )
            for exclusion in record.retrieval_exclusions:
                self._connection.execute(
                    """
                    INSERT INTO retrieval_exclusions (
                        id, context_packet_id, memory_id, exclusion_reason,
                        computed_score, details_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(exclusion.id), str(exclusion.context_packet_id),
                        str(exclusion.memory_id), exclusion.exclusion_reason.value,
                        None
                        if exclusion.computed_score is None
                        else float(exclusion.computed_score.value),
                        _encode_json(exclusion.details),
                        format_utc_timestamp(exclusion.created_at),
                    ),
                )

    def _record(self, packet: ContextPacket) -> ContextPacketRecord:
        results = self._all(
            """
            SELECT * FROM retrieval_results
            WHERE context_packet_id = ? ORDER BY rank, id
            """,
            (str(packet.id),), _retrieval_result, "retrieval results",
        )
        exclusions = self._all(
            """
            SELECT * FROM retrieval_exclusions
            WHERE context_packet_id = ? ORDER BY memory_id, id
            """,
            (str(packet.id),), _retrieval_exclusion, "retrieval exclusions",
        )
        try:
            snapshots = packet.packet_json["retrieval"]
            if isinstance(snapshots, tuple) and len(snapshots) == len(results):
                exact_results: list[RetrievalResult] = []
                for snapshot, result in zip(snapshots, results, strict=True):
                    if not isinstance(snapshot, FrozenJsonObject):
                        exact_results.append(result)
                        continue
                    exact_score = UnitScore(snapshot["score"])
                    if float(exact_score.value) != float(result.score.value):
                        raise LifecycleInvariantError(
                            "Stored retrieval score does not match its packet snapshot."
                        )
                    exact_results.append(replace(result, score=exact_score))
                results = tuple(exact_results)
            return ContextPacketRecord(packet, results, exclusions)
        except DomainError as error:
            raise PersistenceError("Stored context packet aggregate is invalid.") from error

    def get(self, context_packet_id: DomainId) -> ContextPacketRecord | None:
        packet = self._one(
            "SELECT * FROM context_packets WHERE id = ?",
            (str(context_packet_id),), _context_packet, "context packet",
        )
        return None if packet is None else self._record(packet)

    def get_for_run(
        self, processing_run_id: DomainId
    ) -> ContextPacketRecord | None:
        packet = self._one(
            "SELECT * FROM context_packets WHERE processing_run_id = ?",
            (str(processing_run_id),), _context_packet, "context packet",
        )
        return None if packet is None else self._record(packet)


def _validate_model_request_shape(request: ModelRequest, run: ProcessingRun) -> None:
    if request.purpose is ModelRequestPurpose.INITIAL and request.attempt_number != 0:
        raise LifecycleInvariantError("INITIAL model requests require attempt 0.")
    if request.purpose is ModelRequestPurpose.REVISION and request.attempt_number not in (1, 2):
        raise LifecycleInvariantError("REVISION model requests require attempt 1 or 2.")
    if request.attempt_number == 0 and request.purpose is not ModelRequestPurpose.INITIAL:
        raise LifecycleInvariantError("Attempt 0 must have INITIAL purpose.")
    if request.attempt_number in (1, 2) and request.purpose is not ModelRequestPurpose.REVISION:
        raise LifecycleInvariantError("Attempts 1 and 2 must have REVISION purpose.")
    if request.started_at is not None and request.started_at < run.started_at:
        raise LifecycleInvariantError(
            "Model request started_at cannot precede its processing run."
        )
    if request.completed_at is not None and request.started_at is not None:
        if request.completed_at < request.started_at:
            raise LifecycleInvariantError(
                "Model request completed_at cannot precede started_at."
            )
    empty_times = request.started_at is None and request.completed_at is None
    empty_errors = request.error_code is None and request.safe_error_message is None
    if request.status is ModelRequestStatus.PENDING:
        if not empty_times or not empty_errors:
            raise LifecycleInvariantError(
                "PENDING model requests require null timestamps and errors."
            )
    elif request.status is ModelRequestStatus.IN_FLIGHT:
        if request.started_at is None or request.completed_at is not None or not empty_errors:
            raise LifecycleInvariantError(
                "IN_FLIGHT model requests require started_at and null completion/errors."
            )
    elif request.status is ModelRequestStatus.SUCCEEDED:
        if request.started_at is None or request.completed_at is None or not empty_errors:
            raise LifecycleInvariantError(
                "SUCCEEDED model requests require ordered timestamps and null errors."
            )
    elif (
        request.started_at is None
        or request.completed_at is None
        or request.error_code is None
        or request.safe_error_message is None
    ):
        raise LifecycleInvariantError(
            "Failed, timed-out, or cancelled requests require timestamps and safe errors."
        )


class SQLiteModelCallRepository(_SQLiteRepository):
    def _run_for_request(self, request: ModelRequest) -> ProcessingRun:
        return _require_existing(
            SQLiteProcessingRunRepository(self._connection).get(request.processing_run_id),
            "Model request processing run",
        )

    def add_request(self, request: ModelRequest) -> None:
        run = self._run_for_request(request)
        _validate_model_request_shape(request, run)
        if request.status is not ModelRequestStatus.PENDING:
            raise LifecycleInvariantError("A new model request must start as PENDING.")
        if run.status in TERMINAL_PROCESSING_RUN_STATUSES:
            raise LifecycleInvariantError("A terminal run cannot receive a model request.")
        with self._write("Add model request"):
            packet = _fetch_one(
                self._connection,
                "SELECT processing_run_id FROM context_packets WHERE id = ?",
                (str(request.context_packet_id),),
                "Validate model request packet",
            )
            if packet is None or packet["processing_run_id"] != str(request.processing_run_id):
                raise LifecycleInvariantError(
                    "A model request packet must belong to the same processing run."
                )
            if request.attempt_number > 0:
                prior = _fetch_one(
                    self._connection,
                    """
                    SELECT model_requests.status AS request_status,
                           validation_results.status AS validation_status
                    FROM model_requests
                    LEFT JOIN model_responses
                      ON model_responses.model_request_id = model_requests.id
                    LEFT JOIN validation_results
                      ON validation_results.model_response_id = model_responses.id
                    WHERE model_requests.processing_run_id = ?
                      AND model_requests.attempt_number = ?
                    """,
                    (str(request.processing_run_id), request.attempt_number - 1),
                    "Validate prior model attempt",
                )
                if (
                    prior is None
                    or prior["request_status"] != ModelRequestStatus.SUCCEEDED.value
                    or prior["validation_status"] != ValidationStatus.FAILED.value
                ):
                    raise LifecycleInvariantError(
                        "A revision request requires the preceding failed candidate."
                    )
            self._connection.execute(
                """
                INSERT INTO model_requests (
                    id, processing_run_id, context_packet_id, purpose, attempt_number,
                    provider, model_name, status, rendered_prompt, request_json,
                    started_at, completed_at, error_code, safe_error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(request.id), str(request.processing_run_id),
                    str(request.context_packet_id), request.purpose.value,
                    request.attempt_number, request.provider.value, request.model_name,
                    request.status.value, request.rendered_prompt,
                    _encode_json(request.request),
                    None
                    if request.started_at is None
                    else format_utc_timestamp(request.started_at),
                    None
                    if request.completed_at is None
                    else format_utc_timestamp(request.completed_at),
                    request.error_code, request.safe_error_message,
                ),
            )

    def get_request(self, request_id: DomainId) -> ModelRequest | None:
        return self._one(
            "SELECT * FROM model_requests WHERE id = ?",
            (str(request_id),), _model_request, "model request",
        )

    def list_requests_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[ModelRequest, ...]:
        return self._all(
            """
            SELECT * FROM model_requests
            WHERE processing_run_id = ? ORDER BY attempt_number, id
            """,
            (str(processing_run_id),), _model_request, "model requests",
        )

    def update_request(self, request: ModelRequest) -> None:
        run = self._run_for_request(request)
        _validate_model_request_shape(request, run)
        with self._write("Update model request"):
            current = _require_existing(self.get_request(request.id), "Model request")
            immutable_current = (
                current.processing_run_id, current.context_packet_id, current.purpose,
                current.attempt_number, current.provider, current.model_name,
                current.rendered_prompt, current.request,
            )
            immutable_new = (
                request.processing_run_id, request.context_packet_id, request.purpose,
                request.attempt_number, request.provider, request.model_name,
                request.rendered_prompt, request.request,
            )
            if immutable_new != immutable_current:
                raise LifecycleInvariantError("Model request input fields are immutable.")
            if current == request:
                return
            require_model_request_transition(current.status, request.status)
            cursor = self._connection.execute(
                """
                UPDATE model_requests
                SET status = ?, started_at = ?, completed_at = ?,
                    error_code = ?, safe_error_message = ?
                WHERE id = ?
                """,
                (
                    request.status.value,
                    None
                    if request.started_at is None
                    else format_utc_timestamp(request.started_at),
                    None
                    if request.completed_at is None
                    else format_utc_timestamp(request.completed_at),
                    request.error_code, request.safe_error_message, str(request.id),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Model request update did not affect exactly one row.")

    def add_response(self, response: ModelResponse) -> None:
        if response.assistant_message_id is not None:
            raise LifecycleInvariantError(
                "A model response must be persisted before any assistant link."
            )
        with self._write("Add model response"):
            request = _require_existing(
                self.get_request(response.model_request_id), "Model response request"
            )
            if request.status is not ModelRequestStatus.SUCCEEDED:
                raise LifecycleInvariantError(
                    "A model response requires a SUCCEEDED request."
                )
            if request.completed_at is None or response.created_at < request.completed_at:
                raise LifecycleInvariantError(
                    "Model response creation cannot precede request completion."
                )
            self._connection.execute(
                """
                INSERT INTO model_responses (
                    id, model_request_id, response_text, metadata_json,
                    assistant_message_id, created_at
                ) VALUES (?, ?, ?, ?, NULL, ?)
                """,
                (
                    str(response.id), str(response.model_request_id),
                    response.response_text, _encode_json(response.metadata),
                    format_utc_timestamp(response.created_at),
                ),
            )

    def get_response(self, response_id: DomainId) -> ModelResponse | None:
        return self._one(
            "SELECT * FROM model_responses WHERE id = ?",
            (str(response_id),), _model_response, "model response",
        )

    def get_response_for_request(
        self, model_request_id: DomainId
    ) -> ModelResponse | None:
        return self._one(
            "SELECT * FROM model_responses WHERE model_request_id = ?",
            (str(model_request_id),), _model_response, "model response",
        )

    def link_assistant_message(
        self, *, model_response_id: DomainId, assistant_message_id: DomainId
    ) -> None:
        with self._write("Link accepted assistant message"):
            response = _require_existing(
                self.get_response(model_response_id), "Model response"
            )
            if response.assistant_message_id == assistant_message_id:
                return
            if response.assistant_message_id is not None:
                raise PersistenceError(
                    "Model response already links a different assistant message."
                )
            row = _fetch_one(
                self._connection,
                """
                SELECT validation_results.status AS validation_status,
                       messages.role AS message_role,
                       messages.conversation_id AS message_conversation_id,
                       processing_runs.conversation_id AS run_conversation_id,
                       processing_runs.status AS run_status
                FROM model_responses
                JOIN model_requests
                  ON model_requests.id = model_responses.model_request_id
                JOIN processing_runs
                  ON processing_runs.id = model_requests.processing_run_id
                LEFT JOIN validation_results
                  ON validation_results.model_response_id = model_responses.id
                JOIN messages ON messages.id = ?
                WHERE model_responses.id = ?
                """,
                (str(assistant_message_id), str(model_response_id)),
                "Validate assistant message link",
            )
            if row is None:
                raise PersistenceError("Assistant message link inputs do not exist.")
            if row["validation_status"] != ValidationStatus.PASSED.value:
                raise LifecycleInvariantError(
                    "Only a passed validation may receive an assistant link."
                )
            if row["message_role"] != MessageRole.ASSISTANT.value:
                raise LifecycleInvariantError("The linked message must be ASSISTANT.")
            if row["message_conversation_id"] != row["run_conversation_id"]:
                raise LifecycleInvariantError(
                    "Assistant message must belong to the run conversation."
                )
            if ProcessingRunStatus(str(row["run_status"])) in TERMINAL_PROCESSING_RUN_STATUSES:
                raise LifecycleInvariantError(
                    "A terminal run cannot receive a new assistant message link."
                )
            cursor = self._connection.execute(
                """
                UPDATE model_responses SET assistant_message_id = ?
                WHERE id = ? AND assistant_message_id IS NULL
                """,
                (str(assistant_message_id), str(model_response_id)),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("Assistant message link was not applied exactly once.")

    def add_correction(self, correction: CorrectionAttempt) -> None:
        with self._write("Add correction attempt"):
            existing = self._one(
                """
                SELECT * FROM correction_attempts
                WHERE processing_run_id = ? AND attempt_number = ?
                """,
                (str(correction.processing_run_id), correction.attempt_number),
                _correction,
                "correction attempt",
            )
            if existing is not None:
                if existing == correction:
                    return
                raise PersistenceError(
                    "The correction attempt number already identifies another row."
                )
            row = _fetch_one(
                self._connection,
                """
                SELECT prior_request.processing_run_id AS prior_run_id,
                       prior_request.attempt_number AS prior_attempt,
                       prior_validation.status AS prior_validation_status,
                       prior_validation.created_at AS prior_validation_created_at,
                       revised_request.processing_run_id AS revised_run_id,
                       revised_request.attempt_number AS revised_attempt,
                       revised_request.purpose AS revised_purpose,
                       processing_runs.status AS run_status
                FROM model_responses AS prior_response
                JOIN model_requests AS prior_request
                  ON prior_request.id = prior_response.model_request_id
                JOIN validation_results AS prior_validation
                  ON prior_validation.model_response_id = prior_response.id
                JOIN model_requests AS revised_request
                  ON revised_request.id = ?
                JOIN processing_runs
                  ON processing_runs.id = revised_request.processing_run_id
                WHERE prior_response.id = ?
                """,
                (
                    str(correction.revised_model_request_id),
                    str(correction.prior_model_response_id),
                ),
                "Validate correction lineage",
            )
            if row is None:
                raise PersistenceError("Correction lineage records do not exist.")
            if (
                row["prior_run_id"] != str(correction.processing_run_id)
                or row["revised_run_id"] != str(correction.processing_run_id)
                or int(row["prior_attempt"]) != correction.attempt_number - 1
                or int(row["revised_attempt"]) != correction.attempt_number
                or row["revised_purpose"] != ModelRequestPurpose.REVISION.value
                or row["prior_validation_status"] != ValidationStatus.FAILED.value
            ):
                raise LifecycleInvariantError(
                    "Correction lineage must be same-run, consecutive, and validation-driven."
                )
            if correction.created_at < parse_utc_timestamp(
                str(row["prior_validation_created_at"])
            ):
                raise LifecycleInvariantError(
                    "Correction creation cannot precede the failed validation."
                )
            if ProcessingRunStatus(str(row["run_status"])) in TERMINAL_PROCESSING_RUN_STATUSES:
                raise LifecycleInvariantError("A terminal run cannot receive a correction.")
            self._connection.execute(
                """
                INSERT INTO correction_attempts (
                    id, processing_run_id, attempt_number, prior_model_response_id,
                    revised_model_request_id, reason_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(correction.id), str(correction.processing_run_id),
                    correction.attempt_number, str(correction.prior_model_response_id),
                    str(correction.revised_model_request_id),
                    _encode_json(correction.reasons),
                    format_utc_timestamp(correction.created_at),
                ),
            )

    def list_corrections_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[CorrectionAttempt, ...]:
        return self._all(
            """
            SELECT * FROM correction_attempts
            WHERE processing_run_id = ? ORDER BY attempt_number, id
            """,
            (str(processing_run_id),), _correction, "correction attempts",
        )

    def add_failure(self, failure: SafeFailure) -> None:
        with self._write("Add pipeline failure"):
            run = _require_existing(
                SQLiteProcessingRunRepository(self._connection).get(
                    failure.processing_run_id
                ),
                "Pipeline failure processing run",
            )
            if failure.created_at < run.started_at:
                raise LifecycleInvariantError(
                    "Pipeline failure cannot precede processing-run acceptance."
                )
            self._connection.execute(
                """
                INSERT INTO pipeline_failures (
                    id, processing_run_id, stage, error_code, safe_message,
                    details_json, is_terminal, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(failure.id), str(failure.processing_run_id),
                    failure.stage.value, failure.error_code.value,
                    failure.safe_message, _encode_json(failure.details),
                    int(failure.is_terminal), format_utc_timestamp(failure.created_at),
                ),
            )

    def list_failures_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[SafeFailure, ...]:
        return self._all(
            """
            SELECT * FROM pipeline_failures
            WHERE processing_run_id = ? ORDER BY created_at, id
            """,
            (str(processing_run_id),), _safe_failure, "pipeline failures",
        )


class SQLiteValidationRepository(_SQLiteRepository):
    def add(self, result: ValidationResult) -> None:
        with self._write("Add validation result"):
            row = _fetch_one(
                self._connection,
                """
                SELECT model_responses.created_at AS response_created_at,
                       model_requests.status AS request_status
                FROM model_responses
                JOIN model_requests
                  ON model_requests.id = model_responses.model_request_id
                WHERE model_responses.id = ?
                """,
                (str(result.model_response_id),),
                "Validate validation result response",
            )
            if row is None:
                raise PersistenceError("Validation result response does not exist.")
            if row["request_status"] != ModelRequestStatus.SUCCEEDED.value:
                raise LifecycleInvariantError(
                    "Validation requires a SUCCEEDED model request."
                )
            if result.created_at < parse_utc_timestamp(str(row["response_created_at"])):
                raise LifecycleInvariantError(
                    "Validation result cannot precede its model response."
                )
            self._connection.execute(
                """
                INSERT INTO validation_results (
                    id, model_response_id, status, score, violations_json,
                    evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(result.id), str(result.model_response_id), result.status.value,
                    float(result.score.value), _encode_json(result.violations),
                    _encode_json(result.evidence),
                    format_utc_timestamp(result.created_at),
                ),
            )

    def get(self, validation_result_id: DomainId) -> ValidationResult | None:
        return self._one(
            "SELECT * FROM validation_results WHERE id = ?",
            (str(validation_result_id),), _validation_result, "validation result",
        )

    def get_for_response(
        self, model_response_id: DomainId
    ) -> ValidationResult | None:
        return self._one(
            "SELECT * FROM validation_results WHERE model_response_id = ?",
            (str(model_response_id),), _validation_result, "validation result",
        )

    def list_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[ValidationResult, ...]:
        return self._all(
            """
            SELECT validation_results.*
            FROM validation_results
            JOIN model_responses
              ON model_responses.id = validation_results.model_response_id
            JOIN model_requests
              ON model_requests.id = model_responses.model_request_id
            WHERE model_requests.processing_run_id = ?
            ORDER BY model_requests.attempt_number, validation_results.id
            """,
            (str(processing_run_id),), _validation_result, "validation results",
        )


class SQLiteClarificationRepository(_SQLiteRepository):
    def add(self, clarification: ClarificationRequest) -> None:
        with self._write("Add clarification request"):
            existing = self.get_for_run(clarification.processing_run_id)
            if existing is not None:
                if existing == clarification:
                    return
                raise PersistenceError(
                    "The run already has a different clarification request."
                )
            run = _require_existing(
                SQLiteProcessingRunRepository(self._connection).get(
                    clarification.processing_run_id
                ),
                "Clarification processing run",
            )
            if run.status is not ProcessingRunStatus.NEEDS_CLARIFICATION:
                raise LifecycleInvariantError(
                    "A clarification row requires NEEDS_CLARIFICATION run status."
                )
            if clarification.created_at < run.started_at:
                raise LifecycleInvariantError(
                    "Clarification cannot precede processing-run acceptance."
                )
            related = _fetch_one(
                self._connection,
                """
                SELECT
                    EXISTS(SELECT 1 FROM model_requests WHERE processing_run_id = ?) AS requests,
                    EXISTS(SELECT 1 FROM pipeline_failures WHERE processing_run_id = ?) AS failures
                """,
                (str(clarification.processing_run_id), str(clarification.processing_run_id)),
                "Validate clarification exclusivity",
            )
            if related is None or related["requests"] or related["failures"]:
                raise LifecycleInvariantError(
                    "A clarification run cannot have model requests or pipeline failures."
                )
            self._connection.execute(
                """
                INSERT INTO clarification_requests (
                    id, processing_run_id, reason_code, question_text,
                    details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(clarification.id), str(clarification.processing_run_id),
                    clarification.reason.value, clarification.question_text,
                    _encode_json(clarification.details),
                    format_utc_timestamp(clarification.created_at),
                ),
            )

    def get_for_run(
        self, processing_run_id: DomainId
    ) -> ClarificationRequest | None:
        return self._one(
            "SELECT * FROM clarification_requests WHERE processing_run_id = ?",
            (str(processing_run_id),), _clarification, "clarification request",
        )


_SETTING_KEYS = frozenset(
    {
        "ui.theme",
        "ui.context_panel_visible",
        "ui.last_selected_conversation_id",
    }
)


def _validate_setting(key: str, value: FrozenJsonValue) -> FrozenJsonValue:
    if key not in _SETTING_KEYS:
        raise LifecycleInvariantError("Unknown SQLite presentation setting key.")
    frozen = freeze_json(value)
    if key == "ui.theme" and frozen not in ("SYSTEM", "LIGHT", "DARK"):
        raise LifecycleInvariantError("ui.theme must be SYSTEM, LIGHT, or DARK.")
    if key == "ui.context_panel_visible" and not isinstance(frozen, bool):
        raise LifecycleInvariantError("ui.context_panel_visible must be boolean.")
    if key == "ui.last_selected_conversation_id":
        if frozen is not None and not isinstance(frozen, str):
            raise LifecycleInvariantError(
                "ui.last_selected_conversation_id must be UUID text or null."
            )
        if isinstance(frozen, str):
            DomainId(frozen)
    return frozen


class SQLiteSettingsRepository(_SQLiteRepository):
    def get(self, key: str) -> Setting | None:
        return self._one(
            "SELECT * FROM settings WHERE key = ?", (key,), _setting, "setting"
        )

    def list_all(self) -> tuple[Setting, ...]:
        return self._all(
            "SELECT * FROM settings ORDER BY key", (), _setting, "settings"
        )

    def set(
        self, *, key: str, value: FrozenJsonValue, updated_at: datetime
    ) -> Setting:
        frozen = _validate_setting(key, value)
        candidate = Setting(key, frozen, updated_at)
        with self._write("Set presentation setting"):
            current = self.get(key)
            if current is not None and candidate.updated_at < current.updated_at:
                raise LifecycleInvariantError("Setting.updated_at cannot move backward.")
            self._connection.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, _encode_json(frozen), format_utc_timestamp(candidate.updated_at)),
            )
        stored = self.get(key)
        if stored is None:
            raise PersistenceError("Setting upsert did not produce a stored row.")
        return stored


class SQLiteEvaluationRepository(_SQLiteRepository):
    def add_case(self, case: EvaluationCase) -> None:
        with self._write("Add evaluation case"):
            self._connection.execute(
                """
                INSERT INTO evaluation_cases (
                    id, name, category, case_json, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(case.id), case.name, case.category, _encode_json(case.case),
                    int(case.enabled), format_utc_timestamp(case.created_at),
                    format_utc_timestamp(case.updated_at),
                ),
            )

    def get_case(self, evaluation_case_id: DomainId) -> EvaluationCase | None:
        return self._one(
            "SELECT * FROM evaluation_cases WHERE id = ?",
            (str(evaluation_case_id),), _evaluation_case, "evaluation case",
        )

    def list_cases(self, *, enabled_only: bool = False) -> tuple[EvaluationCase, ...]:
        if not isinstance(enabled_only, bool):
            raise LifecycleInvariantError("enabled_only must be boolean.")
        sql = "SELECT * FROM evaluation_cases"
        parameters: tuple[object, ...] = ()
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name, id"
        return self._all(sql, parameters, _evaluation_case, "evaluation cases")

    def add_run(self, run: EvaluationRun) -> None:
        with self._write("Add evaluation run"):
            self._connection.execute(
                """
                INSERT INTO evaluation_runs (
                    id, evaluation_case_id, fixture_version, provider_mode,
                    result_json, passed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run.id), str(run.evaluation_case_id), run.fixture_version,
                    run.provider_mode.value, _encode_json(run.result), int(run.passed),
                    format_utc_timestamp(run.created_at),
                ),
            )

    def list_runs_for_case(
        self, evaluation_case_id: DomainId
    ) -> tuple[EvaluationRun, ...]:
        return self._all(
            """
            SELECT * FROM evaluation_runs
            WHERE evaluation_case_id = ? ORDER BY created_at, id
            """,
            (str(evaluation_case_id),), _evaluation_run, "evaluation runs",
        )


__all__ = [
    "SQLiteClarificationRepository",
    "SQLiteConstraintRepository",
    "SQLiteContextPacketRepository",
    "SQLiteConversationRepository",
    "SQLiteConversationStateRepository",
    "SQLiteEntityRepository",
    "SQLiteEvaluationRepository",
    "SQLiteMemoryRepository",
    "SQLiteMessageRepository",
    "SQLiteModelCallRepository",
    "SQLiteProcessingRunRepository",
    "SQLiteProjectRepository",
    "SQLiteReferenceResolutionRepository",
    "SQLiteSettingsRepository",
    "SQLiteTaskRepository",
    "SQLiteTopicRepository",
    "SQLiteTransactionBoundary",
    "SQLiteValidationRepository",
]
