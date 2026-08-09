"""Typed application use-case inputs, outputs, and invocation protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from enum import StrEnum, unique
from typing import Literal, Protocol

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
from context_for_ai.domain.ports.configuration import ConfigurationOrigin
from context_for_ai.domain.ports.model_gateway import CancellationToken
from context_for_ai.domain.ports.records import (
    EvaluationCase,
    EvaluationRun,
    MemoryRecord,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    UnitScore,
    canonical_decimal_string,
    ensure_utc,
)


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


@unique
class InspectionAvailability(StrEnum):
    """Closed evidence availability vocabulary for context inspection."""

    AVAILABLE = "AVAILABLE"
    EMPTY = "EMPTY"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNAVAILABLE = "UNAVAILABLE"


@unique
class InspectionRunOutcome(StrEnum):
    """Safe historical processing outcome exposed by context inspection."""

    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    CLARIFICATION = "CLARIFICATION"
    CONTROLLED_FAILURE = "CONTROLLED_FAILURE"
    CANCELLED = "CANCELLED"


@unique
class InspectionCheckpoint(StrEnum):
    """Checkpoint derived only from committed inspection artifacts."""

    ACCEPTED = "ACCEPTED"
    CONTEXT_COMMITTED = "CONTEXT_COMMITTED"
    VALIDATION_COMMITTED = "VALIDATION_COMMITTED"
    CLARIFICATION_COMMITTED = "CLARIFICATION_COMMITTED"
    TERMINAL_WITHOUT_CONTEXT = "TERMINAL_WITHOUT_CONTEXT"


@unique
class ActiveStateKind(StrEnum):
    """Closed active-state owner kinds visible on the inspection page."""

    PROJECT = "PROJECT"
    TOPIC = "TOPIC"
    TASK = "TASK"


@unique
class SafeTerminalKind(StrEnum):
    """Terminal outcome kinds safe for historical inspection."""

    CONTROLLED_FAILURE = "CONTROLLED_FAILURE"
    CANCELLED = "CANCELLED"


_INSPECTION_EMPTY_TEXT = "None recorded."
_INSPECTION_NOT_APPLICABLE_TEXT = "Not applicable."
_INSPECTION_UNAVAILABLE_TEXT = "Unavailable for this run."
_ACTIVE_NULL_TEXTS = {
    "No active project.",
    "No active topic.",
    "No active task.",
}


def _positive_integer(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleInvariantError(f"{field_name} must be a positive integer.")


def _canonical_inspection_label(code: str) -> str:
    _required_text("CanonicalLabelView.code", code)
    words = code.split("_")
    if any(not word for word in words):
        raise LifecycleInvariantError(
            "CanonicalLabelView.code must contain non-empty underscore-separated words."
        )
    rendered = " ".join(word.lower() for word in words)
    return rendered[0].upper() + rendered[1:]


@dataclass(frozen=True, slots=True)
class CanonicalLabelView:
    """One canonical enum code and its deterministic application-owned label."""

    code: str
    display_label: str

    def __post_init__(self) -> None:
        expected = _canonical_inspection_label(self.code)
        if self.display_label != expected:
            raise LifecycleInvariantError(
                "CanonicalLabelView.display_label must match its canonical code."
            )


@dataclass(frozen=True, slots=True)
class InspectionScoreView:
    """Canonical unrounded score text and fixed two-decimal display text."""

    canonical_decimal: str
    display_text: str

    def __post_init__(self) -> None:
        try:
            value = Decimal(self.canonical_decimal)
        except (InvalidOperation, TypeError, ValueError) as error:
            raise LifecycleInvariantError(
                "InspectionScoreView requires a canonical finite decimal score."
            ) from error
        if (
            not value.is_finite()
            or value < Decimal(0)
            or value > Decimal(1)
            or canonical_decimal_string(value) != self.canonical_decimal
        ):
            raise LifecycleInvariantError(
                "InspectionScoreView.canonical_decimal must be canonical and in [0,1]."
            )
        expected_display = format(
            value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
            ".2f",
        )
        if self.display_text != expected_display:
            raise LifecycleInvariantError(
                "InspectionScoreView.display_text must use two-decimal half-even formatting."
            )


@dataclass(frozen=True, slots=True)
class InspectionValue[T]:
    """One available or explicitly unavailable safe scalar value."""

    availability: InspectionAvailability
    value: T | None
    display_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.availability, InspectionAvailability):
            raise LifecycleInvariantError(
                "InspectionValue requires a closed inspection availability."
            )
        if self.availability is InspectionAvailability.EMPTY:
            raise LifecycleInvariantError("InspectionValue cannot use EMPTY availability.")
        if self.availability is InspectionAvailability.AVAILABLE:
            if self.value is None or not isinstance(self.display_text, str) or not self.display_text:
                raise LifecycleInvariantError(
                    "An available InspectionValue requires a value and display text."
                )
            return
        if self.value is not None:
            raise LifecycleInvariantError(
                "A non-available InspectionValue cannot retain a value."
            )
        if self.availability is InspectionAvailability.NOT_APPLICABLE:
            if self.display_text not in {
                _INSPECTION_NOT_APPLICABLE_TEXT,
                *_ACTIVE_NULL_TEXTS,
            }:
                raise LifecycleInvariantError(
                    "A not-applicable InspectionValue requires contracted display text."
                )
        elif self.display_text != _INSPECTION_UNAVAILABLE_TEXT:
            raise LifecycleInvariantError(
                "An unavailable InspectionValue requires contracted display text."
            )


@dataclass(frozen=True, slots=True)
class InspectionCollection[T]:
    """One immutable collection with explicit evidence availability."""

    availability: InspectionAvailability
    items: tuple[T, ...]
    display_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.availability, InspectionAvailability):
            raise LifecycleInvariantError(
                "InspectionCollection requires a closed inspection availability."
            )
        items = tuple(self.items)
        object.__setattr__(self, "items", items)
        if self.availability is InspectionAvailability.AVAILABLE:
            if not items or self.display_text != "":
                raise LifecycleInvariantError(
                    "An available InspectionCollection requires items and empty display text."
                )
            return
        if items:
            raise LifecycleInvariantError(
                "A non-available InspectionCollection cannot retain items."
            )
        expected = {
            InspectionAvailability.EMPTY: _INSPECTION_EMPTY_TEXT,
            InspectionAvailability.NOT_APPLICABLE: _INSPECTION_NOT_APPLICABLE_TEXT,
            InspectionAvailability.UNAVAILABLE: _INSPECTION_UNAVAILABLE_TEXT,
        }[self.availability]
        if self.display_text != expected:
            raise LifecycleInvariantError(
                "InspectionCollection requires its contracted availability text."
            )


@dataclass(frozen=True, slots=True)
class InspectionTargetView:
    """Safe display identity and durable state of the selected historical run."""

    user_message_sequence: int
    request_label: str
    outcome: InspectionRunOutcome
    checkpoint: InspectionCheckpoint
    outcome_label: str
    checkpoint_label: str

    def __post_init__(self) -> None:
        _non_negative_integer(
            "InspectionTargetView.user_message_sequence",
            self.user_message_sequence,
        )
        if self.request_label != f"Request {self.user_message_sequence}":
            raise LifecycleInvariantError(
                "InspectionTargetView.request_label must use the safe request sequence."
            )
        if not isinstance(self.outcome, InspectionRunOutcome) or not isinstance(
            self.checkpoint,
            InspectionCheckpoint,
        ):
            raise LifecycleInvariantError(
                "InspectionTargetView requires closed outcome and checkpoint values."
            )
        if self.outcome_label != _canonical_inspection_label(self.outcome.value):
            raise LifecycleInvariantError(
                "InspectionTargetView.outcome_label must match its outcome."
            )
        if self.checkpoint_label != _canonical_inspection_label(self.checkpoint.value):
            raise LifecycleInvariantError(
                "InspectionTargetView.checkpoint_label must match its checkpoint."
            )


@dataclass(frozen=True, slots=True)
class ActiveStateItemView:
    """Readable current label for one packet-snapshotted active owner ID."""

    kind: ActiveStateKind
    display_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ActiveStateKind):
            raise LifecycleInvariantError("ActiveStateItemView requires a closed kind.")
        _required_text("ActiveStateItemView.display_name", self.display_name)


@dataclass(frozen=True, slots=True)
class QualifierEvidenceView:
    """One ordered safe qualifier rule/source observation."""

    ordinal: int
    kind: CanonicalLabelView
    rule_id: str
    matched_text: str

    def __post_init__(self) -> None:
        _positive_integer("QualifierEvidenceView.ordinal", self.ordinal)
        _required_text("QualifierEvidenceView.rule_id", self.rule_id)
        _required_text("QualifierEvidenceView.matched_text", self.matched_text)


@dataclass(frozen=True, slots=True)
class ReferenceMessageSourceView:
    """Safe message-sequence identity for reference source evidence."""

    message_sequence: int
    display_text: str

    def __post_init__(self) -> None:
        _non_negative_integer(
            "ReferenceMessageSourceView.message_sequence",
            self.message_sequence,
        )
        if self.display_text != f"Message {self.message_sequence}":
            raise LifecycleInvariantError(
                "ReferenceMessageSourceView.display_text must use its message sequence."
            )


@dataclass(frozen=True, slots=True)
class ReferenceEvidenceView:
    """One ordered, redacted reference-candidate evidence record."""

    rank: int
    candidate_display_name: str | None
    candidate_type: CanonicalLabelView | None
    score: InspectionScoreView
    rank_reason: CanonicalLabelView
    evidence_message: ReferenceMessageSourceView | None
    is_active: bool | None
    activity_display_text: Literal["Active", "Inactive"] | None

    def __post_init__(self) -> None:
        _positive_integer("ReferenceEvidenceView.rank", self.rank)
        if self.candidate_display_name is not None:
            _required_text(
                "ReferenceEvidenceView.candidate_display_name",
                self.candidate_display_name,
            )
        if (self.is_active is None) != (self.activity_display_text is None):
            raise LifecycleInvariantError(
                "ReferenceEvidenceView activity value and text must be present together."
            )
        if self.is_active is not None:
            if not isinstance(self.is_active, bool):
                raise LifecycleInvariantError(
                    "ReferenceEvidenceView.is_active must be boolean or null."
                )
            expected = "Active" if self.is_active else "Inactive"
            if self.activity_display_text != expected:
                raise LifecycleInvariantError(
                    "ReferenceEvidenceView activity text must match its boolean."
                )


@dataclass(frozen=True, slots=True)
class ReferenceInspectionView:
    """One ordered reference outcome with only allowlisted safe evidence."""

    mention_number: int
    surface_text: str
    status: CanonicalLabelView
    resolved_display_name: InspectionValue[str]
    source_message: InspectionValue[ReferenceMessageSourceView]
    confidence: InspectionScoreView
    evidence: tuple[ReferenceEvidenceView, ...]

    def __post_init__(self) -> None:
        _positive_integer("ReferenceInspectionView.mention_number", self.mention_number)
        _required_text("ReferenceInspectionView.surface_text", self.surface_text)
        evidence = tuple(self.evidence)
        if not evidence:
            raise LifecycleInvariantError(
                "ReferenceInspectionView requires persisted candidate evidence."
            )
        object.__setattr__(self, "evidence", evidence)


@dataclass(frozen=True, slots=True)
class ConstraintConditionView:
    """Safe closed projection of one persisted conditional predicate."""

    grammar_version: str
    kind: CanonicalLabelView
    expected_value: str
    evaluation: CanonicalLabelView

    def __post_init__(self) -> None:
        _required_text("ConstraintConditionView.grammar_version", self.grammar_version)
        _required_text("ConstraintConditionView.expected_value", self.expected_value)


@dataclass(frozen=True, slots=True)
class ConstraintInspectionView:
    """One ordered persisted constraint and its safe source evidence."""

    ordinal: int
    type: CanonicalLabelView
    underlying_type: CanonicalLabelView | None
    scope: CanonicalLabelView
    normalized_rule: str
    priority: int
    source_kind: CanonicalLabelView
    source_text: str
    confidence: InspectionScoreView
    resolution_status: CanonicalLabelView
    condition: ConstraintConditionView | None

    def __post_init__(self) -> None:
        _positive_integer("ConstraintInspectionView.ordinal", self.ordinal)
        _non_negative_integer("ConstraintInspectionView.priority", self.priority)
        _required_text("ConstraintInspectionView.normalized_rule", self.normalized_rule)
        _required_text("ConstraintInspectionView.source_text", self.source_text)


@dataclass(frozen=True, slots=True)
class ConflictRuleView:
    """One safe constraint member of a persisted hard-conflict group."""

    constraint_ordinal: int
    type: CanonicalLabelView
    normalized_rule: str
    source_text: str

    def __post_init__(self) -> None:
        _positive_integer("ConflictRuleView.constraint_ordinal", self.constraint_ordinal)
        _required_text("ConflictRuleView.normalized_rule", self.normalized_rule)
        _required_text("ConflictRuleView.source_text", self.source_text)


@dataclass(frozen=True, slots=True)
class ConflictInspectionView:
    """One ordered persisted conflict group with hidden group identity."""

    ordinal: int
    rules: tuple[ConflictRuleView, ...]

    def __post_init__(self) -> None:
        _positive_integer("ConflictInspectionView.ordinal", self.ordinal)
        rules = tuple(self.rules)
        if len(rules) < 2:
            raise LifecycleInvariantError(
                "ConflictInspectionView requires at least two persisted rules."
            )
        object.__setattr__(self, "rules", rules)


@dataclass(frozen=True, slots=True)
class RetrievedMemoryInspectionView:
    """One selected immutable packet memory snapshot and retrieval evidence."""

    rank: int
    content: str
    scope: CanonicalLabelView
    memory_confidence: InspectionScoreView
    retrieval_score: InspectionScoreView
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _positive_integer("RetrievedMemoryInspectionView.rank", self.rank)
        if not isinstance(self.content, str):
            raise LifecycleInvariantError(
                "RetrievedMemoryInspectionView.content must be exact text."
            )
        reasons = tuple(self.reasons)
        if len(reasons) != 7:
            raise LifecycleInvariantError(
                "RetrievedMemoryInspectionView requires exactly seven reasons."
            )
        for reason in reasons:
            _required_text("RetrievedMemoryInspectionView.reason", reason)
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class ConfidenceInspectionView:
    """Overall confidence and its persisted component evidence."""

    overall: InspectionScoreView
    interpretation: InspectionScoreView
    references: InspectionValue[InspectionScoreView]
    retrieval: InspectionValue[InspectionScoreView]


@dataclass(frozen=True, slots=True)
class SafeValidationViolationView:
    """One ordered canonical safe validation violation."""

    ordinal: int
    code: CanonicalLabelView
    message: str

    def __post_init__(self) -> None:
        _positive_integer("SafeValidationViolationView.ordinal", self.ordinal)
        _required_text("SafeValidationViolationView.message", self.message)


@dataclass(frozen=True, slots=True)
class SafeValidationEvidenceView:
    """One ordered allowlisted validation evidence record."""

    ordinal: int
    check_id: CanonicalLabelView
    severity: CanonicalLabelView
    outcome: CanonicalLabelView
    violation_code: CanonicalLabelView | None
    warning_code: CanonicalLabelView | None
    explanation: str

    def __post_init__(self) -> None:
        _positive_integer("SafeValidationEvidenceView.ordinal", self.ordinal)
        _required_text("SafeValidationEvidenceView.explanation", self.explanation)
        if self.violation_code is not None and self.warning_code is not None:
            raise LifecycleInvariantError(
                "SafeValidationEvidenceView cannot expose both violation and warning codes."
            )


@dataclass(frozen=True, slots=True)
class ValidationInspectionView:
    """Latest-attempt validation projection without candidate or provider data."""

    attempt_number: int
    status: CanonicalLabelView
    score: InspectionScoreView
    violations: tuple[SafeValidationViolationView, ...]
    evidence: tuple[SafeValidationEvidenceView, ...]

    def __post_init__(self) -> None:
        _positive_integer("ValidationInspectionView.attempt_number", self.attempt_number)
        object.__setattr__(self, "violations", tuple(self.violations))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class ClarificationInspectionView:
    """Safe clarification reason and deterministic persisted question."""

    reason: CanonicalLabelView
    question_text: str

    def __post_init__(self) -> None:
        _required_text("ClarificationInspectionView.question_text", self.question_text)


@dataclass(frozen=True, slots=True)
class SafeTerminalStatusView:
    """Allowlisted historical terminal failure or cancellation status."""

    kind: SafeTerminalKind
    kind_label: str
    stage: CanonicalLabelView
    code: CanonicalLabelView
    safe_message: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SafeTerminalKind):
            raise LifecycleInvariantError("SafeTerminalStatusView requires a closed kind.")
        if self.kind_label != _canonical_inspection_label(self.kind.value):
            raise LifecycleInvariantError(
                "SafeTerminalStatusView.kind_label must match its kind."
            )
        _required_text("SafeTerminalStatusView.safe_message", self.safe_message)


@dataclass(frozen=True, slots=True)
class ContextInspectionView:
    """Complete closed historical inspection projection for one accepted run."""

    target: InspectionTargetView
    active_project: InspectionValue[ActiveStateItemView]
    active_topic: InspectionValue[ActiveStateItemView]
    active_task: InspectionValue[ActiveStateItemView]
    intent: InspectionValue[CanonicalLabelView]
    expected_output_type: InspectionValue[CanonicalLabelView]
    qualifier_evidence: InspectionCollection[QualifierEvidenceView]
    references: InspectionCollection[ReferenceInspectionView]
    constraints: InspectionCollection[ConstraintInspectionView]
    conflicts: InspectionCollection[ConflictInspectionView]
    retrieved_memories: InspectionCollection[RetrievedMemoryInspectionView]
    confidence: InspectionValue[ConfidenceInspectionView]
    validation: InspectionValue[ValidationInspectionView]
    correction_count: InspectionValue[int]
    clarification: InspectionValue[ClarificationInspectionView]
    terminal_status: InspectionValue[SafeTerminalStatusView]


@dataclass(frozen=True, slots=True)
class InspectContextRequest:
    """Select the latest accepted run for one shell conversation."""

    conversation_id: DomainId


@dataclass(frozen=True, slots=True)
class ContextInspectionReadyResult:
    """One complete safe inspection view was loaded."""

    view: ContextInspectionView
    result_kind: Literal["CONTEXT_INSPECTION_READY"] = field(
        init=False,
        default="CONTEXT_INSPECTION_READY",
    )


@dataclass(frozen=True, slots=True)
class ContextInspectionEmptyResult:
    """The existing conversation has no accepted processing run."""

    result_kind: Literal["CONTEXT_INSPECTION_EMPTY"] = field(
        init=False,
        default="CONTEXT_INSPECTION_EMPTY",
    )
    safe_message: Literal[
        "No processed request is available for this conversation."
    ] = field(
        init=False,
        default="No processed request is available for this conversation.",
    )


@dataclass(frozen=True, slots=True)
class ContextInspectionLoadFailureResult:
    """Inspection could not construct one complete safe historical view."""

    result_kind: Literal["CONTEXT_INSPECTION_LOAD_FAILURE"] = field(
        init=False,
        default="CONTEXT_INSPECTION_LOAD_FAILURE",
    )
    code: Literal["INSPECTION_LOAD_FAILED"] = field(
        init=False,
        default="INSPECTION_LOAD_FAILED",
    )
    safe_message: Literal["Context inspection could not be loaded safely."] = field(
        init=False,
        default="Context inspection could not be loaded safely.",
    )


type InspectContextResult = (
    ContextInspectionReadyResult
    | ContextInspectionEmptyResult
    | ContextInspectionLoadFailureResult
)


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


@unique
class UiTheme(StrEnum):
    """Closed Qt color-scheme preference stored by the presentation shell."""

    SYSTEM = "SYSTEM"
    LIGHT = "LIGHT"
    DARK = "DARK"


@unique
class ManualSettingKey(StrEnum):
    """The only settings keys editable by TASK-0017."""

    UI_THEME = "ui.theme"
    UI_CONTEXT_PANEL_VISIBLE = "ui.context_panel_visible"


@unique
class SettingsField(StrEnum):
    """Closed settings form fields used by safe validation errors."""

    THEME = "THEME"
    CONTEXT_PANEL_VISIBLE = "CONTEXT_PANEL_VISIBLE"
    LAST_SELECTED_CONVERSATION = "LAST_SELECTED_CONVERSATION"
    UNKNOWN = "UNKNOWN"


@unique
class ConfigurationCategoryName(StrEnum):
    """Exact ordered safe configuration category names."""

    APPLICATION = "Application"
    MODEL = "Model"
    STORAGE = "Storage"
    MEMORY = "Memory"
    VALIDATION = "Validation"
    LOGGING = "Logging"
    SECURITY = "Security"


_CONFIGURATION_ORIGIN_LABELS = {
    ConfigurationOrigin.PROCESS_OVERRIDE: "Process override",
    ConfigurationOrigin.LOCAL_YAML: "Local YAML",
    ConfigurationOrigin.DOCUMENTED_DEFAULT: "Documented default",
    ConfigurationOrigin.FIXED_MVP: "Fixed MVP rule",
}


@dataclass(frozen=True, slots=True)
class InitialUiPreferences:
    """Validated preferences applied before QML is created."""

    theme: UiTheme
    context_panel_visible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.theme, UiTheme):
            raise LifecycleInvariantError("InitialUiPreferences.theme must be canonical.")
        if not isinstance(self.context_panel_visible, bool):
            raise LifecycleInvariantError(
                "InitialUiPreferences.context_panel_visible must be boolean."
            )


@dataclass(frozen=True, slots=True)
class ConfigurationOriginView:
    """One closed origin value and its exact application-owned label."""

    origin: ConfigurationOrigin
    display_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.origin, ConfigurationOrigin):
            raise LifecycleInvariantError(
                "ConfigurationOriginView.origin must be canonical."
            )
        if self.display_label != _CONFIGURATION_ORIGIN_LABELS[self.origin]:
            raise LifecycleInvariantError(
                "ConfigurationOriginView.display_label must match its origin."
            )


@dataclass(frozen=True, slots=True)
class ConfigurationFieldView:
    """One allowlisted configuration field safe for presentation."""

    ordinal: int
    label: str
    value_text: str
    origin: ConfigurationOriginView

    def __post_init__(self) -> None:
        _positive_integer("ConfigurationFieldView.ordinal", self.ordinal)
        _required_text("ConfigurationFieldView.label", self.label)
        _required_text("ConfigurationFieldView.value_text", self.value_text)
        if not isinstance(self.origin, ConfigurationOriginView):
            raise LifecycleInvariantError(
                "ConfigurationFieldView.origin must be a closed safe view."
            )


@dataclass(frozen=True, slots=True)
class ConfigurationCategoryView:
    """One ordered safe configuration category."""

    ordinal: int
    name: ConfigurationCategoryName
    fields: tuple[ConfigurationFieldView, ...]

    def __post_init__(self) -> None:
        _positive_integer("ConfigurationCategoryView.ordinal", self.ordinal)
        if not isinstance(self.name, ConfigurationCategoryName):
            raise LifecycleInvariantError(
                "ConfigurationCategoryView.name must be canonical."
            )
        fields = tuple(self.fields)
        if not fields or any(
            item.ordinal != index
            for index, item in enumerate(fields, start=1)
        ):
            raise LifecycleInvariantError(
                "ConfigurationCategoryView.fields must have consecutive ordinals."
            )
        object.__setattr__(self, "fields", fields)


@dataclass(frozen=True, slots=True)
class ConfigurationInspectionView:
    """The complete closed configuration projection for the settings page."""

    categories: tuple[ConfigurationCategoryView, ...]
    fingerprint: str
    fingerprint_label: Literal["Configuration fingerprint"] = field(
        init=False,
        default="Configuration fingerprint",
    )

    def __post_init__(self) -> None:
        categories = tuple(self.categories)
        expected_names = tuple(ConfigurationCategoryName)
        if (
            tuple(item.name for item in categories) != expected_names
            or any(
                item.ordinal != index
                for index, item in enumerate(categories, start=1)
            )
        ):
            raise LifecycleInvariantError(
                "ConfigurationInspectionView.categories must use exact canonical order."
            )
        if len(self.fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.fingerprint
        ):
            raise LifecycleInvariantError(
                "ConfigurationInspectionView.fingerprint must be 64 lowercase hex characters."
            )
        object.__setattr__(self, "categories", categories)


@dataclass(frozen=True, slots=True)
class ManualSettingsView:
    """The two effective presentation preferences and safe configuration view."""

    theme: UiTheme
    context_panel_visible: bool
    configuration: ConfigurationInspectionView

    def __post_init__(self) -> None:
        if not isinstance(self.theme, UiTheme):
            raise LifecycleInvariantError("ManualSettingsView.theme must be canonical.")
        if not isinstance(self.context_panel_visible, bool):
            raise LifecycleInvariantError(
                "ManualSettingsView.context_panel_visible must be boolean."
            )
        if not isinstance(self.configuration, ConfigurationInspectionView):
            raise LifecycleInvariantError(
                "ManualSettingsView.configuration must be a closed safe view."
            )


@dataclass(frozen=True, slots=True)
class InspectManualSettingsRequest:
    """Request the closed settings and immutable configuration projection."""


@dataclass(frozen=True, slots=True)
class ManualSettingsReadyResult:
    view: ManualSettingsView
    result_kind: Literal["MANUAL_SETTINGS_READY"] = field(
        init=False,
        default="MANUAL_SETTINGS_READY",
    )


@dataclass(frozen=True, slots=True)
class ManualSettingsLoadFailureResult:
    result_kind: Literal["MANUAL_SETTINGS_LOAD_FAILURE"] = field(
        init=False,
        default="MANUAL_SETTINGS_LOAD_FAILURE",
    )
    code: Literal["SETTINGS_LOAD_FAILED"] = field(
        init=False,
        default="SETTINGS_LOAD_FAILED",
    )
    safe_message: Literal["Settings could not be loaded safely."] = field(
        init=False,
        default="Settings could not be loaded safely.",
    )


type InspectManualSettingsResult = (
    ManualSettingsReadyResult | ManualSettingsLoadFailureResult
)


@dataclass(frozen=True, slots=True)
class SettingUpdate:
    """One requested setting value; application validation owns its key and type."""

    key: str
    value: object

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise LifecycleInvariantError("SettingUpdate.key must be exact text.")


@dataclass(frozen=True, slots=True)
class UpdateManualSettingsRequest:
    """A complete ordered set of changed editable settings."""

    values: tuple[SettingUpdate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))


@dataclass(frozen=True, slots=True)
class SettingsFieldError:
    field: SettingsField
    safe_message: str

    def __post_init__(self) -> None:
        if not isinstance(self.field, SettingsField):
            raise LifecycleInvariantError("SettingsFieldError.field must be canonical.")
        expected = {
            SettingsField.THEME: "Theme must be System, Light, or Dark.",
            SettingsField.CONTEXT_PANEL_VISIBLE: (
                "Show context inspection must be true or false."
            ),
            SettingsField.LAST_SELECTED_CONVERSATION: (
                "This setting is not editable here."
            ),
            SettingsField.UNKNOWN: (
                "Only permitted presentation settings can be changed."
            ),
        }[self.field]
        if self.safe_message != expected:
            raise LifecycleInvariantError(
                "SettingsFieldError.safe_message must match its field."
            )


@dataclass(frozen=True, slots=True)
class ManualSettingsUpdateSucceededResult:
    effective_theme: UiTheme
    effective_context_panel_visible: bool
    changed_keys: tuple[ManualSettingKey, ...]
    result_kind: Literal["MANUAL_SETTINGS_UPDATE_SUCCEEDED"] = field(
        init=False,
        default="MANUAL_SETTINGS_UPDATE_SUCCEEDED",
    )
    safe_message: Literal["Settings saved and applied."] = field(
        init=False,
        default="Settings saved and applied.",
    )
    restart_required: Literal[False] = field(init=False, default=False)

    def __post_init__(self) -> None:
        if not isinstance(self.effective_theme, UiTheme):
            raise LifecycleInvariantError(
                "ManualSettingsUpdateSucceededResult theme must be canonical."
            )
        if not isinstance(self.effective_context_panel_visible, bool):
            raise LifecycleInvariantError(
                "ManualSettingsUpdateSucceededResult visibility must be boolean."
            )
        changed_keys = tuple(self.changed_keys)
        expected = tuple(
            key for key in ManualSettingKey if key in set(changed_keys)
        )
        if not changed_keys or changed_keys != expected:
            raise LifecycleInvariantError(
                "ManualSettingsUpdateSucceededResult keys must be unique and ordered."
            )
        object.__setattr__(self, "changed_keys", changed_keys)


@dataclass(frozen=True, slots=True)
class ManualSettingsValidationFailureResult:
    code: Literal[
        "SETTING_VALUE_INVALID",
        "SETTING_KEY_NOT_EDITABLE",
        "SETTING_KEY_UNKNOWN",
    ]
    errors: tuple[SettingsFieldError, ...]
    result_kind: Literal["MANUAL_SETTINGS_VALIDATION_FAILURE"] = field(
        init=False,
        default="MANUAL_SETTINGS_VALIDATION_FAILURE",
    )
    safe_message: Literal["Review the highlighted settings."] = field(
        init=False,
        default="Review the highlighted settings.",
    )

    def __post_init__(self) -> None:
        if self.code not in {
            "SETTING_VALUE_INVALID",
            "SETTING_KEY_NOT_EDITABLE",
            "SETTING_KEY_UNKNOWN",
        }:
            raise LifecycleInvariantError(
                "ManualSettingsValidationFailureResult.code must be closed."
            )
        errors = tuple(self.errors)
        if not errors:
            raise LifecycleInvariantError(
                "ManualSettingsValidationFailureResult requires errors."
            )
        object.__setattr__(self, "errors", errors)


@dataclass(frozen=True, slots=True)
class ManualSettingsMutationFailureResult:
    result_kind: Literal["MANUAL_SETTINGS_MUTATION_FAILURE"] = field(
        init=False,
        default="MANUAL_SETTINGS_MUTATION_FAILURE",
    )
    code: Literal["SETTINGS_UPDATE_FAILED"] = field(
        init=False,
        default="SETTINGS_UPDATE_FAILED",
    )
    safe_message: Literal["Settings could not be saved safely."] = field(
        init=False,
        default="Settings could not be saved safely.",
    )


type UpdateManualSettingsResult = (
    ManualSettingsUpdateSucceededResult
    | ManualSettingsValidationFailureResult
    | ManualSettingsMutationFailureResult
)


@unique
class MemoryOwnerKind(StrEnum):
    CONVERSATION = "CONVERSATION"
    PROJECT = "PROJECT"
    GLOBAL = "GLOBAL"


@unique
class MemoryMutationOperation(StrEnum):
    CREATE = "CREATE"
    EDIT = "EDIT"
    SOFT_DELETE = "SOFT_DELETE"


@unique
class MemoryDuplicateDecision(StrEnum):
    CHECK = "CHECK"
    PROCEED = "PROCEED"


@unique
class MemoryField(StrEnum):
    TYPE = "TYPE"
    SCOPE = "SCOPE"
    OWNER = "OWNER"
    IMPORTANCE = "IMPORTANCE"
    CONFIDENCE = "CONFIDENCE"
    EXPIRY = "EXPIRY"
    SOURCE_DESCRIPTION = "SOURCE_DESCRIPTION"


@dataclass(frozen=True, slots=True)
class MemoryOwnerView:
    kind: MemoryOwnerKind
    display_text: str
    project_status: CanonicalLabelView | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MemoryOwnerKind):
            raise LifecycleInvariantError("MemoryOwnerView.kind must be canonical.")
        _required_text("MemoryOwnerView.display_text", self.display_text)
        if (self.kind is MemoryOwnerKind.PROJECT) != (
            self.project_status is not None
        ):
            raise LifecycleInvariantError(
                "Only a project memory owner carries project status."
            )


@dataclass(frozen=True, slots=True)
class MemorySummaryView:
    content: str
    type: CanonicalLabelView
    scope: CanonicalLabelView
    owner: MemoryOwnerView
    stored_status: CanonicalLabelView
    effective_status: CanonicalLabelView
    updated_at_text: str


@dataclass(frozen=True, slots=True)
class MemorySourceView:
    ordinal: int
    kind: CanonicalLabelView
    description: str
    source_message: str
    created_at_text: str
    display_identity: str = field(init=False)

    def __post_init__(self) -> None:
        _positive_integer("MemorySourceView.ordinal", self.ordinal)
        object.__setattr__(self, "display_identity", f"Source {self.ordinal}")


@dataclass(frozen=True, slots=True)
class MemoryRevisionView:
    revision_number: int
    operation: CanonicalLabelView
    source_ordinal: int
    content_snapshot: str
    keywords: tuple[str, ...]
    topic_terms: tuple[str, ...]
    importance: InspectionScoreView
    confidence: InspectionScoreView
    expires_at_text: str
    stored_status: CanonicalLabelView
    updated_at_text: str
    deleted_at_text: str
    performed_by: CanonicalLabelView
    performed_at_text: str
    display_identity: str = field(init=False)

    def __post_init__(self) -> None:
        _positive_integer(
            "MemoryRevisionView.revision_number", self.revision_number
        )
        _positive_integer("MemoryRevisionView.source_ordinal", self.source_ordinal)
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "topic_terms", tuple(self.topic_terms))
        object.__setattr__(
            self,
            "display_identity",
            f"Revision {self.revision_number}",
        )


@dataclass(frozen=True, slots=True)
class MemoryDetailsView:
    content: str
    keywords: tuple[str, ...]
    topic_terms: tuple[str, ...]
    importance: InspectionScoreView
    confidence: InspectionScoreView
    expires_at_text: str
    created_at_text: str
    updated_at_text: str
    deleted_at_text: str
    stored_status: CanonicalLabelView
    effective_status: CanonicalLabelView
    evaluated_at_text: str
    sources: tuple[MemorySourceView, ...]
    revisions: tuple[MemoryRevisionView, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "topic_terms", tuple(self.topic_terms))
        sources = tuple(self.sources)
        revisions = tuple(self.revisions)
        if any(item.ordinal != index for index, item in enumerate(sources, 1)):
            raise LifecycleInvariantError(
                "MemoryDetailsView.sources must have consecutive ordinals."
            )
        if tuple(item.revision_number for item in revisions) != tuple(
            range(1, len(revisions) + 1)
        ):
            raise LifecycleInvariantError(
                "MemoryDetailsView.revisions must be consecutive."
            )
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "revisions", revisions)


@dataclass(frozen=True, slots=True)
class MemoryInspectionItemView:
    ordinal: int
    summary: MemorySummaryView
    details: MemoryDetailsView
    private_memory_id: DomainId | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    display_identity: str = field(init=False)

    def __post_init__(self) -> None:
        _positive_integer("MemoryInspectionItemView.ordinal", self.ordinal)
        object.__setattr__(self, "display_identity", f"Memory {self.ordinal}")


@dataclass(frozen=True, slots=True)
class MemoryInspectionCollectionView:
    stored_status_filter: MemoryStatus
    evaluated_at_text: str
    items: tuple[MemoryInspectionItemView, ...]
    selected_ordinal: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.stored_status_filter, MemoryStatus):
            raise LifecycleInvariantError(
                "MemoryInspectionCollectionView filter must be canonical."
            )
        items = tuple(self.items)
        if not items or any(item.ordinal != index for index, item in enumerate(items, 1)):
            raise LifecycleInvariantError(
                "MemoryInspectionCollectionView requires ordered items."
            )
        if self.selected_ordinal is not None and self.selected_ordinal not in range(
            1, len(items) + 1
        ):
            raise LifecycleInvariantError(
                "MemoryInspectionCollectionView selection must identify an item."
            )
        object.__setattr__(self, "items", items)


@dataclass(frozen=True, slots=True)
class InspectMemoriesRequest:
    stored_status: MemoryStatus
    selected_memory_id: DomainId | None = None


@dataclass(frozen=True, slots=True)
class MemoryInspectionReadyResult:
    view: MemoryInspectionCollectionView
    result_kind: Literal["MEMORY_INSPECTION_READY"] = field(
        init=False, default="MEMORY_INSPECTION_READY"
    )


@dataclass(frozen=True, slots=True)
class MemoryInspectionEmptyResult:
    stored_status: MemoryStatus
    evaluated_at_text: str
    result_kind: Literal["MEMORY_INSPECTION_EMPTY"] = field(
        init=False, default="MEMORY_INSPECTION_EMPTY"
    )
    safe_message: Literal["No memories match the selected filter."] = field(
        init=False, default="No memories match the selected filter."
    )


@dataclass(frozen=True, slots=True)
class MemoryInspectionLoadFailureResult:
    result_kind: Literal["MEMORY_INSPECTION_LOAD_FAILURE"] = field(
        init=False, default="MEMORY_INSPECTION_LOAD_FAILURE"
    )
    code: Literal["MEMORY_INSPECTION_LOAD_FAILED"] = field(
        init=False, default="MEMORY_INSPECTION_LOAD_FAILED"
    )
    safe_message: Literal["Memories could not be loaded safely."] = field(
        init=False, default="Memories could not be loaded safely."
    )


type InspectMemoriesResult = (
    MemoryInspectionReadyResult
    | MemoryInspectionEmptyResult
    | MemoryInspectionLoadFailureResult
)


@dataclass(frozen=True, slots=True)
class CreateMemoryPresentationRequest:
    conversation_id: DomainId
    memory_type: MemoryType
    scope: MemoryScope
    content: str
    keywords: tuple[str, ...]
    topic_terms: tuple[str, ...]
    importance: Decimal
    confidence: Decimal
    expires_at: datetime | None
    source_description: str
    duplicate_decision: MemoryDuplicateDecision

    def __post_init__(self) -> None:
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "topic_terms", tuple(self.topic_terms))


@dataclass(frozen=True, slots=True)
class EditMemoryPresentationRequest:
    memory_id: DomainId
    expected_revision_number: int
    content: str
    keywords: tuple[str, ...]
    topic_terms: tuple[str, ...]
    importance: Decimal
    confidence: Decimal
    expires_at: datetime | None
    source_description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "topic_terms", tuple(self.topic_terms))


@dataclass(frozen=True, slots=True)
class SoftDeleteMemoryPresentationRequest:
    memory_id: DomainId
    expected_revision_number: int
    source_description: str


@dataclass(frozen=True, slots=True)
class MemoryFieldError:
    field: MemoryField
    safe_message: str

    def __post_init__(self) -> None:
        expected = {
            MemoryField.TYPE: "Choose a valid memory type.",
            MemoryField.SCOPE: "Choose a valid memory scope.",
            MemoryField.OWNER: "An active project is required for project memory.",
            MemoryField.IMPORTANCE: "Importance must be between 0 and 1.",
            MemoryField.CONFIDENCE: "Confidence must be between 0 and 1.",
            MemoryField.EXPIRY: "Expiry must be a valid UTC date and time or empty.",
            MemoryField.SOURCE_DESCRIPTION: (
                "Describe why this memory is being changed."
            ),
        }
        if not isinstance(self.field, MemoryField) or self.safe_message != expected[
            self.field
        ]:
            raise LifecycleInvariantError(
                "MemoryFieldError must use its exact closed message."
            )


@dataclass(frozen=True, slots=True)
class MemoryDuplicateCandidateView:
    ordinal: int
    content: str
    scope: CanonicalLabelView
    owner_display_text: str
    effective_status: CanonicalLabelView
    updated_at_text: str
    display_identity: str = field(init=False)

    def __post_init__(self) -> None:
        _positive_integer("MemoryDuplicateCandidateView.ordinal", self.ordinal)
        object.__setattr__(self, "display_identity", f"Memory {self.ordinal}")


@dataclass(frozen=True, slots=True)
class MemoryMutationSucceededResult:
    operation: MemoryMutationOperation
    affected: MemoryInspectionItemView
    revision_number: int
    result_kind: Literal["MEMORY_MUTATION_SUCCEEDED"] = field(
        init=False, default="MEMORY_MUTATION_SUCCEEDED"
    )
    safe_message: str = field(init=False)

    def __post_init__(self) -> None:
        _positive_integer(
            "MemoryMutationSucceededResult.revision_number",
            self.revision_number,
        )
        object.__setattr__(
            self,
            "safe_message",
            {
                MemoryMutationOperation.CREATE: "Memory created.",
                MemoryMutationOperation.EDIT: "Memory updated.",
                MemoryMutationOperation.SOFT_DELETE: "Memory soft-deleted.",
            }[self.operation],
        )


@dataclass(frozen=True, slots=True)
class MemoryDuplicateGuidanceResult:
    candidates: tuple[MemoryDuplicateCandidateView, ...]
    result_kind: Literal["MEMORY_DUPLICATE_GUIDANCE"] = field(
        init=False, default="MEMORY_DUPLICATE_GUIDANCE"
    )
    safe_message: Literal["Possible duplicate memories were found."] = field(
        init=False, default="Possible duplicate memories were found."
    )

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        if not candidates or any(
            item.ordinal != index for index, item in enumerate(candidates, 1)
        ):
            raise LifecycleInvariantError(
                "MemoryDuplicateGuidanceResult requires ordered candidates."
            )
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True, slots=True)
class MemoryMutationValidationFailureResult:
    errors: tuple[MemoryFieldError, ...]
    result_kind: Literal["MEMORY_MUTATION_VALIDATION_FAILURE"] = field(
        init=False, default="MEMORY_MUTATION_VALIDATION_FAILURE"
    )
    code: Literal["MEMORY_INPUT_INVALID"] = field(
        init=False, default="MEMORY_INPUT_INVALID"
    )
    safe_message: Literal["Review the highlighted memory fields."] = field(
        init=False, default="Review the highlighted memory fields."
    )

    def __post_init__(self) -> None:
        errors = tuple(self.errors)
        if not errors:
            raise LifecycleInvariantError(
                "Memory validation failure requires at least one field error."
            )
        object.__setattr__(self, "errors", errors)


@dataclass(frozen=True, slots=True)
class MemoryMutationStaleResult:
    result_kind: Literal["MEMORY_MUTATION_STALE"] = field(
        init=False, default="MEMORY_MUTATION_STALE"
    )
    code: Literal["MEMORY_REVISION_CONFLICT"] = field(
        init=False, default="MEMORY_REVISION_CONFLICT"
    )
    safe_message: Literal[
        "This memory changed. Review the latest version before trying again."
    ] = field(
        init=False,
        default="This memory changed. Review the latest version before trying again.",
    )


@dataclass(frozen=True, slots=True)
class MemoryMutationRejectedResult:
    code: Literal[
        "MEMORY_NOT_FOUND", "MEMORY_DELETED", "MEMORY_SCOPE_UNAVAILABLE"
    ]
    safe_message: str = field(init=False)
    result_kind: Literal["MEMORY_MUTATION_REJECTED"] = field(
        init=False, default="MEMORY_MUTATION_REJECTED"
    )

    def __post_init__(self) -> None:
        messages = {
            "MEMORY_NOT_FOUND": "The memory is no longer available.",
            "MEMORY_DELETED": (
                "Deleted memories cannot be changed or deleted again."
            ),
            "MEMORY_SCOPE_UNAVAILABLE": (
                "An active project is required for project memory."
            ),
        }
        if self.code not in messages:
            raise LifecycleInvariantError(
                "MemoryMutationRejectedResult.code must be closed."
            )
        object.__setattr__(self, "safe_message", messages[self.code])


@dataclass(frozen=True, slots=True)
class MemoryMutationFailureResult:
    safe_message: Literal[
        "Memory could not be created safely.",
        "Memory could not be updated safely.",
        "Memory could not be soft-deleted safely.",
    ]
    result_kind: Literal["MEMORY_MUTATION_FAILURE"] = field(
        init=False, default="MEMORY_MUTATION_FAILURE"
    )
    code: Literal["MEMORY_MUTATION_FAILED"] = field(
        init=False, default="MEMORY_MUTATION_FAILED"
    )

    def __post_init__(self) -> None:
        if self.safe_message not in {
            "Memory could not be created safely.",
            "Memory could not be updated safely.",
            "Memory could not be soft-deleted safely.",
        }:
            raise LifecycleInvariantError(
                "MemoryMutationFailureResult.safe_message must be closed."
            )


type MemoryMutationResult = (
    MemoryMutationSucceededResult
    | MemoryDuplicateGuidanceResult
    | MemoryMutationValidationFailureResult
    | MemoryMutationStaleResult
    | MemoryMutationRejectedResult
    | MemoryMutationFailureResult
)


@dataclass(frozen=True, slots=True)
class ProjectAssociationView:
    name: str
    status: CanonicalLabelView
    display_text: str

    def __post_init__(self) -> None:
        _required_text("ProjectAssociationView.name", self.name)
        expected = (
            self.name
            if self.status.code == "ACTIVE"
            else f"{self.name} — Archived (current association)"
        )
        if self.display_text != expected:
            raise LifecycleInvariantError(
                "ProjectAssociationView.display_text must match project status."
            )


@dataclass(frozen=True, slots=True)
class ProjectItemView:
    ordinal: int
    name: str
    description: str
    status: CanonicalLabelView
    created_at_text: str
    updated_at_text: str
    is_current_association: bool
    archive_eligible: bool
    archive_ineligible_text: str
    private_project_id: DomainId | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    display_identity: str = field(init=False)

    def __post_init__(self) -> None:
        _positive_integer("ProjectItemView.ordinal", self.ordinal)
        _required_text("ProjectItemView.name", self.name)
        if not isinstance(self.is_current_association, bool) or not isinstance(
            self.archive_eligible, bool
        ):
            raise LifecycleInvariantError(
                "ProjectItemView flags must be boolean."
            )
        expected_ineligible = (
            ""
            if self.archive_eligible
            else "This project cannot be archived while it has an active request."
            if self.status.code == "ACTIVE"
            else ""
        )
        if self.archive_ineligible_text != expected_ineligible:
            raise LifecycleInvariantError(
                "ProjectItemView archive text must match eligibility."
            )
        object.__setattr__(self, "display_identity", f"Project {self.ordinal}")


@dataclass(frozen=True, slots=True)
class ProjectInspectionView:
    active_projects: tuple[ProjectItemView, ...]
    archived_projects: tuple[ProjectItemView, ...]
    current_association: ProjectAssociationView | None
    conversation_state_version: int

    def __post_init__(self) -> None:
        active = tuple(self.active_projects)
        archived = tuple(self.archived_projects)
        if any(item.ordinal != index for index, item in enumerate(active, 1)) or any(
            item.ordinal != index for index, item in enumerate(archived, 1)
        ):
            raise LifecycleInvariantError(
                "ProjectInspectionView project ordinals must be consecutive per list."
            )
        _non_negative_integer(
            "ProjectInspectionView.conversation_state_version",
            self.conversation_state_version,
        )
        object.__setattr__(self, "active_projects", active)
        object.__setattr__(self, "archived_projects", archived)


@dataclass(frozen=True, slots=True)
class InspectProjectsRequest:
    conversation_id: DomainId


@dataclass(frozen=True, slots=True)
class ProjectInspectionReadyResult:
    view: ProjectInspectionView
    result_kind: Literal["PROJECT_INSPECTION_READY"] = field(
        init=False, default="PROJECT_INSPECTION_READY"
    )


@dataclass(frozen=True, slots=True)
class ProjectInspectionEmptyResult:
    result_kind: Literal["PROJECT_INSPECTION_EMPTY"] = field(
        init=False, default="PROJECT_INSPECTION_EMPTY"
    )
    safe_message: Literal["No projects are available."] = field(
        init=False, default="No projects are available."
    )


@dataclass(frozen=True, slots=True)
class ProjectInspectionLoadFailureResult:
    result_kind: Literal["PROJECT_INSPECTION_LOAD_FAILURE"] = field(
        init=False, default="PROJECT_INSPECTION_LOAD_FAILURE"
    )
    code: Literal["PROJECT_INSPECTION_LOAD_FAILED"] = field(
        init=False, default="PROJECT_INSPECTION_LOAD_FAILED"
    )
    safe_message: Literal["Projects could not be loaded safely."] = field(
        init=False, default="Projects could not be loaded safely."
    )


type InspectProjectsResult = (
    ProjectInspectionReadyResult
    | ProjectInspectionEmptyResult
    | ProjectInspectionLoadFailureResult
)


@dataclass(frozen=True, slots=True)
class SelectProjectPresentationRequest:
    conversation_id: DomainId
    project_id: DomainId | None
    expected_state_version: int


@dataclass(frozen=True, slots=True)
class ArchiveProjectPresentationRequest:
    project_id: DomainId
    is_current_association: bool


@dataclass(frozen=True, slots=True)
class ProjectSelectionChangedResult:
    current_association: ProjectAssociationView | None
    conversation_state_version: int
    result_kind: Literal["PROJECT_SELECTION_CHANGED"] = field(
        init=False, default="PROJECT_SELECTION_CHANGED"
    )
    safe_message: Literal["Project selection changed."] = field(
        init=False, default="Project selection changed."
    )


@dataclass(frozen=True, slots=True)
class ProjectSelectionUnchangedResult:
    current_association: ProjectAssociationView | None
    conversation_state_version: int
    result_kind: Literal["PROJECT_SELECTION_UNCHANGED"] = field(
        init=False, default="PROJECT_SELECTION_UNCHANGED"
    )
    safe_message: Literal["Project selection is unchanged."] = field(
        init=False, default="Project selection is unchanged."
    )


@dataclass(frozen=True, slots=True)
class ProjectArchiveSucceededResult:
    archived_project: ProjectItemView
    result_kind: Literal["PROJECT_ARCHIVE_SUCCEEDED"] = field(
        init=False, default="PROJECT_ARCHIVE_SUCCEEDED"
    )
    safe_message: Literal["Project archived."] = field(
        init=False, default="Project archived."
    )


@dataclass(frozen=True, slots=True)
class ProjectArchiveBlockedResult:
    result_kind: Literal["PROJECT_ARCHIVE_BLOCKED"] = field(
        init=False, default="PROJECT_ARCHIVE_BLOCKED"
    )
    code: Literal["PROJECT_HAS_ACTIVE_REQUEST"] = field(
        init=False, default="PROJECT_HAS_ACTIVE_REQUEST"
    )
    safe_message: Literal[
        "This project cannot be archived while it has an active request."
    ] = field(
        init=False,
        default="This project cannot be archived while it has an active request.",
    )


@dataclass(frozen=True, slots=True)
class ProjectMutationStaleResult:
    result_kind: Literal["PROJECT_MUTATION_STALE"] = field(
        init=False, default="PROJECT_MUTATION_STALE"
    )
    code: Literal["PROJECT_STATE_CONFLICT"] = field(
        init=False, default="PROJECT_STATE_CONFLICT"
    )
    safe_message: Literal[
        "The project selection changed. Refresh projects before trying again."
    ] = field(
        init=False,
        default="The project selection changed. Refresh projects before trying again.",
    )


@dataclass(frozen=True, slots=True)
class ProjectMutationRejectedResult:
    code: Literal["ARCHIVED_PROJECT_NOT_SELECTABLE", "PROJECT_NOT_ARCHIVABLE"]
    safe_message: str = field(init=False)
    result_kind: Literal["PROJECT_MUTATION_REJECTED"] = field(
        init=False, default="PROJECT_MUTATION_REJECTED"
    )

    def __post_init__(self) -> None:
        messages = {
            "ARCHIVED_PROJECT_NOT_SELECTABLE": (
                "Archived projects cannot be selected."
            ),
            "PROJECT_NOT_ARCHIVABLE": (
                "The project is no longer available for archiving."
            ),
        }
        if self.code not in messages:
            raise LifecycleInvariantError(
                "ProjectMutationRejectedResult.code must be closed."
            )
        object.__setattr__(self, "safe_message", messages[self.code])


@dataclass(frozen=True, slots=True)
class ProjectMutationFailureResult:
    code: Literal["PROJECT_SELECTION_FAILED", "PROJECT_ARCHIVE_FAILED"]
    safe_message: str = field(init=False)
    result_kind: Literal["PROJECT_MUTATION_FAILURE"] = field(
        init=False, default="PROJECT_MUTATION_FAILURE"
    )

    def __post_init__(self) -> None:
        messages = {
            "PROJECT_SELECTION_FAILED": (
                "Project selection could not be changed safely."
            ),
            "PROJECT_ARCHIVE_FAILED": "The project could not be archived safely.",
        }
        if self.code not in messages:
            raise LifecycleInvariantError(
                "ProjectMutationFailureResult.code must be closed."
            )
        object.__setattr__(self, "safe_message", messages[self.code])


type ProjectMutationResult = (
    ProjectSelectionChangedResult
    | ProjectSelectionUnchangedResult
    | ProjectArchiveSucceededResult
    | ProjectArchiveBlockedResult
    | ProjectMutationStaleResult
    | ProjectMutationRejectedResult
    | ProjectMutationFailureResult
)


class InspectProjects(Protocol):
    def execute(self, request: InspectProjectsRequest) -> InspectProjectsResult: ...


class SelectProjectForPresentation(Protocol):
    def execute(
        self, request: SelectProjectPresentationRequest
    ) -> ProjectMutationResult: ...


class ArchiveProjectForPresentation(Protocol):
    def execute(
        self, request: ArchiveProjectPresentationRequest
    ) -> ProjectMutationResult: ...


@unique
class ValidationAttemptOutcome(StrEnum):
    WAITING = "WAITING"
    IN_PROGRESS = "IN_PROGRESS"
    VALIDATED = "VALIDATED"
    TRANSPORT_FAILURE = "TRANSPORT_FAILURE"


@dataclass(frozen=True, slots=True)
class ValidationHistoryCollection[T]:
    items: tuple[T, ...]
    display_text: str

    def __post_init__(self) -> None:
        items = tuple(self.items)
        expected = "" if items else "Validation has not started for this request."
        if self.display_text != expected:
            raise LifecycleInvariantError(
                "ValidationHistoryCollection requires its exact empty text."
            )
        object.__setattr__(self, "items", items)


@dataclass(frozen=True, slots=True)
class ValidationAttemptReportView:
    status: CanonicalLabelView
    score: InspectionScoreView
    violations: tuple[SafeValidationViolationView, ...]
    evidence: tuple[SafeValidationEvidenceView, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "violations", tuple(self.violations))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class ValidationAttemptFailureView:
    stage: CanonicalLabelView
    code: CanonicalLabelView
    safe_message: str

    def __post_init__(self) -> None:
        _required_text("ValidationAttemptFailureView.safe_message", self.safe_message)


@dataclass(frozen=True, slots=True)
class ValidationHistoryAttemptView:
    attempt_number: int
    purpose: CanonicalLabelView
    outcome: CanonicalLabelView
    validation: ValidationAttemptReportView | None
    validation_display_text: str
    safe_transport_failure: ValidationAttemptFailureView | None
    correction_from_previous: int | None
    display_identity: str = field(init=False)

    def __post_init__(self) -> None:
        _positive_integer(
            "ValidationHistoryAttemptView.attempt_number", self.attempt_number
        )
        if self.correction_from_previous is not None:
            _positive_integer(
                "ValidationHistoryAttemptView.correction_from_previous",
                self.correction_from_previous,
            )
        outcome = self.outcome.code
        if outcome == ValidationAttemptOutcome.VALIDATED.value:
            valid = (
                self.validation is not None
                and self.safe_transport_failure is None
                and self.validation_display_text == ""
            )
        elif outcome in {
            ValidationAttemptOutcome.WAITING.value,
            ValidationAttemptOutcome.IN_PROGRESS.value,
        }:
            valid = (
                self.validation is None
                and self.safe_transport_failure is None
                and self.validation_display_text
                == "Validation has not completed for this attempt."
            )
        elif outcome == ValidationAttemptOutcome.TRANSPORT_FAILURE.value:
            valid = (
                self.validation is None
                and self.safe_transport_failure is not None
                and self.validation_display_text
                == "Validation was not applicable to this attempt."
            )
        else:
            valid = False
        if not valid:
            raise LifecycleInvariantError(
                "ValidationHistoryAttemptView outcome fields are inconsistent."
            )
        object.__setattr__(
            self,
            "display_identity",
            f"Attempt {self.attempt_number}",
        )


@dataclass(frozen=True, slots=True)
class CorrectionHistoryView:
    correction_number: int
    from_attempt_number: int
    to_attempt_number: int
    display_identity: str = field(init=False)
    display_text: str = field(init=False)

    def __post_init__(self) -> None:
        _positive_integer(
            "CorrectionHistoryView.correction_number", self.correction_number
        )
        if (
            self.from_attempt_number != self.correction_number
            or self.to_attempt_number != self.correction_number + 1
        ):
            raise LifecycleInvariantError(
                "CorrectionHistoryView must link adjacent display attempts."
            )
        object.__setattr__(
            self,
            "display_identity",
            f"Correction {self.correction_number}",
        )
        object.__setattr__(
            self,
            "display_text",
            (
                f"Correction {self.correction_number}: attempt "
                f"{self.from_attempt_number} to attempt {self.to_attempt_number}."
            ),
        )


@dataclass(frozen=True, slots=True)
class ValidationHistoryView:
    target: InspectionTargetView
    attempts: ValidationHistoryCollection[ValidationHistoryAttemptView]
    corrections: tuple[CorrectionHistoryView, ...]
    correction_count: int
    terminal_status: SafeTerminalStatusView | None

    def __post_init__(self) -> None:
        corrections = tuple(self.corrections)
        if self.correction_count != len(corrections) or self.correction_count not in range(
            3
        ):
            raise LifecycleInvariantError(
                "ValidationHistoryView correction count must match its rows."
            )
        object.__setattr__(self, "corrections", corrections)


@dataclass(frozen=True, slots=True)
class InspectValidationHistoryRequest:
    conversation_id: DomainId


@dataclass(frozen=True, slots=True)
class ValidationHistoryReadyResult:
    view: ValidationHistoryView
    result_kind: Literal["VALIDATION_HISTORY_READY"] = field(
        init=False, default="VALIDATION_HISTORY_READY"
    )


@dataclass(frozen=True, slots=True)
class ValidationHistoryEmptyResult:
    result_kind: Literal["VALIDATION_HISTORY_EMPTY"] = field(
        init=False, default="VALIDATION_HISTORY_EMPTY"
    )
    safe_message: Literal[
        "No validation history is available for this conversation."
    ] = field(
        init=False,
        default="No validation history is available for this conversation.",
    )


@dataclass(frozen=True, slots=True)
class ValidationHistoryLoadFailureResult:
    result_kind: Literal["VALIDATION_HISTORY_LOAD_FAILURE"] = field(
        init=False, default="VALIDATION_HISTORY_LOAD_FAILURE"
    )
    code: Literal["VALIDATION_HISTORY_LOAD_FAILED"] = field(
        init=False, default="VALIDATION_HISTORY_LOAD_FAILED"
    )
    safe_message: Literal["Validation history could not be loaded safely."] = field(
        init=False, default="Validation history could not be loaded safely."
    )


type InspectValidationHistoryResult = (
    ValidationHistoryReadyResult
    | ValidationHistoryEmptyResult
    | ValidationHistoryLoadFailureResult
)


class InspectValidationHistory(Protocol):
    def execute(
        self, request: InspectValidationHistoryRequest
    ) -> InspectValidationHistoryResult: ...


class InspectMemories(Protocol):
    def execute(self, request: InspectMemoriesRequest) -> InspectMemoriesResult: ...


class CreateMemoryPresentation(Protocol):
    def execute(
        self, request: CreateMemoryPresentationRequest
    ) -> MemoryMutationResult: ...


class EditMemoryPresentation(Protocol):
    def execute(
        self, request: EditMemoryPresentationRequest
    ) -> MemoryMutationResult: ...


class SoftDeleteMemoryPresentation(Protocol):
    def execute(
        self, request: SoftDeleteMemoryPresentationRequest
    ) -> MemoryMutationResult: ...


class CreateMemoryWithGuidance(CreateMemoryPresentation, Protocol):
    """Exact TASK-0017 create-and-duplicate-guidance inward surface."""


class EditMemoryForPresentation(EditMemoryPresentation, Protocol):
    """Exact TASK-0017 guarded edit inward surface."""


class SoftDeleteMemoryForPresentation(SoftDeleteMemoryPresentation, Protocol):
    """Exact TASK-0017 guarded soft-delete inward surface."""


class LoadInitialUiPreferences(Protocol):
    """Load and validate the bounded pre-QML presentation preferences."""

    def execute(self) -> InitialUiPreferences: ...


class InspectManualSettings(Protocol):
    """Return the closed settings and safe configuration projection."""

    def execute(
        self,
        request: InspectManualSettingsRequest,
    ) -> InspectManualSettingsResult: ...


class UpdateManualSettings(Protocol):
    """Atomically update only changed TASK-0017 presentation settings."""

    def execute(
        self,
        request: UpdateManualSettingsRequest,
    ) -> UpdateManualSettingsResult: ...


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


class InspectContext(Protocol):
    """Return one complete safe historical view for a conversation's latest run."""

    def execute(self, request: InspectContextRequest) -> InspectContextResult: ...


class StartupApplicationScope(Protocol):
    """Own startup preparation and one bounded preference read."""

    prepare_application_shell: PrepareApplicationShell
    load_initial_ui_preferences: LoadInitialUiPreferences

    def close(self) -> None: ...


class ForegroundApplicationScope(Protocol):
    """Own one worker-thread connection and the TASK-0014 foreground use cases."""

    process_user_message: ProcessUserMessage
    recover_processing_run: RecoverProcessingRun

    def close(self) -> None: ...


class InspectionApplicationScope(Protocol):
    """Own one worker-thread connection and the read-only inspection use case."""

    inspect_context: InspectContext

    def close(self) -> None: ...


class ManualOperationsApplicationScope(Protocol):
    """Own exactly the ten TASK-0017 use cases on one finite worker connection."""

    inspect_memories: InspectMemories
    create_memory_with_guidance: CreateMemoryWithGuidance
    edit_memory_for_presentation: EditMemoryForPresentation
    soft_delete_memory_for_presentation: SoftDeleteMemoryForPresentation
    inspect_projects: InspectProjects
    select_project_for_presentation: SelectProjectForPresentation
    archive_project_for_presentation: ArchiveProjectForPresentation
    inspect_validation_history: InspectValidationHistory
    inspect_manual_settings: InspectManualSettings
    update_manual_settings: UpdateManualSettings

    def close(self) -> None: ...


class ShellApplicationScopeFactory(Protocol):
    """Create fresh calling-thread-owned finite shell application scopes."""

    def open_startup_scope(self) -> StartupApplicationScope: ...

    def open_foreground_scope(self) -> ForegroundApplicationScope: ...

    def open_inspection_scope(self) -> InspectionApplicationScope: ...

    def open_manual_operations_scope(self) -> ManualOperationsApplicationScope: ...


class IdempotencyKeyFactory(Protocol):
    """Allocate one caller-owned UUID for each accepted shell submission."""

    def new_key(self) -> DomainId: ...


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
