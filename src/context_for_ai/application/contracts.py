"""Typed application use-case inputs, outputs, and invocation protocols."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import Protocol

from context_for_ai.domain.decisions import Constraint, ReferenceOutcome
from context_for_ai.domain.entities import (
    Conversation,
    ConversationState,
    ConversationTask,
    Entity,
    NamedItem,
    Project,
    Topic,
)
from context_for_ai.domain.enums import (
    EntityType,
    EvaluationProviderMode,
    IntentType,
    MemoryEffectiveStatus,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    OutputType,
    ProcessingRunStatus,
    TaskStatus,
)
from context_for_ai.domain.errors import BusyError, LifecycleInvariantError
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
    is_terminal_processing_run,
    memory_effective_status,
)
from context_for_ai.domain.ports.records import (
    ContextPacketRecord,
    EvaluationCase,
    EvaluationRun,
    MemoryRecord,
)
from context_for_ai.domain.value_objects import DomainId, UnitScore, ensure_utc


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _non_negative_integer(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleInvariantError(f"{field_name} must be non-negative.")


@unique
class ProcessResultKind(StrEnum):
    """Canonical top-level result branches for message processing."""

    FINAL = "FINAL"
    EXISTING_RUN = "EXISTING_RUN"
    BUSY = "BUSY"


@dataclass(frozen=True, slots=True)
class ProcessUserMessageInput:
    """One exact UI submission with caller-owned idempotency and project choice."""

    conversation_id: DomainId
    user_text: str
    idempotency_key: DomainId
    project_id: DomainId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.user_text, str):
            raise LifecycleInvariantError(
                "ProcessUserMessageInput.user_text must be exact text."
            )


@dataclass(frozen=True, slots=True)
class ProcessUserMessageOutput:
    """One final, idempotent-existing, or pre-acceptance-busy outcome."""

    result_kind: ProcessResultKind
    processing_run_id: DomainId | None = None
    user_message_id: DomainId | None = None
    processing_status: ProcessingRunStatus | None = None
    active_processing_run_id: DomainId | None = None
    active_processing_status: ProcessingRunStatus | None = None
    busy_error: BusyError | None = None
    assistant_message_id: DomainId | None = None
    assistant_text: str | None = None
    context_packet: ContextPacketRecord | None = None
    validation_result: ValidationResult | None = None
    current_state: ConversationState | None = None
    safe_failure: SafeFailure | None = None
    clarification: ClarificationRequest | None = None

    def __post_init__(self) -> None:
        accepted_fields = (
            self.processing_run_id,
            self.user_message_id,
            self.processing_status,
            self.assistant_message_id,
            self.assistant_text,
            self.context_packet,
            self.validation_result,
            self.current_state,
            self.safe_failure,
            self.clarification,
        )
        if self.result_kind is ProcessResultKind.BUSY:
            if (
                self.active_processing_run_id is None
                or self.active_processing_status is None
                or self.busy_error is None
            ):
                raise LifecycleInvariantError(
                    "BUSY output requires active run ID, status, and BusyError."
                )
            if is_terminal_processing_run(self.active_processing_status):
                raise LifecycleInvariantError(
                    "BUSY output must identify a non-terminal active run."
                )
            if any(value is not None for value in accepted_fields):
                raise LifecycleInvariantError(
                    "BUSY output cannot contain newly accepted-run data."
                )
            return

        if (
            self.active_processing_run_id is not None
            or self.active_processing_status is not None
            or self.busy_error is not None
        ):
            raise LifecycleInvariantError(
                "Only BUSY output may contain active-run rejection data."
            )
        if (
            self.processing_run_id is None
            or self.user_message_id is None
            or self.processing_status is None
            or self.current_state is None
        ):
            raise LifecycleInvariantError(
                "Accepted output requires run, message, status, and current state."
            )
        if self.result_kind is ProcessResultKind.FINAL and not (
            is_terminal_processing_run(self.processing_status)
        ):
            raise LifecycleInvariantError("FINAL output requires a terminal run status.")
        if (self.assistant_message_id is None) != (self.assistant_text is None):
            raise LifecycleInvariantError(
                "Assistant message ID and text must be present together."
            )
        if self.assistant_text is not None and not isinstance(self.assistant_text, str):
            raise LifecycleInvariantError("Assistant output must be text.")
        if self.assistant_message_id is not None and (
            self.processing_status is not ProcessingRunStatus.SUCCEEDED
        ):
            raise LifecycleInvariantError(
                "Only a SUCCEEDED run may expose final assistant text."
            )
        if self.clarification is not None and (
            self.processing_status is not ProcessingRunStatus.NEEDS_CLARIFICATION
        ):
            raise LifecycleInvariantError(
                "Clarification data requires NEEDS_CLARIFICATION status."
            )
        if (
            self.processing_status is ProcessingRunStatus.NEEDS_CLARIFICATION
            and self.clarification is None
        ):
            raise LifecycleInvariantError(
                "NEEDS_CLARIFICATION output requires its persisted request."
            )
        if (
            self.context_packet is not None
            and self.context_packet.packet.processing_run_id != self.processing_run_id
        ):
            raise LifecycleInvariantError(
                "Context packet must belong to the output processing run."
            )
        if (
            self.clarification is not None
            and self.clarification.processing_run_id != self.processing_run_id
        ):
            raise LifecycleInvariantError(
                "Clarification must belong to the output processing run."
            )
        if (
            self.safe_failure is not None
            and self.safe_failure.processing_run_id != self.processing_run_id
        ):
            raise LifecycleInvariantError(
                "Safe failure must belong to the output processing run."
            )


@dataclass(frozen=True, slots=True)
class InspectContextInput:
    """Identify the processing run whose durable context evidence is requested."""

    processing_run_id: DomainId


@dataclass(frozen=True, slots=True)
class InspectContextOutput:
    """Durable context evidence for one run, without storage-layer records."""

    run: ProcessingRun
    packet: ContextPacketRecord | None
    references: tuple[ReferenceOutcome, ...]
    constraints: tuple[Constraint, ...]
    clarification: ClarificationRequest | None
    failures: tuple[SafeFailure, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "failures", tuple(self.failures))
        run_id = self.run.id
        if self.packet is not None and self.packet.packet.processing_run_id != run_id:
            raise LifecycleInvariantError("Inspected packet must belong to the run.")
        if any(reference.processing_run_id != run_id for reference in self.references):
            raise LifecycleInvariantError("Inspected references must belong to the run.")
        if any(constraint.processing_run_id != run_id for constraint in self.constraints):
            raise LifecycleInvariantError("Inspected constraints must belong to the run.")
        if self.clarification is not None and (
            self.clarification.processing_run_id != run_id
        ):
            raise LifecycleInvariantError(
                "Inspected clarification must belong to the run."
            )
        if any(failure.processing_run_id != run_id for failure in self.failures):
            raise LifecycleInvariantError("Inspected failures must belong to the run.")


@dataclass(frozen=True, slots=True)
class SelectProjectInput:
    """Explicitly select an active project, or clear selection, for a conversation."""

    conversation_id: DomainId
    project_id: DomainId | None
    expected_state_version: int

    def __post_init__(self) -> None:
        _non_negative_integer(
            "SelectProjectInput.expected_state_version",
            self.expected_state_version,
        )


@dataclass(frozen=True, slots=True)
class SelectProjectOutput:
    """Updated conversation association and versioned state snapshot."""

    conversation: Conversation
    state: ConversationState

    def __post_init__(self) -> None:
        if self.conversation.id != self.state.conversation_id:
            raise LifecycleInvariantError(
                "Selected-project conversation and state must match."
            )


@dataclass(frozen=True, slots=True)
class PreparedTopicTransition:
    """Canonical topic selection prepared without source-text parsing."""

    topic_id: DomainId
    confidence: UnitScore


@dataclass(frozen=True, slots=True)
class PreparedTaskTransition:
    """Canonical task selection prepared without source-text parsing."""

    task_id: DomainId
    confidence: UnitScore


@dataclass(frozen=True, slots=True)
class PreparedOutputTransition:
    """Canonical intent/output decision prepared by a later interpreter."""

    intent: IntentType
    expected_output_type: OutputType | None
    confidence: UnitScore

    def __post_init__(self) -> None:
        if (
            self.intent
            not in {IntentType.CONTINUE, IntentType.CORRECT, IntentType.UNSUPPORTED}
            and self.expected_output_type is None
        ):
            raise LifecycleInvariantError(
                "A prepared non-control output transition requires an output type."
            )


@dataclass(frozen=True, slots=True)
class ApplyConversationStateTransitionInput:
    """Apply up to one prepared topic, task, and output proposal atomically."""

    conversation_id: DomainId
    expected_state_version: int
    topic: PreparedTopicTransition | None = None
    task: PreparedTaskTransition | None = None
    output: PreparedOutputTransition | None = None

    def __post_init__(self) -> None:
        _non_negative_integer(
            "ApplyConversationStateTransitionInput.expected_state_version",
            self.expected_state_version,
        )
        if (
            self.output is not None
            and self.output.intent in {IntentType.CONTINUE, IntentType.CORRECT}
            and (self.topic is not None or self.task is not None)
        ):
            raise LifecycleInvariantError(
                "CONTINUE and CORRECT cannot carry topic or task proposals."
            )


@dataclass(frozen=True, slots=True)
class ApplyConversationStateTransitionOutput:
    """Resulting state and any task directly selected by the transition."""

    state: ConversationState
    selected_task: ConversationTask | None

    def __post_init__(self) -> None:
        if self.selected_task is not None and (
            self.selected_task.conversation_id != self.state.conversation_id
            or self.selected_task.id != self.state.active_task_id
        ):
            raise LifecycleInvariantError(
                "Selected task must be the resulting state's active task."
            )


@dataclass(frozen=True, slots=True)
class TransitionTaskStatusInput:
    """Apply one explicit named task-status operation."""

    conversation_id: DomainId
    task_id: DomainId
    target_status: TaskStatus
    expected_state_version: int

    def __post_init__(self) -> None:
        _non_negative_integer(
            "TransitionTaskStatusInput.expected_state_version",
            self.expected_state_version,
        )


@dataclass(frozen=True, slots=True)
class TransitionTaskStatusOutput:
    """Updated task and the conversation's resulting state snapshot."""

    task: ConversationTask
    state: ConversationState

    def __post_init__(self) -> None:
        if self.task.conversation_id != self.state.conversation_id:
            raise LifecycleInvariantError(
                "Task-status output task and state must share a conversation."
            )


@dataclass(frozen=True, slots=True)
class ArchiveProjectInput:
    """Name one existing project for explicit archival."""

    project_id: DomainId


@dataclass(frozen=True, slots=True)
class ArchiveProjectOutput:
    """Return the project after its explicit archive transition."""

    project: Project


@dataclass(frozen=True, slots=True)
class RegisterProjectInput:
    """Explicit inputs for one project owner/registry creation."""

    name: str
    description: str | None
    source_message_id: DomainId | None

    def __post_init__(self) -> None:
        _required_text("RegisterProjectInput.name", self.name)
        if self.description is not None and not isinstance(self.description, str):
            raise LifecycleInvariantError(
                "RegisterProjectInput.description must be text or null."
            )


@dataclass(frozen=True, slots=True)
class RegisterProjectOutput:
    project: Project
    entity: Entity

    def __post_init__(self) -> None:
        if (
            self.entity.entity_type is not EntityType.PROJECT
            or self.entity.native_id != self.project.id
            or self.entity.project_id != self.project.id
        ):
            raise LifecycleInvariantError(
                "Registered project output requires its canonical registry identity."
            )


@dataclass(frozen=True, slots=True)
class RegisterTopicInput:
    """Explicit inputs for one conversation topic/registry creation."""

    conversation_id: DomainId
    label: str
    source_message_id: DomainId | None

    def __post_init__(self) -> None:
        _required_text("RegisterTopicInput.label", self.label)


@dataclass(frozen=True, slots=True)
class RegisterTopicOutput:
    topic: Topic
    entity: Entity

    def __post_init__(self) -> None:
        if (
            self.entity.entity_type is not EntityType.TOPIC
            or self.entity.native_id != self.topic.id
        ):
            raise LifecycleInvariantError(
                "Registered topic output requires its canonical registry identity."
            )


@dataclass(frozen=True, slots=True)
class RegisterTaskInput:
    """Explicit inputs for one OPEN conversation task/registry creation."""

    conversation_id: DomainId
    topic_id: DomainId | None
    title: str
    source_message_id: DomainId | None

    def __post_init__(self) -> None:
        _required_text("RegisterTaskInput.title", self.title)


@dataclass(frozen=True, slots=True)
class RegisterTaskOutput:
    task: ConversationTask
    entity: Entity

    def __post_init__(self) -> None:
        if (
            self.entity.entity_type is not EntityType.TASK
            or self.entity.native_id != self.task.id
        ):
            raise LifecycleInvariantError(
                "Registered task output requires its canonical registry identity."
            )


@dataclass(frozen=True, slots=True)
class RegisterNamedItemInput:
    """Exactly one declaration-message or explicit-UI named-item operation."""

    conversation_id: DomainId
    declaration_message_id: DomainId | None
    explicit_ui_label: str | None
    selected_project_id: DomainId | None

    def __post_init__(self) -> None:
        if self.declaration_message_id is not None:
            if self.explicit_ui_label is not None or self.selected_project_id is not None:
                raise LifecycleInvariantError(
                    "Declaration named-item mode cannot include UI label/project inputs."
                )
            return
        if self.explicit_ui_label is None:
            raise LifecycleInvariantError(
                "UI named-item mode requires an explicit label and project selection."
            )
        _required_text("RegisterNamedItemInput.explicit_ui_label", self.explicit_ui_label)


@dataclass(frozen=True, slots=True)
class RegisterNamedItemOutput:
    named_item: NamedItem
    entity: Entity

    def __post_init__(self) -> None:
        if (
            self.entity.entity_type is not EntityType.NAMED_ITEM
            or self.entity.native_id != self.named_item.id
            or self.entity.project_id != self.named_item.project_id
            or self.entity.source_message_id != self.named_item.source_message_id
        ):
            raise LifecycleInvariantError(
                "Registered named-item output requires matching owner/registry identity."
            )


@dataclass(frozen=True, slots=True)
class CreateMemoryInput:
    """User-supplied data for one explicit manual memory creation."""

    conversation_id: DomainId | None
    project_id: DomainId | None
    memory_type: MemoryType
    scope: MemoryScope
    content: str
    keywords: tuple[str, ...]
    topic_terms: tuple[str, ...]
    importance: UnitScore
    confidence: UnitScore
    expires_at: datetime | None
    source_description: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise LifecycleInvariantError("CreateMemoryInput.content must be text.")
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "topic_terms", tuple(self.topic_terms))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", ensure_utc(self.expires_at))
        _required_text("CreateMemoryInput.source_description", self.source_description)


@dataclass(frozen=True, slots=True)
class GetMemoryInput:
    """Identify one memory for explicit inspection."""

    memory_id: DomainId


@dataclass(frozen=True, slots=True)
class ListMemoriesInput:
    """Select memories by stored lifecycle state for explicit inspection."""

    status: MemoryStatus


@dataclass(frozen=True, slots=True)
class EditMemoryInput:
    """Complete user-supplied replacement snapshot for an explicit memory edit."""

    memory_id: DomainId
    content: str
    keywords: tuple[str, ...]
    topic_terms: tuple[str, ...]
    importance: UnitScore
    confidence: UnitScore
    expires_at: datetime | None
    source_description: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise LifecycleInvariantError("EditMemoryInput.content must be text.")
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "topic_terms", tuple(self.topic_terms))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", ensure_utc(self.expires_at))
        _required_text("EditMemoryInput.source_description", self.source_description)


@dataclass(frozen=True, slots=True)
class SoftDeleteMemoryInput:
    """Identify one memory for an explicit provenance-preserving soft deletion."""

    memory_id: DomainId
    source_description: str

    def __post_init__(self) -> None:
        _required_text(
            "SoftDeleteMemoryInput.source_description",
            self.source_description,
        )


@dataclass(frozen=True, slots=True)
class MemoryOutput:
    """One complete memory record evaluated at one explicit clock value."""

    record: MemoryRecord
    evaluated_at: datetime
    effective_status: MemoryEffectiveStatus

    def __post_init__(self) -> None:
        evaluated_at = ensure_utc(self.evaluated_at)
        if self.effective_status is not memory_effective_status(
            self.record.memory,
            evaluated_at,
        ):
            raise LifecycleInvariantError(
                "MemoryOutput.effective_status must match its evaluated memory state."
            )
        object.__setattr__(self, "evaluated_at", evaluated_at)


@dataclass(frozen=True, slots=True)
class MemoryListOutput:
    """Ordered memory outputs sharing one explicit query clock value."""

    records: tuple[MemoryOutput, ...]
    evaluated_at: datetime

    def __post_init__(self) -> None:
        records = tuple(self.records)
        evaluated_at = ensure_utc(self.evaluated_at)
        if any(record.evaluated_at != evaluated_at for record in records):
            raise LifecycleInvariantError(
                "MemoryListOutput records must share its evaluated_at value."
            )
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "evaluated_at", evaluated_at)


@dataclass(frozen=True, slots=True)
class InspectValidationInput:
    """Identify one processing run for validation-lineage inspection."""

    processing_run_id: DomainId


@dataclass(frozen=True, slots=True)
class ValidationAttempt:
    """One persisted candidate, report, and optional revision lineage record."""

    request: ModelRequest
    response: ModelResponse
    result: ValidationResult
    correction: CorrectionAttempt | None

    def __post_init__(self) -> None:
        if self.response.model_request_id != self.request.id:
            raise LifecycleInvariantError("Validation response must match its request.")
        if self.result.model_response_id != self.response.id:
            raise LifecycleInvariantError("Validation result must match its response.")
        if self.correction is not None and (
            self.correction.revised_model_request_id != self.request.id
        ):
            raise LifecycleInvariantError(
                "Correction record must match the revised request."
            )


@dataclass(frozen=True, slots=True)
class InspectValidationOutput:
    """Complete persisted candidate-validation lineage for one processing run."""

    run: ProcessingRun
    attempts: tuple[ValidationAttempt, ...]
    failures: tuple[SafeFailure, ...]

    def __post_init__(self) -> None:
        attempts = tuple(self.attempts)
        failures = tuple(self.failures)
        if any(attempt.request.processing_run_id != self.run.id for attempt in attempts):
            raise LifecycleInvariantError("Validation attempts must belong to the run.")
        if any(failure.processing_run_id != self.run.id for failure in failures):
            raise LifecycleInvariantError("Validation failures must belong to the run.")
        object.__setattr__(self, "attempts", attempts)
        object.__setattr__(self, "failures", failures)


@dataclass(frozen=True, slots=True)
class RunEvaluationInput:
    """Select persisted cases and a provider mode for one evaluation execution."""

    cases: tuple[EvaluationCase, ...]
    fixture_version: str
    provider_mode: EvaluationProviderMode

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        _required_text("RunEvaluationInput.fixture_version", self.fixture_version)


@dataclass(frozen=True, slots=True)
class RunEvaluationOutput:
    """Persisted per-case outcomes; result JSON semantics remain later-task work."""

    runs: tuple[EvaluationRun, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "runs", tuple(self.runs))


class ProcessUserMessage(Protocol):
    """Coordinate one idempotent foreground message submission."""

    def execute(
        self, request: ProcessUserMessageInput
    ) -> ProcessUserMessageOutput: ...


class InspectContext(Protocol):
    """Return durable context evidence for one processing run."""

    def execute(self, request: InspectContextInput) -> InspectContextOutput: ...


class SelectProject(Protocol):
    """Apply one explicit conversation project selection."""

    def execute(self, request: SelectProjectInput) -> SelectProjectOutput: ...


class ApplyConversationStateTransition(Protocol):
    """Apply prepared state proposals without interpreting source text."""

    def execute(
        self, request: ApplyConversationStateTransitionInput
    ) -> ApplyConversationStateTransitionOutput: ...


class TransitionTaskStatus(Protocol):
    """Apply one explicit task-status lifecycle operation."""

    def execute(
        self, request: TransitionTaskStatusInput
    ) -> TransitionTaskStatusOutput: ...


class ArchiveProject(Protocol):
    """Archive one active project under the canonical run guard."""

    def execute(self, request: ArchiveProjectInput) -> ArchiveProjectOutput: ...


class RegisterProject(Protocol):
    """Atomically create one project and its canonical registry row."""

    def execute(self, request: RegisterProjectInput) -> RegisterProjectOutput: ...


class RegisterTopic(Protocol):
    """Atomically create one topic and its canonical registry row."""

    def execute(self, request: RegisterTopicInput) -> RegisterTopicOutput: ...


class RegisterTask(Protocol):
    """Atomically create one task and its canonical registry row."""

    def execute(self, request: RegisterTaskInput) -> RegisterTaskOutput: ...


class RegisterNamedItem(Protocol):
    """Atomically create one explicit named item and its registry row."""

    def execute(
        self,
        request: RegisterNamedItemInput,
    ) -> RegisterNamedItemOutput: ...


class CreateMemory(Protocol):
    """Create one manual memory with provenance and its initial revision."""

    def execute(self, request: CreateMemoryInput) -> MemoryOutput: ...


class GetMemory(Protocol):
    """Retrieve one memory and its complete provenance history."""

    def execute(self, request: GetMemoryInput) -> MemoryOutput: ...


class ListMemories(Protocol):
    """List explicitly inspectable memories by stored lifecycle state."""

    def execute(self, request: ListMemoriesInput) -> MemoryListOutput: ...


class EditMemory(Protocol):
    """Apply one explicit user edit and immutable revision."""

    def execute(self, request: EditMemoryInput) -> MemoryOutput: ...


class SoftDeleteMemory(Protocol):
    """Apply one explicit soft deletion and immutable revision."""

    def execute(self, request: SoftDeleteMemoryInput) -> MemoryOutput: ...


class InspectValidation(Protocol):
    """Return persisted validation and correction lineage for one run."""

    def execute(
        self, request: InspectValidationInput
    ) -> InspectValidationOutput: ...


class RunEvaluation(Protocol):
    """Execute the selected evaluation cases through a configured provider mode."""

    def execute(self, request: RunEvaluationInput) -> RunEvaluationOutput: ...
