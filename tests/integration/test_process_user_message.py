"""End-to-end SQLite acceptance coverage for TASK-0014 submission."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from context_for_ai.application import (
    BusyResult,
    CancellationCheckpoint,
    CancelledResult,
    ClarificationResult,
    ConcurrencyConflictResult,
    ContextPacketStageService,
    ExistingRunResult,
    ProcessUserMessageRequest,
    ProcessUserMessageService,
    SucceededResult,
)
from context_for_ai.bootstrap import DeterministicComponents, RepositoryPorts, SystemPorts
from context_for_ai.context_engine import (
    DeterministicClarificationBuilder,
    DeterministicConstraintEngine,
    DeterministicContextPacketBuilder,
    DeterministicContextRetriever,
    DeterministicCorrectionController,
    DeterministicInterpretationEngine,
    DeterministicPromptRenderer,
    DeterministicReferenceMentionExtractor,
    DeterministicReferenceResolver,
    DeterministicResponseValidator,
)
from context_for_ai.domain.entities import Conversation, ConversationState
from context_for_ai.domain.enums import (
    FailureCode,
    IntentType,
    OutputType,
    ProcessingRunStatus,
    ProviderKind,
    QualifierKind,
)
from context_for_ai.domain.ports.configuration import (
    ApplicationSettings,
    ConfigurationSnapshot,
    ContextSettings,
    IntentRule,
    LoggingSettings,
    MemorySettings,
    ModelSettings,
    OutputShapeRule,
    QualifierRule,
    UnsupportedRequestRule,
    ValidationSettings,
)
from context_for_ai.domain.ports.model_gateway import (
    CompletedGeneration,
    GenerationRequest,
)
from context_for_ai.domain.ports.errors import AdmissionRaceError
from context_for_ai.domain.lifecycle import ProcessingRun
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore
from context_for_ai.infrastructure.configuration import load_configuration
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


BASE_TIME = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)


@dataclass(slots=True)
class SequenceIds:
    next_value: int = 1

    def new_id(self) -> DomainId:
        value = DomainId(
            f"90000000-0000-4000-8000-{self.next_value:012x}"
        )
        self.next_value += 1
        return value


@dataclass(slots=True)
class SequenceClock:
    next_value: int = 0

    def now(self) -> datetime:
        value = BASE_TIME + timedelta(seconds=self.next_value)
        self.next_value += 1
        return value


@dataclass(slots=True)
class Token:
    cancelled: bool = False

    def is_cancelled(self) -> bool:
        return self.cancelled


@dataclass(slots=True)
class StaticConfigurationLoader:
    snapshot: ConfigurationSnapshot
    calls: int = 0

    def load(self) -> ConfigurationSnapshot:
        self.calls += 1
        return self.snapshot


class TraceCollector:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


class SuccessfulGateway:
    def __init__(self, connection: object, text: str = "A complete answer — café") -> None:
        self.connection = connection
        self.text = text
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest, cancellation_token: Token) -> CompletedGeneration:
        assert not self.connection.in_transaction
        assert not cancellation_token.is_cancelled()
        self.requests.append(request)
        return CompletedGeneration(
            self.text,
            FrozenJsonObject({"fixture": "safe"}),
            timedelta(microseconds=1250),
            None,
        )


class ControlledCasRepository:
    def __init__(self, base: object, failures: int) -> None:
        self.base = base
        self.failures = failures
        self.calls = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self.base, name)

    def compare_and_swap(self, *, expected_version: int, state: object) -> bool:
        self.calls += 1
        if self.calls <= self.failures:
            return False
        return self.base.compare_and_swap(  # type: ignore[attr-defined,no-any-return]
            expected_version=expected_version,
            state=state,
        )


class AdmissionRaceProcessingRuns:
    def __init__(self, base: object, conflicting_run: ProcessingRun) -> None:
        self.base = base
        self.conflicting_run = conflicting_run
        self.post_boundary_reads = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self.base, name)

    def get_by_idempotency_key(self, **_: object) -> None:
        return None

    def get_non_terminal(self) -> None:
        return None

    def add_with_admission_race_capture(self, _: ProcessingRun) -> None:
        raise AdmissionRaceError(self.conflicting_run)


def inward_configuration(application_root: Path) -> ConfigurationSnapshot:
    loaded = load_configuration(application_root=application_root, environ={})
    context = loaded.context
    validation = loaded.validation
    return ConfigurationSnapshot(
        ApplicationSettings(
            loaded.app.environment, loaded.app.data_directory, loaded.app.foreground_run_limit
        ),
        ModelSettings(
            ProviderKind(loaded.model.provider.upper()),
            loaded.model.base_url,
            loaded.model.name,
            loaded.model.context_window_tokens,
            loaded.model.request_timeout_seconds,
            Decimal(str(loaded.model.temperature)),
        ),
        ContextSettings(
            context.tokenizer_estimator,
            context.maximum_prompt_tokens,
            context.reserved_response_tokens,
            context.recent_message_limit,
            context.retrieved_memory_limit,
            UnitScore(str(context.minimum_relevance_score)),
            context.topic_stack_limit,
            context.rule_set_version,
            context.conditional_grammar_version,
            tuple(
                IntentRule(
                    rule.id,
                    IntentType(rule.intent),
                    None if rule.output_type is None else OutputType(rule.output_type),
                    rule.phrases,
                    rule.priority,
                )
                for rule in context.intent_rules
            ),
            tuple(
                QualifierRule(rule.id, QualifierKind(rule.qualifier), rule.phrases)
                for rule in context.qualifier_rules
            ),
            tuple(
                UnsupportedRequestRule(rule.id, rule.category, rule.phrases)
                for rule in context.unsupported_request_rules
            ),
        ),
        MemorySettings(
            loaded.memory.allow_manual_create,
            loaded.memory.allow_manual_edit,
            loaded.memory.allow_manual_soft_delete,
            loaded.memory.automatic_mutation,
        ),
        ValidationSettings(
            validation.max_revisions,
            validation.rule_set_version,
            tuple(
                OutputShapeRule(
                    rule.id,
                    OutputType(rule.output_type),
                    rule.shape,
                )
                for rule in validation.output_shape_rules
            ),
            validation.preserve_change_verb_list_id,
            validation.preserve_change_verbs,
            validation.action_markers,
        ),
        LoggingSettings(
            loaded.logging.level,
            loaded.logging.directory,
            loaded.logging.retention_days,
            False,
        ),
        loaded.configuration_directory,
        loaded.configuration_fingerprint,
    )


def repository_ports(connection: object) -> RepositoryPorts:
    return RepositoryPorts(
        SQLiteProjectRepository(connection),
        SQLiteConversationRepository(connection),
        SQLiteTopicRepository(connection),
        SQLiteTaskRepository(connection),
        SQLiteConversationStateRepository(connection),
        SQLiteMessageRepository(connection),
        SQLiteEntityRepository(connection),
        SQLiteReferenceResolutionRepository(connection),
        SQLiteConstraintRepository(connection),
        SQLiteMemoryRepository(connection),
        SQLiteProcessingRunRepository(connection),
        SQLiteContextPacketRepository(connection),
        SQLiteModelCallRepository(connection),
        SQLiteValidationRepository(connection),
        SQLiteClarificationRepository(connection),
        SQLiteSettingsRepository(connection),
        SQLiteEvaluationRepository(connection),
    )


@pytest.fixture
def composition(tmp_path: Path, fixture_application_root: Path) -> SimpleNamespace:
    connection = connect_database(apply_migrations(tmp_path / "pipeline.sqlite3"))
    repositories = repository_ports(connection)
    ids = SequenceIds()
    clock = SequenceClock()
    configuration = inward_configuration(fixture_application_root)
    loader = StaticConfigurationLoader(configuration)
    traces = TraceCollector()
    gateway = SuccessfulGateway(connection)
    transactions = SQLiteTransactionBoundary(connection)
    system = SystemPorts(gateway, clock, ids, loader, traces, transactions)
    deterministic = DeterministicComponents(
        DeterministicInterpretationEngine(configuration.context),
        DeterministicReferenceMentionExtractor(),
        DeterministicReferenceResolver(ids),
        DeterministicConstraintEngine(configuration.context, ids),
        DeterministicClarificationBuilder(),
        DeterministicContextRetriever(ids),
        DeterministicContextPacketBuilder(),
        DeterministicPromptRenderer(),
        DeterministicResponseValidator(),
        DeterministicCorrectionController(),
    )
    stage = ContextPacketStageService(
        builder=deterministic.context_packet_builder,
        packets=repositories.context_packets,
        runs=repositories.processing_runs,
        model_calls=repositories.model_calls,
        id_generator=ids,
        transactions=transactions,
    )
    service = ProcessUserMessageService(
        repositories=repositories,
        system=system,
        deterministic=deterministic,
        context_packet_stage=stage,
    )
    conversation_id = DomainId("91000000-0000-4000-8000-000000000001")
    created = BASE_TIME - timedelta(minutes=1)
    with transactions.transaction():
        repositories.conversations.add(
            Conversation(conversation_id, None, "Pipeline", created, created)
        )
        repositories.conversation_states.add(
            ConversationState(
                conversation_id,
                None,
                None,
                None,
                None,
                (),
                0,
                created,
            )
        )
    value = SimpleNamespace(
        connection=connection,
        repositories=repositories,
        service=service,
        system=system,
        deterministic=deterministic,
        stage=stage,
        transactions=transactions,
        clock=clock,
        ids=ids,
        configuration=configuration,
        gateway=gateway,
        traces=traces,
        loader=loader,
        conversation_id=conversation_id,
    )
    yield value
    connection.close()


def request(composition: SimpleNamespace, key_number: int = 1) -> ProcessUserMessageRequest:
    return ProcessUserMessageRequest(
        composition.conversation_id,
        "answer café — naïve\n",
        DomainId(f"92000000-0000-4000-8000-{key_number:012x}"),
        None,
    )


def test_at002_success_preserves_exact_bytes_and_durable_ids_before_gateway(
    composition: SimpleNamespace,
) -> None:
    result = composition.service.execute(request(composition), Token())

    assert isinstance(result, SucceededResult)
    assert result.assistant_text == composition.gateway.text
    assert len(composition.gateway.requests) == 1
    generation = composition.gateway.requests[0]
    assert generation.processing_run_id == result.processing_run_id
    assert generation.context_packet_id == result.context_packet_id
    assert generation.model_request_id is not None
    stored_user = composition.repositories.messages.get(result.user_message_id)
    stored_assistant = composition.repositories.messages.get(result.assistant_message_id)
    assert stored_user.original_text == "answer café — naïve\n"
    assert stored_assistant.original_text.encode("utf-8") == result.assistant_text.encode(
        "utf-8"
    )
    assert [event.event_name for event in composition.traces.events] == [
        "run_accepted",
        "context_built",
        "reference_resolved",
        "constraints_resolved",
        "retrieval_completed",
        "packet_built",
        "model_request_started",
        "model_request_finished",
        "validation_completed",
        "run_succeeded",
    ]


def test_admission_existing_key_wins_and_invokes_no_second_gateway(
    composition: SimpleNamespace,
) -> None:
    first = composition.service.execute(request(composition), Token())
    repeated = composition.service.execute(
        replace(request(composition), user_text="different text is ignored"),
        Token(),
    )

    assert isinstance(first, SucceededResult)
    assert isinstance(repeated, ExistingRunResult)
    assert repeated.processing_run_id == first.processing_run_id
    assert repeated.assistant_text == first.assistant_text
    assert len(composition.gateway.requests) == 1


def test_admission_busy_and_preacceptance_cancellation_write_nothing(
    composition: SimpleNamespace,
) -> None:
    repositories = composition.repositories
    original_continue = composition.service._continue_context
    composition.service._continue_context = lambda **_: BusyResult  # type: ignore[method-assign,assignment]
    accepted_placeholder = composition.service.execute(request(composition), Token())
    composition.service._continue_context = original_continue  # type: ignore[method-assign]
    assert accepted_placeholder is BusyResult

    busy = composition.service.execute(request(composition, 2), Token())
    cancelled = composition.service.execute(request(composition, 3), Token(True))

    assert isinstance(busy, BusyResult)
    assert isinstance(cancelled, BusyResult)
    assert repositories.messages.next_sequence_number(composition.conversation_id) == 1


def test_admission_race_uses_captured_conflict_and_rolls_back_loser_message(
    composition: SimpleNamespace,
) -> None:
    conflicting = ProcessingRun(
        DomainId("94000000-0000-4000-8000-000000000001"),
        composition.conversation_id,
        DomainId("94000000-0000-4000-8000-000000000002"),
        str(DomainId("94000000-0000-4000-8000-000000000003")),
        ProcessingRunStatus.PERSISTED,
        0,
        composition.configuration.configuration_fingerprint,
        BASE_TIME,
        None,
    )
    race_runs = AdmissionRaceProcessingRuns(
        composition.repositories.processing_runs,
        conflicting,
    )
    repositories = replace(
        composition.repositories,
        processing_runs=race_runs,
    )
    service = ProcessUserMessageService(
        repositories=repositories,
        system=composition.system,
        deterministic=composition.deterministic,
        context_packet_stage=composition.stage,
    )

    result = service.execute(request(composition), Token())

    assert isinstance(result, BusyResult)
    assert result.active_processing_run_id == conflicting.id
    assert composition.repositories.messages.next_sequence_number(
        composition.conversation_id
    ) == 0
    assert composition.repositories.processing_runs.get_non_terminal() is None
    assert composition.gateway.requests == []


def test_preacceptance_cancellation_without_active_run_has_no_rows(
    composition: SimpleNamespace,
) -> None:
    result = composition.service.execute(request(composition), Token(True))

    assert isinstance(result, CancelledResult)
    assert result.checkpoint is CancellationCheckpoint.BEFORE_ACCEPTANCE
    assert result.processing_run_id is None
    assert composition.repositories.processing_runs.get_non_terminal() is None
    assert composition.repositories.messages.next_sequence_number(
        composition.conversation_id
    ) == 0


def test_context_unresolved_reference_persists_clarification_without_gateway(
    composition: SimpleNamespace,
) -> None:
    ambiguous = replace(request(composition), user_text="answer this reference")

    result = composition.service.execute(ambiguous, Token())

    assert isinstance(result, ClarificationResult)
    assert result.clarification.reason.value == "UNRESOLVED_REFERENCE"
    stored = composition.repositories.clarifications.get_for_run(
        result.processing_run_id
    )
    assert stored == result.clarification
    assert composition.repositories.reference_resolutions.list_for_run(
        result.processing_run_id
    )
    assert composition.repositories.context_packets.get_for_run(
        result.processing_run_id
    ) is None
    assert composition.repositories.model_calls.list_requests_for_run(
        result.processing_run_id
    ) == ()
    assert composition.repositories.model_calls.list_failures_for_run(
        result.processing_run_id
    ) == ()
    assert composition.gateway.requests == []
    assert [event.event_name for event in composition.traces.events][-2:] == [
        "reference_resolved",
        "run_clarification",
    ]


@pytest.mark.parametrize("cas_failures", [1, 2])
def test_context_cas_recomputes_once_then_succeeds_or_terminalizes(
    composition: SimpleNamespace,
    cas_failures: int,
) -> None:
    controlled_states = ControlledCasRepository(
        composition.repositories.conversation_states,
        cas_failures,
    )
    repositories = replace(
        composition.repositories,
        conversation_states=controlled_states,
    )
    service = ProcessUserMessageService(
        repositories=repositories,
        system=composition.system,
        deterministic=composition.deterministic,
        context_packet_stage=composition.stage,
    )

    result = service.execute(request(composition), Token())

    assert controlled_states.calls == 2
    if cas_failures == 1:
        assert isinstance(result, SucceededResult)
        assert len(composition.gateway.requests) == 1
        assert composition.repositories.context_packets.get_for_run(
            result.processing_run_id
        ) is not None
    else:
        assert isinstance(result, ConcurrencyConflictResult)
        assert result.safe_failure.error_code is FailureCode.CONCURRENCY_CONFLICT
        assert composition.gateway.requests == []
        assert composition.repositories.context_packets.get_for_run(
            result.processing_run_id
        ) is None
        assert composition.repositories.reference_resolutions.list_for_run(
            result.processing_run_id
        ) == ()
        assert composition.repositories.constraints.list_for_run(
            result.processing_run_id
        ) == ()
        assert [event.event_name for event in composition.traces.events] == [
            "run_accepted",
            "run_failed",
        ]
