"""TASK-0005 integration coverage for canonical SQLite repositories."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from context_for_ai.context_engine.prompt_rendering import _plan_initial
from context_for_ai.context_engine.response_validation import (
    DeterministicResponseValidator,
)
from context_for_ai.domain.decisions import (
    CONDITION_GRAMMAR_VERSION,
    CONTEXT_PACKET_SCHEMA_VERSION,
    HISTORICAL_PROMPT_POLICY_VERSION,
    PROMPT_POLICY_VERSION,
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
    ValidationCheckId,
    ValidationOutcome,
    ValidationSeverity,
    ValidationStatus,
    ValidationViolationCode,
    ValidationWarningCode,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
    CorrectionAttempt,
    MatchLocation,
    ModelRequest,
    ModelResponse,
    ProcessingRun,
    SafeFailure,
    ValidationEvidence,
    ValidationResult,
    ValidationViolation,
    ValidationViolationEvidence,
    calculate_validation_score,
)
from context_for_ai.domain.policies import memory_revision_metadata
from context_for_ai.domain.ports import (
    AdmissionRaceError,
    ClarificationRepository,
    CorrectionExhausted,
    ConstraintRepository,
    ContextPacketRecord,
    ContextPacketRepository,
    ConversationRepository,
    ConversationStateRepository,
    EntityRepository,
    EvaluationCase,
    EvaluationRepository,
    EvaluationRun,
    MemoryRepository,
    MessageRepository,
    ModelCallRepository,
    PersistenceError,
    ProcessingRunRepository,
    ProjectRepository,
    ReferenceResolutionRepository,
    SettingsRepository,
    TaskRepository,
    TopicRepository,
    TransactionBoundary,
    ValidationRepository,
    ValidationRequest,
    ContextBudgetExceeded,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore
from context_for_ai.infrastructure.database import (
    SQLiteClarificationRepository,
    SQLiteConstraintRepository,
    SQLiteContextPacketRepository,
    SQLiteConversationRepository,
    SQLiteConversationStateRepository,
    SQLiteEntityRepository,
    SQLiteEvaluationRepository,
    SQLiteMemoryRepository,
    SQLiteMessageRepository,
    SQLiteModelCallRepository,
    SQLiteProcessingRunRepository,
    SQLiteProjectRepository,
    SQLiteReferenceResolutionRepository,
    SQLiteSettingsRepository,
    SQLiteTaskRepository,
    SQLiteTopicRepository,
    SQLiteTransactionBoundary,
    SQLiteValidationRepository,
    apply_migrations,
    connect_database,
)


BASE_TIME = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def identifier(number: int) -> DomainId:
    return DomainId(f"10000000-0000-4000-8000-{number:012x}")


def stamp(seconds: int) -> datetime:
    return BASE_TIME + timedelta(seconds=seconds)


def context_packet_fixture(
    *,
    packet_id: DomainId,
    run: ProcessingRun,
    message: Message,
    created_at: datetime,
    results: tuple[RetrievalResult, ...] = (),
    memories: tuple[Memory, ...] = (),
    correction_limit: int = 2,
    prompt_policy_version: str = PROMPT_POLICY_VERSION,
) -> ContextPacket:
    assert tuple(result.memory_id for result in results) == tuple(
        memory.id for memory in memories
    )
    confidence = Decimal("1") if not results else results[0].score.value
    payload: dict[str, object] = {
        "schema_version": CONTEXT_PACKET_SCHEMA_VERSION,
        "trace": {
            "processing_run_id": str(run.id),
            "conversation_id": str(run.conversation_id),
            "user_message_id": str(message.id),
            "state_version": 0,
            "configuration_fingerprint": run.configuration_fingerprint,
        },
        "request": {
            "original_text": message.original_text,
            "intent": "ANSWER",
            "intent_rule_id": "fixture-intent",
            "expected_output_type": "TEXT_ANSWER",
            "qualifiers": (),
            "confidence": confidence,
        },
        "active_state": {
            "project_id": None,
            "topic_id": None,
            "task_id": None,
            "previous_task_id": None,
            "topic_stack": (),
        },
        "validation_context": {
            "rule_set_version": "fixture-validation-v1",
            "active_topic": None,
            "output_shape_rule": {
                "id": "fixture-shape-answer",
                "output_type": "TEXT_ANSWER",
                "shape": "NON_EMPTY_TEXT",
            },
            "preserve_change_verb_list_id": "fixture-preserve-v1",
            "preserve_change_verbs": ("change",),
            "action_markers": ("TOOL_CALL:",),
        },
        "references": (),
        "constraints": (),
        "retrieval": tuple(
            {
                "memory_id": str(memory.id),
                "content": memory.content,
                "score": result.score.value,
                "rank": result.rank,
                "reasons": result.reasons,
                "scope": memory.scope.value,
                "confidence": memory.confidence.value,
            }
            for result, memory in zip(results, memories, strict=True)
        ),
        "confidence": {
            "interpretation": confidence,
            "references": None,
            "retrieval": None if not results else results[0].score.value,
            "overall": confidence,
        },
        "response_policy": {
            "output_type": "TEXT_ANSWER",
            "validate_before_display": True,
            "text_only": True,
            "no_actions": True,
            "streaming": False,
            "correction_limit": correction_limit,
            "model_generation_limit": correction_limit + 1,
            "absolute_model_generation_cap": 3,
        },
        "rendering": {
            "prompt_policy_version": prompt_policy_version,
            "token_estimator": "conservative_utf8_v1",
            "token_budget": 10000,
            "mandatory_estimated_tokens": 0,
            "estimated_prompt_tokens": 0,
            "included_sections": (),
            "omitted_sections": (),
        },
    }
    plan = _plan_initial(
        context_packet_id=packet_id,
        packet_json=FrozenJsonObject(payload),
        effective_budget=10000,
    )
    assert not isinstance(plan, ContextBudgetExceeded)
    payload["rendering"] = plan.metadata.to_json_object()
    return ContextPacket(
        packet_id,
        run.id,
        message.id,
        FrozenJsonObject(payload),
        CONTEXT_PACKET_SCHEMA_VERSION,
        prompt_policy_version,
        run.configuration_fingerprint,
        created_at,
    )


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    database_path = apply_migrations(tmp_path / "repositories.sqlite3")
    opened = connect_database(database_path)
    try:
        yield opened
    finally:
        opened.close()


def repositories(connection: sqlite3.Connection) -> SimpleNamespace:
    return SimpleNamespace(
        transactions=SQLiteTransactionBoundary(connection),
        projects=SQLiteProjectRepository(connection),
        conversations=SQLiteConversationRepository(connection),
        topics=SQLiteTopicRepository(connection),
        tasks=SQLiteTaskRepository(connection),
        states=SQLiteConversationStateRepository(connection),
        messages=SQLiteMessageRepository(connection),
        entities=SQLiteEntityRepository(connection),
        references=SQLiteReferenceResolutionRepository(connection),
        constraints=SQLiteConstraintRepository(connection),
        memories=SQLiteMemoryRepository(connection),
        runs=SQLiteProcessingRunRepository(connection),
        packets=SQLiteContextPacketRepository(connection),
        models=SQLiteModelCallRepository(connection),
        validations=SQLiteValidationRepository(connection),
        clarifications=SQLiteClarificationRepository(connection),
        settings=SQLiteSettingsRepository(connection),
        evaluations=SQLiteEvaluationRepository(connection),
    )


@dataclass(frozen=True, slots=True)
class CoreRecords:
    project: Project
    conversation: Conversation
    state: ConversationState
    user_message: Message
    run: ProcessingRun


def seed_core(bundle: SimpleNamespace) -> CoreRecords:
    project = Project(
        identifier(1),
        "Context for AI",
        "Repository fixture",
        ProjectStatus.ACTIVE,
        stamp(0),
        stamp(0),
    )
    conversation = Conversation(
        identifier(2), project.id, "SQLite repositories", stamp(1), stamp(1)
    )
    state = ConversationState(
        conversation.id, None, None, None, None, (), 0, stamp(2)
    )
    user_message = Message(
        identifier(3),
        conversation.id,
        MessageRole.USER,
        "  Preserve exact Unicode: café ☕\nsecond line  ",
        stamp(3),
        0,
    )
    run = ProcessingRun(
        identifier(4),
        conversation.id,
        user_message.id,
        str(identifier(5)),
        ProcessingRunStatus.PERSISTED,
        0,
        "fixture-fingerprint",
        stamp(4),
        None,
    )
    with bundle.transactions.transaction():
        bundle.projects.add(project)
        bundle.conversations.add(conversation)
        bundle.states.add(state)
        bundle.messages.add(user_message)
        bundle.runs.add(run)
    return CoreRecords(project, conversation, state, user_message, run)


def add_memory(
    bundle: SimpleNamespace,
    core: CoreRecords,
    *,
    number: int,
    content: str,
    scope: MemoryScope = MemoryScope.PROJECT,
    created_second: int = 10,
) -> tuple[Memory, MemorySource, MemoryRevision]:
    conversation_id = core.conversation.id if scope is MemoryScope.CONVERSATION else None
    project_id = core.project.id if scope is MemoryScope.PROJECT else None
    memory = Memory(
        identifier(number),
        conversation_id,
        project_id,
        MemoryType.TECHNICAL_ENVIRONMENT,
        scope,
        MemoryStatus.ACTIVE,
        content,
        ("sqlite", "café"),
        ("persistence",),
        UnitScore("0.70"),
        UnitScore("0.90"),
        stamp(created_second + 100),
        stamp(created_second),
        stamp(created_second),
        None,
    )
    source = MemorySource(
        identifier(number + 1),
        memory.id,
        MemorySourceKind.MANUAL_ENTRY,
        None,
        "Explicit fixture memory",
        stamp(created_second),
    )
    revision = MemoryRevision(
        identifier(number + 2),
        memory.id,
        1,
        MemoryRevisionOperation.CREATE,
        memory.content,
        memory_revision_metadata(memory, source.id),
        LocalActor.LOCAL_USER,
        stamp(created_second),
    )
    bundle.memories.add(memory, source, revision)
    return memory, source, revision


def add_empty_packet(
    bundle: SimpleNamespace,
    core: CoreRecords,
    *,
    packet_number: int = 30,
    correction_limit: int = 2,
    prompt_policy_version: str = PROMPT_POLICY_VERSION,
) -> tuple[ContextPacketRecord, ProcessingRun]:
    packet = context_packet_fixture(
        packet_id=identifier(packet_number),
        run=core.run,
        message=core.user_message,
        created_at=stamp(10),
        correction_limit=correction_limit,
        prompt_policy_version=prompt_policy_version,
    )
    record = ContextPacketRecord(packet, (), ())
    context_ready = replace(core.run, status=ProcessingRunStatus.CONTEXT_READY)
    with bundle.transactions.transaction():
        bundle.packets.add(record)
        bundle.runs.update(context_ready)
    return record, context_ready


def initial_request(core: CoreRecords, packet: ContextPacket) -> ModelRequest:
    request_id = identifier(40)
    return ModelRequest(
        request_id,
        core.run.id,
        packet.id,
        ModelRequestPurpose.INITIAL,
        0,
        ProviderKind.OLLAMA,
        "fixture-model",
        ModelRequestStatus.PENDING,
        "Rendered prompt\nwith Unicode ☕",
        model_request_projection(
            request_id=request_id,
            processing_run_id=core.run.id,
            context_packet_id=packet.id,
            attempt_number=0,
            render_kind="INITIAL",
            prompt_policy_version=packet.prompt_policy_version,
        ),
        None,
        None,
        None,
        None,
    )


def model_request_projection(
    *,
    request_id: DomainId,
    processing_run_id: DomainId,
    context_packet_id: DomainId,
    attempt_number: int,
    render_kind: str,
    prompt_policy_version: str = PROMPT_POLICY_VERSION,
) -> FrozenJsonObject:
    return FrozenJsonObject(
        {
            "schema_version": "mvp-model-request-v1",
            "correlation": {
                "processing_run_id": str(processing_run_id),
                "context_packet_id": str(context_packet_id),
                "model_request_id": str(request_id),
                "attempt_number": attempt_number,
            },
            "generation_settings": {
                "context_window_tokens": 4096,
                "request_timeout_seconds": 60,
                "temperature_decimal": "0",
            },
            "rendering": {
                "render_kind": render_kind,
                "prompt_policy_version": prompt_policy_version,
                "estimated_prompt_tokens": 64,
                "effective_prompt_budget": 3584,
                "included_sections": (),
                "omitted_sections": (),
            },
        }
    )


def completed_response_projection(
    request: ModelRequest,
    response_id: DomainId,
    *,
    provider_metadata: FrozenJsonObject | None = None,
) -> FrozenJsonObject:
    return FrozenJsonObject(
        {
            "schema_version": "mvp-completed-generation-v1",
            "correlation": {
                "processing_run_id": str(request.processing_run_id),
                "context_packet_id": str(request.context_packet_id),
                "model_request_id": str(request.id),
                "model_response_id": str(response_id),
                "attempt_number": request.attempt_number,
            },
            "elapsed_microseconds": 125000,
            "token_usage": {
                "prompt_tokens": 12,
                "generated_tokens": 8,
                "total_tokens": 20,
            },
            "provider_metadata": (
                FrozenJsonObject({"fixture": "sqlite"})
                if provider_metadata is None
                else provider_metadata
            ),
        }
    )


def validate_response(
    packet: ContextPacket,
    response: ModelResponse,
    *,
    result_id: DomainId = identifier(42),
    created_at: datetime = BASE_TIME + timedelta(seconds=22),
) -> ValidationResult:
    return DeterministicResponseValidator().validate(
        ValidationRequest(
            packet,
            response.id,
            result_id,
            response.response_text,
            created_at,
        )
    )


def validation_input(
    *,
    candidate_token_count: int,
    sentence_count: int,
    output: bool = False,
) -> FrozenJsonObject:
    return FrozenJsonObject(
        {
            "candidate_token_count": candidate_token_count,
            "sentence_count": sentence_count,
            "predicate": None,
            "topic_terms": (),
            "output_type": "TEXT_ANSWER" if output else None,
            "output_shape": "NON_EMPTY_TEXT" if output else None,
        }
    )


def repetition_score_report(
    result_id: DomainId,
    response_id: DomainId,
    repetition_count: int,
) -> ValidationResult:
    sentence_count = max(1, repetition_count * 2)
    common = {
        "candidate_token_count": sentence_count,
        "sentence_count": sentence_count,
    }
    evidence: list[ValidationEvidence] = [
        ValidationEvidence(
            0,
            ValidationCheckId.TOPIC,
            None,
            None,
            ValidationSeverity.INFO,
            ValidationOutcome.NOT_APPLICABLE,
            validation_input(**common),
            (),
            None,
            None,
            None,
            "The check is not applicable to this packet.",
        ),
        ValidationEvidence(
            1,
            ValidationCheckId.OUTPUT_SHAPE,
            "fixture-shape-answer",
            None,
            ValidationSeverity.INFO,
            ValidationOutcome.PASSED,
            validation_input(**common, output=True),
            (),
            None,
            None,
            None,
            "The deterministic predicate passed.",
        ),
        ValidationEvidence(
            2,
            ValidationCheckId.ACTION_MARKER,
            None,
            None,
            ValidationSeverity.INFO,
            ValidationOutcome.PASSED,
            validation_input(**common),
            (),
            None,
            None,
            None,
            "The deterministic predicate passed.",
        ),
    ]
    if repetition_count:
        for group in range(repetition_count):
            start = group * 4
            evidence.append(
                ValidationEvidence(
                    len(evidence),
                    ValidationCheckId.REPETITION,
                    None,
                    None,
                    ValidationSeverity.WARNING,
                    ValidationOutcome.WARNING,
                    validation_input(**common),
                    (
                        MatchLocation(start, start + 1, group * 2),
                        MatchLocation(start + 2, start + 3, group * 2 + 1),
                    ),
                    None,
                    None,
                    ValidationWarningCode.UNNECESSARY_REPETITION,
                    "A non-failing deterministic warning was recorded.",
                )
            )
    else:
        evidence.append(
            ValidationEvidence(
                len(evidence),
                ValidationCheckId.REPETITION,
                None,
                None,
                ValidationSeverity.INFO,
                ValidationOutcome.PASSED,
                validation_input(**common),
                (),
                None,
                None,
                None,
                "The deterministic predicate passed.",
            )
        )
    frozen_evidence = tuple(evidence)
    return ValidationResult(
        result_id,
        response_id,
        ValidationStatus.PASSED,
        calculate_validation_score((), frozen_evidence),
        (),
        frozen_evidence,
        stamp(22),
    )


REPOSITORY_IMPLEMENTATIONS = (
    (ProjectRepository, SQLiteProjectRepository),
    (ConversationRepository, SQLiteConversationRepository),
    (TopicRepository, SQLiteTopicRepository),
    (TaskRepository, SQLiteTaskRepository),
    (ConversationStateRepository, SQLiteConversationStateRepository),
    (MessageRepository, SQLiteMessageRepository),
    (EntityRepository, SQLiteEntityRepository),
    (ReferenceResolutionRepository, SQLiteReferenceResolutionRepository),
    (ConstraintRepository, SQLiteConstraintRepository),
    (MemoryRepository, SQLiteMemoryRepository),
    (ProcessingRunRepository, SQLiteProcessingRunRepository),
    (ContextPacketRepository, SQLiteContextPacketRepository),
    (ModelCallRepository, SQLiteModelCallRepository),
    (ValidationRepository, SQLiteValidationRepository),
    (ClarificationRepository, SQLiteClarificationRepository),
    (SettingsRepository, SQLiteSettingsRepository),
    (EvaluationRepository, SQLiteEvaluationRepository),
    (TransactionBoundary, SQLiteTransactionBoundary),
)


@pytest.mark.parametrize(("protocol", "implementation"), REPOSITORY_IMPLEMENTATIONS)
def test_sqlite_adapters_conform_to_inward_protocol_signatures(
    protocol: type[object], implementation: type[object]
) -> None:
    protocol_methods = {
        name: method
        for name, method in inspect.getmembers(protocol, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    for name, protocol_method in protocol_methods.items():
        implementation_method = getattr(implementation, name)
        assert tuple(inspect.signature(implementation_method).parameters) == tuple(
            inspect.signature(protocol_method).parameters
        )
        assert get_type_hints(implementation_method) == get_type_hints(protocol_method)


def test_core_entity_state_message_and_archive_repositories(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)

    assert bundle.projects.get(core.project.id) == core.project
    assert bundle.conversations.get(core.conversation.id) == core.conversation
    assert bundle.states.get(core.conversation.id) == core.state
    assert bundle.messages.get(core.user_message.id) == core.user_message
    assert bundle.runs.get(core.run.id) == core.run
    assert bundle.runs.get_by_idempotency_key(
        conversation_id=core.conversation.id,
        idempotency_key=DomainId(core.run.idempotency_key),
    ) == core.run
    bundle.runs.add(core.run)
    assert connection.execute("SELECT count(*) FROM processing_runs").fetchone()[0] == 1

    unscoped = Conversation(identifier(6), None, None, stamp(5), stamp(5))
    bundle.conversations.add(unscoped)
    updated_unscoped = replace(unscoped, title="Unscoped", updated_at=stamp(6))
    bundle.conversations.update(updated_unscoped)
    assert bundle.conversations.list_for_project(None) == (updated_unscoped,)

    first_topic = Topic(
        identifier(10), core.conversation.id, "Persistence", "persistence", stamp(10), stamp(10)
    )
    second_topic = Topic(
        identifier(11), core.conversation.id, "SQLite", "sqlite", stamp(11), stamp(11)
    )
    bundle.topics.add(second_topic)
    bundle.topics.add(first_topic)
    renamed_topic = replace(
        first_topic,
        label="Durable persistence",
        normalized_label="durable persistence",
        updated_at=stamp(12),
    )
    bundle.topics.update(renamed_topic)
    assert bundle.topics.get_by_normalized_label(
        core.conversation.id, "durable persistence"
    ) == renamed_topic
    assert bundle.topics.list_for_conversation(core.conversation.id) == (
        renamed_topic,
        second_topic,
    )

    task = ConversationTask(
        identifier(12),
        core.conversation.id,
        renamed_topic.id,
        "Implement repositories",
        TaskStatus.OPEN,
        stamp(13),
        stamp(13),
    )
    bundle.tasks.add(task)
    in_progress_task = replace(task, status=TaskStatus.IN_PROGRESS, updated_at=stamp(14))
    bundle.tasks.update(in_progress_task)

    selected_state = replace(
        core.state,
        active_topic_id=renamed_topic.id,
        active_task_id=task.id,
        expected_output_type=OutputType.TEXT_CODE,
        topic_stack=(renamed_topic.id,),
        version=1,
        updated_at=stamp(15),
    )
    assert bundle.states.compare_and_swap(expected_version=0, state=selected_state)
    assert not bundle.states.compare_and_swap(expected_version=0, state=selected_state)
    assert bundle.states.get(core.conversation.id) == selected_state

    second_message = Message(
        identifier(13), core.conversation.id, MessageRole.USER, "second", stamp(16), 1
    )
    third_message = Message(
        identifier(14), core.conversation.id, MessageRole.USER, "third", stamp(17), 2
    )
    bundle.messages.add(second_message)
    bundle.messages.add(third_message)
    assert bundle.messages.next_sequence_number(core.conversation.id) == 3
    assert bundle.messages.list_for_conversation(
        core.conversation.id, limit=2
    ) == (second_message, third_message)

    project_entity = Entity(
        identifier(20),
        EntityType.PROJECT,
        core.project.id,
        core.project.id,
        core.project.name,
        "context for ai",
        None,
        True,
        stamp(18),
        stamp(18),
    )
    topic_entity = Entity(
        identifier(21),
        EntityType.TOPIC,
        renamed_topic.id,
        core.project.id,
        renamed_topic.label,
        renamed_topic.normalized_label,
        None,
        True,
        stamp(19),
        stamp(19),
    )
    task_entity = Entity(
        identifier(22),
        EntityType.TASK,
        task.id,
        core.project.id,
        task.title,
        "implement repositories",
        None,
        True,
        stamp(20),
        stamp(20),
    )
    bundle.entities.add(project_entity)
    bundle.entities.add(topic_entity)
    bundle.entities.add(task_entity)

    named_item = NamedItem(
        identifier(23),
        core.conversation.id,
        core.project.id,
        "Repository layer",
        "repository layer",
        core.user_message.id,
        stamp(21),
        stamp(21),
    )
    named_entity = Entity(
        identifier(24),
        EntityType.NAMED_ITEM,
        named_item.id,
        core.project.id,
        named_item.display_name,
        named_item.normalized_name,
        core.user_message.id,
        True,
        stamp(21),
        stamp(21),
    )
    bundle.entities.add_named_item(named_item, named_entity)
    renamed_named_item = replace(
        named_item,
        display_name="SQLite repository layer",
        normalized_name="sqlite repository layer",
        updated_at=stamp(22),
    )
    renamed_entity = replace(
        named_entity,
        display_name="SQLite repository layer",
        normalized_name="sqlite repository layer",
        updated_at=stamp(22),
    )
    bundle.entities.update_named_item(renamed_named_item, renamed_entity)
    assert bundle.entities.get_named_item(named_item.id) == renamed_named_item
    assert bundle.entities.get(named_entity.id) == renamed_entity
    assert {entity.id for entity in bundle.entities.list_reference_candidates(
        conversation_id=core.conversation.id, project_id=core.project.id
    )} == {project_entity.id, topic_entity.id, task_entity.id, named_entity.id}

    retitled_conversation = replace(
        core.conversation, title="Retitled", updated_at=stamp(23)
    )
    bundle.conversations.update(retitled_conversation)
    assert bundle.conversations.get(core.conversation.id) == retitled_conversation

    with pytest.raises(LifecycleInvariantError, match="cannot be archived"):
        bundle.projects.update(
            replace(core.project, status=ProjectStatus.ARCHIVED, updated_at=stamp(24))
        )

    cleared_state = replace(
        selected_state,
        active_task_id=None,
        previous_task_id=task.id,
        version=2,
        updated_at=stamp(25),
    )
    assert bundle.states.compare_and_swap(expected_version=1, state=cleared_state)
    completed_task = replace(
        in_progress_task, status=TaskStatus.COMPLETED, updated_at=stamp(26)
    )
    bundle.tasks.update(completed_task)
    assert bundle.entities.get(task_entity.id).is_active is False
    reopened_task = replace(completed_task, status=TaskStatus.OPEN, updated_at=stamp(27))
    bundle.tasks.update(reopened_task)
    assert bundle.tasks.list_for_conversation(core.conversation.id) == (reopened_task,)
    assert bundle.entities.get(task_entity.id).is_active is True

    failed_run = replace(
        core.run, status=ProcessingRunStatus.FAILED, completed_at=stamp(28)
    )
    terminal_failure = SafeFailure(
        identifier(99),
        core.run.id,
        PipelineStage.TERMINALIZATION,
        FailureCode.PERSISTENCE_ERROR,
        "The processing run ended safely.",
        FrozenJsonObject({"test_fixture": True}),
        True,
        stamp(28),
    )
    with bundle.transactions.transaction():
        bundle.runs.update(failed_run)
        bundle.models.add_failure(terminal_failure)
    archived_project = replace(
        core.project, status=ProjectStatus.ARCHIVED, updated_at=stamp(29)
    )
    bundle.projects.update(archived_project)
    assert bundle.projects.list_by_status(ProjectStatus.ARCHIVED) == (archived_project,)
    assert bundle.entities.get(project_entity.id).is_active is False
    assert bundle.entities.get(task_entity.id).is_active is False
    stale_candidates = bundle.entities.list_reference_candidates(
        conversation_id=core.conversation.id, project_id=core.project.id
    )
    assert {entity.id for entity in stale_candidates} == {
        project_entity.id,
        topic_entity.id,
        task_entity.id,
        named_entity.id,
    }
    assert all(entity.is_active is False for entity in stale_candidates)


def test_context_packet_rejects_trace_conversation_outside_its_run(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet = context_packet_fixture(
        packet_id=identifier(30),
        run=core.run,
        message=core.user_message,
        created_at=stamp(10),
    )
    payload = dict(packet.packet_json.items())
    trace = packet.packet_json["trace"]
    assert isinstance(trace, FrozenJsonObject)
    payload["trace"] = {
        **dict(trace.items()),
        "conversation_id": str(identifier(999)),
    }
    mismatched = ContextPacket(
        packet.id,
        packet.processing_run_id,
        packet.message_id,
        FrozenJsonObject(payload),
        packet.schema_version,
        packet.prompt_policy_version,
        packet.configuration_fingerprint,
        packet.created_at,
    )

    with pytest.raises(LifecycleInvariantError, match="trace conversation"):
        bundle.packets.add(ContextPacketRecord(mismatched, (), ()))

    assert bundle.packets.get(packet.id) is None


def test_decision_memory_and_packet_aggregates_round_trip_exactly(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    selected_memory, _, _ = add_memory(
        bundle,
        core,
        number=100,
        content="Use SQLite JSON safely — café",
        created_second=10,
    )
    duplicate_memory, _, _ = add_memory(
        bundle,
        core,
        number=110,
        content=selected_memory.content,
        created_second=11,
    )
    resolved_entity = Entity(
        identifier(121),
        EntityType.PROJECT,
        core.project.id,
        core.project.id,
        core.project.name,
        "context for ai",
        None,
        True,
        stamp(12),
        stamp(12),
    )
    bundle.entities.add(resolved_entity)

    resolved = ReferenceOutcome(
        identifier(120),
        core.run.id,
        core.user_message.id,
        1,
        "it",
        ReferenceStatus.RESOLVED,
        resolved_entity.id,
        None,
        UnitScore("0.90"),
        (
            ReferenceCandidateEvidence(
                1,
                resolved_entity.id,
                resolved_entity.entity_type,
                resolved_entity.display_name,
                resolved_entity.normalized_name,
                UnitScore("0.90"),
                ReferenceRankReason.ACTIVE_STATE,
                None,
                None,
                None,
                None,
                True,
            ),
        ),
        stamp(12),
    )
    unresolved = ReferenceOutcome(
        identifier(122),
        core.run.id,
        core.user_message.id,
        0,
        "that",
        ReferenceStatus.UNRESOLVED,
        None,
        None,
        UnitScore("0.00"),
        (
            ReferenceCandidateEvidence(
                1,
                None,
                None,
                None,
                None,
                UnitScore("0.00"),
                ReferenceRankReason.NO_CANDIDATE,
                None,
                None,
                None,
                None,
                None,
            ),
        ),
        stamp(12),
    )
    bundle.references.add_all((unresolved, resolved))
    assert bundle.references.list_for_run(core.run.id) == (unresolved, resolved)
    assert bundle.references.list_resolved_for_messages(
        (core.user_message.id,)
    ) == (resolved,)

    condition = Condition(
        CONDITION_GRAMMAR_VERSION,
        ConditionKind.OUTPUT_TYPE_EQUALS,
        OutputType.TEXT_CODE.value,
        ConditionEvaluation.TRUE,
    )
    conditional = Constraint(
        identifier(123),
        core.run.id,
        core.user_message.id,
        1,
        ConstraintType.CONDITIONAL,
        ConstraintType.PRESERVE,
        ConstraintScope.CURRENT_RESPONSE,
        "MUST_PRESERVE:SCHEMA",
        900,
        ConstraintSourceKind.CURRENT_MESSAGE,
        "if output type is TEXT_CODE, preserve schema",
        UnitScore("0.95"),
        ConstraintResolutionStatus.ACTIVE,
        None,
        condition,
        stamp(13),
    )
    hard = Constraint(
        identifier(124),
        core.run.id,
        core.user_message.id,
        0,
        ConstraintType.FORBIDDEN,
        None,
        ConstraintScope.CURRENT_RESPONSE,
        "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
        1000,
        ConstraintSourceKind.DERIVED_OUTPUT_POLICY,
        "text-only policy",
        UnitScore("1"),
        ConstraintResolutionStatus.ACTIVE,
        "group-☕",
        None,
        stamp(13),
    )
    bundle.constraints.add_all((conditional, hard))
    assert bundle.constraints.list_for_run(core.run.id) == (hard, conditional)

    packet_id = identifier(130)
    retrieval = RetrievalResult(
        identifier(131),
        packet_id,
        selected_memory.id,
        0,
        UnitScore("0.75"),
        (
            "project_match=1",
            "topic_match=1",
            "keyword_jaccard=0.2",
            "recency=1",
            "importance=0.7",
            "scope_match=0.8",
            "correction_match=0",
        ),
        stamp(14),
    )
    exclusion = RetrievalExclusion(
        identifier(132),
        packet_id,
        duplicate_memory.id,
        RetrievalExclusionReason.DUPLICATE_CONTENT,
        UnitScore("0.75"),
        FrozenJsonObject({"retained_memory_id": str(selected_memory.id)}),
        stamp(14),
    )
    packet = context_packet_fixture(
        packet_id=packet_id,
        run=core.run,
        message=core.user_message,
        created_at=stamp(14),
        results=(retrieval,),
        memories=(selected_memory,),
    )
    packet_record = ContextPacketRecord(packet, (retrieval,), (exclusion,))
    bundle.packets.add(packet_record)
    assert bundle.packets.get(packet.id) == packet_record
    assert bundle.packets.get_for_run(core.run.id) == packet_record

    edited = replace(
        selected_memory,
        content="Use SQLite transactions safely — café",
        updated_at=stamp(15),
    )
    edit_source = MemorySource(
        identifier(133),
        edited.id,
        MemorySourceKind.USER_EDIT,
        None,
        "Explicit edit",
        stamp(15),
    )
    edit_revision = MemoryRevision(
        identifier(134),
        edited.id,
        2,
        MemoryRevisionOperation.EDIT,
        edited.content,
        memory_revision_metadata(edited, edit_source.id),
        LocalActor.LOCAL_USER,
        stamp(15),
    )
    bundle.memories.update_with_revision(edited, edit_source, edit_revision)
    deleted = replace(
        edited,
        status=MemoryStatus.DELETED,
        updated_at=stamp(16),
        deleted_at=stamp(16),
    )
    delete_source = MemorySource(
        identifier(135),
        deleted.id,
        MemorySourceKind.USER_EDIT,
        None,
        "Explicit soft deletion",
        stamp(16),
    )
    delete_revision = MemoryRevision(
        identifier(136),
        deleted.id,
        3,
        MemoryRevisionOperation.SOFT_DELETE,
        deleted.content,
        memory_revision_metadata(deleted, delete_source.id),
        LocalActor.LOCAL_USER,
        stamp(16),
    )
    bundle.memories.update_with_revision(deleted, delete_source, delete_revision)

    stored = bundle.memories.get(deleted.id)
    assert stored is not None
    assert stored.memory == deleted
    assert stored.sources == (
        MemorySource(
            identifier(101),
            selected_memory.id,
            MemorySourceKind.MANUAL_ENTRY,
            None,
            "Explicit fixture memory",
            stamp(10),
        ),
        edit_source,
        delete_source,
    )
    assert tuple(revision.revision_number for revision in stored.revisions) == (1, 2, 3)
    assert bundle.memories.list_by_status(MemoryStatus.DELETED) == (stored,)
    candidate_ids = {
        record.memory.id
        for record in bundle.memories.list_retrieval_candidates()
    }
    assert candidate_ids == {deleted.id, duplicate_memory.id}


def test_model_success_lineage_settings_evaluation_and_restart_persistence(
    tmp_path: Path,
) -> None:
    database_path = apply_migrations(tmp_path / "restart.sqlite3")
    connection = connect_database(database_path)
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet_record, context_ready = add_empty_packet(bundle, core)
    pending = initial_request(core, packet_record.packet)
    generating = replace(context_ready, status=ProcessingRunStatus.GENERATING)
    with bundle.transactions.transaction():
        bundle.runs.update(generating)
        bundle.models.add_request(pending)

    in_flight = replace(
        pending, status=ModelRequestStatus.IN_FLIGHT, started_at=stamp(20)
    )
    succeeded_request = replace(
        in_flight, status=ModelRequestStatus.SUCCEEDED, completed_at=stamp(21)
    )
    bundle.models.update_request(in_flight)
    response_id = identifier(41)
    response = ModelResponse(
        response_id,
        succeeded_request.id,
        "Complete buffered response — café",
        completed_response_projection(succeeded_request, response_id),
        None,
        stamp(21),
    )
    validation = replace(
        validate_response(packet_record.packet, response),
        created_at=response.created_at,
    )
    with bundle.transactions.transaction():
        bundle.models.update_request(succeeded_request)
        bundle.models.add_response(response)
        bundle.validations.add(validation)
    mismatched_assistant = Message(
        identifier(49),
        core.conversation.id,
        MessageRole.ASSISTANT,
        f"{response.response_text} ",
        stamp(22),
        1,
    )
    with pytest.raises(LifecycleInvariantError, match="bytes must exactly equal"):
        with bundle.transactions.transaction():
            bundle.messages.add(mismatched_assistant)
            bundle.models.link_assistant_message(
                model_response_id=response.id,
                assistant_message_id=mismatched_assistant.id,
            )
    assert bundle.messages.get(mismatched_assistant.id) is None
    assert bundle.models.get_response(response.id).assistant_message_id is None

    assistant = Message(
        identifier(43),
        core.conversation.id,
        MessageRole.ASSISTANT,
        response.response_text,
        stamp(23),
        1,
    )
    with bundle.transactions.transaction():
        bundle.messages.add(assistant)
        bundle.models.link_assistant_message(
            model_response_id=response.id,
            assistant_message_id=assistant.id,
        )
        bundle.runs.update(
            replace(
                generating,
                status=ProcessingRunStatus.SUCCEEDED,
                completed_at=stamp(24),
            )
        )
    bundle.models.link_assistant_message(
        model_response_id=response.id,
        assistant_message_id=assistant.id,
    )

    assert bundle.models.get_request(succeeded_request.id) == succeeded_request
    assert bundle.models.list_requests_for_run(core.run.id) == (succeeded_request,)
    assert bundle.models.get_response_for_request(succeeded_request.id) == replace(
        response, assistant_message_id=assistant.id
    )
    assert bundle.validations.get(validation.id) == validation
    assert bundle.validations.get_for_response(response.id) == validation
    assert bundle.validations.list_for_run(core.run.id) == (validation,)

    theme = bundle.settings.set(key="ui.theme", value="DARK", updated_at=stamp(25))
    visible = bundle.settings.set(
        key="ui.context_panel_visible", value=True, updated_at=stamp(25)
    )
    selected = bundle.settings.set(
        key="ui.last_selected_conversation_id",
        value=str(core.conversation.id),
        updated_at=stamp(25),
    )
    assert bundle.settings.get("ui.theme") == theme
    assert bundle.settings.list_all() == (visible, selected, theme)

    case_b = EvaluationCase(
        identifier(50),
        "B case",
        "persistence",
        FrozenJsonObject({"fixture": [1, {"unicode": "☕"}]}),
        False,
        stamp(26),
        stamp(26),
    )
    case_a = EvaluationCase(
        identifier(51),
        "A case",
        "persistence",
        FrozenJsonObject({"opaque": True}),
        True,
        stamp(26),
        stamp(26),
    )
    bundle.evaluations.add_case(case_b)
    bundle.evaluations.add_case(case_a)
    evaluation_run = EvaluationRun(
        identifier(52),
        case_a.id,
        "fixture-v1",
        EvaluationProviderMode.MOCK,
        FrozenJsonObject({"passed_assertions": ["mapping", "restart"]}),
        True,
        stamp(27),
    )
    bundle.evaluations.add_run(evaluation_run)
    assert bundle.evaluations.list_cases() == (case_a, case_b)
    assert bundle.evaluations.list_cases(enabled_only=True) == (case_a,)
    assert bundle.evaluations.get_case(case_a.id) == case_a
    assert bundle.evaluations.list_runs_for_case(case_a.id) == (evaluation_run,)

    connection.close()
    reopened = connect_database(database_path)
    try:
        restarted = repositories(reopened)
        assert restarted.runs.get(core.run.id).status is ProcessingRunStatus.SUCCEEDED
        assert restarted.packets.get(packet_record.packet.id) == packet_record
        assert restarted.models.get_request(succeeded_request.id) == succeeded_request
        assert restarted.models.get_response(response.id) == replace(
            response, assistant_message_id=assistant.id
        )
        assert restarted.validations.get(validation.id) == validation
        assert restarted.messages.get(assistant.id) == assistant
        assert restarted.settings.get("ui.theme") == theme
        assert restarted.evaluations.list_runs_for_case(case_a.id) == (evaluation_run,)
        assert not isinstance(restarted.runs.get(core.run.id), sqlite3.Row)
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "prompt_policy_version",
    (HISTORICAL_PROMPT_POLICY_VERSION, PROMPT_POLICY_VERSION),
)
def test_context_packet_and_model_request_policy_round_trip_without_rewrite(
    connection: sqlite3.Connection,
    prompt_policy_version: str,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet_record, context_ready = add_empty_packet(
        bundle,
        core,
        prompt_policy_version=prompt_policy_version,
    )
    request = initial_request(core, packet_record.packet)
    with bundle.transactions.transaction():
        bundle.runs.update(
            replace(context_ready, status=ProcessingRunStatus.GENERATING)
        )
        bundle.models.add_request(request)

    assert bundle.packets.get(packet_record.packet.id) == packet_record
    assert bundle.models.get_request(request.id) == request
    packet_row = connection.execute(
        """
        SELECT prompt_policy_version, packet_json
        FROM context_packets WHERE id = ?
        """,
        (str(packet_record.packet.id),),
    ).fetchone()
    request_row = connection.execute(
        "SELECT request_json FROM model_requests WHERE id = ?",
        (str(request.id),),
    ).fetchone()
    assert packet_row["prompt_policy_version"] == prompt_policy_version
    assert json.loads(packet_row["packet_json"])["rendering"][
        "prompt_policy_version"
    ] == prompt_policy_version
    assert json.loads(request_row["request_json"])["rendering"][
        "prompt_policy_version"
    ] == prompt_policy_version


@pytest.mark.parametrize(
    ("packet_policy", "request_policy"),
    (
        (HISTORICAL_PROMPT_POLICY_VERSION, PROMPT_POLICY_VERSION),
        (PROMPT_POLICY_VERSION, HISTORICAL_PROMPT_POLICY_VERSION),
    ),
)
def test_model_request_policy_must_match_context_packet_policy(
    connection: sqlite3.Connection,
    packet_policy: str,
    request_policy: str,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet_record, context_ready = add_empty_packet(
        bundle,
        core,
        prompt_policy_version=packet_policy,
    )
    request = initial_request(core, packet_record.packet)
    mismatched = replace(
        request,
        request=model_request_projection(
            request_id=request.id,
            processing_run_id=request.processing_run_id,
            context_packet_id=request.context_packet_id,
            attempt_number=request.attempt_number,
            render_kind="INITIAL",
            prompt_policy_version=request_policy,
        ),
    )
    bundle.runs.update(
        replace(context_ready, status=ProcessingRunStatus.GENERATING)
    )

    with pytest.raises(LifecycleInvariantError, match="must match its context packet"):
        bundle.models.add_request(mismatched)

    assert bundle.models.get_request(request.id) is None


def test_model_request_unknown_prompt_policy_fails_closed(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet_record, context_ready = add_empty_packet(bundle, core)
    request = initial_request(core, packet_record.packet)
    unknown = replace(
        request,
        request=model_request_projection(
            request_id=request.id,
            processing_run_id=request.processing_run_id,
            context_packet_id=request.context_packet_id,
            attempt_number=request.attempt_number,
            render_kind="INITIAL",
            prompt_policy_version="mvp-prompt-policy-v999",
        ),
    )
    bundle.runs.update(
        replace(context_ready, status=ProcessingRunStatus.GENERATING)
    )

    with pytest.raises(LifecycleInvariantError, match="supported prompt policy"):
        bundle.models.add_request(unknown)

    assert bundle.models.get_request(request.id) is None


@pytest.mark.parametrize(
    "stored_policy",
    (HISTORICAL_PROMPT_POLICY_VERSION, "mvp-prompt-policy-v999"),
)
def test_stored_model_request_invalid_prompt_policy_is_not_exposed(
    connection: sqlite3.Connection,
    stored_policy: str,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet_record, context_ready = add_empty_packet(bundle, core)
    request = initial_request(core, packet_record.packet)
    with bundle.transactions.transaction():
        bundle.runs.update(
            replace(context_ready, status=ProcessingRunStatus.GENERATING)
        )
        bundle.models.add_request(request)

    row = connection.execute(
        "SELECT request_json FROM model_requests WHERE id = ?",
        (str(request.id),),
    ).fetchone()
    stored_projection = json.loads(row["request_json"])
    stored_projection["rendering"]["prompt_policy_version"] = stored_policy
    connection.execute(
        "UPDATE model_requests SET request_json = ? WHERE id = ?",
        (
            json.dumps(
                stored_projection,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            str(request.id),
        ),
    )
    connection.commit()

    with pytest.raises(PersistenceError, match="could not be mapped"):
        bundle.models.get_request(request.id)
    with pytest.raises(PersistenceError, match="could not be mapped"):
        bundle.models.list_requests_for_run(core.run.id)


def test_model_correction_lifecycle_rejects_invalid_candidates_and_duplicates(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet_record, context_ready = add_empty_packet(bundle, core)

    invalid_pending_time = replace(
        initial_request(core, packet_record.packet), started_at=stamp(20)
    )
    with pytest.raises(LifecycleInvariantError, match="PENDING"):
        bundle.models.add_request(invalid_pending_time)
    invalid_purpose = replace(
        initial_request(core, packet_record.packet),
        purpose=ModelRequestPurpose.INITIAL,
        attempt_number=1,
    )
    with pytest.raises(LifecycleInvariantError, match="INITIAL"):
        bundle.models.add_request(invalid_purpose)

    pending = initial_request(core, packet_record.packet)
    generating = replace(context_ready, status=ProcessingRunStatus.GENERATING)
    with bundle.transactions.transaction():
        bundle.runs.update(generating)
        bundle.models.add_request(pending)
    with pytest.raises(PersistenceError):
        bundle.models.add_request(pending)

    in_flight = replace(
        pending, status=ModelRequestStatus.IN_FLIGHT, started_at=stamp(20)
    )
    succeeded_request = replace(
        in_flight, status=ModelRequestStatus.SUCCEEDED, completed_at=stamp(21)
    )
    bundle.models.update_request(in_flight)
    response_id = identifier(41)
    response = ModelResponse(
        response_id,
        succeeded_request.id,
        "TOOL_CALL:",
        completed_response_projection(succeeded_request, response_id),
        None,
        stamp(21),
    )
    failed_validation = replace(
        validate_response(packet_record.packet, response),
        created_at=response.created_at,
    )
    assert failed_validation.status is ValidationStatus.FAILED
    with bundle.transactions.transaction():
        bundle.models.update_request(succeeded_request)
        bundle.models.add_response(response)
        bundle.validations.add(failed_validation)

    assistant = Message(
        identifier(43),
        core.conversation.id,
        MessageRole.ASSISTANT,
        response.response_text,
        stamp(23),
        1,
    )
    bundle.messages.add(assistant)
    with pytest.raises(LifecycleInvariantError, match="passed validation"):
        bundle.models.link_assistant_message(
            model_response_id=response.id,
            assistant_message_id=assistant.id,
        )
    assert bundle.models.get_response(response.id).assistant_message_id is None

    revising = replace(generating, status=ProcessingRunStatus.REVISING)
    bundle.runs.update(revising)
    revision_request_id = identifier(44)
    revision_request = ModelRequest(
        revision_request_id,
        core.run.id,
        packet_record.packet.id,
        ModelRequestPurpose.REVISION,
        1,
        ProviderKind.OLLAMA,
        "fixture-model",
        ModelRequestStatus.PENDING,
        "Revision prompt",
        model_request_projection(
            request_id=revision_request_id,
            processing_run_id=core.run.id,
            context_packet_id=packet_record.packet.id,
            attempt_number=1,
            render_kind="CORRECTION",
        ),
        None,
        None,
        None,
        None,
    )
    correction = CorrectionAttempt(
        identifier(45),
        core.run.id,
        1,
        response.id,
        revision_request.id,
        failed_validation.violations,
        stamp(23),
    )
    wrong_reasons = replace(
        correction,
        reasons=failed_validation.violations[:1],
    )
    with pytest.raises(LifecycleInvariantError, match="exactly equal"):
        with bundle.transactions.transaction():
            bundle.models.add_request(revision_request)
            bundle.models.add_correction(wrong_reasons)
    assert bundle.models.get_request(revision_request.id) is None
    assert bundle.models.list_corrections_for_run(core.run.id) == ()

    with bundle.transactions.transaction():
        bundle.models.add_request(revision_request)
        bundle.models.add_correction(correction)
    bundle.models.add_correction(correction)
    assert bundle.models.list_requests_for_run(core.run.id) == (
        succeeded_request,
        revision_request,
    )
    assert bundle.models.list_corrections_for_run(core.run.id) == (correction,)
    stored_reason_json = connection.execute(
        "SELECT reason_json FROM correction_attempts WHERE id = ?",
        (str(correction.id),),
    ).fetchone()[0]
    assert tuple(
        FrozenJsonObject(item) for item in json.loads(stored_reason_json)
    ) == tuple(
        violation.to_json_object() for violation in failed_validation.violations
    )

    conflicting_correction = replace(correction, id=identifier(46))
    with pytest.raises(PersistenceError, match="already identifies"):
        bundle.models.add_correction(conflicting_correction)

    controlled = replace(
        revising,
        status=ProcessingRunStatus.CONTROLLED_FAILURE,
        completed_at=stamp(24),
    )
    failure = SafeFailure(
        identifier(47),
        core.run.id,
        PipelineStage.VALIDATION,
        FailureCode.VALIDATION_EXHAUSTED,
        "The response did not pass validation.",
        FrozenJsonObject({"attempt_number": 1}),
        True,
        stamp(24),
    )
    with bundle.transactions.transaction():
        bundle.runs.update(controlled)
        bundle.models.add_failure(failure)
    assert bundle.models.list_failures_for_run(core.run.id) == (failure,)
    assert bundle.models.get_response(response.id).assistant_message_id is None


def test_validation_json_and_every_reachable_score_round_trip_exactly(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet_record, context_ready = add_empty_packet(bundle, core)
    pending = initial_request(core, packet_record.packet)
    generating = replace(context_ready, status=ProcessingRunStatus.GENERATING)
    with bundle.transactions.transaction():
        bundle.runs.update(generating)
        bundle.models.add_request(pending)
    in_flight = replace(
        pending,
        status=ModelRequestStatus.IN_FLIGHT,
        started_at=stamp(20),
    )
    succeeded = replace(
        in_flight,
        status=ModelRequestStatus.SUCCEEDED,
        completed_at=stamp(21),
    )
    bundle.models.update_request(in_flight)
    response_id = identifier(41)
    response = ModelResponse(
        response_id,
        succeeded.id,
        "Buffered candidate",
        completed_response_projection(succeeded, response_id),
        None,
        stamp(21),
    )
    first_report = replace(
        repetition_score_report(identifier(42), response.id, 0),
        created_at=response.created_at,
    )
    with bundle.transactions.transaction():
        bundle.models.update_request(succeeded)
        bundle.models.add_response(response)
        bundle.validations.add(first_report)

    for repetition_count in range(21):
        report = repetition_score_report(
            identifier(42),
            response.id,
            repetition_count,
        )
        report = replace(report, created_at=response.created_at)
        expected_score = max(
            Decimal("0.00"),
            Decimal("1.00") - Decimal("0.05") * repetition_count,
        )
        assert report.score.value == expected_score

        if repetition_count > 0:
            bundle.validations.add(report)

        assert bundle.validations.get(report.id) == report
        row = connection.execute(
            """
            SELECT score, violations_json, evidence_json
            FROM validation_results WHERE id = ?
            """,
            (str(report.id),),
        ).fetchone()
        assert UnitScore(row["score"]) == report.score
        assert json.loads(row["violations_json"]) == []
        stored_evidence = json.loads(row["evidence_json"])
        assert sum(item["outcome"] == "WARNING" for item in stored_evidence) == (
            repetition_count
        )
        connection.execute(
            "DELETE FROM validation_results WHERE id = ?",
            (str(report.id),),
        )
        connection.commit()

    not_run = repetition_score_report(identifier(42), response.id, 0)
    object.__setattr__(not_run, "status", ValidationStatus.NOT_RUN)
    with pytest.raises(LifecycleInvariantError, match="NOT_RUN"):
        bundle.validations.add(not_run)
    assert bundle.validations.get(not_run.id) is None


def test_preconstructed_validation_exhaustion_projection_has_no_candidate_link(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    packet_record, context_ready = add_empty_packet(
        bundle,
        core,
        correction_limit=0,
    )
    pending = initial_request(core, packet_record.packet)
    generating = replace(context_ready, status=ProcessingRunStatus.GENERATING)
    with bundle.transactions.transaction():
        bundle.runs.update(generating)
        bundle.models.add_request(pending)
    in_flight = replace(
        pending,
        status=ModelRequestStatus.IN_FLIGHT,
        started_at=stamp(20),
    )
    succeeded = replace(
        in_flight,
        status=ModelRequestStatus.SUCCEEDED,
        completed_at=stamp(21),
    )
    bundle.models.update_request(in_flight)
    response_id = identifier(41)
    response = ModelResponse(
        response_id,
        succeeded.id,
        "TOOL_CALL:",
        completed_response_projection(succeeded, response_id),
        None,
        stamp(21),
    )
    report = replace(
        validate_response(packet_record.packet, response),
        created_at=response.created_at,
    )
    with bundle.transactions.transaction():
        bundle.models.update_request(succeeded)
        bundle.models.add_response(response)
        bundle.validations.add(report)
    exhausted = CorrectionExhausted(
        core.run.id,
        packet_record.packet.id,
        succeeded.id,
        response.id,
        report.id,
        0,
        0,
    )
    failure = SafeFailure(
        identifier(47),
        exhausted.processing_run_id,
        PipelineStage.VALIDATION,
        FailureCode.VALIDATION_EXHAUSTED,
        "The response did not pass validation.",
        FrozenJsonObject(
            {
                "context_packet_id": str(exhausted.context_packet_id),
                "failed_model_request_id": str(exhausted.failed_model_request_id),
                "failed_model_response_id": str(exhausted.failed_model_response_id),
                "validation_result_id": str(exhausted.validation_result_id),
                "attempt_number": exhausted.attempt_number,
                "correction_limit": exhausted.correction_limit,
            }
        ),
        True,
        stamp(23),
    )
    terminal = replace(
        generating,
        status=ProcessingRunStatus.CONTROLLED_FAILURE,
        completed_at=stamp(23),
    )

    with bundle.transactions.transaction():
        bundle.models.add_failure(failure)
        bundle.runs.update(terminal)

    assert bundle.models.list_failures_for_run(core.run.id) == (failure,)
    assert bundle.models.list_corrections_for_run(core.run.id) == ()
    assert bundle.models.get_response(response.id).assistant_message_id is None
    assert connection.execute(
        "SELECT count(*) FROM correction_attempts WHERE processing_run_id = ?",
        (str(core.run.id),),
    ).fetchone()[0] == 0


def test_context_construction_failure_round_trips_without_unrelated_rows(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    failure = SafeFailure(
        identifier(90),
        core.run.id,
        PipelineStage.CONTEXT,
        FailureCode.CONTEXT_CONSTRUCTION_FAILED,
        "Context could not be constructed safely.",
        FrozenJsonObject(
            {
                "component": "PACKET_BUILD",
                "reason_code": "CONTEXT_INVARIANT_VIOLATION",
            }
        ),
        True,
        stamp(5),
    )
    controlled_run = replace(
        core.run,
        status=ProcessingRunStatus.CONTROLLED_FAILURE,
        completed_at=stamp(5),
    )

    with bundle.transactions.transaction():
        bundle.runs.update(controlled_run)
        bundle.models.add_failure(failure)

    assert bundle.runs.get(core.run.id) == controlled_run
    assert bundle.models.list_failures_for_run(core.run.id) == (failure,)
    stored_failure = connection.execute(
        """
        SELECT stage, error_code, safe_message, details_json, is_terminal
        FROM pipeline_failures WHERE id = ?
        """,
        (str(failure.id),),
    ).fetchone()
    assert stored_failure is not None
    assert tuple(stored_failure) == (
        "CONTEXT",
        "CONTEXT_CONSTRUCTION_FAILED",
        "Context could not be constructed safely.",
        '{"component":"PACKET_BUILD","reason_code":"CONTEXT_INVARIANT_VIOLATION"}',
        1,
    )
    unrelated_tables = (
        "reference_resolutions",
        "constraints",
        "context_packets",
        "retrieval_results",
        "retrieval_exclusions",
        "model_requests",
        "model_responses",
        "validation_results",
        "correction_attempts",
        "clarification_requests",
    )
    assert {
        table_name: connection.execute(
            f"SELECT count(*) FROM {table_name}"
        ).fetchone()[0]
        for table_name in unrelated_tables
    } == {table_name: 0 for table_name in unrelated_tables}
    assert connection.execute(
        "SELECT count(*) FROM messages WHERE role = 'ASSISTANT'"
    ).fetchone()[0] == 0

    class RollbackMarker(Exception):
        pass

    rolled_back_failure = replace(failure, id=identifier(91), created_at=stamp(6))
    with pytest.raises(PersistenceError, match="different terminal failure"):
        with bundle.transactions.transaction():
            bundle.models.add_failure(rolled_back_failure)
            raise RollbackMarker

    assert bundle.runs.get(core.run.id) == controlled_run
    assert bundle.models.list_failures_for_run(core.run.id) == (failure,)
    assert connection.execute(
        "SELECT count(*) FROM pipeline_failures"
    ).fetchone()[0] == 1


def test_transactions_idempotency_foreign_keys_and_typed_failures(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)

    unknown_conversation_message = Message(
        identifier(60), identifier(999), MessageRole.USER, "orphan", stamp(5), 0
    )
    with pytest.raises(PersistenceError) as foreign_key_error:
        bundle.messages.add(unknown_conversation_message)
    assert not isinstance(foreign_key_error.value, sqlite3.Error)
    assert bundle.messages.get(unknown_conversation_message.id) is None

    class RollbackMarker(Exception):
        pass

    rolled_back_project = Project(
        identifier(61), "Rolled back", None, ProjectStatus.ACTIVE, stamp(5), stamp(5)
    )
    with pytest.raises(RollbackMarker):
        with bundle.transactions.transaction():
            bundle.projects.add(rolled_back_project)
            raise RollbackMarker
    assert bundle.projects.get(rolled_back_project.id) is None

    competing_message = Message(
        identifier(62), core.conversation.id, MessageRole.USER, "competing", stamp(6), 1
    )
    competing_run = ProcessingRun(
        identifier(63),
        core.conversation.id,
        competing_message.id,
        str(identifier(64)),
        ProcessingRunStatus.PERSISTED,
        0,
        "fixture-fingerprint",
        stamp(6),
        None,
    )
    with pytest.raises(PersistenceError):
        with bundle.transactions.transaction():
            bundle.messages.add(competing_message)
            bundle.runs.add(competing_run)
    assert bundle.messages.get(competing_message.id) is None
    assert bundle.runs.get(competing_run.id) is None

    clarification = ClarificationRequest(
        identifier(65),
        core.run.id,
        ClarificationReason.UNRESOLVED_REFERENCE,
        'Please clarify what "it" refers to.',
        FrozenJsonObject({"surface_text": "it", "candidates": []}),
        stamp(7),
    )
    clarified_run = replace(
        core.run,
        status=ProcessingRunStatus.NEEDS_CLARIFICATION,
        completed_at=stamp(7),
    )
    with bundle.transactions.transaction():
        bundle.runs.update(clarified_run)
        bundle.clarifications.add(clarification)
    bundle.clarifications.add(clarification)
    assert bundle.clarifications.get_for_run(core.run.id) == clarification
    with pytest.raises(PersistenceError, match="different clarification"):
        bundle.clarifications.add(replace(clarification, id=identifier(66)))

    with bundle.transactions.transaction():
        bundle.messages.add(competing_message)
        bundle.runs.add(competing_run)
    failed_run = replace(
        competing_run,
        status=ProcessingRunStatus.FAILED,
        completed_at=stamp(8),
    )
    first_failure = SafeFailure(
        identifier(67),
        competing_run.id,
        PipelineStage.RECOVERY,
        FailureCode.PROCESS_RESTARTED,
        "The in-flight request could not be proven safe to repeat.",
        FrozenJsonObject({"recovered": False}),
        True,
        stamp(8),
    )
    second_failure = SafeFailure(
        identifier(68),
        competing_run.id,
        PipelineStage.TERMINALIZATION,
        FailureCode.PERSISTENCE_ERROR,
        "The terminal state was retained for diagnosis.",
        FrozenJsonObject({"sequence": 2}),
        True,
        stamp(9),
    )
    with bundle.transactions.transaction():
        bundle.runs.update(failed_run)
        bundle.models.add_failure(first_failure)
    with pytest.raises(PersistenceError, match="different terminal failure"):
        bundle.models.add_failure(second_failure)
    assert bundle.models.list_failures_for_run(competing_run.id) == (first_failure,)
    assert bundle.runs.get_non_terminal() is None

    committed_project = Project(
        identifier(70), "Committed", None, ProjectStatus.ACTIVE, stamp(10), stamp(10)
    )
    committed_conversation = Conversation(
        identifier(71), committed_project.id, None, stamp(10), stamp(10)
    )
    with bundle.transactions.transaction():
        bundle.projects.add(committed_project)
        bundle.conversations.add(committed_conversation)
    assert bundle.projects.get(committed_project.id) == committed_project
    assert bundle.conversations.get(committed_conversation.id) == committed_conversation

    atomic_memory = Memory(
        identifier(72),
        None,
        committed_project.id,
        MemoryType.PROJECT_FACT,
        MemoryScope.PROJECT,
        MemoryStatus.ACTIVE,
        "This aggregate must roll back.",
        (),
        (),
        UnitScore("0.5"),
        UnitScore("1"),
        None,
        stamp(11),
        stamp(11),
        None,
    )
    existing_memory, _, existing_revision = add_memory(
        bundle,
        core,
        number=80,
        content="Existing aggregate used to force a late revision failure.",
    )
    atomic_source = MemorySource(
        identifier(73),
        atomic_memory.id,
        MemorySourceKind.MANUAL_ENTRY,
        None,
        "Valid source that must roll back",
        stamp(11),
    )
    atomic_revision = MemoryRevision(
        existing_revision.id,
        atomic_memory.id,
        1,
        MemoryRevisionOperation.CREATE,
        atomic_memory.content,
        memory_revision_metadata(atomic_memory, atomic_source.id),
        LocalActor.LOCAL_USER,
        stamp(11),
    )
    with pytest.raises(PersistenceError):
        bundle.memories.add(atomic_memory, atomic_source, atomic_revision)
    assert bundle.memories.get(atomic_memory.id) is None
    assert bundle.memories.get(existing_memory.id) is not None
    assert connection.execute(
        "SELECT count(*) FROM memory_sources WHERE id = ?",
        (str(atomic_source.id),),
    ).fetchone()[0] == 0


def test_caught_joined_failure_marks_outer_transaction_rollback_only(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    project = Project(
        identifier(90),
        "Rollback only",
        None,
        ProjectStatus.ACTIVE,
        stamp(20),
        stamp(20),
    )

    with pytest.raises(PersistenceError, match="joined operation failed"):
        with bundle.transactions.transaction():
            bundle.projects.add(project)
            try:
                with bundle.transactions.transaction():
                    raise RuntimeError("caught nested failure")
            except RuntimeError:
                pass

    assert bundle.projects.get(project.id) is None
    assert connection.in_transaction is False


def test_caught_repository_failure_marks_outer_transaction_rollback_only(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    project = Project(
        identifier(91),
        "First value",
        None,
        ProjectStatus.ACTIVE,
        stamp(21),
        stamp(21),
    )
    conflicting = replace(project, name="Conflicting value")

    with pytest.raises(PersistenceError, match="joined operation failed"):
        with bundle.transactions.transaction():
            bundle.projects.add(project)
            try:
                bundle.projects.add(conflicting)
            except PersistenceError:
                pass

    assert bundle.projects.get(project.id) is None


def test_admission_insert_captures_conflicting_run_before_loser_rollback(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    loser_message = Message(
        identifier(92),
        core.conversation.id,
        MessageRole.USER,
        "losing admission",
        stamp(22),
        1,
    )
    loser_run = ProcessingRun(
        identifier(93),
        core.conversation.id,
        loser_message.id,
        str(identifier(94)),
        ProcessingRunStatus.PERSISTED,
        core.state.version,
        core.run.configuration_fingerprint,
        stamp(22),
        None,
    )

    with pytest.raises(AdmissionRaceError) as captured:
        with bundle.transactions.transaction():
            bundle.messages.add(loser_message)
            bundle.runs.add_with_admission_race_capture(loser_run)

    assert captured.value.conflicting_run == core.run
    assert bundle.messages.get(loser_message.id) is None
    assert bundle.runs.get(loser_run.id) is None


def test_invalid_stored_rows_are_never_exposed_as_sqlite_rows(
    connection: sqlite3.Connection,
) -> None:
    bundle = repositories(connection)
    core = seed_core(bundle)
    connection.execute("PRAGMA ignore_check_constraints = ON")
    connection.execute(
        "UPDATE processing_runs SET status = 'UNKNOWN' WHERE id = ?",
        (str(core.run.id),),
    )
    connection.commit()
    connection.execute("PRAGMA ignore_check_constraints = OFF")

    with pytest.raises(PersistenceError, match="could not be mapped") as error:
        bundle.runs.get(core.run.id)
    assert not isinstance(error.value, sqlite3.Error)


def test_transaction_boundary_annotation_matches_port() -> None:
    assert get_type_hints(SQLiteTransactionBoundary.transaction)["return"] == (
        AbstractContextManager[None]
    )
