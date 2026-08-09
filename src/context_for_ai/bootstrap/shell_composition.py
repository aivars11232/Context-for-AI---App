"""Production composition for startup and finite foreground shell scopes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import sqlite3
import threading

from context_for_ai.application import (
    ContextPacketStageService,
    InspectContextService,
    PrepareApplicationShellService,
    ProcessUserMessageService,
    RecoverProcessingRunService,
)
from context_for_ai.bootstrap.contracts import (
    DeterministicComponents,
    RepositoryPorts,
    SystemPorts,
)
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
from context_for_ai.domain.enums import IntentType, OutputType, ProviderKind, QualifierKind
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
from context_for_ai.domain.ports.system import Clock, IdGenerator, TraceLogger
from context_for_ai.domain.value_objects import DomainId, UnitScore
from context_for_ai.infrastructure.configuration import ApplicationConfiguration
from context_for_ai.infrastructure.database import (
    SQLiteClarificationRepository,
    SQLiteConstraintRepository,
    SQLiteContextPacketRepository,
    SQLiteConversationRepository,
    SQLiteConversationStateRepository,
    SQLiteEntityRepository,
    SQLiteEvaluationRepository,
    SQLiteInspectionSnapshotBoundary,
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
    connect_database,
)
from context_for_ai.infrastructure.ollama import OllamaModelProvider


type ConnectionFactory = Callable[[Path], sqlite3.Connection]


def configuration_snapshot_from(
    loaded: ApplicationConfiguration,
) -> ConfigurationSnapshot:
    """Convert one validated outer configuration to its immutable inward form."""

    if not isinstance(loaded, ApplicationConfiguration):
        raise TypeError("Production composition requires validated configuration.")
    context = loaded.context
    validation = loaded.validation
    return ConfigurationSnapshot(
        app=ApplicationSettings(
            loaded.app.environment,
            loaded.app.data_directory,
            loaded.app.foreground_run_limit,
        ),
        model=ModelSettings(
            ProviderKind(loaded.model.provider),
            loaded.model.base_url,
            loaded.model.name,
            loaded.model.context_window_tokens,
            loaded.model.request_timeout_seconds,
            Decimal(loaded.model.temperature),
        ),
        context=ContextSettings(
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
                    None
                    if rule.output_type is None
                    else OutputType(rule.output_type),
                    rule.phrases,
                    rule.priority,
                )
                for rule in context.intent_rules
            ),
            tuple(
                QualifierRule(
                    rule.id,
                    QualifierKind(rule.qualifier),
                    rule.phrases,
                )
                for rule in context.qualifier_rules
            ),
            tuple(
                UnsupportedRequestRule(rule.id, rule.category, rule.phrases)
                for rule in context.unsupported_request_rules
            ),
        ),
        memory=MemorySettings(
            loaded.memory.allow_manual_create,
            loaded.memory.allow_manual_edit,
            loaded.memory.allow_manual_soft_delete,
            loaded.memory.automatic_mutation,
        ),
        validation=ValidationSettings(
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
        logging=LoggingSettings(
            loaded.logging.level,
            loaded.logging.directory,
            loaded.logging.retention_days,
            False,
        ),
        configuration_directory=loaded.configuration_directory,
        configuration_fingerprint=loaded.configuration_fingerprint,
    )


class UtcSystemClock:
    """Return application timestamps from the process UTC clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidDomainIdGenerator:
    """Create local random UUID-backed domain identifiers."""

    def new_id(self) -> DomainId:
        return DomainId.new()


class UuidIdempotencyKeyFactory:
    """Create one local caller-owned UUID for an accepted submission."""

    def new_key(self) -> DomainId:
        return DomainId.new()


@dataclass(frozen=True, slots=True)
class _StaticConfigurationLoader:
    snapshot: ConfigurationSnapshot

    def load(self) -> ConfigurationSnapshot:
        return self.snapshot


class _OwnedSQLiteScope:
    """Close one SQLite connection only on the thread that opened it."""

    __slots__ = ("_closed", "_connection", "_owner_thread_id")

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._owner_thread_id = threading.get_ident()
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        if threading.get_ident() != self._owner_thread_id:
            raise RuntimeError(
                "SQLite application scope must close on its owning thread."
            )
        self._connection.close()
        self._closed = True


class _StartupScope(_OwnedSQLiteScope):
    __slots__ = ("prepare_application_shell",)

    def __init__(
        self,
        connection: sqlite3.Connection,
        prepare_application_shell: PrepareApplicationShellService,
    ) -> None:
        super().__init__(connection)
        self.prepare_application_shell = prepare_application_shell


class _ForegroundScope(_OwnedSQLiteScope):
    __slots__ = ("process_user_message", "recover_processing_run")

    def __init__(
        self,
        connection: sqlite3.Connection,
        process_user_message: ProcessUserMessageService,
        recover_processing_run: RecoverProcessingRunService,
    ) -> None:
        super().__init__(connection)
        self.process_user_message = process_user_message
        self.recover_processing_run = recover_processing_run


class _InspectionScope(_OwnedSQLiteScope):
    __slots__ = ("inspect_context",)

    def __init__(
        self,
        connection: sqlite3.Connection,
        inspect_context: InspectContextService,
    ) -> None:
        super().__init__(connection)
        self.inspect_context = inspect_context


class ProductionShellScopeFactory:
    """Build fresh calling-thread-owned application scopes around SQLite."""

    def __init__(
        self,
        *,
        configuration: ApplicationConfiguration,
        database_path: Path,
        trace_logger: TraceLogger,
        connection_factory: ConnectionFactory = connect_database,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._configuration = configuration_snapshot_from(configuration)
        self._database_path = Path(database_path).resolve()
        self._trace_logger = trace_logger
        self._connection_factory = connection_factory
        self._clock = UtcSystemClock() if clock is None else clock
        self._id_generator = (
            UuidDomainIdGenerator() if id_generator is None else id_generator
        )
        self._configuration_loader = _StaticConfigurationLoader(
            self._configuration
        )
        self._model_gateway = OllamaModelProvider(
            self._configuration.model.base_url,
            self._configuration.model.name,
        )
        self._deterministic = self._build_deterministic_components()

    @property
    def configuration_snapshot(self) -> ConfigurationSnapshot:
        """Expose the already-converted immutable snapshot for diagnostics/tests."""

        return self._configuration

    def _build_deterministic_components(self) -> DeterministicComponents:
        return DeterministicComponents(
            DeterministicInterpretationEngine(self._configuration.context),
            DeterministicReferenceMentionExtractor(),
            DeterministicReferenceResolver(self._id_generator),
            DeterministicConstraintEngine(
                self._configuration.context,
                self._id_generator,
            ),
            DeterministicClarificationBuilder(),
            DeterministicContextRetriever(self._id_generator),
            DeterministicContextPacketBuilder(),
            DeterministicPromptRenderer(),
            DeterministicResponseValidator(),
            DeterministicCorrectionController(),
        )

    @staticmethod
    def _repositories(connection: sqlite3.Connection) -> RepositoryPorts:
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

    def open_startup_scope(self) -> _StartupScope:
        connection = self._connection_factory(self._database_path)
        try:
            transactions = SQLiteTransactionBoundary(connection)
            service = PrepareApplicationShellService(
                projects=SQLiteProjectRepository(connection),
                conversations=SQLiteConversationRepository(connection),
                conversation_states=SQLiteConversationStateRepository(connection),
                processing_runs=SQLiteProcessingRunRepository(connection),
                settings=SQLiteSettingsRepository(connection),
                transactions=transactions,
                clock=self._clock,
                id_generator=self._id_generator,
            )
            return _StartupScope(connection, service)
        except BaseException:
            connection.close()
            raise

    def open_foreground_scope(self) -> _ForegroundScope:
        connection = self._connection_factory(self._database_path)
        try:
            repositories = self._repositories(connection)
            transactions = SQLiteTransactionBoundary(connection)
            system = SystemPorts(
                self._model_gateway,
                self._clock,
                self._id_generator,
                self._configuration_loader,
                self._trace_logger,
                transactions,
            )
            stage = ContextPacketStageService(
                builder=self._deterministic.context_packet_builder,
                packets=repositories.context_packets,
                runs=repositories.processing_runs,
                model_calls=repositories.model_calls,
                id_generator=self._id_generator,
                transactions=transactions,
            )
            process = ProcessUserMessageService(
                repositories=repositories,
                system=system,
                deterministic=self._deterministic,
                context_packet_stage=stage,
            )
            recover = RecoverProcessingRunService(
                repositories=repositories,
                system=system,
                deterministic=self._deterministic,
                context_packet_stage=stage,
            )
            return _ForegroundScope(connection, process, recover)
        except BaseException:
            connection.close()
            raise

    def open_inspection_scope(self) -> _InspectionScope:
        connection = self._connection_factory(self._database_path)
        try:
            repositories = self._repositories(connection)
            service = InspectContextService(
                repositories=repositories,
                snapshots=SQLiteInspectionSnapshotBoundary(connection),
            )
            return _InspectionScope(connection, service)
        except BaseException:
            connection.close()
            raise


__all__ = [
    "ProductionShellScopeFactory",
    "UtcSystemClock",
    "UuidDomainIdGenerator",
    "UuidIdempotencyKeyFactory",
    "configuration_snapshot_from",
]
