"""Composition-only contracts for assembling the modular monolith."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from context_for_ai.application import (
    ApplyConversationStateTransition,
    ArchiveProject,
    CreateMemory,
    EditMemory,
    GetMemory,
    InspectContext,
    InspectValidation,
    ListMemories,
    ProcessUserMessage,
    RegisterNamedItem,
    RegisterProject,
    RegisterTask,
    RegisterTopic,
    RunEvaluation,
    SelectProject,
    SoftDeleteMemory,
    TransitionTaskStatus,
)
from context_for_ai.domain.ports import (
    ClarificationBuilder,
    ClarificationRepository,
    Clock,
    ConfigurationLoader,
    ConstraintEngine,
    ConstraintRepository,
    ContextPacketRepository,
    ContextRetriever,
    ConversationRepository,
    ConversationStateRepository,
    CorrectionController,
    EntityRepository,
    EvaluationRepository,
    IdGenerator,
    InterpretationEngine,
    MemoryRepository,
    MessageRepository,
    ModelCallRepository,
    ModelGateway,
    ProcessingRunRepository,
    ProjectRepository,
    ReferenceMentionExtractor,
    ReferenceResolver,
    ReferenceResolutionRepository,
    ResponseValidator,
    SettingsRepository,
    TaskRepository,
    TopicRepository,
    TraceLogger,
    TransactionBoundary,
    ValidationRepository,
)


@dataclass(frozen=True, slots=True)
class RepositoryPorts:
    """Complete set of persistence ports supplied at composition time."""

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
    settings: SettingsRepository
    evaluations: EvaluationRepository


@dataclass(frozen=True, slots=True)
class SystemPorts:
    """Complete set of infrastructure-facing non-repository ports."""

    model_gateway: ModelGateway
    clock: Clock
    id_generator: IdGenerator
    configuration_loader: ConfigurationLoader
    trace_logger: TraceLogger
    transactions: TransactionBoundary


@dataclass(frozen=True, slots=True)
class DeterministicComponents:
    """Context components invoked abstractly by application services."""

    interpretation_engine: InterpretationEngine
    reference_mention_extractor: ReferenceMentionExtractor
    reference_resolver: ReferenceResolver
    constraint_engine: ConstraintEngine
    clarification_builder: ClarificationBuilder
    context_retriever: ContextRetriever
    response_validator: ResponseValidator
    correction_controller: CorrectionController


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    """All abstract collaborators supplied to application implementations."""

    repositories: RepositoryPorts
    system: SystemPorts
    deterministic: DeterministicComponents


@dataclass(frozen=True, slots=True)
class ApplicationUseCases:
    """All presentation-facing use cases returned by composition."""

    process_user_message: ProcessUserMessage
    inspect_context: InspectContext
    select_project: SelectProject
    apply_conversation_state_transition: ApplyConversationStateTransition
    transition_task_status: TransitionTaskStatus
    archive_project: ArchiveProject
    register_project: RegisterProject
    register_topic: RegisterTopic
    register_task: RegisterTask
    register_named_item: RegisterNamedItem
    create_memory: CreateMemory
    get_memory: GetMemory
    list_memories: ListMemories
    edit_memory: EditMemory
    soft_delete_memory: SoftDeleteMemory
    inspect_validation: InspectValidation
    run_evaluation: RunEvaluation


class CompositionRoot(Protocol):
    """Wire concrete adapters once and return only inward use-case interfaces."""

    def compose(self) -> ApplicationUseCases: ...
