"""Foreground submission and restart recovery orchestration for TASK-0014."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from context_for_ai.application.contracts import (
    BusyErrorValue,
    BusyResult,
    CancellationCheckpoint,
    CancelledResult,
    ClarificationResult,
    ConcurrencyConflictErrorValue,
    ConcurrencyConflictResult,
    ConfigurationErrorValue,
    ConfigurationFailureResult,
    ContextPacketStage,
    ControlledFailureError,
    ControlledFailureResult,
    ExistingRunResult,
    NoRecoveryRequiredResult,
    PersistenceErrorValue,
    PersistenceFailureResult,
    PreparedOutputTransition,
    PreparedTaskTransition,
    PreparedTopicTransition,
    ProcessUserMessageRequest,
    ProcessUserMessageResult,
    RecoverProcessingRunRequest,
    RecoveryCompletedResult,
    RecoveryResult,
    SucceededResult,
    ValidationExhaustedErrorValue,
    ValidationExhaustedResult,
)
from context_for_ai.application.conversation_state import (
    calculate_prepared_state_transition,
)
from context_for_ai.context_engine.normalization import normalize_phrase
from context_for_ai.domain.decisions import (
    Constraint,
    ConstraintDecision,
    ConstraintPacketLineage,
    CorrectionEnvelope,
    InterpretationDecision,
    ReferenceOutcome,
)
from context_for_ai.domain.entities import (
    Conversation,
    ConversationState,
    ConversationTask,
    Entity,
    Memory,
    Message,
    Project,
    Topic,
)
from context_for_ai.domain.enums import (
    ClarificationReason,
    ConstraintResolutionStatus,
    ConstraintSourceKind,
    FailureCode,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    PipelineStage,
    ProcessingRunStatus,
    ProjectStatus,
    PromptRenderKind,
    ProviderKind,
    ValidationStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
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
    ConfidenceBand,
    confidence_band,
)
from context_for_ai.domain.ports.configuration import (
    ConfigurationLoader,
    ConfigurationSnapshot,
    ValidationConfigurationSnapshot,
)
from context_for_ai.domain.ports.context import (
    ClarificationBuildRequest,
    ClarificationBuilder,
    ConstraintEngine,
    ConstraintEvaluationRequest,
    ContextBudgetExceeded,
    ContextPacketBuildRequest,
    ContextPacketBuildSuccess,
    ContextRetriever,
    CorrectionController,
    CorrectionExhausted,
    CorrectionPlanRequest,
    FailedCandidateLineage,
    InterpretationEngine,
    InterpretationRequest,
    PromptRenderRequest,
    PromptRenderResult,
    PromptRenderer,
    ReferenceMentionExtractionRequest,
    ReferenceMentionExtractor,
    ReferenceResolutionRequest,
    ReferenceResolver,
    ResponseValidator,
    RetrievalDecision,
    RetrievalRequest,
    ValidationRequest,
)
from context_for_ai.domain.ports.errors import (
    AdmissionRaceError,
    ConfigurationError,
    PersistenceError,
)
from context_for_ai.domain.ports.model_gateway import (
    CancellationToken,
    CompletedGeneration,
    GenerationFailure,
    GenerationRequest,
    GenerationSettings,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelGateway,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
)
from context_for_ai.domain.ports.records import ContextPacketRecord, MemoryRecord
from context_for_ai.domain.ports.repositories import (
    ClarificationRepository,
    ConstraintRepository,
    ContextPacketRepository,
    ConversationRepository,
    ConversationStateRepository,
    EntityRepository,
    MemoryRepository,
    MessageRepository,
    ModelCallRepository,
    ProcessingRunRepository,
    ProjectRepository,
    ReferenceResolutionRepository,
    TaskRepository,
    TopicRepository,
    ValidationRepository,
)
from context_for_ai.domain.ports.system import (
    Clock,
    IdGenerator,
    TraceEvent,
    TraceLogger,
    TransactionBoundary,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    canonical_decimal_string,
)


_CANCELLED_MESSAGE = "The request was cancelled."
_PERSISTENCE_MESSAGE = "Processing could not be saved safely."
_CONTEXT_FAILURE_MESSAGE = "Context could not be constructed safely."
_CORRECTION_BUDGET_MESSAGE = (
    "The correction context exceeds the configured prompt budget."
)
_EXHAUSTED_MESSAGE = "The response did not pass validation."
_CONFIGURATION_CHANGED_MESSAGE = (
    "The application configuration changed before processing could resume."
)
_PROCESS_RESTARTED_MESSAGE = (
    "The interrupted model request cannot be safely repeated."
)
_INCONSISTENT_RECOVERY_MESSAGE = (
    "Stored processing state is inconsistent and cannot be resumed safely."
)


class _Repositories(Protocol):
    projects: ProjectRepository
    conversations: ConversationRepository
    topics: TopicRepository
    tasks: TaskRepository
    conversation_states: ConversationStateRepository
    messages: MessageRepository
    entities: EntityRepository
    reference_resolutions: ReferenceResolutionRepository
    constraints: ConstraintRepository
    memories: MemoryRepository
    processing_runs: ProcessingRunRepository
    context_packets: ContextPacketRepository
    model_calls: ModelCallRepository
    validations: ValidationRepository
    clarifications: ClarificationRepository


class _System(Protocol):
    model_gateway: ModelGateway
    clock: Clock
    id_generator: IdGenerator
    configuration_loader: ConfigurationLoader
    trace_logger: TraceLogger
    transactions: TransactionBoundary


class _Deterministic(Protocol):
    interpretation_engine: InterpretationEngine
    reference_mention_extractor: ReferenceMentionExtractor
    reference_resolver: ReferenceResolver
    constraint_engine: ConstraintEngine
    clarification_builder: ClarificationBuilder
    context_retriever: ContextRetriever
    prompt_renderer: PromptRenderer
    response_validator: ResponseValidator
    correction_controller: CorrectionController


@dataclass(frozen=True, slots=True)
class _AcceptedRun:
    run: ProcessingRun
    message: Message | None
    state: ConversationState | None = None


@dataclass(frozen=True, slots=True)
class _RecoverySnapshot:
    run: ProcessingRun
    message: Message | None
    state: ConversationState | None
    packet: ContextPacketRecord | None
    reference_outcomes: tuple[ReferenceOutcome, ...]
    constraints: tuple[Constraint, ...]
    requests: tuple[ModelRequest, ...]
    responses: tuple[ModelResponse | None, ...]
    validations: tuple[ValidationResult | None, ...]
    listed_validations: tuple[ValidationResult, ...]
    assistant_messages: tuple[Message | None, ...]
    corrections: tuple[CorrectionAttempt, ...]
    failures: tuple[SafeFailure, ...]
    clarification: ClarificationRequest | None

    @property
    def current_index(self) -> int | None:
        if not self.requests:
            return None
        return max(
            range(len(self.requests)),
            key=lambda index: (
                self.requests[index].attempt_number,
                str(self.requests[index].id),
            ),
        )


@dataclass(frozen=True, slots=True)
class _RecoveryIssue:
    reason: str
    relevant_requests: tuple[ModelRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class _PreparedContext:
    source_state: ConversationState
    next_state: ConversationState
    selected_task: ConversationTask | None
    reference_outcomes: tuple[ReferenceOutcome, ...]
    constraint_decision: ConstraintDecision | None
    clarification: ClarificationRequest | None
    packet_request: ContextPacketBuildRequest | None
    context_time: datetime
    reference_phase_ran: bool
    constraint_phase_ran: bool


@dataclass(frozen=True, slots=True)
class _Candidate:
    request: ModelRequest
    response: ModelResponse
    validation: ValidationResult
    candidate_text: str


class _ContextCasConflict(Exception):
    def __init__(self, expected_version: int) -> None:
        self.expected_version = expected_version


class _ContextFailure(Exception):
    def __init__(self, component: str, reason_code: str) -> None:
        self.component = component
        self.reason_code = reason_code


class _CancelledAt(Exception):
    def __init__(self, checkpoint: CancellationCheckpoint) -> None:
        self.checkpoint = checkpoint


def model_request_projection(
    generation: GenerationRequest,
    render: PromptRenderResult,
) -> FrozenJsonObject:
    """Return the closed mvp-model-request-v1 persistence projection."""

    return FrozenJsonObject(
        {
            "schema_version": "mvp-model-request-v1",
            "correlation": {
                "processing_run_id": str(generation.processing_run_id),
                "context_packet_id": str(generation.context_packet_id),
                "model_request_id": str(generation.model_request_id),
                "attempt_number": generation.attempt_number,
            },
            "generation_settings": {
                "context_window_tokens": generation.settings.context_window_tokens,
                "request_timeout_seconds": generation.settings.request_timeout_seconds,
                "temperature_decimal": canonical_decimal_string(
                    generation.settings.temperature
                ),
            },
            "rendering": {
                "render_kind": render.render_kind.value,
                "prompt_policy_version": render.prompt_policy_version,
                "estimated_prompt_tokens": render.estimated_prompt_tokens,
                "effective_prompt_budget": render.effective_prompt_budget,
                "included_sections": tuple(
                    section.value for section in render.included_sections
                ),
                "omitted_sections": tuple(
                    omission.to_json_object() for omission in render.omitted_sections
                ),
            },
        }
    )


def completed_response_projection(
    request: ModelRequest,
    response_id: DomainId,
    completed: CompletedGeneration,
) -> FrozenJsonObject:
    """Return the closed mvp-completed-generation-v1 persistence projection."""

    elapsed_microseconds = (
        completed.elapsed.days * 86_400_000_000
        + completed.elapsed.seconds * 1_000_000
        + completed.elapsed.microseconds
    )
    usage = completed.token_usage
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
            "elapsed_microseconds": elapsed_microseconds,
            "token_usage": (
                None
                if usage is None
                else {
                    "prompt_tokens": usage.prompt_tokens,
                    "generated_tokens": usage.generated_tokens,
                    "total_tokens": usage.total_tokens,
                }
            ),
            "provider_metadata": completed.provider_metadata,
        }
    )


def _validation_snapshot(configuration: ConfigurationSnapshot) -> ValidationConfigurationSnapshot:
    validation = configuration.validation
    return ValidationConfigurationSnapshot(
        configuration.configuration_fingerprint,
        validation.max_revisions,
        validation.rule_set_version,
        validation.output_shape_rules,
        validation.preserve_change_verb_list_id,
        validation.preserve_change_verbs,
        validation.action_markers,
    )


def _required(value: object | None, record_name: str) -> object:
    if value is None:
        raise _ContextFailure("INTERPRETATION", "REQUIRED_CONTEXT_RECORD_MISSING")
    return value


class _PipelineService:
    def __init__(
        self,
        *,
        repositories: _Repositories,
        system: _System,
        deterministic: _Deterministic,
        context_packet_stage: ContextPacketStage,
    ) -> None:
        self._repositories = repositories
        self._system = system
        self._deterministic = deterministic
        self._context_packet_stage = context_packet_stage

    def _emit(
        self,
        *,
        timestamp: datetime,
        event_name: str,
        stage: PipelineStage,
        configuration_fingerprint: str,
        run: ProcessingRun,
        context_packet_id: DomainId | None = None,
        model_request_id: DomainId | None = None,
        model_response_id: DomainId | None = None,
        validation_result_id: DomainId | None = None,
        clarification_request_id: DomainId | None = None,
        correction_attempt_number: int | None = None,
        error_type: FailureCode | None = None,
    ) -> None:
        try:
            self._system.trace_logger.emit(
                TraceEvent(
                    timestamp=timestamp,
                    level="INFO",
                    event_name=event_name,
                    stage=stage,
                    configuration_fingerprint=configuration_fingerprint,
                    conversation_id=run.conversation_id,
                    user_message_id=run.user_message_id,
                    processing_run_id=run.id,
                    context_packet_id=context_packet_id,
                    model_request_id=model_request_id,
                    model_response_id=model_response_id,
                    validation_result_id=validation_result_id,
                    clarification_request_id=clarification_request_id,
                    correction_attempt_number=correction_attempt_number,
                    error_type=error_type,
                )
            )
        except Exception:
            return

    def _state(self, conversation_id: DomainId) -> ConversationState:
        state = self._repositories.conversation_states.get(conversation_id)
        if state is None:
            raise PersistenceError("Conversation state does not exist.")
        return state

    def _latest_validation(self, run_id: DomainId) -> ValidationResult | None:
        values = self._repositories.validations.list_for_run(run_id)
        return None if not values else values[-1]

    def _existing_result(self, run: ProcessingRun) -> ExistingRunResult:
        state = self._state(run.conversation_id)
        packet_record = self._repositories.context_packets.get_for_run(run.id)
        validation = self._latest_validation(run.id)
        clarification = self._repositories.clarifications.get_for_run(run.id)
        terminal_failures = tuple(
            item
            for item in self._repositories.model_calls.list_failures_for_run(run.id)
            if item.is_terminal
        )
        safe_failure = terminal_failures[0] if len(terminal_failures) == 1 else None
        assistant_id: DomainId | None = None
        assistant_text: str | None = None
        for request in self._repositories.model_calls.list_requests_for_run(run.id):
            response = self._repositories.model_calls.get_response_for_request(request.id)
            if response is not None and response.assistant_message_id is not None:
                assistant = self._repositories.messages.get(response.assistant_message_id)
                if assistant is None:
                    raise PersistenceError("Linked assistant message does not exist.")
                assistant_id = assistant.id
                assistant_text = assistant.original_text
        return ExistingRunResult(
            run.id,
            run.user_message_id,
            run.status,
            state,
            None if packet_record is None else packet_record.packet.id,
            validation,
            assistant_id,
            assistant_text,
            clarification,
            safe_failure,
        )

    def _controlled_result(
        self,
        run: ProcessingRun,
        failure: SafeFailure,
        *,
        packet_id: DomainId | None = None,
        validation: ValidationResult | None = None,
    ) -> ControlledFailureResult:
        return ControlledFailureResult(
            run.id,
            run.user_message_id,
            run.status,
            self._state(run.conversation_id),
            packet_id,
            validation,
            ControlledFailureError(failure.error_code, failure.safe_message),
            failure,
        )

    def _trace_failed(
        self,
        configuration: ConfigurationSnapshot,
        run: ProcessingRun,
        failure: SafeFailure,
        *,
        packet_id: DomainId | None = None,
        request: ModelRequest | None = None,
        response: ModelResponse | None = None,
        validation: ValidationResult | None = None,
    ) -> None:
        self._emit(
            timestamp=failure.created_at,
            event_name="run_failed",
            stage=failure.stage,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=run,
            context_packet_id=packet_id,
            model_request_id=None if request is None else request.id,
            model_response_id=None if response is None else response.id,
            validation_result_id=None if validation is None else validation.id,
            correction_attempt_number=(
                None
                if request is None or request.attempt_number == 0
                else request.attempt_number
            ),
            error_type=failure.error_code,
        )

    def _persistence_failure(
        self,
        *,
        configuration: ConfigurationSnapshot,
        failed_stage: PipelineStage,
        accepted: _AcceptedRun | None,
        packet_id: DomainId | None = None,
        validation: ValidationResult | None = None,
    ) -> PersistenceFailureResult:
        error = PersistenceErrorValue(failed_stage)
        if accepted is None:
            return PersistenceFailureResult(
                None, None, None, None, None, None, error, None, False
            )
        try:
            durable_run = self._repositories.processing_runs.get(accepted.run.id)
            if durable_run is None:
                return PersistenceFailureResult(
                    None, None, None, None, None, None, error, None, False
                )
            durable_state = self._state(durable_run.conversation_id)
            durable_packet = self._repositories.context_packets.get_for_run(durable_run.id)
            durable_validation = self._latest_validation(durable_run.id)
        except PersistenceError:
            if accepted.state is None:
                return PersistenceFailureResult(
                    None, None, None, None, None, None, error, None, False
                )
            return PersistenceFailureResult(
                accepted.run.id,
                accepted.run.user_message_id,
                accepted.run.status,
                accepted.state,
                packet_id,
                validation,
                error,
                None,
                False,
            )
        durable_packet_id = (
            None if durable_packet is None else durable_packet.packet.id
        )
        if durable_run.status not in NON_TERMINAL_PROCESSING_RUN_STATUSES:
            return PersistenceFailureResult(
                durable_run.id,
                durable_run.user_message_id,
                durable_run.status,
                durable_state,
                durable_packet_id,
                durable_validation,
                error,
                None,
                False,
            )

        failure_id = self._system.id_generator.new_id()
        terminal_time = self._system.clock.now()
        failure = SafeFailure(
            failure_id,
            durable_run.id,
            PipelineStage.TERMINALIZATION,
            FailureCode.PERSISTENCE_ERROR,
            _PERSISTENCE_MESSAGE,
            FrozenJsonObject(
                {
                    "failed_stage": failed_stage.value,
                    "prior_run_status": durable_run.status.value,
                }
            ),
            True,
            terminal_time,
        )
        terminal_run = replace(
            durable_run,
            status=ProcessingRunStatus.FAILED,
            completed_at=terminal_time,
        )
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.add_failure(failure)
                self._repositories.processing_runs.update(terminal_run)
        except Exception:
            return PersistenceFailureResult(
                durable_run.id,
                durable_run.user_message_id,
                durable_run.status,
                durable_state,
                durable_packet_id,
                durable_validation,
                error,
                None,
                False,
            )
        self._trace_failed(
            configuration,
            terminal_run,
            failure,
            packet_id=durable_packet_id,
            validation=durable_validation,
        )
        return PersistenceFailureResult(
            terminal_run.id,
            terminal_run.user_message_id,
            terminal_run.status,
            self._state(terminal_run.conversation_id),
            durable_packet_id,
            durable_validation,
            error,
            failure,
            True,
        )

    def _cancel_accepted(
        self,
        *,
        accepted: _AcceptedRun,
        configuration: ConfigurationSnapshot,
        checkpoint: CancellationCheckpoint,
        packet_id: DomainId | None,
    ) -> CancelledResult | PersistenceFailureResult:
        try:
            current = self._repositories.processing_runs.get(accepted.run.id)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.CONTEXT,
                accepted=accepted,
                packet_id=packet_id,
            )
        if current is None:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.CONTEXT,
                accepted=accepted,
                packet_id=packet_id,
            )
        stage = (
            PipelineStage.REQUEST
            if checkpoint is CancellationCheckpoint.BEFORE_REQUEST_PREPARATION
            else PipelineStage.CONTEXT
        )
        failure_id = self._system.id_generator.new_id()
        terminal_time = self._system.clock.now()
        failure = SafeFailure(
            failure_id,
            current.id,
            stage,
            FailureCode.CANCELLED_BY_USER,
            _CANCELLED_MESSAGE,
            FrozenJsonObject(
                {
                    "checkpoint": checkpoint.value,
                    "context_packet_id": None if packet_id is None else str(packet_id),
                }
            ),
            True,
            terminal_time,
        )
        terminal_run = replace(
            current,
            status=ProcessingRunStatus.CANCELLED,
            completed_at=terminal_time,
        )
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.add_failure(failure)
                self._repositories.processing_runs.update(terminal_run)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=stage,
                accepted=accepted,
                packet_id=packet_id,
            )
        validation = self._latest_validation(terminal_run.id)
        self._trace_failed(
            configuration,
            terminal_run,
            failure,
            packet_id=packet_id,
            validation=validation,
        )
        return CancelledResult(
            terminal_run.id,
            terminal_run.user_message_id,
            terminal_run.status,
            self._state(terminal_run.conversation_id),
            packet_id,
            validation,
            FailureCode.CANCELLED_BY_USER,
            checkpoint,
            failure,
            True,
        )

    @staticmethod
    def _check_cancelled(
        cancellation_token: CancellationToken,
        checkpoint: CancellationCheckpoint,
    ) -> None:
        if cancellation_token.is_cancelled():
            raise _CancelledAt(checkpoint)

    def _clarification(
        self,
        *,
        run: ProcessingRun,
        reason: ClarificationReason,
        details: FrozenJsonObject,
        created_at: datetime,
    ) -> ClarificationRequest:
        clarification_id = self._system.id_generator.new_id()
        try:
            return self._deterministic.clarification_builder.build(
                ClarificationBuildRequest(
                    clarification_id,
                    run.id,
                    reason,
                    details,
                    created_at,
                )
            )
        except Exception as error:
            if isinstance(error, PersistenceError):
                raise
            raise _ContextFailure(
                "INTERPRETATION", "INVALID_COMPONENT_RESULT"
            ) from None

    def _prepared_proposals(
        self,
        *,
        state: ConversationState,
        interpretation: InterpretationDecision,
        context_time: datetime,
    ) -> tuple[ConversationState, ConversationTask | None]:
        confidence = interpretation.interpretation.confidence
        topic_proposal: PreparedTopicTransition | None = None
        stored_topic: Topic | None = None
        if interpretation.proposed_topic_label is not None:
            stored_topic = self._repositories.topics.get_by_normalized_label(
                state.conversation_id,
                normalize_phrase(interpretation.proposed_topic_label),
            )
            if stored_topic is not None:
                topic_proposal = PreparedTopicTransition(stored_topic.id, confidence)

        task_proposal: PreparedTaskTransition | None = None
        stored_task: ConversationTask | None = None
        if interpretation.proposed_task_title is not None:
            normalized_title = normalize_phrase(interpretation.proposed_task_title)
            stored_task = next(
                (
                    task
                    for task in self._repositories.tasks.list_for_conversation(
                        state.conversation_id
                    )
                    if normalize_phrase(task.title) == normalized_title
                ),
                None,
            )
            if stored_task is not None:
                task_proposal = PreparedTaskTransition(stored_task.id, confidence)

        output = PreparedOutputTransition(
            interpretation.interpretation.intent,
            interpretation.interpretation.expected_output_type,
            confidence,
        )
        from context_for_ai.application.contracts import (
            ApplyConversationStateTransitionInput,
        )

        calculation = calculate_prepared_state_transition(
            current=state,
            request=ApplyConversationStateTransitionInput(
                state.conversation_id,
                state.version,
                topic_proposal,
                task_proposal,
                output,
            ),
            stored_topic=stored_topic,
            stored_task=stored_task,
            updated_at=context_time,
        )
        return calculation.state, calculation.selected_task

    @staticmethod
    def _constraint_lineage(
        decision: ConstraintDecision,
        message: Message,
    ) -> tuple[ConstraintPacketLineage, ...]:
        evidence = {item.constraint_id: item for item in decision.evidence}
        conflict_related: dict[DomainId, set[DomainId]] = {
            constraint.id: set() for constraint in decision.constraints
        }
        for group in decision.conflict_groups:
            for constraint_id in group.constraint_ids:
                conflict_related[constraint_id].update(
                    item for item in group.constraint_ids if item != constraint_id
                )

        results: list[ConstraintPacketLineage] = []
        for constraint in decision.constraints:
            related = set(conflict_related[constraint.id])
            winner: DomainId | None = None
            if constraint.resolution_status is ConstraintResolutionStatus.OVERRIDDEN:
                target = evidence[constraint.id].target_key
                candidates = tuple(
                    item
                    for item in decision.constraints
                    if item.id != constraint.id
                    and item.resolution_status is ConstraintResolutionStatus.ACTIVE
                    and (
                        evidence[item.id].target_key == target
                        or evidence[item.id].target_key.partition(":")[2]
                        == target.partition(":")[2]
                    )
                )
                if not candidates:
                    raise _ContextFailure(
                        "CONSTRAINT_RESOLUTION", "INVALID_COMPONENT_RESULT"
                    )
                winner_constraint = sorted(
                    candidates,
                    key=lambda item: (-item.priority, str(item.id)),
                )[0]
                winner = winner_constraint.id
                related.add(winner)
            results.append(
                ConstraintPacketLineage(
                    constraint.id,
                    (
                        message.id
                        if constraint.source_kind is ConstraintSourceKind.CURRENT_MESSAGE
                        else None
                    ),
                    None,
                    None,
                    winner,
                    tuple(sorted(related, key=str)),
                )
            )
        return tuple(results)

    def _prepare_context(
        self,
        *,
        run: ProcessingRun,
        configuration: ConfigurationSnapshot,
        cancellation_token: CancellationToken,
    ) -> _PreparedContext:
        message = self._repositories.messages.get(run.user_message_id)
        state = self._repositories.conversation_states.get(run.conversation_id)
        conversation = self._repositories.conversations.get(run.conversation_id)
        if message is None or state is None or conversation is None:
            raise _ContextFailure(
                "INTERPRETATION", "REQUIRED_CONTEXT_RECORD_MISSING"
            )
        context_time = self._system.clock.now()
        try:
            interpretation = self._deterministic.interpretation_engine.interpret(
                InterpretationRequest(run.id, message, state, context_time)
            )
        except Exception as error:
            if isinstance(error, PersistenceError):
                raise
            raise _ContextFailure(
                "INTERPRETATION", "INVALID_COMPONENT_RESULT"
            ) from None
        self._check_cancelled(
            cancellation_token, CancellationCheckpoint.CONTEXT_CONSTRUCTION
        )
        if interpretation.clarification_reason is not None:
            clarification = self._clarification(
                run=run,
                reason=interpretation.clarification_reason,
                details=interpretation.clarification_details,  # type: ignore[arg-type]
                created_at=context_time,
            )
            return _PreparedContext(
                state,
                state,
                None,
                (),
                None,
                clarification,
                None,
                context_time,
                False,
                False,
            )

        scoped_entities = self._repositories.entities.list_reference_candidates(
            conversation_id=run.conversation_id,
            project_id=conversation.project_id,
        )
        try:
            mentions = self._deterministic.reference_mention_extractor.extract(
                ReferenceMentionExtractionRequest(
                    message,
                    interpretation.reference_mentions,
                    scoped_entities,
                )
            )
            recent_limit = configuration.context.recent_message_limit
            prior_messages = tuple(
                item
                for item in self._repositories.messages.list_for_conversation(
                    run.conversation_id,
                    limit=recent_limit + 1,
                )
                if item.id != message.id
            )
            prior_messages = () if recent_limit == 0 else prior_messages[-recent_limit:]
            prior_outcomes = self._repositories.reference_resolutions.list_resolved_for_messages(
                tuple(item.id for item in prior_messages)
            )
            references = self._deterministic.reference_resolver.resolve(
                ReferenceResolutionRequest(
                    run.id,
                    message,
                    prior_messages,
                    state,
                    mentions,
                    scoped_entities,
                    prior_outcomes,
                    context_time,
                )
            )
        except Exception as error:
            if isinstance(error, PersistenceError):
                raise
            raise _ContextFailure(
                "REFERENCE_RESOLUTION", "INVALID_COMPONENT_RESULT"
            ) from None
        self._check_cancelled(
            cancellation_token, CancellationCheckpoint.CONTEXT_CONSTRUCTION
        )
        if references.blocks_generation:
            clarification = self._clarification(
                run=run,
                reason=references.clarification_reason,  # type: ignore[arg-type]
                details=references.clarification_details,  # type: ignore[arg-type]
                created_at=context_time,
            )
            return _PreparedContext(
                state,
                state,
                None,
                references.outcomes,
                None,
                clarification,
                None,
                context_time,
                True,
                False,
            )

        active_project: Project | None = None
        if conversation.project_id is not None:
            active_project = self._repositories.projects.get(conversation.project_id)
            if active_project is None:
                raise _ContextFailure(
                    "CONSTRAINT_RESOLUTION", "REQUIRED_CONTEXT_RECORD_MISSING"
                )
        try:
            constraints = self._deterministic.constraint_engine.evaluate(
                ConstraintEvaluationRequest(
                    message,
                    state,
                    interpretation,
                    references.outcomes,
                    (),
                    (),
                    None if active_project is None else active_project.name,
                    context_time,
                )
            )
        except Exception as error:
            if isinstance(error, PersistenceError):
                raise
            raise _ContextFailure(
                "CONSTRAINT_RESOLUTION", "INVALID_COMPONENT_RESULT"
            ) from None
        self._check_cancelled(
            cancellation_token, CancellationCheckpoint.CONTEXT_CONSTRUCTION
        )
        if constraints.clarification_reason is not None:
            clarification = self._clarification(
                run=run,
                reason=constraints.clarification_reason,
                details=constraints.clarification_details,  # type: ignore[arg-type]
                created_at=context_time,
            )
            return _PreparedContext(
                state,
                state,
                None,
                references.outcomes,
                constraints,
                clarification,
                None,
                context_time,
                True,
                True,
            )

        try:
            next_state, selected_task = self._prepared_proposals(
                state=state,
                interpretation=interpretation,
                context_time=context_time,
            )
        except Exception as error:
            if isinstance(error, PersistenceError):
                raise
            raise _ContextFailure(
                "INTERPRETATION", "CONTEXT_INVARIANT_VIOLATION"
            ) from None

        packet_id = self._system.id_generator.new_id()
        active_topic: Topic | None = None
        if next_state.active_topic_id is not None:
            active_topic = self._repositories.topics.get(next_state.active_topic_id)
            if active_topic is None:
                raise _ContextFailure(
                    "RETRIEVAL", "REQUIRED_CONTEXT_RECORD_MISSING"
                )
        memory_records = self._repositories.memories.list_retrieval_candidates()
        memories = tuple(record.memory for record in memory_records)
        try:
            retrieval = self._deterministic.context_retriever.retrieve(
                RetrievalRequest(
                    packet_id,
                    run.id,
                    message.id,
                    run.conversation_id,
                    conversation.project_id,
                    None if active_topic is None else active_topic.label,
                    message.original_text,
                    memories,
                    configuration.context.minimum_relevance_score,
                    configuration.context.retrieved_memory_limit,
                    context_time,
                )
            )
        except Exception as error:
            if isinstance(error, PersistenceError):
                raise
            raise _ContextFailure("RETRIEVAL", "INVALID_COMPONENT_RESULT") from None
        self._check_cancelled(
            cancellation_token, CancellationCheckpoint.CONTEXT_CONSTRUCTION
        )
        memories_by_id = {memory.id: memory for memory in memories}
        selected_memories = tuple(
            memories_by_id[result.memory_id] for result in retrieval.selected
        )
        lineage = self._constraint_lineage(constraints, message)
        packet_request = ContextPacketBuildRequest(
            packet_id,
            run,
            message,
            next_state,
            conversation.project_id,
            active_topic,
            interpretation,
            references.outcomes,
            constraints,
            lineage,
            retrieval,
            selected_memories,
            configuration.model.context_window_tokens,
            configuration.context.maximum_prompt_tokens,
            configuration.context.reserved_response_tokens,
            _validation_snapshot(configuration),
            context_time,
        )
        self._check_cancelled(
            cancellation_token, CancellationCheckpoint.CONTEXT_CONSTRUCTION
        )
        return _PreparedContext(
            state,
            next_state,
            selected_task,
            references.outcomes,
            constraints,
            None,
            packet_request,
            context_time,
            True,
            True,
        )

    def _context_phase_events(
        self,
        *,
        configuration: ConfigurationSnapshot,
        run: ProcessingRun,
        prepared: _PreparedContext,
        packet_id: DomainId | None,
    ) -> None:
        self._emit(
            timestamp=prepared.context_time,
            event_name="context_built",
            stage=PipelineStage.CONTEXT,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=run,
            context_packet_id=packet_id,
        )
        if prepared.reference_phase_ran:
            self._emit(
                timestamp=prepared.context_time,
                event_name="reference_resolved",
                stage=PipelineStage.CONTEXT,
                configuration_fingerprint=configuration.configuration_fingerprint,
                run=run,
                context_packet_id=packet_id,
            )
        if prepared.constraint_phase_ran:
            self._emit(
                timestamp=prepared.context_time,
                event_name="constraints_resolved",
                stage=PipelineStage.CONTEXT,
                configuration_fingerprint=configuration.configuration_fingerprint,
                run=run,
                context_packet_id=packet_id,
            )

    def _terminalize(
        self,
        *,
        accepted: _AcceptedRun,
        configuration: ConfigurationSnapshot,
        target_status: ProcessingRunStatus,
        stage: PipelineStage,
        code: FailureCode,
        safe_message: str,
        details: FrozenJsonObject,
        packet_id: DomainId | None = None,
        validation: ValidationResult | None = None,
        request_update: ModelRequest | None = None,
        trace_request: ModelRequest | None = None,
        response: ModelResponse | None = None,
    ) -> tuple[ProcessingRun, SafeFailure] | PersistenceFailureResult:
        try:
            current = self._repositories.processing_runs.get(accepted.run.id)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=stage,
                accepted=accepted,
                packet_id=packet_id,
                validation=validation,
            )
        if current is None:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=stage,
                accepted=accepted,
                packet_id=packet_id,
                validation=validation,
            )
        failure_id = self._system.id_generator.new_id()
        terminal_time = self._system.clock.now()
        if request_update is not None:
            request_update = replace(request_update, completed_at=terminal_time)
        failure = SafeFailure(
            failure_id,
            current.id,
            stage,
            code,
            safe_message,
            details,
            True,
            terminal_time,
        )
        terminal_run = replace(
            current,
            status=target_status,
            completed_at=terminal_time,
        )
        try:
            with self._system.transactions.transaction():
                if request_update is not None:
                    self._repositories.model_calls.update_request(request_update)
                self._repositories.model_calls.add_failure(failure)
                self._repositories.processing_runs.update(terminal_run)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=stage,
                accepted=accepted,
                packet_id=packet_id,
                validation=validation,
            )
        self._trace_failed(
            configuration,
            terminal_run,
            failure,
            packet_id=packet_id,
            request=request_update if request_update is not None else trace_request,
            response=response,
            validation=validation,
        )
        return terminal_run, failure

    def _context_failure_result(
        self,
        *,
        accepted: _AcceptedRun,
        configuration: ConfigurationSnapshot,
        issue: _ContextFailure,
    ) -> ProcessUserMessageResult:
        terminal = self._terminalize(
            accepted=accepted,
            configuration=configuration,
            target_status=ProcessingRunStatus.CONTROLLED_FAILURE,
            stage=PipelineStage.CONTEXT,
            code=FailureCode.CONTEXT_CONSTRUCTION_FAILED,
            safe_message=_CONTEXT_FAILURE_MESSAGE,
            details=FrozenJsonObject(
                {"component": issue.component, "reason_code": issue.reason_code}
            ),
        )
        if isinstance(terminal, PersistenceFailureResult):
            return terminal
        run, failure = terminal
        return self._controlled_result(run, failure)

    def _concurrency_conflict_result(
        self,
        *,
        accepted: _AcceptedRun,
        configuration: ConfigurationSnapshot,
        expected_version: int,
    ) -> ProcessUserMessageResult:
        observed = self._state(accepted.run.conversation_id)
        terminal = self._terminalize(
            accepted=accepted,
            configuration=configuration,
            target_status=ProcessingRunStatus.FAILED,
            stage=PipelineStage.CONTEXT,
            code=FailureCode.CONCURRENCY_CONFLICT,
            safe_message=(
                "The conversation changed while context was being prepared."
            ),
            details=FrozenJsonObject(
                {
                    "conversation_id": str(accepted.run.conversation_id),
                    "expected_state_version": expected_version,
                    "observed_state_version": observed.version,
                    "retry_count": 1,
                }
            ),
        )
        if isinstance(terminal, PersistenceFailureResult):
            return terminal
        run, failure = terminal
        return ConcurrencyConflictResult(
            run.id,
            run.user_message_id,
            self._state(run.conversation_id),
            ConcurrencyConflictErrorValue(),
            failure,
        )

    def _commit_prepared_context(
        self,
        *,
        accepted: _AcceptedRun,
        prepared: _PreparedContext,
        configuration: ConfigurationSnapshot,
    ) -> ContextPacketBuildSuccess | ClarificationResult | ControlledFailureResult:
        run = self._repositories.processing_runs.get(accepted.run.id)
        if run is None:
            raise PersistenceError("Accepted processing run does not exist.")
        if prepared.clarification is not None:
            clarified = replace(
                run,
                status=ProcessingRunStatus.NEEDS_CLARIFICATION,
                completed_at=prepared.context_time,
            )
            with self._system.transactions.transaction():
                self._repositories.reference_resolutions.add_all(
                    prepared.reference_outcomes
                )
                if prepared.constraint_decision is not None:
                    self._repositories.constraints.add_all(
                        prepared.constraint_decision.constraints
                    )
                self._repositories.processing_runs.update(clarified)
                self._repositories.clarifications.add(prepared.clarification)
            self._context_phase_events(
                configuration=configuration,
                run=clarified,
                prepared=prepared,
                packet_id=None,
            )
            self._emit(
                timestamp=prepared.context_time,
                event_name="run_clarification",
                stage=PipelineStage.CONTEXT,
                configuration_fingerprint=configuration.configuration_fingerprint,
                run=clarified,
                clarification_request_id=prepared.clarification.id,
            )
            return ClarificationResult(
                clarified.id,
                clarified.user_message_id,
                self._state(clarified.conversation_id),
                prepared.clarification,
            )

        packet_request = prepared.packet_request
        if packet_request is None or prepared.constraint_decision is None:
            raise _ContextFailure("PACKET_BUILD", "INVALID_COMPONENT_RESULT")
        with self._system.transactions.transaction():
            try:
                result = self._context_packet_stage.execute(packet_request)
            except PersistenceError:
                raise
            except Exception:
                raise _ContextFailure(
                    "PACKET_BUILD", "INVALID_COMPONENT_RESULT"
                ) from None
            if isinstance(result, ContextPacketBuildSuccess):
                self._repositories.reference_resolutions.add_all(
                    prepared.reference_outcomes
                )
                self._repositories.constraints.add_all(
                    prepared.constraint_decision.constraints
                )
                if prepared.selected_task is not None:
                    stored_task = self._repositories.tasks.get(
                        prepared.selected_task.id
                    )
                    if stored_task != prepared.selected_task:
                        self._repositories.tasks.update(prepared.selected_task)
                if prepared.next_state is prepared.source_state:
                    current_state = self._state(run.conversation_id)
                    if current_state.version != prepared.source_state.version:
                        raise _ContextCasConflict(prepared.source_state.version)
                elif not self._repositories.conversation_states.compare_and_swap(
                    expected_version=prepared.source_state.version,
                    state=prepared.next_state,
                ):
                    raise _ContextCasConflict(prepared.source_state.version)
            elif not isinstance(result, ContextBudgetExceeded):
                raise _ContextFailure("PACKET_BUILD", "INVALID_COMPONENT_RESULT")

        stored_run = self._repositories.processing_runs.get(run.id)
        if stored_run is None:
            raise PersistenceError("Context outcome processing run does not exist.")
        if isinstance(result, ContextBudgetExceeded):
            terminal_failures = tuple(
                item
                for item in self._repositories.model_calls.list_failures_for_run(run.id)
                if item.is_terminal
            )
            if len(terminal_failures) != 1:
                raise PersistenceError("Context budget failure is not durable.")
            failure = terminal_failures[0]
            self._trace_failed(configuration, stored_run, failure)
            return self._controlled_result(stored_run, failure)

        packet_id = result.record.packet.id
        self._context_phase_events(
            configuration=configuration,
            run=stored_run,
            prepared=prepared,
            packet_id=packet_id,
        )
        self._emit(
            timestamp=prepared.context_time,
            event_name="retrieval_completed",
            stage=PipelineStage.CONTEXT,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=stored_run,
            context_packet_id=packet_id,
        )
        self._emit(
            timestamp=prepared.context_time,
            event_name="packet_built",
            stage=PipelineStage.CONTEXT,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=stored_run,
            context_packet_id=packet_id,
        )
        return result

    def _continue_context(
        self,
        *,
        accepted: _AcceptedRun,
        configuration: ConfigurationSnapshot,
        cancellation_token: CancellationToken,
    ) -> ProcessUserMessageResult:
        try:
            self._check_cancelled(
                cancellation_token, CancellationCheckpoint.AFTER_ACCEPTANCE
            )
        except _CancelledAt as cancelled:
            return self._cancel_accepted(
                accepted=accepted,
                configuration=configuration,
                checkpoint=cancelled.checkpoint,
                packet_id=None,
            )

        for attempt in range(2):
            try:
                prepared = self._prepare_context(
                    run=accepted.run,
                    configuration=configuration,
                    cancellation_token=cancellation_token,
                )
                result = self._commit_prepared_context(
                    accepted=accepted,
                    prepared=prepared,
                    configuration=configuration,
                )
            except _CancelledAt as cancelled:
                return self._cancel_accepted(
                    accepted=accepted,
                    configuration=configuration,
                    checkpoint=cancelled.checkpoint,
                    packet_id=None,
                )
            except _ContextCasConflict as conflict:
                if attempt == 0:
                    continue
                return self._concurrency_conflict_result(
                    accepted=accepted,
                    configuration=configuration,
                    expected_version=conflict.expected_version,
                )
            except _ContextFailure as issue:
                return self._context_failure_result(
                    accepted=accepted,
                    configuration=configuration,
                    issue=issue,
                )
            except PersistenceError:
                return self._persistence_failure(
                    configuration=configuration,
                    failed_stage=PipelineStage.CONTEXT,
                    accepted=accepted,
                )

            if isinstance(result, (ClarificationResult, ControlledFailureResult)):
                return result
            stored_run = self._repositories.processing_runs.get(accepted.run.id)
            if stored_run is None:
                return self._persistence_failure(
                    configuration=configuration,
                    failed_stage=PipelineStage.CONTEXT,
                    accepted=accepted,
                    packet_id=result.record.packet.id,
                )
            return self._continue_from_packet(
                accepted=accepted,
                run=stored_run,
                packet_record=result.record,
                initial_render=result.initial_render,
                configuration=configuration,
                cancellation_token=cancellation_token,
            )
        raise AssertionError("The bounded context CAS loop did not terminate.")

    @staticmethod
    def _generation_settings(
        configuration: ConfigurationSnapshot,
    ) -> GenerationSettings:
        return GenerationSettings(
            configuration.model.context_window_tokens,
            configuration.model.request_timeout_seconds,
            configuration.model.temperature,
        )

    def _new_model_request(
        self,
        *,
        run: ProcessingRun,
        packet_id: DomainId,
        render: PromptRenderResult,
        attempt_number: int,
        configuration: ConfigurationSnapshot,
        request_id: DomainId,
    ) -> tuple[ModelRequest, GenerationRequest]:
        generation = GenerationRequest(
            configuration.model.name,
            render.rendered_prompt,
            self._generation_settings(configuration),
            run.id,
            packet_id,
            request_id,
            attempt_number,
        )
        purpose = (
            ModelRequestPurpose.INITIAL
            if attempt_number == 0
            else ModelRequestPurpose.REVISION
        )
        request = ModelRequest(
            request_id,
            run.id,
            packet_id,
            purpose,
            attempt_number,
            configuration.model.provider,
            configuration.model.name,
            ModelRequestStatus.PENDING,
            render.rendered_prompt,
            model_request_projection(generation, render),
            None,
            None,
            None,
            None,
        )
        return request, generation

    @staticmethod
    def _generation_from_stored(request: ModelRequest) -> GenerationRequest:
        settings = request.request["generation_settings"]
        if not isinstance(settings, FrozenJsonObject):
            raise LifecycleInvariantError("Stored generation settings are invalid.")
        return GenerationRequest(
            request.model_name,
            request.rendered_prompt,
            GenerationSettings(
                settings["context_window_tokens"],  # type: ignore[arg-type]
                settings["request_timeout_seconds"],  # type: ignore[arg-type]
                Decimal(settings["temperature_decimal"]),  # type: ignore[arg-type]
            ),
            request.processing_run_id,
            request.context_packet_id,
            request.id,
            request.attempt_number,
        )

    def _prepare_initial_request(
        self,
        *,
        accepted: _AcceptedRun,
        run: ProcessingRun,
        packet: ContextPacketRecord,
        render: PromptRenderResult,
        configuration: ConfigurationSnapshot,
    ) -> tuple[ModelRequest, GenerationRequest] | PersistenceFailureResult:
        request_id = self._system.id_generator.new_id()
        request, generation = self._new_model_request(
            run=run,
            packet_id=packet.packet.id,
            render=render,
            attempt_number=0,
            configuration=configuration,
            request_id=request_id,
        )
        generating = replace(run, status=ProcessingRunStatus.GENERATING)
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.add_request(request)
                self._repositories.processing_runs.update(generating)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.REQUEST,
                accepted=accepted,
                packet_id=packet.packet.id,
            )
        return request, generation

    def _claim_and_generate(
        self,
        *,
        accepted: _AcceptedRun,
        run: ProcessingRun,
        packet: ContextPacketRecord,
        request: ModelRequest,
        generation: GenerationRequest,
        configuration: ConfigurationSnapshot,
        cancellation_token: CancellationToken,
    ) -> ProcessUserMessageResult:
        claim_time = self._system.clock.now()
        in_flight = replace(
            request,
            status=ModelRequestStatus.IN_FLIGHT,
            started_at=claim_time,
        )
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.update_request(in_flight)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.REQUEST,
                accepted=accepted,
                packet_id=packet.packet.id,
            )
        self._emit(
            timestamp=claim_time,
            event_name="model_request_started",
            stage=PipelineStage.REQUEST,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=run,
            context_packet_id=packet.packet.id,
            model_request_id=in_flight.id,
            correction_attempt_number=(
                None if in_flight.attempt_number == 0 else in_flight.attempt_number
            ),
        )
        outcome = self._system.model_gateway.generate(
            generation,
            cancellation_token,
        )
        if isinstance(outcome, CompletedGeneration):
            return self._commit_candidate(
                accepted=accepted,
                run=run,
                packet=packet,
                request=in_flight,
                completed=outcome,
                configuration=configuration,
                cancellation_token=cancellation_token,
            )
        return self._commit_gateway_failure(
            accepted=accepted,
            run=run,
            packet=packet,
            request=in_flight,
            failure_outcome=outcome,
            configuration=configuration,
        )

    def _commit_gateway_failure(
        self,
        *,
        accepted: _AcceptedRun,
        run: ProcessingRun,
        packet: ContextPacketRecord,
        request: ModelRequest,
        failure_outcome: GenerationFailure,
        configuration: ConfigurationSnapshot,
    ) -> ProcessUserMessageResult:
        failure_id = self._system.id_generator.new_id()
        terminal_time = self._system.clock.now()
        failed_request = replace(
            request,
            status=failure_outcome.model_request_status,
            completed_at=terminal_time,
            error_code=failure_outcome.diagnostic_code,
            safe_error_message=failure_outcome.safe_message,
        )
        failure = SafeFailure(
            failure_id,
            run.id,
            PipelineStage.TRANSPORT,
            failure_outcome.failure_code,
            failure_outcome.safe_message,
            FrozenJsonObject(
                {
                    "attempt_number": request.attempt_number,
                    "context_packet_id": str(packet.packet.id),
                    "diagnostic_code": failure_outcome.diagnostic_code,
                    "model_request_id": str(request.id),
                }
            ),
            True,
            terminal_time,
        )
        terminal_run = replace(
            run,
            status=failure_outcome.processing_run_status,
            completed_at=terminal_time,
        )
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.update_request(failed_request)
                self._repositories.model_calls.add_failure(failure)
                self._repositories.processing_runs.update(terminal_run)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.TRANSPORT,
                accepted=accepted,
                packet_id=packet.packet.id,
            )
        self._emit(
            timestamp=terminal_time,
            event_name="model_request_finished",
            stage=PipelineStage.TRANSPORT,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=terminal_run,
            context_packet_id=packet.packet.id,
            model_request_id=request.id,
            correction_attempt_number=(
                None if request.attempt_number == 0 else request.attempt_number
            ),
            error_type=failure.error_code,
        )
        self._trace_failed(
            configuration,
            terminal_run,
            failure,
            packet_id=packet.packet.id,
            request=failed_request,
        )
        if isinstance(failure_outcome, ModelCancelledFailure):
            return CancelledResult(
                terminal_run.id,
                terminal_run.user_message_id,
                terminal_run.status,
                self._state(terminal_run.conversation_id),
                packet.packet.id,
                self._latest_validation(terminal_run.id),
                FailureCode.MODEL_CANCELLED,
                CancellationCheckpoint.GATEWAY,
                failure,
                True,
            )
        return self._controlled_result(
            terminal_run,
            failure,
            packet_id=packet.packet.id,
            validation=self._latest_validation(terminal_run.id),
        )

    def _commit_candidate(
        self,
        *,
        accepted: _AcceptedRun,
        run: ProcessingRun,
        packet: ContextPacketRecord,
        request: ModelRequest,
        completed: CompletedGeneration,
        configuration: ConfigurationSnapshot,
        cancellation_token: CancellationToken,
    ) -> ProcessUserMessageResult:
        response_id = self._system.id_generator.new_id()
        validation_id = self._system.id_generator.new_id()
        candidate_time = self._system.clock.now()
        succeeded_request = replace(
            request,
            status=ModelRequestStatus.SUCCEEDED,
            completed_at=candidate_time,
        )
        response = ModelResponse(
            response_id,
            request.id,
            completed.response_text,
            completed_response_projection(request, response_id, completed),
            None,
            candidate_time,
        )
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.update_request(succeeded_request)
                self._repositories.model_calls.add_response(response)
                validation = self._deterministic.response_validator.validate(
                    ValidationRequest(
                        packet.packet,
                        response.id,
                        validation_id,
                        response.response_text,
                        candidate_time,
                    )
                )
                self._repositories.validations.add(validation)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.VALIDATION,
                accepted=accepted,
                packet_id=packet.packet.id,
            )
        self._emit(
            timestamp=candidate_time,
            event_name="model_request_finished",
            stage=PipelineStage.TRANSPORT,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=run,
            context_packet_id=packet.packet.id,
            model_request_id=request.id,
            model_response_id=response.id,
            correction_attempt_number=(
                None if request.attempt_number == 0 else request.attempt_number
            ),
        )
        self._emit(
            timestamp=candidate_time,
            event_name="validation_completed",
            stage=PipelineStage.VALIDATION,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=run,
            context_packet_id=packet.packet.id,
            model_request_id=request.id,
            model_response_id=response.id,
            validation_result_id=validation.id,
            correction_attempt_number=(
                None if request.attempt_number == 0 else request.attempt_number
            ),
        )
        candidate = _Candidate(
            succeeded_request,
            response,
            validation,
            completed.response_text,
        )
        if validation.status is ValidationStatus.PASSED:
            return self._commit_success(
                accepted=accepted,
                run=run,
                packet=packet,
                candidate=candidate,
                configuration=configuration,
            )
        return self._continue_failed_candidate(
            accepted=accepted,
            run=run,
            packet=packet,
            candidate=candidate,
            configuration=configuration,
            cancellation_token=cancellation_token,
        )

    def _commit_success(
        self,
        *,
        accepted: _AcceptedRun,
        run: ProcessingRun,
        packet: ContextPacketRecord,
        candidate: _Candidate,
        configuration: ConfigurationSnapshot,
    ) -> ProcessUserMessageResult:
        if candidate.response.response_text.encode(
            "utf-8"
        ) != candidate.candidate_text.encode("utf-8"):
            raise LifecycleInvariantError("Candidate response byte equality failed.")
        assistant_id = self._system.id_generator.new_id()
        terminal_time = self._system.clock.now()
        current_run = self._repositories.processing_runs.get(run.id)
        if current_run is None:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.TERMINALIZATION,
                accepted=accepted,
                packet_id=packet.packet.id,
                validation=candidate.validation,
            )
        assistant = Message(
            assistant_id,
            run.conversation_id,
            MessageRole.ASSISTANT,
            candidate.response.response_text,
            terminal_time,
            self._repositories.messages.next_sequence_number(run.conversation_id),
        )
        succeeded_run = replace(
            current_run,
            status=ProcessingRunStatus.SUCCEEDED,
            completed_at=terminal_time,
        )
        try:
            with self._system.transactions.transaction():
                self._repositories.messages.add(assistant)
                self._repositories.model_calls.link_assistant_message(
                    model_response_id=candidate.response.id,
                    assistant_message_id=assistant.id,
                )
                self._repositories.processing_runs.update(succeeded_run)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.TERMINALIZATION,
                accepted=accepted,
                packet_id=packet.packet.id,
                validation=candidate.validation,
            )
        self._emit(
            timestamp=terminal_time,
            event_name="run_succeeded",
            stage=PipelineStage.TERMINALIZATION,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=succeeded_run,
            context_packet_id=packet.packet.id,
            model_request_id=candidate.request.id,
            model_response_id=candidate.response.id,
            validation_result_id=candidate.validation.id,
            correction_attempt_number=(
                None
                if candidate.request.attempt_number == 0
                else candidate.request.attempt_number
            ),
        )
        return SucceededResult(
            succeeded_run.id,
            succeeded_run.user_message_id,
            self._state(succeeded_run.conversation_id),
            packet.packet.id,
            candidate.validation,
            assistant.id,
            assistant.original_text,
        )

    def _exhaust_validation(
        self,
        *,
        accepted: _AcceptedRun,
        run: ProcessingRun,
        packet: ContextPacketRecord,
        candidate: _Candidate,
        exhausted: CorrectionExhausted,
        configuration: ConfigurationSnapshot,
    ) -> ProcessUserMessageResult:
        terminal = self._terminalize(
            accepted=accepted,
            configuration=configuration,
            target_status=ProcessingRunStatus.CONTROLLED_FAILURE,
            stage=PipelineStage.VALIDATION,
            code=FailureCode.VALIDATION_EXHAUSTED,
            safe_message=_EXHAUSTED_MESSAGE,
            details=FrozenJsonObject(
                {
                    "context_packet_id": str(exhausted.context_packet_id),
                    "failed_model_request_id": str(
                        exhausted.failed_model_request_id
                    ),
                    "failed_model_response_id": str(
                        exhausted.failed_model_response_id
                    ),
                    "validation_result_id": str(exhausted.validation_result_id),
                    "attempt_number": exhausted.attempt_number,
                    "correction_limit": exhausted.correction_limit,
                }
            ),
            packet_id=packet.packet.id,
            validation=candidate.validation,
            trace_request=candidate.request,
            response=candidate.response,
        )
        if isinstance(terminal, PersistenceFailureResult):
            return terminal
        terminal_run, failure = terminal
        return ValidationExhaustedResult(
            terminal_run.id,
            terminal_run.user_message_id,
            self._state(terminal_run.conversation_id),
            packet.packet.id,
            candidate.validation,
            ValidationExhaustedErrorValue(),
            failure,
        )

    def _correction_budget_failure(
        self,
        *,
        accepted: _AcceptedRun,
        packet: ContextPacketRecord,
        candidate: _Candidate,
        envelope: CorrectionEnvelope,
        budget: ContextBudgetExceeded,
        configuration: ConfigurationSnapshot,
    ) -> ProcessUserMessageResult:
        terminal = self._terminalize(
            accepted=accepted,
            configuration=configuration,
            target_status=ProcessingRunStatus.CONTROLLED_FAILURE,
            stage=PipelineStage.CORRECTION,
            code=FailureCode.CONTEXT_BUDGET_EXCEEDED,
            safe_message=_CORRECTION_BUDGET_MESSAGE,
            details=FrozenJsonObject(
                {
                    "phase": "CORRECTION",
                    "context_packet_id": str(packet.packet.id),
                    "failed_model_response_id": str(candidate.response.id),
                    "attempt_number": envelope.attempt_number,
                    "token_estimator": budget.token_estimator,
                    "estimated_required_tokens": budget.estimated_required_tokens,
                    "effective_prompt_budget": budget.effective_prompt_budget,
                }
            ),
            packet_id=packet.packet.id,
            validation=candidate.validation,
            trace_request=candidate.request,
            response=candidate.response,
        )
        if isinstance(terminal, PersistenceFailureResult):
            return terminal
        terminal_run, failure = terminal
        return self._controlled_result(
            terminal_run,
            failure,
            packet_id=packet.packet.id,
            validation=candidate.validation,
        )

    def _continue_failed_candidate(
        self,
        *,
        accepted: _AcceptedRun,
        run: ProcessingRun,
        packet: ContextPacketRecord,
        candidate: _Candidate,
        configuration: ConfigurationSnapshot,
        cancellation_token: CancellationToken,
    ) -> ProcessUserMessageResult:
        try:
            self._check_cancelled(
                cancellation_token,
                CancellationCheckpoint.BEFORE_REQUEST_PREPARATION,
            )
        except _CancelledAt as cancelled:
            return self._cancel_accepted(
                accepted=accepted,
                configuration=configuration,
                checkpoint=cancelled.checkpoint,
                packet_id=packet.packet.id,
            )
        failed_lineage = FailedCandidateLineage(
            run.id,
            packet.packet.id,
            candidate.request.id,
            candidate.response.id,
            candidate.request.attempt_number,
            candidate.request.purpose,
            candidate.request.status,
            candidate.response.assistant_message_id,
        )
        decision = self._deterministic.correction_controller.plan(
            CorrectionPlanRequest(
                packet.packet,
                failed_lineage,
                candidate.validation,
            )
        )
        if isinstance(decision, CorrectionExhausted):
            return self._exhaust_validation(
                accepted=accepted,
                run=run,
                packet=packet,
                candidate=candidate,
                exhausted=decision,
                configuration=configuration,
            )
        render = self._deterministic.prompt_renderer.render(
            PromptRenderRequest(packet.packet, decision)
        )
        if isinstance(render, ContextBudgetExceeded):
            return self._correction_budget_failure(
                accepted=accepted,
                packet=packet,
                candidate=candidate,
                envelope=decision,
                budget=render,
                configuration=configuration,
            )
        request_id = self._system.id_generator.new_id()
        correction_id = self._system.id_generator.new_id()
        correction_time = self._system.clock.now()
        current_run = self._repositories.processing_runs.get(run.id)
        if current_run is None:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.CORRECTION,
                accepted=accepted,
                packet_id=packet.packet.id,
                validation=candidate.validation,
            )
        revised_request, generation = self._new_model_request(
            run=current_run,
            packet_id=packet.packet.id,
            render=render,
            attempt_number=decision.attempt_number,
            configuration=configuration,
            request_id=request_id,
        )
        correction = CorrectionAttempt(
            correction_id,
            run.id,
            decision.attempt_number,
            candidate.response.id,
            revised_request.id,
            decision.violations,
            correction_time,
        )
        revising = replace(current_run, status=ProcessingRunStatus.REVISING)
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.add_request(revised_request)
                self._repositories.model_calls.add_correction(correction)
                if current_run.status is not ProcessingRunStatus.REVISING:
                    self._repositories.processing_runs.update(revising)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.CORRECTION,
                accepted=accepted,
                packet_id=packet.packet.id,
                validation=candidate.validation,
            )
        self._emit(
            timestamp=correction_time,
            event_name="correction_started",
            stage=PipelineStage.CORRECTION,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=revising,
            context_packet_id=packet.packet.id,
            model_request_id=revised_request.id,
            model_response_id=candidate.response.id,
            validation_result_id=candidate.validation.id,
            correction_attempt_number=decision.attempt_number,
        )
        return self._claim_and_generate(
            accepted=accepted,
            run=revising,
            packet=packet,
            request=revised_request,
            generation=generation,
            configuration=configuration,
            cancellation_token=cancellation_token,
        )

    def _continue_from_packet(
        self,
        *,
        accepted: _AcceptedRun,
        run: ProcessingRun,
        packet_record: ContextPacketRecord,
        initial_render: PromptRenderResult,
        configuration: ConfigurationSnapshot,
        cancellation_token: CancellationToken,
    ) -> ProcessUserMessageResult:
        try:
            self._check_cancelled(
                cancellation_token,
                CancellationCheckpoint.BEFORE_REQUEST_PREPARATION,
            )
        except _CancelledAt as cancelled:
            return self._cancel_accepted(
                accepted=accepted,
                configuration=configuration,
                checkpoint=cancelled.checkpoint,
                packet_id=packet_record.packet.id,
            )
        prepared = self._prepare_initial_request(
            accepted=accepted,
            run=run,
            packet=packet_record,
            render=initial_render,
            configuration=configuration,
        )
        if isinstance(prepared, PersistenceFailureResult):
            return prepared
        request, generation = prepared
        return self._claim_and_generate(
            accepted=accepted,
            run=replace(run, status=ProcessingRunStatus.GENERATING),
            packet=packet_record,
            request=request,
            generation=generation,
            configuration=configuration,
            cancellation_token=cancellation_token,
        )


class ProcessUserMessageService(_PipelineService):
    """Coordinate one exact idempotent foreground user-message pipeline."""

    def _admit(
        self,
        request: ProcessUserMessageRequest,
        cancellation_token: CancellationToken,
        configuration: ConfigurationSnapshot,
    ) -> _AcceptedRun | ExistingRunResult | BusyResult | CancelledResult:
        try:
            with self._system.transactions.transaction():
                existing = self._repositories.processing_runs.get_by_idempotency_key(
                    conversation_id=request.conversation_id,
                    idempotency_key=request.idempotency_key,
                )
                if existing is not None:
                    return self._existing_result(existing)
                active = self._repositories.processing_runs.get_non_terminal()
                if active is not None:
                    return BusyResult(
                        active.id,
                        active.status,
                        BusyErrorValue(active.id),
                    )
                if cancellation_token.is_cancelled():
                    return CancelledResult(
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        FailureCode.CANCELLED_BY_USER,
                        CancellationCheckpoint.BEFORE_ACCEPTANCE,
                        None,
                        False,
                    )
                conversation = self._repositories.conversations.get(
                    request.conversation_id
                )
                state = self._repositories.conversation_states.get(
                    request.conversation_id
                )
                if conversation is None or state is None:
                    raise PersistenceError(
                        "Admission conversation and state must already exist."
                    )
                selected_project: Project | None = None
                if request.project_id is not None:
                    selected_project = self._repositories.projects.get(
                        request.project_id
                    )
                    if (
                        selected_project is None
                        or selected_project.status is not ProjectStatus.ACTIVE
                    ):
                        raise PersistenceError(
                            "Admission project must exist and be active."
                        )
                sequence_number = self._repositories.messages.next_sequence_number(
                    request.conversation_id
                )
                message_id = self._system.id_generator.new_id()
                run_id = self._system.id_generator.new_id()
                accepted_at = self._system.clock.now()
                message = Message(
                    message_id,
                    request.conversation_id,
                    MessageRole.USER,
                    request.user_text,
                    accepted_at,
                    sequence_number,
                )
                accepted_state = state
                self._repositories.messages.add(message)
                if conversation.project_id != request.project_id:
                    updated_conversation = replace(
                        conversation,
                        project_id=request.project_id,
                        updated_at=accepted_at,
                    )
                    accepted_state = ConversationState(
                        state.conversation_id,
                        state.active_topic_id,
                        state.active_task_id,
                        state.previous_task_id,
                        state.expected_output_type,
                        state.topic_stack,
                        state.version + 1,
                        accepted_at,
                    )
                    self._repositories.conversations.update(updated_conversation)
                    if not self._repositories.conversation_states.compare_and_swap(
                        expected_version=state.version,
                        state=accepted_state,
                    ):
                        raise PersistenceError(
                            "Admission project selection lost its state version."
                        )
                run = ProcessingRun(
                    run_id,
                    request.conversation_id,
                    message.id,
                    str(request.idempotency_key),
                    ProcessingRunStatus.PERSISTED,
                    accepted_state.version,
                    configuration.configuration_fingerprint,
                    accepted_at,
                    None,
                )
                self._repositories.processing_runs.add_with_admission_race_capture(run)
                return _AcceptedRun(run, message, accepted_state)
        except AdmissionRaceError as race:
            conflicting = race.conflicting_run
            if (
                conflicting.conversation_id == request.conversation_id
                and conflicting.idempotency_key == str(request.idempotency_key)
            ):
                return self._existing_result(conflicting)
            return BusyResult(
                conflicting.id,
                conflicting.status,
                BusyErrorValue(conflicting.id),
            )

    def execute(
        self,
        request: ProcessUserMessageRequest,
        cancellation_token: CancellationToken,
    ) -> ProcessUserMessageResult:
        try:
            configuration = self._system.configuration_loader.load()
        except ConfigurationError as error:
            return ConfigurationFailureResult(
                ConfigurationErrorValue(
                    error.file_name,
                    error.key or "root",
                )
            )
        try:
            admission = self._admit(request, cancellation_token, configuration)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.ACCEPTANCE,
                accepted=None,
            )
        if not isinstance(admission, _AcceptedRun):
            return admission
        self._emit(
            timestamp=admission.run.started_at,
            event_name="run_accepted",
            stage=PipelineStage.ACCEPTANCE,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=admission.run,
        )
        return self._continue_context(
            accepted=admission,
            configuration=configuration,
            cancellation_token=cancellation_token,
        )


class RecoverProcessingRunService(_PipelineService):
    """Resume or safely terminalize the sole durable non-terminal run."""

    @staticmethod
    def _relevant_requests(
        requests: tuple[ModelRequest, ...] | list[ModelRequest],
    ) -> tuple[ModelRequest, ...]:
        by_id = {request.id: request for request in requests}
        return tuple(sorted(by_id.values(), key=lambda item: str(item.id)))

    @classmethod
    def _issue(
        cls,
        reason: str,
        *requests: ModelRequest,
    ) -> _RecoveryIssue:
        return _RecoveryIssue(reason, cls._relevant_requests(list(requests)))

    def _read_snapshot(self, run: ProcessingRun) -> _RecoverySnapshot:
        message = self._repositories.messages.get(run.user_message_id)
        state = self._repositories.conversation_states.get(run.conversation_id)
        packet = self._repositories.context_packets.get_for_run(run.id)
        requests = tuple(
            sorted(
                self._repositories.model_calls.list_requests_for_run(run.id),
                key=lambda item: (item.attempt_number, str(item.id)),
            )
        )
        responses = tuple(
            self._repositories.model_calls.get_response_for_request(item.id)
            for item in requests
        )
        validations = tuple(
            None
            if response is None
            else self._repositories.validations.get_for_response(response.id)
            for response in responses
        )
        assistant_messages = tuple(
            None
            if response is None or response.assistant_message_id is None
            else self._repositories.messages.get(response.assistant_message_id)
            for response in responses
        )
        return _RecoverySnapshot(
            run,
            message,
            state,
            packet,
            self._repositories.reference_resolutions.list_for_run(run.id),
            self._repositories.constraints.list_for_run(run.id),
            requests,
            responses,
            validations,
            self._repositories.validations.list_for_run(run.id),
            assistant_messages,
            self._repositories.model_calls.list_corrections_for_run(run.id),
            self._repositories.model_calls.list_failures_for_run(run.id),
            self._repositories.clarifications.get_for_run(run.id),
        )

    def _load_snapshot(self) -> _RecoverySnapshot | None:
        with self._system.transactions.transaction():
            run = self._repositories.processing_runs.get_non_terminal()
            return None if run is None else self._read_snapshot(run)

    @staticmethod
    def _correction_limit(packet: ContextPacketRecord) -> int | None:
        policy = packet.packet.packet_json.get("response_policy")
        if not isinstance(policy, FrozenJsonObject):
            return None
        limit = policy.get("correction_limit")
        generation_limit = policy.get("model_generation_limit")
        absolute_cap = policy.get("absolute_model_generation_cap")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit not in (0, 1, 2)
            or generation_limit != limit + 1
            or absolute_cap != 3
        ):
            return None
        return limit

    @staticmethod
    def _stored_transport_failure(
        request: ModelRequest,
    ) -> GenerationFailure | None:
        candidates: tuple[GenerationFailure, ...] = (
            ProviderUnavailableFailure(),
            ModelNotFoundFailure(),
            ModelTimeoutFailure(),
            ModelCancelledFailure(),
            InvalidProviderResponseFailure(),
        )
        for candidate in candidates:
            if (
                request.status is candidate.model_request_status
                and request.error_code == candidate.diagnostic_code
                and request.safe_error_message == candidate.safe_message
            ):
                return candidate
        return None

    @staticmethod
    def _request_times_are_valid(
        request: ModelRequest,
        run: ProcessingRun,
    ) -> bool:
        if request.started_at is not None and request.started_at < run.started_at:
            return False
        if (
            request.started_at is not None
            and request.completed_at is not None
            and request.completed_at < request.started_at
        ):
            return False
        empty_times = request.started_at is None and request.completed_at is None
        empty_errors = request.error_code is None and request.safe_error_message is None
        if request.status is ModelRequestStatus.PENDING:
            return empty_times and empty_errors
        if request.status is ModelRequestStatus.IN_FLIGHT:
            return (
                request.started_at is not None
                and request.completed_at is None
                and empty_errors
            )
        if request.status is ModelRequestStatus.SUCCEEDED:
            return (
                request.started_at is not None
                and request.completed_at is not None
                and empty_errors
            )
        return (
            request.started_at is not None
            and request.completed_at is not None
            and request.error_code is not None
            and request.safe_error_message is not None
        )

    def _classify_impossible(
        self,
        snapshot: _RecoverySnapshot,
    ) -> _RecoveryIssue | None:
        run = snapshot.run
        packet = snapshot.packet
        requests = snapshot.requests

        if packet is None and (
            run.status is not ProcessingRunStatus.PERSISTED or bool(requests)
        ):
            return _RecoveryIssue(
                "MISSING_REQUIRED_PACKET",
                self._relevant_requests(requests),
            )

        if packet is not None and (
            run.status is ProcessingRunStatus.PERSISTED
            or packet.packet.processing_run_id != run.id
            or packet.packet.message_id != run.user_message_id
            or packet.packet.configuration_fingerprint
            != run.configuration_fingerprint
        ):
            return _RecoveryIssue("PACKET_STATUS_MISMATCH")

        by_attempt: dict[int, list[ModelRequest]] = {}
        for model_request in requests:
            by_attempt.setdefault(model_request.attempt_number, []).append(
                model_request
            )
        duplicate_requests = [
            model_request
            for values in by_attempt.values()
            if len(values) > 1
            for model_request in values
        ]
        if duplicate_requests:
            return _RecoveryIssue(
                "DUPLICATE_REQUEST_ATTEMPT",
                self._relevant_requests(duplicate_requests),
            )

        packet_mismatches = tuple(
            model_request
            for model_request in requests
            if packet is None
            or model_request.processing_run_id != run.id
            or model_request.context_packet_id != packet.packet.id
        )
        if packet_mismatches:
            return _RecoveryIssue(
                "REQUEST_PACKET_MISMATCH",
                self._relevant_requests(packet_mismatches),
            )

        response_mismatches: list[ModelRequest] = []
        for model_request, response in zip(
            requests, snapshot.responses, strict=True
        ):
            if response is None:
                if model_request.status is ModelRequestStatus.SUCCEEDED:
                    response_mismatches.append(model_request)
                continue
            if (
                response.model_request_id != model_request.id
                or model_request.status is not ModelRequestStatus.SUCCEEDED
                or model_request.completed_at is None
                or response.created_at != model_request.completed_at
            ):
                response_mismatches.append(model_request)
        if response_mismatches:
            return _RecoveryIssue(
                "RESPONSE_REQUEST_MISMATCH",
                self._relevant_requests(response_mismatches),
            )

        validation_mismatches: list[ModelRequest] = []
        paired_validation_ids: set[DomainId] = set()
        for model_request, response, validation in zip(
            requests,
            snapshot.responses,
            snapshot.validations,
            strict=True,
        ):
            if response is None:
                if validation is not None:
                    validation_mismatches.append(model_request)
                continue
            if (
                validation is None
                or validation.model_response_id != response.id
                or validation.created_at != response.created_at
            ):
                validation_mismatches.append(model_request)
            else:
                paired_validation_ids.add(validation.id)
        listed_validation_ids = {
            validation.id for validation in snapshot.listed_validations
        }
        if listed_validation_ids != paired_validation_ids:
            validation_mismatches.extend(requests)
        if validation_mismatches:
            return _RecoveryIssue(
                "VALIDATION_RESPONSE_MISMATCH",
                self._relevant_requests(validation_mismatches),
            )

        assistant_mismatches: list[ModelRequest] = []
        for model_request, response, validation, assistant in zip(
            requests,
            snapshot.responses,
            snapshot.validations,
            snapshot.assistant_messages,
            strict=True,
        ):
            if response is None or validation is None:
                continue
            linked = response.assistant_message_id is not None
            if not linked:
                if assistant is not None:
                    assistant_mismatches.append(model_request)
                continue
            if (
                validation.status is not ValidationStatus.PASSED
                or assistant is None
                or assistant.id != response.assistant_message_id
                or assistant.role is not MessageRole.ASSISTANT
                or assistant.conversation_id != run.conversation_id
                or assistant.created_at < response.created_at
                or assistant.original_text.encode("utf-8")
                != response.response_text.encode("utf-8")
            ):
                assistant_mismatches.append(model_request)
        if assistant_mismatches:
            return _RecoveryIssue(
                "ASSISTANT_VALIDATION_MISMATCH",
                self._relevant_requests(assistant_mismatches),
            )

        correction_mismatches: list[ModelRequest] = []
        correction_by_attempt: dict[int, list[CorrectionAttempt]] = {}
        for correction in snapshot.corrections:
            correction_by_attempt.setdefault(correction.attempt_number, []).append(
                correction
            )
        for model_request in requests:
            corrections = correction_by_attempt.get(
                model_request.attempt_number, []
            )
            if model_request.attempt_number == 0:
                if corrections:
                    correction_mismatches.append(model_request)
                continue
            prior = by_attempt.get(model_request.attempt_number - 1, [])
            prior_request = None if len(prior) != 1 else prior[0]
            if len(corrections) != 1 or prior_request is None:
                correction_mismatches.append(model_request)
                continue
            correction = corrections[0]
            prior_index = requests.index(prior_request)
            prior_response = snapshot.responses[prior_index]
            prior_validation = snapshot.validations[prior_index]
            if (
                correction.processing_run_id != run.id
                or correction.revised_model_request_id != model_request.id
                or correction.attempt_number != model_request.attempt_number
                or prior_response is None
                or prior_validation is None
                or prior_validation.status is not ValidationStatus.FAILED
                or correction.prior_model_response_id != prior_response.id
                or correction.reasons != prior_validation.violations
                or correction.created_at < prior_validation.created_at
            ):
                correction_mismatches.extend(
                    item
                    for item in (prior_request, model_request)
                    if item is not None
                )
        request_ids = {item.id for item in requests}
        for correction in snapshot.corrections:
            if correction.revised_model_request_id not in request_ids:
                prior_requests = tuple(
                    request
                    for index, request in enumerate(requests)
                    if snapshot.responses[index] is not None
                    and snapshot.responses[index].id
                    == correction.prior_model_response_id
                )
                correction_mismatches.extend(prior_requests)
        if correction_mismatches or any(
            len(values) != 1 for values in correction_by_attempt.values()
        ):
            return _RecoveryIssue(
                "CORRECTION_LINEAGE_MISMATCH",
                self._relevant_requests(correction_mismatches),
            )

        status_mismatches: list[ModelRequest] = []
        status_invalid = bool(
            run.status not in NON_TERMINAL_PROCESSING_RUN_STATUSES
            or run.completed_at is not None
            or snapshot.message is None
            or snapshot.message.id != run.user_message_id
            or snapshot.message.conversation_id != run.conversation_id
            or snapshot.message.role is not MessageRole.USER
            or snapshot.state is None
            or snapshot.state.conversation_id != run.conversation_id
            or snapshot.failures
            or snapshot.clarification is not None
        )
        if status_invalid:
            status_mismatches.extend(requests)

        attempts = tuple(model_request.attempt_number for model_request in requests)
        if attempts != tuple(range(len(requests))):
            status_mismatches.extend(requests)
        for model_request in requests:
            expected_purpose = (
                ModelRequestPurpose.INITIAL
                if model_request.attempt_number == 0
                else ModelRequestPurpose.REVISION
            )
            if (
                model_request.purpose is not expected_purpose
                or not self._request_times_are_valid(model_request, run)
            ):
                status_mismatches.append(model_request)
            try:
                self._generation_from_stored(model_request)
            except (
                ArithmeticError,
                KeyError,
                TypeError,
                ValueError,
                LifecycleInvariantError,
            ):
                status_mismatches.append(model_request)

        if run.status is ProcessingRunStatus.PERSISTED:
            if (
                packet is not None
                or snapshot.reference_outcomes
                or snapshot.constraints
                or requests
            ):
                status_invalid = True
                status_mismatches.extend(requests)
        elif run.status is ProcessingRunStatus.CONTEXT_READY:
            if packet is None or requests:
                status_invalid = True
                status_mismatches.extend(requests)
        else:
            if packet is None or not requests:
                status_invalid = True
                status_mismatches.extend(requests)
            elif (
                run.status is ProcessingRunStatus.GENERATING
                and requests[-1].attempt_number != 0
            ) or (
                run.status is ProcessingRunStatus.REVISING
                and requests[-1].attempt_number == 0
            ):
                status_invalid = True
                status_mismatches.append(requests[-1])

        if packet is not None and requests:
            correction_limit = self._correction_limit(packet)
            if (
                correction_limit is None
                or len(requests) > correction_limit + 1
                or requests[-1].attempt_number > correction_limit
            ):
                status_invalid = True
                status_mismatches.extend(requests)

            for index, model_request in enumerate(requests[:-1]):
                validation = snapshot.validations[index]
                response = snapshot.responses[index]
                if (
                    model_request.status is not ModelRequestStatus.SUCCEEDED
                    or response is None
                    or validation is None
                    or validation.status is not ValidationStatus.FAILED
                    or response.assistant_message_id is not None
                ):
                    status_invalid = True
                    status_mismatches.append(model_request)

            current = requests[-1]
            if current.status in {
                ModelRequestStatus.FAILED,
                ModelRequestStatus.TIMED_OUT,
                ModelRequestStatus.CANCELLED,
            } and self._stored_transport_failure(current) is None:
                status_invalid = True
                status_mismatches.append(current)

        if status_invalid or status_mismatches:
            return _RecoveryIssue(
                "STATUS_ARTIFACT_MISMATCH",
                self._relevant_requests(status_mismatches),
            )
        return None

    def _emit_recovery_event(
        self,
        *,
        event_name: str,
        configuration: ConfigurationSnapshot,
        snapshot: _RecoverySnapshot,
        error_type: FailureCode | None = None,
    ) -> None:
        index = snapshot.current_index
        model_request = None if index is None else snapshot.requests[index]
        response = None if index is None else snapshot.responses[index]
        validation = None if index is None else snapshot.validations[index]
        self._emit(
            timestamp=self._system.clock.now(),
            event_name=event_name,
            stage=PipelineStage.RECOVERY,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=snapshot.run,
            context_packet_id=(
                None if snapshot.packet is None else snapshot.packet.packet.id
            ),
            model_request_id=(
                None if model_request is None else model_request.id
            ),
            model_response_id=None if response is None else response.id,
            validation_result_id=None if validation is None else validation.id,
            clarification_request_id=(
                None
                if snapshot.clarification is None
                else snapshot.clarification.id
            ),
            correction_attempt_number=(
                None
                if model_request is None or model_request.attempt_number == 0
                else model_request.attempt_number
            ),
            error_type=error_type,
        )

    def _refresh_snapshot(
        self,
        snapshot: _RecoverySnapshot,
    ) -> _RecoverySnapshot:
        try:
            with self._system.transactions.transaction():
                run = self._repositories.processing_runs.get(snapshot.run.id)
                return snapshot if run is None else self._read_snapshot(run)
        except PersistenceError:
            return snapshot

    @staticmethod
    def _outcome_error_type(
        outcome: ProcessUserMessageResult,
    ) -> FailureCode | None:
        if isinstance(outcome, CancelledResult):
            return outcome.cancellation_code
        if isinstance(outcome, ValidationExhaustedResult):
            return outcome.error.code
        if isinstance(outcome, ConcurrencyConflictResult):
            return outcome.error.code
        if isinstance(outcome, ControlledFailureResult):
            return outcome.error.code
        if isinstance(outcome, PersistenceFailureResult):
            return FailureCode.PERSISTENCE_ERROR
        return None

    def _finish(
        self,
        *,
        configuration: ConfigurationSnapshot,
        snapshot: _RecoverySnapshot,
        outcome: ProcessUserMessageResult,
    ) -> RecoveryResult:
        final_snapshot = self._refresh_snapshot(snapshot)
        self._emit_recovery_event(
            event_name="recovery_completed",
            configuration=configuration,
            snapshot=final_snapshot,
            error_type=self._outcome_error_type(outcome),
        )
        if isinstance(outcome, PersistenceFailureResult):
            return outcome
        if isinstance(
            outcome,
            (
                SucceededResult,
                ClarificationResult,
                CancelledResult,
                ValidationExhaustedResult,
                ConcurrencyConflictResult,
                ControlledFailureResult,
            ),
        ):
            return RecoveryCompletedResult(snapshot.run.id, outcome)
        raise LifecycleInvariantError("Recovery produced a non-terminal outcome.")

    def _configuration_changed(
        self,
        *,
        accepted: _AcceptedRun,
        snapshot: _RecoverySnapshot,
        configuration: ConfigurationSnapshot,
    ) -> ProcessUserMessageResult:
        index = snapshot.current_index
        current_request = None if index is None else snapshot.requests[index]
        response = None if index is None else snapshot.responses[index]
        validation = None if index is None else snapshot.validations[index]
        terminal = self._terminalize(
            accepted=accepted,
            configuration=configuration,
            target_status=ProcessingRunStatus.FAILED,
            stage=PipelineStage.RECOVERY,
            code=FailureCode.CONFIGURATION_CHANGED,
            safe_message=_CONFIGURATION_CHANGED_MESSAGE,
            details=FrozenJsonObject(
                {
                    "stored_configuration_fingerprint": (
                        snapshot.run.configuration_fingerprint
                    ),
                    "current_configuration_fingerprint": (
                        configuration.configuration_fingerprint
                    ),
                    "prior_run_status": snapshot.run.status.value,
                }
            ),
            packet_id=(
                None if snapshot.packet is None else snapshot.packet.packet.id
            ),
            validation=validation,
            trace_request=current_request,
            response=response,
        )
        if isinstance(terminal, PersistenceFailureResult):
            return terminal
        run, failure = terminal
        return self._controlled_result(
            run,
            failure,
            packet_id=(
                None if snapshot.packet is None else snapshot.packet.packet.id
            ),
            validation=validation,
        )

    def _impossible_state(
        self,
        *,
        accepted: _AcceptedRun,
        snapshot: _RecoverySnapshot,
        configuration: ConfigurationSnapshot,
        issue: _RecoveryIssue,
    ) -> ProcessUserMessageResult:
        relevant = (
            None
            if not issue.relevant_requests
            else issue.relevant_requests[0]
        )
        relevant_index = (
            None if relevant is None else snapshot.requests.index(relevant)
        )
        response = (
            None
            if relevant_index is None
            else snapshot.responses[relevant_index]
        )
        validation = (
            None
            if relevant_index is None
            else snapshot.validations[relevant_index]
        )
        terminal = self._terminalize(
            accepted=accepted,
            configuration=configuration,
            target_status=ProcessingRunStatus.FAILED,
            stage=PipelineStage.RECOVERY,
            code=FailureCode.PERSISTENCE_ERROR,
            safe_message=_INCONSISTENT_RECOVERY_MESSAGE,
            details=FrozenJsonObject(
                {
                    "recovery_reason": issue.reason,
                    "prior_run_status": snapshot.run.status.value,
                    "model_request_id": (
                        None if relevant is None else str(relevant.id)
                    ),
                    "attempt_number": (
                        None if relevant is None else relevant.attempt_number
                    ),
                }
            ),
            packet_id=(
                None if snapshot.packet is None else snapshot.packet.packet.id
            ),
            validation=validation,
            trace_request=relevant,
            response=response,
        )
        if isinstance(terminal, PersistenceFailureResult):
            return terminal
        run, failure = terminal
        return self._controlled_result(
            run,
            failure,
            packet_id=(
                None if snapshot.packet is None else snapshot.packet.packet.id
            ),
            validation=validation,
        )

    def _recover_uncertain_request(
        self,
        *,
        accepted: _AcceptedRun,
        snapshot: _RecoverySnapshot,
        configuration: ConfigurationSnapshot,
        request: ModelRequest,
    ) -> ProcessUserMessageResult:
        packet = snapshot.packet
        if packet is None:
            return self._impossible_state(
                accepted=accepted,
                snapshot=snapshot,
                configuration=configuration,
                issue=self._issue("MISSING_REQUIRED_PACKET", request),
            )
        failed_request = replace(
            request,
            status=ModelRequestStatus.FAILED,
            error_code=FailureCode.PROCESS_RESTARTED.value,
            safe_error_message=_PROCESS_RESTARTED_MESSAGE,
        )
        terminal = self._terminalize(
            accepted=accepted,
            configuration=configuration,
            target_status=ProcessingRunStatus.FAILED,
            stage=PipelineStage.RECOVERY,
            code=FailureCode.PROCESS_RESTARTED,
            safe_message=_PROCESS_RESTARTED_MESSAGE,
            details=FrozenJsonObject(
                {
                    "model_request_id": str(request.id),
                    "attempt_number": request.attempt_number,
                    "context_packet_id": str(packet.packet.id),
                    "prior_request_status": ModelRequestStatus.IN_FLIGHT.value,
                }
            ),
            packet_id=packet.packet.id,
            request_update=failed_request,
        )
        if isinstance(terminal, PersistenceFailureResult):
            return terminal
        run, failure = terminal
        return self._controlled_result(
            run,
            failure,
            packet_id=packet.packet.id,
            validation=(
                None
                if not snapshot.listed_validations
                else snapshot.listed_validations[-1]
            ),
        )

    def _recover_success(
        self,
        *,
        accepted: _AcceptedRun,
        snapshot: _RecoverySnapshot,
        configuration: ConfigurationSnapshot,
        candidate: _Candidate,
    ) -> ProcessUserMessageResult:
        packet = snapshot.packet
        if packet is None:
            return self._impossible_state(
                accepted=accepted,
                snapshot=snapshot,
                configuration=configuration,
                issue=self._issue("MISSING_REQUIRED_PACKET", candidate.request),
            )
        if candidate.response.assistant_message_id is None:
            return self._commit_success(
                accepted=accepted,
                run=snapshot.run,
                packet=packet,
                candidate=candidate,
                configuration=configuration,
            )
        assistant = self._repositories.messages.get(
            candidate.response.assistant_message_id
        )
        if assistant is None:
            return self._impossible_state(
                accepted=accepted,
                snapshot=snapshot,
                configuration=configuration,
                issue=self._issue(
                    "ASSISTANT_VALIDATION_MISMATCH", candidate.request
                ),
            )
        current = self._repositories.processing_runs.get(snapshot.run.id)
        if current is None:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.TERMINALIZATION,
                accepted=accepted,
                packet_id=packet.packet.id,
                validation=candidate.validation,
            )
        succeeded = replace(
            current,
            status=ProcessingRunStatus.SUCCEEDED,
            completed_at=assistant.created_at,
        )
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.link_assistant_message(
                    model_response_id=candidate.response.id,
                    assistant_message_id=assistant.id,
                )
                self._repositories.processing_runs.update(succeeded)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.TERMINALIZATION,
                accepted=accepted,
                packet_id=packet.packet.id,
                validation=candidate.validation,
            )
        self._emit(
            timestamp=assistant.created_at,
            event_name="run_succeeded",
            stage=PipelineStage.TERMINALIZATION,
            configuration_fingerprint=configuration.configuration_fingerprint,
            run=succeeded,
            context_packet_id=packet.packet.id,
            model_request_id=candidate.request.id,
            model_response_id=candidate.response.id,
            validation_result_id=candidate.validation.id,
            correction_attempt_number=(
                None
                if candidate.request.attempt_number == 0
                else candidate.request.attempt_number
            ),
        )
        return SucceededResult(
            succeeded.id,
            succeeded.user_message_id,
            self._state(succeeded.conversation_id),
            packet.packet.id,
            candidate.validation,
            assistant.id,
            assistant.original_text,
        )

    def _recover_terminal_request(
        self,
        *,
        accepted: _AcceptedRun,
        snapshot: _RecoverySnapshot,
        configuration: ConfigurationSnapshot,
        request: ModelRequest,
    ) -> ProcessUserMessageResult:
        packet = snapshot.packet
        mapped = self._stored_transport_failure(request)
        if packet is None or mapped is None or request.completed_at is None:
            return self._impossible_state(
                accepted=accepted,
                snapshot=snapshot,
                configuration=configuration,
                issue=self._issue("STATUS_ARTIFACT_MISMATCH", request),
            )
        failure_id = self._system.id_generator.new_id()
        terminal_time = request.completed_at
        failure = SafeFailure(
            failure_id,
            snapshot.run.id,
            PipelineStage.TRANSPORT,
            mapped.failure_code,
            mapped.safe_message,
            FrozenJsonObject(
                {
                    "attempt_number": request.attempt_number,
                    "context_packet_id": str(packet.packet.id),
                    "diagnostic_code": mapped.diagnostic_code,
                    "model_request_id": str(request.id),
                }
            ),
            True,
            terminal_time,
        )
        terminal_run = replace(
            snapshot.run,
            status=mapped.processing_run_status,
            completed_at=terminal_time,
        )
        try:
            with self._system.transactions.transaction():
                self._repositories.model_calls.add_failure(failure)
                self._repositories.processing_runs.update(terminal_run)
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.TRANSPORT,
                accepted=accepted,
                packet_id=packet.packet.id,
                validation=(
                    None
                    if not snapshot.listed_validations
                    else snapshot.listed_validations[-1]
                ),
            )
        self._trace_failed(
            configuration,
            terminal_run,
            failure,
            packet_id=packet.packet.id,
            request=request,
        )
        latest_validation = (
            None
            if not snapshot.listed_validations
            else snapshot.listed_validations[-1]
        )
        if isinstance(mapped, ModelCancelledFailure):
            return CancelledResult(
                terminal_run.id,
                terminal_run.user_message_id,
                terminal_run.status,
                self._state(terminal_run.conversation_id),
                packet.packet.id,
                latest_validation,
                FailureCode.MODEL_CANCELLED,
                CancellationCheckpoint.GATEWAY,
                failure,
                True,
            )
        return self._controlled_result(
            terminal_run,
            failure,
            packet_id=packet.packet.id,
            validation=latest_validation,
        )

    def _resume(
        self,
        *,
        accepted: _AcceptedRun,
        snapshot: _RecoverySnapshot,
        configuration: ConfigurationSnapshot,
        cancellation_token: CancellationToken,
    ) -> ProcessUserMessageResult:
        run = snapshot.run
        packet = snapshot.packet
        self._emit_recovery_event(
            event_name="recovery_resumed",
            configuration=configuration,
            snapshot=snapshot,
        )
        if run.status is ProcessingRunStatus.PERSISTED:
            return self._continue_context(
                accepted=accepted,
                configuration=configuration,
                cancellation_token=cancellation_token,
            )
        if run.status is ProcessingRunStatus.CONTEXT_READY:
            if packet is None:
                return self._impossible_state(
                    accepted=accepted,
                    snapshot=snapshot,
                    configuration=configuration,
                    issue=_RecoveryIssue("MISSING_REQUIRED_PACKET"),
                )
            try:
                self._check_cancelled(
                    cancellation_token,
                    CancellationCheckpoint.BEFORE_REQUEST_PREPARATION,
                )
            except _CancelledAt as cancelled:
                return self._cancel_accepted(
                    accepted=accepted,
                    configuration=configuration,
                    checkpoint=cancelled.checkpoint,
                    packet_id=packet.packet.id,
                )
            render = self._deterministic.prompt_renderer.render(
                PromptRenderRequest(packet.packet, None)
            )
            if isinstance(render, ContextBudgetExceeded):
                return self._impossible_state(
                    accepted=accepted,
                    snapshot=snapshot,
                    configuration=configuration,
                    issue=_RecoveryIssue("STATUS_ARTIFACT_MISMATCH"),
                )
            return self._continue_from_packet(
                accepted=accepted,
                run=run,
                packet_record=packet,
                initial_render=render,
                configuration=configuration,
                cancellation_token=cancellation_token,
            )

        index = snapshot.current_index
        if packet is None or index is None:
            return self._impossible_state(
                accepted=accepted,
                snapshot=snapshot,
                configuration=configuration,
                issue=_RecoveryIssue("STATUS_ARTIFACT_MISMATCH"),
            )
        model_request = snapshot.requests[index]
        response = snapshot.responses[index]
        validation = snapshot.validations[index]
        if model_request.status is ModelRequestStatus.PENDING:
            return self._claim_and_generate(
                accepted=accepted,
                run=run,
                packet=packet,
                request=model_request,
                generation=self._generation_from_stored(model_request),
                configuration=configuration,
                cancellation_token=cancellation_token,
            )
        if model_request.status is ModelRequestStatus.SUCCEEDED:
            if response is None or validation is None:
                return self._impossible_state(
                    accepted=accepted,
                    snapshot=snapshot,
                    configuration=configuration,
                    issue=self._issue(
                        "VALIDATION_RESPONSE_MISMATCH", model_request
                    ),
                )
            candidate = _Candidate(
                model_request,
                response,
                validation,
                response.response_text,
            )
            if validation.status is ValidationStatus.PASSED:
                return self._recover_success(
                    accepted=accepted,
                    snapshot=snapshot,
                    configuration=configuration,
                    candidate=candidate,
                )
            correction_limit = self._correction_limit(packet)
            if correction_limit == model_request.attempt_number:
                decision = self._deterministic.correction_controller.plan(
                    CorrectionPlanRequest(
                        packet.packet,
                        FailedCandidateLineage(
                            run.id,
                            packet.packet.id,
                            model_request.id,
                            response.id,
                            model_request.attempt_number,
                            model_request.purpose,
                            model_request.status,
                            response.assistant_message_id,
                        ),
                        validation,
                    )
                )
                if not isinstance(decision, CorrectionExhausted):
                    return self._impossible_state(
                        accepted=accepted,
                        snapshot=snapshot,
                        configuration=configuration,
                        issue=self._issue(
                            "STATUS_ARTIFACT_MISMATCH", model_request
                        ),
                    )
                return self._exhaust_validation(
                    accepted=accepted,
                    run=run,
                    packet=packet,
                    candidate=candidate,
                    exhausted=decision,
                    configuration=configuration,
                )
            return self._continue_failed_candidate(
                accepted=accepted,
                run=run,
                packet=packet,
                candidate=candidate,
                configuration=configuration,
                cancellation_token=cancellation_token,
            )
        return self._recover_terminal_request(
            accepted=accepted,
            snapshot=snapshot,
            configuration=configuration,
            request=model_request,
        )

    def execute(
        self,
        request: RecoverProcessingRunRequest,
        cancellation_token: CancellationToken,
    ) -> RecoveryResult:
        del request
        try:
            configuration = self._system.configuration_loader.load()
        except ConfigurationError as error:
            return ConfigurationFailureResult(
                ConfigurationErrorValue(error.file_name, error.key or "root")
            )
        try:
            snapshot = self._load_snapshot()
        except PersistenceError:
            return self._persistence_failure(
                configuration=configuration,
                failed_stage=PipelineStage.RECOVERY,
                accepted=None,
            )
        if snapshot is None:
            return NoRecoveryRequiredResult()
        accepted = _AcceptedRun(
            snapshot.run,
            snapshot.message,
            snapshot.state,
        )
        issue = self._classify_impossible(snapshot)
        self._emit_recovery_event(
            event_name="recovery_started",
            configuration=configuration,
            snapshot=snapshot,
        )
        if (
            snapshot.run.configuration_fingerprint
            != configuration.configuration_fingerprint
        ):
            outcome = self._configuration_changed(
                accepted=accepted,
                snapshot=snapshot,
                configuration=configuration,
            )
            return self._finish(
                configuration=configuration,
                snapshot=snapshot,
                outcome=outcome,
            )
        if issue is not None:
            outcome = self._impossible_state(
                accepted=accepted,
                snapshot=snapshot,
                configuration=configuration,
                issue=issue,
            )
            return self._finish(
                configuration=configuration,
                snapshot=snapshot,
                outcome=outcome,
            )

        index = snapshot.current_index
        current = None if index is None else snapshot.requests[index]
        if current is not None and current.status is ModelRequestStatus.IN_FLIGHT:
            outcome = self._recover_uncertain_request(
                accepted=accepted,
                snapshot=snapshot,
                configuration=configuration,
                request=current,
            )
        else:
            try:
                outcome = self._resume(
                    accepted=accepted,
                    snapshot=snapshot,
                    configuration=configuration,
                    cancellation_token=cancellation_token,
                )
            except PersistenceError:
                outcome = self._persistence_failure(
                    configuration=configuration,
                    failed_stage=PipelineStage.RECOVERY,
                    accepted=accepted,
                    packet_id=(
                        None
                        if snapshot.packet is None
                        else snapshot.packet.packet.id
                    ),
                    validation=(
                        None
                        if not snapshot.listed_validations
                        else snapshot.listed_validations[-1]
                    ),
                )
        return self._finish(
            configuration=configuration,
            snapshot=snapshot,
            outcome=outcome,
        )


__all__ = [
    "ProcessUserMessageService",
    "RecoverProcessingRunService",
    "completed_response_projection",
    "model_request_projection",
]
