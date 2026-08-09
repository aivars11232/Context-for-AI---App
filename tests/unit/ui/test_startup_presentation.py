"""Unit tests for closed pre-shell startup failure presentation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import StringIO

import pytest

from context_for_ai.application import (
    ShellPreparationFailureKind,
    ShellPreparationFailureResult,
)
from context_for_ai.ui.startup import (
    NativeStartupErrorPresenter,
    StartupFailureKind,
    StartupFailureView,
    StartupPresentationMode,
    safe_stderr_record,
    startup_failure_for_preparation,
)


@pytest.mark.parametrize(
    ("kind", "code", "message"),
    (
        (
            StartupFailureKind.CONFIGURATION,
            "CONFIGURATION_INVALID",
            "The application configuration is invalid.",
        ),
        (
            StartupFailureKind.MIGRATION,
            "MIGRATION_FAILED",
            "The local database could not be prepared safely.",
        ),
        (
            StartupFailureKind.COMPOSITION,
            "APPLICATION_STARTUP_FAILED",
            "The application could not be started safely.",
        ),
        (
            StartupFailureKind.QML_LOAD,
            "QML_LOAD_FAILED",
            "The application window could not be opened.",
        ),
        (
            StartupFailureKind.RECOVERY_PREFLIGHT,
            "RECOVERY_PREFLIGHT_FAILED",
            "Previous processing state could not be inspected safely.",
        ),
    ),
)
def test_startup_failure_algebra_has_exact_closed_values(
    kind: StartupFailureKind,
    code: str,
    message: str,
) -> None:
    failure = (
        StartupFailureView(kind, "models.yaml", "model.name")
        if kind is StartupFailureKind.CONFIGURATION
        else StartupFailureView(kind)
    )

    assert failure.code == code
    assert failure.safe_message == message
    with pytest.raises(FrozenInstanceError):
        failure.safe_message = "unsafe"  # type: ignore[misc]


def test_only_configuration_may_expose_a_safe_file_and_key() -> None:
    generic = StartupFailureView(StartupFailureKind.CONFIGURATION)
    assert generic.file is None
    assert generic.key is None
    with pytest.raises(ValueError, match="key requires"):
        StartupFailureView(StartupFailureKind.CONFIGURATION, key="model.name")
    with pytest.raises(ValueError, match="must not be a path"):
        StartupFailureView(
            StartupFailureKind.CONFIGURATION,
            "/private/config/models.yaml",
            "model.name",
        )
    with pytest.raises(ValueError, match="safe non-empty"):
        StartupFailureView(
            StartupFailureKind.CONFIGURATION,
            "models.yaml",
            "model.name\nsecret",
        )
    with pytest.raises(ValueError, match="Only configuration"):
        StartupFailureView(
            StartupFailureKind.MIGRATION,
            "models.yaml",
            None,
        )


def test_preparation_failures_map_to_recovery_preflight_or_generic_composition() -> None:
    preflight = startup_failure_for_preparation(
        ShellPreparationFailureResult(
            ShellPreparationFailureKind.RECOVERY_PREFLIGHT_FAILED
        )
    )
    setup = startup_failure_for_preparation(
        ShellPreparationFailureResult(
            ShellPreparationFailureKind.CONVERSATION_SETUP_FAILED
        )
    )

    assert preflight.failure_kind is StartupFailureKind.RECOVERY_PREFLIGHT
    assert setup.failure_kind is StartupFailureKind.COMPOSITION
    assert setup.code == "APPLICATION_STARTUP_FAILED"


def test_safe_stderr_record_is_one_line_and_contains_only_allowlisted_location() -> None:
    failure = StartupFailureView(
        StartupFailureKind.CONFIGURATION,
        "context.yaml",
        "context.maximum_prompt_tokens",
    )

    record = safe_stderr_record(failure)

    assert record == (
        "Context for AI startup error (CONFIGURATION_INVALID): "
        "The application configuration is invalid. "
        "[context.yaml:context.maximum_prompt_tokens]"
    )
    assert "\n" not in record
    assert "/" not in record


def test_presenter_writes_once_and_uses_modal_only_for_interactive_mode() -> None:
    stderr = StringIO()
    modal_calls: list[StartupFailureView] = []
    presenter = NativeStartupErrorPresenter(
        stderr=stderr,
        modal=modal_calls.append,
    )
    failure = StartupFailureView(StartupFailureKind.QML_LOAD)

    presenter.present(failure, StartupPresentationMode.NON_INTERACTIVE)
    assert stderr.getvalue().splitlines() == [safe_stderr_record(failure)]
    assert modal_calls == []

    stderr.seek(0)
    stderr.truncate(0)
    presenter.present(failure, StartupPresentationMode.INTERACTIVE)
    assert stderr.getvalue().splitlines() == [safe_stderr_record(failure)]
    assert modal_calls == [failure]


def test_modal_failure_cannot_replace_or_expand_safe_stderr_projection() -> None:
    stderr = StringIO()

    def broken_modal(_: StartupFailureView) -> None:
        raise RuntimeError("unsafe modal defect /private/path")

    presenter = NativeStartupErrorPresenter(stderr=stderr, modal=broken_modal)
    failure = StartupFailureView(StartupFailureKind.COMPOSITION)

    presenter.present(failure, StartupPresentationMode.INTERACTIVE)

    output = stderr.getvalue()
    assert output.splitlines() == [safe_stderr_record(failure)]
    assert "unsafe" not in output
    assert "/private" not in output
