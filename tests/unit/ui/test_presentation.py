"""Tests for Qt-independent shell presentation values and closed mapping."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import threading
from unittest.mock import Mock

import pytest

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
    RecoveryCompletedResult,
    SucceededResult,
    ValidationExhaustedResult,
)
from context_for_ai.ui.presentation import (
    ExecutionKind,
    ForegroundExecutionFailureView,
    ForegroundTerminalEnvelope,
    MonotonicCancellationToken,
    ShellState,
    contained_foreground_result,
    terminal_presentation_view,
)


def dto(result_type: type[object], **attributes: object) -> object:
    value = Mock(spec=result_type)
    for name, attribute in attributes.items():
        setattr(value, name, attribute)
    return value


def error(message: str = "Safe failure.") -> SimpleNamespace:
    return SimpleNamespace(safe_message=message)


def status(value: str) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def test_shell_state_is_the_exact_closed_fourteen_value_set() -> None:
    assert tuple(state.value for state in ShellState) == (
        "STARTUP",
        "RECOVERY",
        "IDLE",
        "PENDING",
        "CANCELLATION_REQUESTED",
        "CANCELLED",
        "CLARIFICATION",
        "SUCCESS",
        "CONTROLLED_FAILURE",
        "BUSY",
        "EXISTING_RUN",
        "PERSISTENCE_FAILURE",
        "RECOVERY_FAILURE",
        "SHUTDOWN",
    )


def test_cancellation_is_thread_safe_idempotent_and_monotonic() -> None:
    token = MonotonicCancellationToken()
    barrier = threading.Barrier(17)
    outcomes: list[bool] = []
    lock = threading.Lock()

    def cancel() -> None:
        barrier.wait()
        outcome = token.request_cancellation()
        with lock:
            outcomes.append(outcome)

    workers = [threading.Thread(target=cancel) for _ in range(16)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 15
    assert token.is_cancelled() is True
    assert token.request_cancellation() is False
    assert token.is_cancelled() is True


@pytest.mark.parametrize(
    ("kind", "message"),
    (
        (ExecutionKind.SUBMISSION, "Processing could not be completed safely."),
        (
            ExecutionKind.RECOVERY,
            "Previous processing could not be recovered safely.",
        ),
    ),
)
def test_execution_failure_is_exact_content_free_and_frozen(
    kind: ExecutionKind,
    message: str,
) -> None:
    failure = ForegroundExecutionFailureView(kind)

    assert failure.result_kind == "FOREGROUND_EXECUTION_FAILURE"
    assert failure.code == "APPLICATION_EXECUTION_FAILED"
    assert failure.safe_message == message
    with pytest.raises(FrozenInstanceError):
        failure.safe_message = "unsafe"  # type: ignore[misc]


def test_terminal_envelope_is_frozen_and_requires_positive_execution_id() -> None:
    failure = ForegroundExecutionFailureView(ExecutionKind.SUBMISSION)
    envelope = ForegroundTerminalEnvelope(
        1,
        ExecutionKind.SUBMISSION,
        failure,
    )

    assert envelope.result is failure
    with pytest.raises(FrozenInstanceError):
        envelope.execution_id = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="positive"):
        ForegroundTerminalEnvelope(0, ExecutionKind.SUBMISSION, failure)


def test_wrong_or_unknown_worker_values_become_closed_execution_failure() -> None:
    wrong_family = NoRecoveryRequiredResult()

    unknown = contained_foreground_result(ExecutionKind.SUBMISSION, object())
    wrong = contained_foreground_result(ExecutionKind.SUBMISSION, wrong_family)

    assert unknown == ForegroundExecutionFailureView(ExecutionKind.SUBMISSION)
    assert wrong == unknown
    assert contained_foreground_result(
        ExecutionKind.RECOVERY,
        wrong_family,
    ) is wrong_family


@pytest.mark.parametrize(
    ("result", "expected"),
    (
        (
            dto(
                SucceededResult,
                result_kind="SUCCEEDED",
                assistant_text="Exact result — café\n",
            ),
            (ShellState.SUCCESS, "SUCCEEDED", "", "Exact result — café\n", "", True),
        ),
        (
            dto(
                ClarificationResult,
                result_kind="CLARIFICATION_REQUIRED",
                clarification=SimpleNamespace(question_text="Which one?"),
            ),
            (
                ShellState.CLARIFICATION,
                "CLARIFICATION_REQUIRED",
                "",
                "",
                "Which one?",
                True,
            ),
        ),
        (
            dto(CancelledResult, result_kind="CANCELLED", safe_failure=None),
            (
                ShellState.CANCELLED,
                "CANCELLED",
                "The request was cancelled.",
                "",
                "",
                True,
            ),
        ),
        (
            dto(
                CancelledResult,
                result_kind="CANCELLED",
                safe_failure=error("Persisted cancellation."),
            ),
            (
                ShellState.CANCELLED,
                "CANCELLED",
                "Persisted cancellation.",
                "",
                "",
                True,
            ),
        ),
        (
            dto(
                ValidationExhaustedResult,
                result_kind="VALIDATION_EXHAUSTED",
                error=error("Validation failed."),
            ),
            (
                ShellState.CONTROLLED_FAILURE,
                "VALIDATION_EXHAUSTED",
                "Validation failed.",
                "",
                "",
                True,
            ),
        ),
        (
            dto(
                ConcurrencyConflictResult,
                result_kind="CONCURRENCY_CONFLICT",
                error=error("Conversation changed."),
            ),
            (
                ShellState.CONTROLLED_FAILURE,
                "CONCURRENCY_CONFLICT",
                "Conversation changed.",
                "",
                "",
                True,
            ),
        ),
        (
            dto(
                ControlledFailureResult,
                result_kind="CONTROLLED_FAILURE",
                error=error("Provider unavailable."),
            ),
            (
                ShellState.CONTROLLED_FAILURE,
                "CONTROLLED_FAILURE",
                "Provider unavailable.",
                "",
                "",
                True,
            ),
        ),
        (
            dto(
                ConfigurationFailureResult,
                result_kind="CONFIGURATION_FAILURE",
                error=SimpleNamespace(
                    safe_message="The application configuration is invalid.",
                    file="models.yaml",
                    key="model.name",
                ),
            ),
            (
                ShellState.CONTROLLED_FAILURE,
                "CONFIGURATION_FAILURE",
                "The application configuration is invalid.\nmodels.yaml: model.name",
                "",
                "",
                False,
            ),
        ),
        (
            dto(BusyResult, result_kind="BUSY", error=error("Already busy.")),
            (ShellState.BUSY, "BUSY", "Already busy.", "", "", False),
        ),
        (
            dto(
                PersistenceFailureResult,
                result_kind="PERSISTENCE_FAILURE",
                error=error("Save failed."),
                processing_run_id=None,
                processing_status=None,
                failure_persisted=False,
            ),
            (
                ShellState.PERSISTENCE_FAILURE,
                "PERSISTENCE_FAILURE",
                "Save failed.",
                "",
                "",
                True,
            ),
        ),
        (
            dto(
                PersistenceFailureResult,
                result_kind="PERSISTENCE_FAILURE",
                error=error("Save failed."),
                processing_run_id=object(),
                processing_status=status("GENERATING"),
                failure_persisted=False,
            ),
            (
                ShellState.PERSISTENCE_FAILURE,
                "PERSISTENCE_FAILURE",
                "Save failed.",
                "",
                "",
                False,
            ),
        ),
        (
            dto(
                ExistingRunResult,
                result_kind="EXISTING_RUN",
                processing_status=status("SUCCEEDED"),
                assistant_text="Existing exact text",
                clarification=None,
                safe_failure=None,
            ),
            (
                ShellState.EXISTING_RUN,
                "EXISTING_RUN",
                "",
                "Existing exact text",
                "",
                True,
            ),
        ),
        (
            dto(
                ExistingRunResult,
                result_kind="EXISTING_RUN",
                processing_status=status("NEEDS_CLARIFICATION"),
                assistant_text=None,
                clarification=SimpleNamespace(question_text="Clarify existing."),
                safe_failure=None,
            ),
            (
                ShellState.EXISTING_RUN,
                "EXISTING_RUN",
                "",
                "",
                "Clarify existing.",
                True,
            ),
        ),
        (
            dto(
                ExistingRunResult,
                result_kind="EXISTING_RUN",
                processing_status=status("FAILED"),
                assistant_text=None,
                clarification=None,
                safe_failure=error("Existing failed safely."),
            ),
            (
                ShellState.EXISTING_RUN,
                "EXISTING_RUN",
                "Existing failed safely.",
                "",
                "",
                True,
            ),
        ),
        (
            dto(
                ExistingRunResult,
                result_kind="EXISTING_RUN",
                processing_status=status("GENERATING"),
                assistant_text=None,
                clarification=None,
                safe_failure=None,
            ),
            (
                ShellState.EXISTING_RUN,
                "EXISTING_RUN",
                "This request is already being processed.",
                "",
                "",
                False,
            ),
        ),
    ),
)
def test_every_submission_result_variant_maps_to_closed_safe_fields(
    result: object,
    expected: tuple[ShellState, str, str, str, str, bool],
) -> None:
    view = terminal_presentation_view(
        ExecutionKind.SUBMISSION,
        result,  # type: ignore[arg-type]
    )

    assert (
        view.state,
        view.status_kind,
        view.status_message,
        view.assistant_text,
        view.clarification_text,
        view.submission_permitted_after_cleanup,
    ) == expected


def test_recovery_result_variants_are_unwrapped_or_fail_closed() -> None:
    outcome = dto(
        SucceededResult,
        result_kind="SUCCEEDED",
        assistant_text="Recovered exact text",
    )
    completed = dto(RecoveryCompletedResult, outcome=outcome)
    configuration = dto(
        ConfigurationFailureResult,
        result_kind="CONFIGURATION_FAILURE",
        error=SimpleNamespace(
            safe_message="The application configuration is invalid.",
            file="app.yaml",
            key="app.environment",
        ),
    )
    persistence = dto(
        PersistenceFailureResult,
        result_kind="PERSISTENCE_FAILURE",
        error=error("Recovery save failed."),
    )

    idle = terminal_presentation_view(
        ExecutionKind.RECOVERY,
        NoRecoveryRequiredResult(),
    )
    success = terminal_presentation_view(
        ExecutionKind.RECOVERY,
        completed,  # type: ignore[arg-type]
    )
    configuration_failure = terminal_presentation_view(
        ExecutionKind.RECOVERY,
        configuration,  # type: ignore[arg-type]
    )
    persistence_failure = terminal_presentation_view(
        ExecutionKind.RECOVERY,
        persistence,  # type: ignore[arg-type]
    )
    boundary_failure = terminal_presentation_view(
        ExecutionKind.RECOVERY,
        ForegroundExecutionFailureView(ExecutionKind.RECOVERY),
    )

    assert idle.state is ShellState.IDLE
    assert idle.status_kind == ""
    assert idle.submission_permitted_after_cleanup is True
    assert success.state is ShellState.SUCCESS
    assert success.assistant_text == "Recovered exact text"
    assert configuration_failure.state is ShellState.RECOVERY_FAILURE
    assert configuration_failure.status_message.endswith(
        "\napp.yaml: app.environment"
    )
    assert persistence_failure.state is ShellState.RECOVERY_FAILURE
    assert persistence_failure.status_message == "Recovery save failed."
    assert boundary_failure.state is ShellState.RECOVERY_FAILURE
    assert boundary_failure.status_message == (
        "Previous processing could not be recovered safely."
    )
    assert all(
        not view.submission_permitted_after_cleanup
        for view in (
            configuration_failure,
            persistence_failure,
            boundary_failure,
        )
    )
