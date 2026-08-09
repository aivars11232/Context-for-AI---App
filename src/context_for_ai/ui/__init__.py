"""GUI-thread shell facade and immutable presentation values."""

from context_for_ai.ui.presentation import (
    ContextInspectionPageState,
    ContextInspectionPresentationView,
    ExecutionKind,
    ForegroundExecutionFailureView,
    ForegroundTerminalEnvelope,
    InspectionCollectionPresentation,
    InspectionExecutionFailureView,
    InspectionListItemPresentation,
    InspectionResultPresentation,
    InspectionScalarPresentation,
    InspectionSectionPresentation,
    InspectionTerminalEnvelope,
    MonotonicCancellationToken,
    Route,
    ShellState,
    TerminalPresentationView,
)
from context_for_ai.ui.shell import ShellFacade
from context_for_ai.ui.startup import (
    NativeStartupErrorPresenter,
    StartupErrorPresenter,
    StartupFailureKind,
    StartupFailureView,
    StartupPresentationMode,
    safe_stderr_record,
    startup_failure_for_preparation,
)


__all__ = [
    "ExecutionKind",
    "ContextInspectionPageState",
    "ContextInspectionPresentationView",
    "ForegroundExecutionFailureView",
    "ForegroundTerminalEnvelope",
    "InspectionCollectionPresentation",
    "InspectionExecutionFailureView",
    "InspectionListItemPresentation",
    "InspectionResultPresentation",
    "InspectionScalarPresentation",
    "InspectionSectionPresentation",
    "InspectionTerminalEnvelope",
    "MonotonicCancellationToken",
    "NativeStartupErrorPresenter",
    "Route",
    "ShellFacade",
    "ShellState",
    "StartupErrorPresenter",
    "StartupFailureKind",
    "StartupFailureView",
    "StartupPresentationMode",
    "TerminalPresentationView",
    "safe_stderr_record",
    "startup_failure_for_preparation",
]
