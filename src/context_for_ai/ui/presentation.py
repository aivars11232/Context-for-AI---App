"""Qt-independent closed presentation values and foreground result mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, unique
import threading
from typing import Literal

from context_for_ai.application import (
    BusyResult,
    CancelledResult,
    ClarificationResult,
    ConcurrencyConflictResult,
    ConfigurationFailureResult,
    ControlledFailureResult,
    ExistingRunResult,
    NoRecoveryRequiredResult,
    PersistenceFailureResult,
    ProcessUserMessageResult,
    RecoveryCompletedResult,
    RecoveryResult,
    SucceededResult,
    ValidationExhaustedResult,
)


@unique
class ShellState(StrEnum):
    STARTUP = "STARTUP"
    RECOVERY = "RECOVERY"
    IDLE = "IDLE"
    PENDING = "PENDING"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLED = "CANCELLED"
    CLARIFICATION = "CLARIFICATION"
    SUCCESS = "SUCCESS"
    CONTROLLED_FAILURE = "CONTROLLED_FAILURE"
    BUSY = "BUSY"
    EXISTING_RUN = "EXISTING_RUN"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    RECOVERY_FAILURE = "RECOVERY_FAILURE"
    SHUTDOWN = "SHUTDOWN"


@unique
class ExecutionKind(StrEnum):
    SUBMISSION = "SUBMISSION"
    RECOVERY = "RECOVERY"


_EXECUTION_FAILURE_MESSAGES = {
    ExecutionKind.SUBMISSION: "Processing could not be completed safely.",
    ExecutionKind.RECOVERY: "Previous processing could not be recovered safely.",
}


@dataclass(frozen=True, slots=True)
class ForegroundExecutionFailureView:
    """Content-free containment for an unexpected worker-boundary defect."""

    execution_kind: ExecutionKind
    result_kind: Literal["FOREGROUND_EXECUTION_FAILURE"] = field(
        init=False,
        default="FOREGROUND_EXECUTION_FAILURE",
    )
    code: Literal["APPLICATION_EXECUTION_FAILED"] = field(
        init=False,
        default="APPLICATION_EXECUTION_FAILED",
    )
    safe_message: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.execution_kind, ExecutionKind):
            raise ValueError("Foreground execution failure kind must be closed.")
        object.__setattr__(
            self,
            "safe_message",
            _EXECUTION_FAILURE_MESSAGES[self.execution_kind],
        )


type ForegroundResult = (
    ProcessUserMessageResult | RecoveryResult | ForegroundExecutionFailureView
)


@dataclass(frozen=True, slots=True)
class ForegroundTerminalEnvelope:
    """The sole immutable result value permitted to cross from one worker."""

    execution_id: int
    execution_kind: ExecutionKind
    result: ForegroundResult

    def __post_init__(self) -> None:
        if (
            not isinstance(self.execution_id, int)
            or isinstance(self.execution_id, bool)
            or self.execution_id < 1
        ):
            raise ValueError("Foreground execution ID must be a positive integer.")
        if not isinstance(self.execution_kind, ExecutionKind):
            raise ValueError("Foreground envelope execution kind must be closed.")


@dataclass(frozen=True, slots=True)
class TerminalPresentationView:
    """Primitive-only GUI projection of one closed terminal result."""

    state: ShellState
    status_kind: str = ""
    status_message: str = ""
    assistant_text: str = ""
    clarification_text: str = ""
    submission_permitted_after_cleanup: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.state, ShellState):
            raise ValueError("Terminal presentation state must be closed.")
        if any(
            not isinstance(value, str)
            for value in (
                self.status_kind,
                self.status_message,
                self.assistant_text,
                self.clarification_text,
            )
        ) or not isinstance(self.submission_permitted_after_cleanup, bool):
            raise ValueError("Terminal presentation values must be primitive.")


class MonotonicCancellationToken:
    """Thread-safe cancellation that can move only from false to true."""

    __slots__ = ("_cancelled", "_lock")

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def request_cancellation(self) -> bool:
        with self._lock:
            if self._cancelled:
                return False
            self._cancelled = True
            return True


_SUBMISSION_RESULT_TYPES = (
    SucceededResult,
    ExistingRunResult,
    BusyResult,
    ClarificationResult,
    CancelledResult,
    ValidationExhaustedResult,
    ConfigurationFailureResult,
    PersistenceFailureResult,
    ConcurrencyConflictResult,
    ControlledFailureResult,
)
_RECOVERY_RESULT_TYPES = (
    NoRecoveryRequiredResult,
    RecoveryCompletedResult,
    ConfigurationFailureResult,
    PersistenceFailureResult,
)
_TERMINAL_PROCESSING_STATUSES = frozenset(
    {"NEEDS_CLARIFICATION", "SUCCEEDED", "CONTROLLED_FAILURE", "FAILED", "CANCELLED"}
)
_ALREADY_PROCESSING_MESSAGE = "This request is already being processed."
_CANCELLED_MESSAGE = "The request was cancelled."


def contained_foreground_result(
    execution_kind: ExecutionKind,
    result: object,
) -> ForegroundResult:
    """Keep only the closed result family for one execution kind."""

    expected_types = (
        _SUBMISSION_RESULT_TYPES
        if execution_kind is ExecutionKind.SUBMISSION
        else _RECOVERY_RESULT_TYPES
    )
    if isinstance(result, expected_types):
        return result
    return ForegroundExecutionFailureView(execution_kind)


def _configuration_message(result: ConfigurationFailureResult) -> str:
    error = result.error
    return f"{error.safe_message}\n{error.file}: {error.key}"


def _existing_run_view(result: ExistingRunResult) -> TerminalPresentationView:
    status = result.processing_status.value
    if status == "SUCCEEDED":
        return TerminalPresentationView(
            ShellState.EXISTING_RUN,
            result.result_kind,
            assistant_text=result.assistant_text or "",
            submission_permitted_after_cleanup=True,
        )
    if status == "NEEDS_CLARIFICATION":
        return TerminalPresentationView(
            ShellState.EXISTING_RUN,
            result.result_kind,
            clarification_text=(
                "" if result.clarification is None else result.clarification.question_text
            ),
            submission_permitted_after_cleanup=True,
        )
    if status in _TERMINAL_PROCESSING_STATUSES:
        return TerminalPresentationView(
            ShellState.EXISTING_RUN,
            result.result_kind,
            status_message=(
                "" if result.safe_failure is None else result.safe_failure.safe_message
            ),
            submission_permitted_after_cleanup=True,
        )
    return TerminalPresentationView(
        ShellState.EXISTING_RUN,
        result.result_kind,
        status_message=_ALREADY_PROCESSING_MESSAGE,
        submission_permitted_after_cleanup=False,
    )


def _persistence_allows_submission(result: PersistenceFailureResult) -> bool:
    if result.processing_run_id is None and result.processing_status is None:
        return True
    return bool(
        result.failure_persisted
        and result.processing_status is not None
        and result.processing_status.value in _TERMINAL_PROCESSING_STATUSES
    )


def _terminal_result_view(result: ProcessUserMessageResult) -> TerminalPresentationView:
    if isinstance(result, SucceededResult):
        return TerminalPresentationView(
            ShellState.SUCCESS,
            result.result_kind,
            assistant_text=result.assistant_text,
            submission_permitted_after_cleanup=True,
        )
    if isinstance(result, ClarificationResult):
        return TerminalPresentationView(
            ShellState.CLARIFICATION,
            result.result_kind,
            clarification_text=result.clarification.question_text,
            submission_permitted_after_cleanup=True,
        )
    if isinstance(result, CancelledResult):
        return TerminalPresentationView(
            ShellState.CANCELLED,
            result.result_kind,
            status_message=(
                _CANCELLED_MESSAGE
                if result.safe_failure is None
                else result.safe_failure.safe_message
            ),
            submission_permitted_after_cleanup=True,
        )
    if isinstance(
        result,
        (
            ValidationExhaustedResult,
            ConcurrencyConflictResult,
            ControlledFailureResult,
        ),
    ):
        return TerminalPresentationView(
            ShellState.CONTROLLED_FAILURE,
            result.result_kind,
            status_message=result.error.safe_message,
            submission_permitted_after_cleanup=True,
        )
    if isinstance(result, ConfigurationFailureResult):
        return TerminalPresentationView(
            ShellState.CONTROLLED_FAILURE,
            result.result_kind,
            status_message=_configuration_message(result),
            submission_permitted_after_cleanup=False,
        )
    if isinstance(result, BusyResult):
        return TerminalPresentationView(
            ShellState.BUSY,
            result.result_kind,
            status_message=result.error.safe_message,
            submission_permitted_after_cleanup=False,
        )
    if isinstance(result, ExistingRunResult):
        return _existing_run_view(result)
    if isinstance(result, PersistenceFailureResult):
        return TerminalPresentationView(
            ShellState.PERSISTENCE_FAILURE,
            result.result_kind,
            status_message=result.error.safe_message,
            submission_permitted_after_cleanup=_persistence_allows_submission(result),
        )
    raise TypeError("Unknown closed submission result.")


def terminal_presentation_view(
    execution_kind: ExecutionKind,
    result: ForegroundResult,
) -> TerminalPresentationView:
    """Map one already-contained foreground result to safe primitive fields."""

    if isinstance(result, ForegroundExecutionFailureView):
        state = (
            ShellState.CONTROLLED_FAILURE
            if execution_kind is ExecutionKind.SUBMISSION
            else ShellState.RECOVERY_FAILURE
        )
        return TerminalPresentationView(
            state,
            result.result_kind,
            status_message=result.safe_message,
            submission_permitted_after_cleanup=False,
        )
    if execution_kind is ExecutionKind.SUBMISSION:
        if not isinstance(result, _SUBMISSION_RESULT_TYPES):
            raise TypeError("Submission envelope contains a recovery result.")
        return _terminal_result_view(result)
    if isinstance(result, NoRecoveryRequiredResult):
        return TerminalPresentationView(
            ShellState.IDLE,
            submission_permitted_after_cleanup=True,
        )
    if isinstance(result, RecoveryCompletedResult):
        return _terminal_result_view(result.outcome)
    if isinstance(result, ConfigurationFailureResult):
        return TerminalPresentationView(
            ShellState.RECOVERY_FAILURE,
            result.result_kind,
            status_message=_configuration_message(result),
            submission_permitted_after_cleanup=False,
        )
    if isinstance(result, PersistenceFailureResult):
        return TerminalPresentationView(
            ShellState.RECOVERY_FAILURE,
            result.result_kind,
            status_message=result.error.safe_message,
            submission_permitted_after_cleanup=False,
        )
    raise TypeError("Unknown closed recovery result.")


__all__ = [
    "ExecutionKind",
    "ForegroundExecutionFailureView",
    "ForegroundTerminalEnvelope",
    "MonotonicCancellationToken",
    "ShellState",
    "TerminalPresentationView",
    "contained_foreground_result",
    "terminal_presentation_view",
]
