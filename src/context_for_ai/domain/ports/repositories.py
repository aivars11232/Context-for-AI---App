"""Inward repository protocols for canonical domain and lifecycle records."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from context_for_ai.domain.decisions import Constraint, ReferenceOutcome
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
from context_for_ai.domain.enums import MemoryStatus, ProjectStatus
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
    CorrectionAttempt,
    ModelRequest,
    ModelResponse,
    ProcessingRun,
    SafeFailure,
    ValidationResult,
)
from context_for_ai.domain.ports.records import (
    ContextPacketRecord,
    EvaluationCase,
    EvaluationRun,
    MemoryRecord,
    Setting,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonValue


class ProjectRepository(Protocol):
    """Persist and retrieve projects without exposing storage mechanics."""

    def add(self, project: Project) -> None: ...

    def get(self, project_id: DomainId) -> Project | None: ...

    def list_by_status(self, status: ProjectStatus) -> tuple[Project, ...]: ...

    def update(self, project: Project) -> None: ...


class ConversationRepository(Protocol):
    """Persist conversations and their sole active-project association."""

    def add(self, conversation: Conversation) -> None: ...

    def get(self, conversation_id: DomainId) -> Conversation | None: ...

    def list_for_project(
        self, project_id: DomainId | None
    ) -> tuple[Conversation, ...]: ...

    def update(self, conversation: Conversation) -> None: ...


class TopicRepository(Protocol):
    """Persist explicit conversation topics."""

    def add(self, topic: Topic) -> None: ...

    def get(self, topic_id: DomainId) -> Topic | None: ...

    def get_by_normalized_label(
        self, conversation_id: DomainId, normalized_label: str
    ) -> Topic | None: ...

    def list_for_conversation(
        self, conversation_id: DomainId
    ) -> tuple[Topic, ...]: ...

    def update(self, topic: Topic) -> None: ...


class TaskRepository(Protocol):
    """Persist explicit conversation-task lifecycle records."""

    def add(self, task: ConversationTask) -> None: ...

    def get(self, task_id: DomainId) -> ConversationTask | None: ...

    def list_for_conversation(
        self, conversation_id: DomainId
    ) -> tuple[ConversationTask, ...]: ...

    def update(self, task: ConversationTask) -> None: ...


class ConversationStateRepository(Protocol):
    """Persist versioned conversation state using compare-and-swap."""

    def add(self, state: ConversationState) -> None: ...

    def get(self, conversation_id: DomainId) -> ConversationState | None: ...

    def compare_and_swap(
        self, *, expected_version: int, state: ConversationState
    ) -> bool: ...


class MessageRepository(Protocol):
    """Append and retrieve immutable conversation messages."""

    def add(self, message: Message) -> None: ...

    def get(self, message_id: DomainId) -> Message | None: ...

    def list_for_conversation(
        self, conversation_id: DomainId, *, limit: int | None = None
    ) -> tuple[Message, ...]: ...

    def next_sequence_number(self, conversation_id: DomainId) -> int: ...


class EntityRepository(Protocol):
    """Persist the entity registry and explicit named-item records."""

    def add(self, entity: Entity) -> None: ...

    def add_named_item(self, named_item: NamedItem, entity: Entity) -> None: ...

    def update_named_item(self, named_item: NamedItem, entity: Entity) -> None: ...

    def get(self, entity_id: DomainId) -> Entity | None: ...

    def get_named_item(self, named_item_id: DomainId) -> NamedItem | None: ...

    def list_reference_candidates(
        self, *, conversation_id: DomainId, project_id: DomainId | None
    ) -> tuple[Entity, ...]:
        """Return all in-scope active and inactive registry candidates."""
        ...

    def update(self, entity: Entity) -> None: ...


class ReferenceResolutionRepository(Protocol):
    """Persist every resolved, ambiguous, and unresolved reference outcome."""

    def add_all(self, outcomes: tuple[ReferenceOutcome, ...]) -> None: ...

    def list_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[ReferenceOutcome, ...]: ...

    def list_resolved_for_messages(
        self,
        message_ids: tuple[DomainId, ...],
    ) -> tuple[ReferenceOutcome, ...]: ...


class ConstraintRepository(Protocol):
    """Persist canonical constraints and their resolution status."""

    def add_all(self, constraints: tuple[Constraint, ...]) -> None: ...

    def list_for_run(self, processing_run_id: DomainId) -> tuple[Constraint, ...]: ...


class MemoryRepository(Protocol):
    """Persist manual memories with source and revision lineage."""

    def add(
        self,
        memory: Memory,
        source: MemorySource,
        revision: MemoryRevision,
    ) -> None: ...

    def get(self, memory_id: DomainId) -> MemoryRecord | None: ...

    def list_by_status(self, status: MemoryStatus) -> tuple[MemoryRecord, ...]: ...

    def list_retrieval_candidates(self) -> tuple[MemoryRecord, ...]:
        """Return the complete considered set; the retriever owns eligibility."""
        ...

    def update_with_revision(
        self,
        memory: Memory,
        source: MemorySource,
        revision: MemoryRevision,
    ) -> None: ...


class ProcessingRunRepository(Protocol):
    """Persist idempotent processing runs and their lifecycle state."""

    def add(self, run: ProcessingRun) -> None: ...

    def get(self, processing_run_id: DomainId) -> ProcessingRun | None: ...

    def get_by_idempotency_key(
        self, *, conversation_id: DomainId, idempotency_key: DomainId
    ) -> ProcessingRun | None: ...

    def get_non_terminal(self) -> ProcessingRun | None: ...

    def update(self, run: ProcessingRun) -> None: ...


class ContextPacketRepository(Protocol):
    """Persist immutable packets and complete retrieval audit evidence."""

    def add(self, record: ContextPacketRecord) -> None: ...

    def get(self, context_packet_id: DomainId) -> ContextPacketRecord | None: ...

    def get_for_run(
        self, processing_run_id: DomainId
    ) -> ContextPacketRecord | None: ...


class ModelCallRepository(Protocol):
    """Persist request, response, correction, and safe-failure lineage."""

    def add_request(self, request: ModelRequest) -> None: ...

    def get_request(self, request_id: DomainId) -> ModelRequest | None: ...

    def list_requests_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[ModelRequest, ...]: ...

    def update_request(self, request: ModelRequest) -> None: ...

    def add_response(self, response: ModelResponse) -> None: ...

    def get_response(self, response_id: DomainId) -> ModelResponse | None: ...

    def get_response_for_request(
        self, model_request_id: DomainId
    ) -> ModelResponse | None: ...

    def link_assistant_message(
        self, *, model_response_id: DomainId, assistant_message_id: DomainId
    ) -> None: ...

    def add_correction(self, correction: CorrectionAttempt) -> None: ...

    def list_corrections_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[CorrectionAttempt, ...]: ...

    def add_failure(self, failure: SafeFailure) -> None: ...

    def list_failures_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[SafeFailure, ...]: ...


class ValidationRepository(Protocol):
    """Persist one deterministic validation result per model response."""

    def add(self, result: ValidationResult) -> None: ...

    def get(self, validation_result_id: DomainId) -> ValidationResult | None: ...

    def get_for_response(
        self, model_response_id: DomainId
    ) -> ValidationResult | None: ...

    def list_for_run(
        self, processing_run_id: DomainId
    ) -> tuple[ValidationResult, ...]: ...


class ClarificationRepository(Protocol):
    """Persist and retrieve the sole deterministic clarification for a run."""

    def add(self, clarification: ClarificationRequest) -> None: ...

    def get_for_run(
        self, processing_run_id: DomainId
    ) -> ClarificationRequest | None: ...


class SettingsRepository(Protocol):
    """Persist only the approved non-secret presentation settings."""

    def get(self, key: str) -> Setting | None: ...

    def list_all(self) -> tuple[Setting, ...]: ...

    def set(self, *, key: str, value: FrozenJsonValue, updated_at: datetime) -> Setting: ...


class EvaluationRepository(Protocol):
    """Persist opaque evaluation cases and runs without defining later JSON shapes."""

    def add_case(self, case: EvaluationCase) -> None: ...

    def get_case(self, evaluation_case_id: DomainId) -> EvaluationCase | None: ...

    def list_cases(self, *, enabled_only: bool = False) -> tuple[EvaluationCase, ...]: ...

    def add_run(self, run: EvaluationRun) -> None: ...

    def list_runs_for_case(
        self, evaluation_case_id: DomainId
    ) -> tuple[EvaluationRun, ...]: ...
