"""Typed application use-case inputs, outputs, and invocation protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, unique
from typing import Literal, Protocol

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
    FailureCode,
    IntentType,
    MemoryEffectiveStatus,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    OutputType,
    PipelineStage,
    ProcessingRunStatus,
    TaskStatus,
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
    is_terminal_processing_run,
    memory_effective_status,
)
from context_for_ai.domain.ports.context import (
    ContextPacketBuildRequest,
    ContextPacketBuildResult,
)
from context_for_ai.domain.ports.model_gateway import CancellationToken
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


@dataclass(frozen=True, slots=True)
class ProcessUserMessageRequest:
    """One exact UI submission with caller-owned idempotency and project choice."""

    conversation_id: DomainId
    user_text: str
    idempotency_key: DomainId
    project_id: DomainId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.user_text, str):
            raise LifecycleInvariantError(
                "ProcessUserMessageRequest.user_text must be exact text."
            )


@dataclass(frozen=True, slots=True)
class BusyErrorValue:
    """Closed safe value for global foreground admission rejection."""

    active_processing_run_id: DomainId
    code: Literal["BUSY"] = field(init=False, default="BUSY")
    safe_message: Literal["Another request is already being processed."] = field(
        init=False,
        default="Another request is already being processed.",
    )


@dataclass(frozen=True, slots=True)
class BusyResult:
    """A fresh idempotency key was rejected before acceptance."""

    active_processing_run_id: DomainId
    active_processing_status: ProcessingRunStatus
    error: BusyErrorValue
    result_kind: Literal["BUSY"] = field(init=False, default="BUSY")

    def __post_init__(self) -> None:
        if is_terminal_processing_run(self.active_processing_status):
            raise LifecycleInvariantError(
                "BusyResult must identify a non-terminal active run."
            )
        if self.error.active_processing_run_id != self.active_processing_run_id:
            raise LifecycleInvariantError(
                "BusyResult.error must identify the same active run."
            )


@dataclass(frozen=True, slots=True)
class SucceededResult:
    """A validated candidate was durably linked as the assistant message."""

    processing_run_id: DomainId
    user_message_id: DomainId
    current_state: ConversationState
    context_packet_id: DomainId
    latest_validation_result: ValidationResult
    assistant_message_id: DomainId
    assistant_text: str
    result_kind: Literal["SUCCEEDED"] = field(init=False, default="SUCCEEDED")
    processing_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.SUCCEEDED,
    )

    def __post_init__(self) -> None:
        if self.latest_validation_result.status is not ValidationStatus.PASSED:
            raise LifecycleInvariantError(
                "SucceededResult requires a passed latest validation result."
            )
        if not isinstance(self.assistant_text, str):
            raise LifecycleInvariantError(
                "SucceededResult.assistant_text must be exact text."
            )


@dataclass(frozen=True, slots=True)
class ExistingRunResult:
    """A read-only snapshot reconstructed for an existing idempotency key."""

    processing_run_id: DomainId
    user_message_id: DomainId
    processing_status: ProcessingRunStatus
    current_state: ConversationState
    context_packet_id: DomainId | None
    latest_validation_result: ValidationResult | None
    assistant_message_id: DomainId | None
    assistant_text: str | None
    clarification: ClarificationRequest | None
    safe_failure: SafeFailure | None
    result_kind: Literal["EXISTING_RUN"] = field(
        init=False,
        default="EXISTING_RUN",
    )

    def __post_init__(self) -> None:
        assistant_present = self.assistant_message_id is not None
        if assistant_present != (self.assistant_text is not None):
            raise LifecycleInvariantError(
                "ExistingRunResult assistant ID and text must be present together."
            )
        if self.assistant_text is not None and not isinstance(self.assistant_text, str):
            raise LifecycleInvariantError(
                "ExistingRunResult.assistant_text must be exact text or null."
            )
        if self.processing_status is ProcessingRunStatus.SUCCEEDED:
            if (
                not assistant_present
                or self.context_packet_id is None
                or self.latest_validation_result is None
                or self.latest_validation_result.status is not ValidationStatus.PASSED
                or self.clarification is not None
                or self.safe_failure is not None
            ):
                raise LifecycleInvariantError(
                    "A succeeded existing run requires only its passed assistant lineage."
                )
        elif self.processing_status is ProcessingRunStatus.NEEDS_CLARIFICATION:
            if (
                self.clarification is None
                or assistant_present
                or self.context_packet_id is not None
                or self.latest_validation_result is not None
                or self.safe_failure is not None
            ):
                raise LifecycleInvariantError(
                    "A clarification existing run requires only its clarification."
                )
        elif self.processing_status in {
            ProcessingRunStatus.CONTROLLED_FAILURE,
            ProcessingRunStatus.FAILED,
            ProcessingRunStatus.CANCELLED,
        }:
            if self.safe_failure is None or assistant_present or self.clarification is not None:
                raise LifecycleInvariantError(
                    "A failed existing run requires only its terminal safe failure."
                )
        elif assistant_present or self.clarification is not None or self.safe_failure is not None:
            raise LifecycleInvariantError(
                "A non-terminal existing run cannot expose a terminal payload."
            )
        if self.context_packet_id is None and self.processing_status in {
            ProcessingRunStatus.CONTEXT_READY,
            ProcessingRunStatus.GENERATING,
            ProcessingRunStatus.REVISING,
            ProcessingRunStatus.SUCCEEDED,
        }:
            raise LifecycleInvariantError(
                "This existing run status requires a context packet."
            )
        if self.clarification is not None and (
            self.clarification.processing_run_id != self.processing_run_id
        ):
            raise LifecycleInvariantError(
                "ExistingRunResult clarification must belong to the run."
            )
        if self.safe_failure is not None and (
            self.safe_failure.processing_run_id != self.processing_run_id
            or not self.safe_failure.is_terminal
        ):
            raise LifecycleInvariantError(
                "ExistingRunResult safe failure must be terminal and belong to the run."
            )


@dataclass(frozen=True, slots=True)
class ClarificationResult:
    """The deterministic context decision requires one user clarification."""

    processing_run_id: DomainId
    user_message_id: DomainId
    current_state: ConversationState
    clarification: ClarificationRequest
    result_kind: Literal["CLARIFICATION_REQUIRED"] = field(
        init=False,
        default="CLARIFICATION_REQUIRED",
    )
    processing_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.NEEDS_CLARIFICATION,
    )
    context_packet_id: None = field(init=False, default=None)
    latest_validation_result: None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.clarification.processing_run_id != self.processing_run_id:
            raise LifecycleInvariantError(
                "ClarificationResult clarification must belong to the run."
            )


@unique
class CancellationCheckpoint(StrEnum):
    """The only application/provider cancellation observations exposed publicly."""

    BEFORE_ACCEPTANCE = "BEFORE_ACCEPTANCE"
    AFTER_ACCEPTANCE = "AFTER_ACCEPTANCE"
    CONTEXT_CONSTRUCTION = "CONTEXT_CONSTRUCTION"
    BEFORE_REQUEST_PREPARATION = "BEFORE_REQUEST_PREPARATION"
    GATEWAY = "GATEWAY"


@dataclass(frozen=True, slots=True)
class CancelledResult:
    """A closed pre-acceptance or durably accepted cancellation result."""

    processing_run_id: DomainId | None
    user_message_id: DomainId | None
    processing_status: ProcessingRunStatus | None
    current_state: ConversationState | None
    context_packet_id: DomainId | None
    latest_validation_result: ValidationResult | None
    cancellation_code: FailureCode
    checkpoint: CancellationCheckpoint
    safe_failure: SafeFailure | None
    failure_persisted: bool
    result_kind: Literal["CANCELLED"] = field(init=False, default="CANCELLED")

    def __post_init__(self) -> None:
        if self.cancellation_code not in {
            FailureCode.CANCELLED_BY_USER,
            FailureCode.MODEL_CANCELLED,
        }:
            raise LifecycleInvariantError(
                "CancelledResult requires a canonical cancellation code."
            )
        if not isinstance(self.checkpoint, CancellationCheckpoint) or not isinstance(
            self.failure_persisted, bool
        ):
            raise LifecycleInvariantError(
                "CancelledResult requires a typed checkpoint and persistence flag."
            )
        if self.checkpoint is CancellationCheckpoint.BEFORE_ACCEPTANCE:
            if (
                self.cancellation_code is not FailureCode.CANCELLED_BY_USER
                or self.failure_persisted
                or any(
                    value is not None
                    for value in (
                        self.processing_run_id,
                        self.user_message_id,
                        self.processing_status,
                        self.current_state,
                        self.context_packet_id,
                        self.latest_validation_result,
                        self.safe_failure,
                    )
                )
            ):
                raise LifecycleInvariantError(
                    "Pre-acceptance cancellation cannot contain durable run data."
                )
            return
        if (
            self.processing_run_id is None
            or self.user_message_id is None
            or self.processing_status is not ProcessingRunStatus.CANCELLED
            or self.current_state is None
            or self.safe_failure is None
            or not self.failure_persisted
        ):
            raise LifecycleInvariantError(
                "Accepted cancellation requires durable IDs, state, status, and failure."
            )
        if (
            self.safe_failure.processing_run_id != self.processing_run_id
            or self.safe_failure.error_code is not self.cancellation_code
            or not self.safe_failure.is_terminal
        ):
            raise LifecycleInvariantError(
                "Accepted cancellation failure must match and belong to the run."
            )
        if self.checkpoint is CancellationCheckpoint.GATEWAY:
            if (
                self.cancellation_code is not FailureCode.MODEL_CANCELLED
                or self.context_packet_id is None
            ):
                raise LifecycleInvariantError(
                    "Gateway cancellation requires MODEL_CANCELLED and a packet."
                )
        elif self.cancellation_code is not FailureCode.CANCELLED_BY_USER:
            raise LifecycleInvariantError(
                "Only gateway cancellation may use MODEL_CANCELLED."
            )
        if self.checkpoint in {
            CancellationCheckpoint.AFTER_ACCEPTANCE,
            CancellationCheckpoint.CONTEXT_CONSTRUCTION,
        } and self.context_packet_id is not None:
            raise LifecycleInvariantError(
                "Context-stage cancellation cannot identify a context packet."
            )
        if (
            self.checkpoint is CancellationCheckpoint.BEFORE_REQUEST_PREPARATION
            and self.context_packet_id is None
        ):
            raise LifecycleInvariantError(
                "Request-preparation cancellation requires a context packet."
            )


@dataclass(frozen=True, slots=True)
class ValidationExhaustedErrorValue:
    """Closed public error for bounded correction exhaustion."""

    code: FailureCode = field(init=False, default=FailureCode.VALIDATION_EXHAUSTED)
    safe_message: Literal["The response did not pass validation."] = field(
        init=False,
        default="The response did not pass validation.",
    )


@dataclass(frozen=True, slots=True)
class ValidationExhaustedResult:
    """Every allowed candidate failed deterministic validation."""

    processing_run_id: DomainId
    user_message_id: DomainId
    current_state: ConversationState
    context_packet_id: DomainId
    latest_validation_result: ValidationResult
    error: ValidationExhaustedErrorValue
    safe_failure: SafeFailure
    result_kind: Literal["VALIDATION_EXHAUSTED"] = field(
        init=False,
        default="VALIDATION_EXHAUSTED",
    )
    processing_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.CONTROLLED_FAILURE,
    )

    def __post_init__(self) -> None:
        if self.latest_validation_result.status is not ValidationStatus.FAILED:
            raise LifecycleInvariantError(
                "ValidationExhaustedResult requires a failed latest validation."
            )
        _validate_result_failure(
            self.processing_run_id,
            self.safe_failure,
            FailureCode.VALIDATION_EXHAUSTED,
        )


@dataclass(frozen=True, slots=True)
class ConfigurationErrorValue:
    """Closed safe configuration failure without a configured value."""

    file: str
    key: str
    code: FailureCode = field(init=False, default=FailureCode.CONFIGURATION_INVALID)
    safe_message: Literal["The application configuration is invalid."] = field(
        init=False,
        default="The application configuration is invalid.",
    )

    def __post_init__(self) -> None:
        _required_text("ConfigurationErrorValue.file", self.file)
        _required_text("ConfigurationErrorValue.key", self.key)


@dataclass(frozen=True, slots=True)
class ConfigurationFailureResult:
    """Configuration acquisition failed before any repository access."""

    error: ConfigurationErrorValue
    result_kind: Literal["CONFIGURATION_FAILURE"] = field(
        init=False,
        default="CONFIGURATION_FAILURE",
    )


@dataclass(frozen=True, slots=True)
class PersistenceErrorValue:
    """Closed safe persistence error with only the failed pipeline stage."""

    failed_stage: PipelineStage
    code: FailureCode = field(init=False, default=FailureCode.PERSISTENCE_ERROR)
    safe_message: Literal["Processing could not be saved safely."] = field(
        init=False,
        default="Processing could not be saved safely.",
    )

    def __post_init__(self) -> None:
        if not isinstance(self.failed_stage, PipelineStage):
            raise LifecycleInvariantError(
                "PersistenceErrorValue.failed_stage must be canonical."
            )


@dataclass(frozen=True, slots=True)
class PersistenceFailureResult:
    """A mandatory write rolled back and could not be truthfully claimed."""

    processing_run_id: DomainId | None
    user_message_id: DomainId | None
    processing_status: ProcessingRunStatus | None
    current_state: ConversationState | None
    context_packet_id: DomainId | None
    latest_validation_result: ValidationResult | None
    error: PersistenceErrorValue
    safe_failure: SafeFailure | None
    failure_persisted: bool
    result_kind: Literal["PERSISTENCE_FAILURE"] = field(
        init=False,
        default="PERSISTENCE_FAILURE",
    )

    def __post_init__(self) -> None:
        if not isinstance(self.failure_persisted, bool):
            raise LifecycleInvariantError(
                "PersistenceFailureResult.failure_persisted must be boolean."
            )
        if self.failure_persisted:
            if (
                self.processing_run_id is None
                or self.user_message_id is None
                or self.processing_status is not ProcessingRunStatus.FAILED
                or self.current_state is None
                or self.safe_failure is None
            ):
                raise LifecycleInvariantError(
                    "A persisted persistence failure requires its terminal run snapshot."
                )
            _validate_result_failure(
                self.processing_run_id,
                self.safe_failure,
                FailureCode.PERSISTENCE_ERROR,
            )
            return
        if self.safe_failure is not None:
            raise LifecycleInvariantError(
                "An unpersisted persistence failure cannot expose a SafeFailure."
            )
        has_run = self.processing_run_id is not None
        if has_run:
            if (
                self.user_message_id is None
                or self.processing_status is None
                or self.current_state is None
            ):
                raise LifecycleInvariantError(
                    "An accepted persistence failure requires its last durable snapshot."
                )
        elif any(
            value is not None
            for value in (
                self.user_message_id,
                self.processing_status,
                self.current_state,
                self.context_packet_id,
                self.latest_validation_result,
            )
        ):
            raise LifecycleInvariantError(
                "A pre-acceptance persistence failure cannot contain run data."
            )


@dataclass(frozen=True, slots=True)
class ConcurrencyConflictErrorValue:
    """Closed safe error for the second context state CAS conflict."""

    code: FailureCode = field(init=False, default=FailureCode.CONCURRENCY_CONFLICT)
    safe_message: Literal[
        "The conversation changed while context was being prepared."
    ] = field(
        init=False,
        default="The conversation changed while context was being prepared.",
    )


@dataclass(frozen=True, slots=True)
class ConcurrencyConflictResult:
    """The one permitted context recomputation also lost its state CAS."""

    processing_run_id: DomainId
    user_message_id: DomainId
    current_state: ConversationState
    error: ConcurrencyConflictErrorValue
    safe_failure: SafeFailure
    result_kind: Literal["CONCURRENCY_CONFLICT"] = field(
        init=False,
        default="CONCURRENCY_CONFLICT",
    )
    processing_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.FAILED,
    )
    context_packet_id: None = field(init=False, default=None)
    latest_validation_result: None = field(init=False, default=None)

    def __post_init__(self) -> None:
        _validate_result_failure(
            self.processing_run_id,
            self.safe_failure,
            FailureCode.CONCURRENCY_CONFLICT,
        )


_CONTROLLED_FAILURE_CODES = frozenset(
    {
        FailureCode.CONTEXT_BUDGET_EXCEEDED,
        FailureCode.CONTEXT_CONSTRUCTION_FAILED,
        FailureCode.CONFIGURATION_CHANGED,
        FailureCode.PROCESS_RESTARTED,
        FailureCode.PERSISTENCE_ERROR,
        FailureCode.PROVIDER_UNAVAILABLE,
        FailureCode.MODEL_NOT_FOUND,
        FailureCode.MODEL_TIMEOUT,
        FailureCode.INVALID_PROVIDER_RESPONSE,
    }
)


@dataclass(frozen=True, slots=True)
class ControlledFailureError:
    """Closed public projection of one canonical controlled safe failure."""

    code: FailureCode
    safe_message: str

    def __post_init__(self) -> None:
        if self.code not in _CONTROLLED_FAILURE_CODES:
            raise LifecycleInvariantError(
                "ControlledFailureError.code is not in the closed result family."
            )
        _required_text("ControlledFailureError.safe_message", self.safe_message)


@dataclass(frozen=True, slots=True)
class ControlledFailureResult:
    """A durably terminalized non-validation operational failure."""

    processing_run_id: DomainId
    user_message_id: DomainId
    processing_status: ProcessingRunStatus
    current_state: ConversationState
    context_packet_id: DomainId | None
    latest_validation_result: ValidationResult | None
    error: ControlledFailureError
    safe_failure: SafeFailure
    result_kind: Literal["CONTROLLED_FAILURE"] = field(
        init=False,
        default="CONTROLLED_FAILURE",
    )

    def __post_init__(self) -> None:
        if self.processing_status not in {
            ProcessingRunStatus.CONTROLLED_FAILURE,
            ProcessingRunStatus.FAILED,
        }:
            raise LifecycleInvariantError(
                "ControlledFailureResult requires CONTROLLED_FAILURE or FAILED status."
            )
        _validate_result_failure(
            self.processing_run_id,
            self.safe_failure,
            self.error.code,
        )
        if self.error.safe_message != self.safe_failure.safe_message:
            raise LifecycleInvariantError(
                "ControlledFailureResult error must match its SafeFailure."
            )


def _validate_result_failure(
    processing_run_id: DomainId,
    failure: SafeFailure,
    expected_code: FailureCode,
) -> None:
    if (
        failure.processing_run_id != processing_run_id
        or failure.error_code is not expected_code
        or not failure.is_terminal
    ):
        raise LifecycleInvariantError(
            "Result SafeFailure must be terminal, match its code, and belong to the run."
        )


type ProcessUserMessageResult = (
    SucceededResult
    | ExistingRunResult
    | BusyResult
    | ClarificationResult
    | CancelledResult
    | ValidationExhaustedResult
    | ConfigurationFailureResult
    | PersistenceFailureResult
    | ConcurrencyConflictResult
    | ControlledFailureResult
)


@dataclass(frozen=True, slots=True)
class RecoverProcessingRunRequest:
    """Deliberately empty request selecting only the global active run."""


@dataclass(frozen=True, slots=True)
class NoRecoveryRequiredResult:
    """No global non-terminal processing run exists."""

    result_kind: Literal["NO_RECOVERY_REQUIRED"] = field(
        init=False,
        default="NO_RECOVERY_REQUIRED",
    )


type RecoveredTerminalOutcome = (
    SucceededResult
    | ClarificationResult
    | CancelledResult
    | ValidationExhaustedResult
    | ConcurrencyConflictResult
    | ControlledFailureResult
)


@dataclass(frozen=True, slots=True)
class RecoveryCompletedResult:
    """One active run was resumed or safely terminalized."""

    processing_run_id: DomainId
    outcome: RecoveredTerminalOutcome
    result_kind: Literal["RECOVERY_COMPLETED"] = field(
        init=False,
        default="RECOVERY_COMPLETED",
    )

    def __post_init__(self) -> None:
        if self.outcome.processing_run_id != self.processing_run_id:
            raise LifecycleInvariantError(
                "RecoveryCompletedResult outcome must identify the recovered run."
            )
        if (
            isinstance(self.outcome, CancelledResult)
            and self.outcome.checkpoint is CancellationCheckpoint.BEFORE_ACCEPTANCE
        ):
            raise LifecycleInvariantError(
                "Recovery cannot produce pre-acceptance cancellation."
            )


type RecoveryResult = (
    NoRecoveryRequiredResult
    | RecoveryCompletedResult
    | ConfigurationFailureResult
    | PersistenceFailureResult
)


@dataclass(frozen=True, slots=True)
class PrepareApplicationShellRequest:
    """Request one pre-QML recovery preflight and conversation selection."""


@dataclass(frozen=True, slots=True)
class ShellReadyResult:
    """A usable conversation is ready and no startup recovery is required."""

    conversation_id: DomainId
    initial_conversation_created: bool
    result_kind: Literal["SHELL_READY"] = field(
        init=False,
        default="SHELL_READY",
    )

    def __post_init__(self) -> None:
        if not isinstance(self.initial_conversation_created, bool):
            raise LifecycleInvariantError(
                "ShellReadyResult.initial_conversation_created must be boolean."
            )


@dataclass(frozen=True, slots=True)
class RecoveryRequiredResult:
    """The sole global non-terminal run requires one foreground recovery."""

    processing_run_id: DomainId
    conversation_id: DomainId
    result_kind: Literal["RECOVERY_REQUIRED"] = field(
        init=False,
        default="RECOVERY_REQUIRED",
    )


@unique
class ShellPreparationFailureKind(StrEnum):
    """Closed preparation stages that may fail before Qt is created."""

    RECOVERY_PREFLIGHT_FAILED = "RECOVERY_PREFLIGHT_FAILED"
    CONVERSATION_SETUP_FAILED = "CONVERSATION_SETUP_FAILED"


_SHELL_PREPARATION_FAILURE_MESSAGES = {
    ShellPreparationFailureKind.RECOVERY_PREFLIGHT_FAILED: (
        "Previous processing state could not be inspected safely."
    ),
    ShellPreparationFailureKind.CONVERSATION_SETUP_FAILED: (
        "A conversation could not be opened safely."
    ),
}


@dataclass(frozen=True, slots=True)
class ShellPreparationFailureResult:
    """A closed content-free persistence failure during shell preparation."""

    failure_kind: ShellPreparationFailureKind
    result_kind: Literal["SHELL_PREPARATION_FAILURE"] = field(
        init=False,
        default="SHELL_PREPARATION_FAILURE",
    )
    code: FailureCode = field(
        init=False,
        default=FailureCode.PERSISTENCE_ERROR,
    )
    safe_message: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.failure_kind, ShellPreparationFailureKind):
            raise LifecycleInvariantError(
                "ShellPreparationFailureResult requires a closed failure kind."
            )
        object.__setattr__(
            self,
            "safe_message",
            _SHELL_PREPARATION_FAILURE_MESSAGES[self.failure_kind],
        )


type PrepareApplicationShellResult = (
    ShellReadyResult | RecoveryRequiredResult | ShellPreparationFailureResult
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
        self,
        request: ProcessUserMessageRequest,
        cancellation_token: CancellationToken,
    ) -> ProcessUserMessageResult: ...


class RecoverProcessingRun(Protocol):
    """Resume or safely terminalize the one global non-terminal run."""

    def execute(
        self,
        request: RecoverProcessingRunRequest,
        cancellation_token: CancellationToken,
    ) -> RecoveryResult: ...


class PrepareApplicationShell(Protocol):
    """Prepare one safe initial shell selection before Qt creation."""

    def execute(
        self,
        request: PrepareApplicationShellRequest,
    ) -> PrepareApplicationShellResult: ...


class StartupApplicationScope(Protocol):
    """Own the startup connection and its sole preparation use case."""

    prepare_application_shell: PrepareApplicationShell

    def close(self) -> None: ...


class ForegroundApplicationScope(Protocol):
    """Own one worker-thread connection and the TASK-0014 foreground use cases."""

    process_user_message: ProcessUserMessage
    recover_processing_run: RecoverProcessingRun

    def close(self) -> None: ...


class ShellApplicationScopeFactory(Protocol):
    """Create fresh calling-thread-owned startup and foreground scopes."""

    def open_startup_scope(self) -> StartupApplicationScope: ...

    def open_foreground_scope(self) -> ForegroundApplicationScope: ...


class IdempotencyKeyFactory(Protocol):
    """Allocate one caller-owned UUID for each accepted shell submission."""

    def new_key(self) -> DomainId: ...


class InspectContext(Protocol):
    """Return durable context evidence for one processing run."""

    def execute(self, request: InspectContextInput) -> InspectContextOutput: ...


class ContextPacketStage(Protocol):
    """Persist one packet outcome and its processing-run transition atomically."""

    def execute(
        self, request: ContextPacketBuildRequest
    ) -> ContextPacketBuildResult: ...


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
