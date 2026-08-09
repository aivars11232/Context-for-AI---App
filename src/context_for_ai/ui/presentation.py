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
    ContextInspectionEmptyResult,
    ContextInspectionLoadFailureResult,
    ContextInspectionReadyResult,
    ContextInspectionView,
    DomainId,
    ExistingRunResult,
    InspectionAvailability,
    InspectionRunOutcome,
    NoRecoveryRequiredResult,
    PersistenceFailureResult,
    ProcessUserMessageResult,
    RecoveryCompletedResult,
    RecoveryResult,
    SucceededResult,
    ValidationExhaustedResult,
)


@unique
class Route(StrEnum):
    CHAT = "CHAT"
    CONTEXT_INSPECTION = "CONTEXT_INSPECTION"


@unique
class ContextInspectionPageState(StrEnum):
    INACTIVE = "INACTIVE"
    LOADING = "LOADING"
    READY = "READY"
    EMPTY = "EMPTY"
    CLARIFICATION = "CLARIFICATION"
    CONTROLLED_FAILURE = "CONTROLLED_FAILURE"
    LOAD_ERROR = "LOAD_ERROR"
    SHUTDOWN = "SHUTDOWN"


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
class InspectionExecutionFailureView:
    """Content-free containment for an unexpected inspection-worker defect."""

    result_kind: Literal["INSPECTION_EXECUTION_FAILURE"] = field(
        init=False,
        default="INSPECTION_EXECUTION_FAILURE",
    )
    code: Literal["INSPECTION_EXECUTION_FAILED"] = field(
        init=False,
        default="INSPECTION_EXECUTION_FAILED",
    )
    safe_message: Literal[
        "Context inspection could not be loaded safely."
    ] = field(
        init=False,
        default="Context inspection could not be loaded safely.",
    )


type InspectionResult = (
    ContextInspectionReadyResult
    | ContextInspectionEmptyResult
    | ContextInspectionLoadFailureResult
    | InspectionExecutionFailureView
)


@dataclass(frozen=True, slots=True)
class InspectionTerminalEnvelope:
    """The sole immutable result value permitted from one inspection worker."""

    generation: int
    conversation_id: DomainId
    result: InspectionResult

    def __post_init__(self) -> None:
        if (
            not isinstance(self.generation, int)
            or isinstance(self.generation, bool)
            or self.generation < 1
        ):
            raise ValueError("Inspection generation must be a positive integer.")
        if not isinstance(self.conversation_id, DomainId):
            raise ValueError("Inspection envelope requires a conversation ID.")
        if not isinstance(
            self.result,
            (
                ContextInspectionReadyResult,
                ContextInspectionEmptyResult,
                ContextInspectionLoadFailureResult,
                InspectionExecutionFailureView,
            ),
        ):
            raise ValueError("Inspection envelope requires a closed safe result.")


@dataclass(frozen=True, slots=True)
class InspectionScalarPresentation:
    """One primitive scalar row with its complete accessible name."""

    label: str
    display_text: str
    accessible_name: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("Inspection scalar label must be non-empty text.")
        if not isinstance(self.display_text, str):
            raise ValueError("Inspection scalar value must be text.")
        object.__setattr__(
            self,
            "accessible_name",
            f"{self.label}: {self.display_text}",
        )


@dataclass(frozen=True, slots=True)
class InspectionListItemPresentation:
    """One primitive inspection list item and any contracted nested lists."""

    accessible_name: str
    scalars: tuple[InspectionScalarPresentation, ...] = ()
    collections: tuple[InspectionCollectionPresentation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.accessible_name, str) or not self.accessible_name:
            raise ValueError("Inspection list item name must be non-empty text.")
        object.__setattr__(self, "scalars", tuple(self.scalars))
        object.__setattr__(self, "collections", tuple(self.collections))


@dataclass(frozen=True, slots=True)
class InspectionCollectionPresentation:
    """One primitive list projection with explicit availability placeholder."""

    accessible_id: str
    accessible_name: str
    availability: str
    display_text: str
    items: tuple[InspectionListItemPresentation, ...]

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (
                self.accessible_id,
                self.accessible_name,
                self.availability,
            )
        ) or not isinstance(self.display_text, str):
            raise ValueError("Inspection collection metadata must be primitive text.")
        items = tuple(self.items)
        object.__setattr__(self, "items", items)
        available = self.availability == InspectionAvailability.AVAILABLE.value
        if available != bool(items):
            raise ValueError(
                "Inspection collection items must match AVAILABLE availability."
            )
        if available and self.display_text:
            raise ValueError("Available inspection collection has no placeholder.")
        if not available and not self.display_text:
            raise ValueError("Unavailable inspection collection requires a placeholder.")


@dataclass(frozen=True, slots=True)
class InspectionSectionPresentation:
    """One of the nine ordered, named context-inspection groups."""

    accessible_id: str
    accessible_name: str
    scalars: tuple[InspectionScalarPresentation, ...]
    collections: tuple[InspectionCollectionPresentation, ...]

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (self.accessible_id, self.accessible_name)
        ):
            raise ValueError("Inspection section identity must be non-empty text.")
        object.__setattr__(self, "scalars", tuple(self.scalars))
        object.__setattr__(self, "collections", tuple(self.collections))


_SECTION_IDENTITIES = (
    ("contextInspectionSectionTarget", "Inspected request"),
    ("contextInspectionSectionActiveState", "Active state"),
    ("contextInspectionSectionInterpretation", "Interpretation"),
    ("contextInspectionSectionReferences", "References"),
    ("contextInspectionSectionConstraints", "Constraints and conflicts"),
    ("contextInspectionSectionMemories", "Retrieved memories"),
    ("contextInspectionSectionConfidence", "Confidence"),
    ("contextInspectionSectionValidation", "Validation"),
    ("contextInspectionSectionFinalStatus", "Final status"),
)


@dataclass(frozen=True, slots=True)
class ContextInspectionPresentationView:
    """Complete primitive-only nine-section projection retained by the facade."""

    outcome: str
    sections: tuple[InspectionSectionPresentation, ...]

    def __post_init__(self) -> None:
        if self.outcome not in {value.value for value in InspectionRunOutcome}:
            raise ValueError("Inspection presentation outcome must be closed.")
        sections = tuple(self.sections)
        identities = tuple(
            (section.accessible_id, section.accessible_name) for section in sections
        )
        if identities != _SECTION_IDENTITIES:
            raise ValueError("Inspection presentation requires all nine ordered groups.")
        object.__setattr__(self, "sections", sections)


@dataclass(frozen=True, slots=True)
class InspectionResultPresentation:
    """One accepted inspection result transition rendered entirely from safe data."""

    state: ContextInspectionPageState
    status_text: str
    announcement_text: str
    view: ContextInspectionPresentationView | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ContextInspectionPageState):
            raise ValueError("Inspection result presentation state must be closed.")
        if not isinstance(self.status_text, str) or not isinstance(
            self.announcement_text,
            str,
        ):
            raise ValueError("Inspection result status values must be text.")
        if (self.view is not None) != (
            self.state
            in {
                ContextInspectionPageState.READY,
                ContextInspectionPageState.CLARIFICATION,
                ContextInspectionPageState.CONTROLLED_FAILURE,
            }
        ):
            raise ValueError("Inspection result data must match its loaded page state.")


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


def contained_inspection_result(result: object) -> InspectionResult:
    """Keep only the closed safe result family at the inspection boundary."""

    if isinstance(
        result,
        (
            ContextInspectionReadyResult,
            ContextInspectionEmptyResult,
            ContextInspectionLoadFailureResult,
            InspectionExecutionFailureView,
        ),
    ):
        return result
    return InspectionExecutionFailureView()


def _scalar(label: str, display_text: str) -> InspectionScalarPresentation:
    return InspectionScalarPresentation(label, display_text)


def _collection_projection(
    *,
    accessible_id: str,
    accessible_name: str,
    availability: InspectionAvailability,
    display_text: str,
    items: tuple[InspectionListItemPresentation, ...],
) -> InspectionCollectionPresentation:
    return InspectionCollectionPresentation(
        accessible_id,
        accessible_name,
        availability.value,
        display_text,
        items,
    )


def _nested_collection(
    *,
    accessible_id: str,
    accessible_name: str,
    items: tuple[InspectionListItemPresentation, ...],
) -> InspectionCollectionPresentation:
    return _collection_projection(
        accessible_id=accessible_id,
        accessible_name=accessible_name,
        availability=(
            InspectionAvailability.AVAILABLE
            if items
            else InspectionAvailability.EMPTY
        ),
        display_text="" if items else "None recorded.",
        items=items,
    )


def _qualifier_collection(view: ContextInspectionView) -> InspectionCollectionPresentation:
    source = view.qualifier_evidence
    items = tuple(
        InspectionListItemPresentation(
            accessible_name=(
                f"Qualifier {item.ordinal}: {item.kind.display_label}, "
                f"{item.matched_text}"
            ),
            scalars=(
                _scalar("Kind", item.kind.display_label),
                _scalar("Rule", item.rule_id),
                _scalar("Matched text", item.matched_text),
            ),
        )
        for item in source.items
    )
    return _collection_projection(
        accessible_id="contextInspectionQualifiers",
        accessible_name="Qualifier evidence",
        availability=source.availability,
        display_text=source.display_text,
        items=items,
    )


def _reference_collection(view: ContextInspectionView) -> InspectionCollectionPresentation:
    source = view.references
    items: list[InspectionListItemPresentation] = []
    for item in source.items:
        evidence_items: list[InspectionListItemPresentation] = []
        for evidence in item.evidence:
            scalars = [
                _scalar("Rank reason", evidence.rank_reason.display_label),
                _scalar("Score", evidence.score.display_text),
            ]
            if evidence.candidate_display_name is not None:
                scalars.append(
                    _scalar("Candidate", evidence.candidate_display_name)
                )
            if evidence.candidate_type is not None:
                scalars.append(
                    _scalar("Candidate type", evidence.candidate_type.display_label)
                )
            if evidence.evidence_message is not None:
                scalars.append(
                    _scalar(
                        "Evidence message",
                        evidence.evidence_message.display_text,
                    )
                )
            if evidence.activity_display_text is not None:
                scalars.append(
                    _scalar("Activity", evidence.activity_display_text)
                )
            evidence_items.append(
                InspectionListItemPresentation(
                    accessible_name=(
                        f"Reference {item.mention_number} evidence {evidence.rank}: "
                        f"{evidence.rank_reason.display_label}, score "
                        f"{evidence.score.display_text}"
                    ),
                    scalars=tuple(scalars),
                )
            )
        nested = _nested_collection(
            accessible_id=(
                f"contextInspectionReferenceEvidence-{item.mention_number}"
            ),
            accessible_name=f"Evidence for reference {item.mention_number}",
            items=tuple(evidence_items),
        )
        items.append(
            InspectionListItemPresentation(
                accessible_name=(
                    f"Reference {item.mention_number}: {item.surface_text}, "
                    f"{item.status.display_label}"
                ),
                scalars=(
                    _scalar("Surface text", item.surface_text),
                    _scalar("Status", item.status.display_label),
                    _scalar(
                        "Resolved display name",
                        item.resolved_display_name.display_text,
                    ),
                    _scalar("Source message", item.source_message.display_text),
                    _scalar("Confidence", item.confidence.display_text),
                ),
                collections=(nested,),
            )
        )
    return _collection_projection(
        accessible_id="contextInspectionReferences",
        accessible_name="References",
        availability=source.availability,
        display_text=source.display_text,
        items=tuple(items),
    )


def _constraint_collection(view: ContextInspectionView) -> InspectionCollectionPresentation:
    source = view.constraints
    items: list[InspectionListItemPresentation] = []
    for item in source.items:
        scalars = [
            _scalar("Type", item.type.display_label),
            _scalar("Scope", item.scope.display_label),
            _scalar("Rule", item.normalized_rule),
            _scalar("Priority", str(item.priority)),
            _scalar("Source kind", item.source_kind.display_label),
            _scalar("Source text", item.source_text),
            _scalar("Confidence", item.confidence.display_text),
            _scalar("Resolution", item.resolution_status.display_label),
        ]
        if item.underlying_type is not None:
            scalars.append(
                _scalar("Underlying type", item.underlying_type.display_label)
            )
        if item.condition is not None:
            scalars.extend(
                (
                    _scalar("Condition grammar", item.condition.grammar_version),
                    _scalar("Condition kind", item.condition.kind.display_label),
                    _scalar("Condition expected value", item.condition.expected_value),
                    _scalar(
                        "Condition evaluation",
                        item.condition.evaluation.display_label,
                    ),
                )
            )
        items.append(
            InspectionListItemPresentation(
                accessible_name=(
                    f"Constraint {item.ordinal}: {item.type.display_label}, "
                    f"{item.resolution_status.display_label}"
                ),
                scalars=tuple(scalars),
            )
        )
    return _collection_projection(
        accessible_id="contextInspectionConstraints",
        accessible_name="Constraints",
        availability=source.availability,
        display_text=source.display_text,
        items=tuple(items),
    )


def _conflict_collection(view: ContextInspectionView) -> InspectionCollectionPresentation:
    source = view.conflicts
    items: list[InspectionListItemPresentation] = []
    for item in source.items:
        rule_items = tuple(
            InspectionListItemPresentation(
                accessible_name=(
                    f"Conflict {item.ordinal} rule {rule.constraint_ordinal}: "
                    f"{rule.type.display_label}, {rule.normalized_rule}"
                ),
                scalars=(
                    _scalar("Type", rule.type.display_label),
                    _scalar("Rule", rule.normalized_rule),
                    _scalar("Source text", rule.source_text),
                ),
            )
            for rule in item.rules
        )
        items.append(
            InspectionListItemPresentation(
                accessible_name=(
                    f"Conflict {item.ordinal}: {len(item.rules)} rules"
                ),
                scalars=(_scalar("Rule count", str(len(item.rules))),),
                collections=(
                    _nested_collection(
                        accessible_id=(
                            f"contextInspectionConflictRules-{item.ordinal}"
                        ),
                        accessible_name=f"Rules in conflict {item.ordinal}",
                        items=rule_items,
                    ),
                ),
            )
        )
    return _collection_projection(
        accessible_id="contextInspectionConflicts",
        accessible_name="Conflicts",
        availability=source.availability,
        display_text=source.display_text,
        items=tuple(items),
    )


def _memory_collection(view: ContextInspectionView) -> InspectionCollectionPresentation:
    source = view.retrieved_memories
    items = tuple(
        InspectionListItemPresentation(
            accessible_name=(
                f"Retrieved memory {item.rank}: score "
                f"{item.retrieval_score.display_text}"
            ),
            scalars=(
                _scalar("Content", item.content),
                _scalar("Scope", item.scope.display_label),
                _scalar("Memory confidence", item.memory_confidence.display_text),
                _scalar("Retrieval score", item.retrieval_score.display_text),
                *tuple(
                    _scalar(f"Retrieval reason {index}", reason)
                    for index, reason in enumerate(item.reasons, start=1)
                ),
            ),
        )
        for item in source.items
    )
    return _collection_projection(
        accessible_id="contextInspectionMemories",
        accessible_name="Retrieved memories",
        availability=source.availability,
        display_text=source.display_text,
        items=items,
    )


def _validation_projection(
    view: ContextInspectionView,
) -> tuple[
    tuple[InspectionScalarPresentation, ...],
    tuple[InspectionCollectionPresentation, ...],
]:
    source = view.validation
    if source.availability is not InspectionAvailability.AVAILABLE:
        return (
            (
                _scalar("Validation", source.display_text),
                _scalar("Correction count", view.correction_count.display_text),
            ),
            (),
        )
    value = source.value
    if value is None:
        raise ValueError("Available validation projection lacks its value.")
    violation_items = tuple(
        InspectionListItemPresentation(
            accessible_name=(
                f"Validation violation {item.ordinal}: {item.code.display_label}"
            ),
            scalars=(
                _scalar("Code", item.code.display_label),
                _scalar("Message", item.message),
            ),
        )
        for item in value.violations
    )
    evidence_items: list[InspectionListItemPresentation] = []
    for item in value.evidence:
        scalars = [
            _scalar("Check", item.check_id.display_label),
            _scalar("Severity", item.severity.display_label),
            _scalar("Outcome", item.outcome.display_label),
        ]
        if item.violation_code is not None:
            scalars.append(
                _scalar("Violation code", item.violation_code.display_label)
            )
        if item.warning_code is not None:
            scalars.append(
                _scalar("Warning code", item.warning_code.display_label)
            )
        scalars.append(_scalar("Explanation", item.explanation))
        evidence_items.append(
            InspectionListItemPresentation(
                accessible_name=(
                    f"Validation evidence {item.ordinal}: "
                    f"{item.check_id.display_label}, {item.outcome.display_label}"
                ),
                scalars=tuple(scalars),
            )
        )
    return (
        (
            _scalar("Validation attempt", str(value.attempt_number)),
            _scalar("Validation status", value.status.display_label),
            _scalar("Validation score", value.score.display_text),
            _scalar("Correction count", view.correction_count.display_text),
        ),
        (
            _nested_collection(
                accessible_id="contextInspectionValidationViolations",
                accessible_name="Validation violations",
                items=violation_items,
            ),
            _nested_collection(
                accessible_id="contextInspectionValidationEvidence",
                accessible_name="Validation evidence",
                items=tuple(evidence_items),
            ),
        ),
    )


def _final_status_scalars(
    view: ContextInspectionView,
) -> tuple[InspectionScalarPresentation, ...]:
    scalars: list[InspectionScalarPresentation] = []
    clarification = view.clarification
    if clarification.availability is InspectionAvailability.AVAILABLE:
        value = clarification.value
        if value is None:
            raise ValueError("Available clarification projection lacks its value.")
        scalars.extend(
            (
                _scalar("Clarification reason", value.reason.display_label),
                _scalar("Clarification question", value.question_text),
            )
        )
    else:
        scalars.append(_scalar("Clarification", clarification.display_text))

    terminal = view.terminal_status
    if terminal.availability is InspectionAvailability.AVAILABLE:
        value = terminal.value
        if value is None:
            raise ValueError("Available terminal projection lacks its value.")
        scalars.extend(
            (
                _scalar("Final outcome", value.kind_label),
                _scalar("Failure stage", value.stage.display_label),
                _scalar("Failure code", value.code.display_label),
                _scalar("Status message", value.safe_message),
            )
        )
    else:
        scalars.append(_scalar("Final status", terminal.display_text))
    return tuple(scalars)


def context_inspection_presentation_view(
    view: ContextInspectionView,
) -> ContextInspectionPresentationView:
    """Map one safe application view to the complete primitive QML dataset."""

    if not isinstance(view, ContextInspectionView):
        raise TypeError("Context inspection presentation requires its safe view.")
    target = view.target
    confidence_scalars: tuple[InspectionScalarPresentation, ...]
    if view.confidence.availability is InspectionAvailability.AVAILABLE:
        confidence = view.confidence.value
        if confidence is None:
            raise ValueError("Available confidence projection lacks its value.")
        confidence_scalars = (
            _scalar("Overall confidence", confidence.overall.display_text),
            _scalar(
                "Interpretation confidence",
                confidence.interpretation.display_text,
            ),
            _scalar("Reference confidence", confidence.references.display_text),
            _scalar("Retrieval confidence", confidence.retrieval.display_text),
        )
    else:
        confidence_scalars = (_scalar("Confidence", view.confidence.display_text),)

    validation_scalars, validation_collections = _validation_projection(view)
    sections = (
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[0],
            scalars=(
                _scalar("Request", target.request_label),
                _scalar("Outcome", target.outcome_label),
                _scalar("Processing checkpoint", target.checkpoint_label),
            ),
            collections=(),
        ),
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[1],
            scalars=(
                _scalar("Active project", view.active_project.display_text),
                _scalar("Active topic", view.active_topic.display_text),
                _scalar("Active task", view.active_task.display_text),
            ),
            collections=(),
        ),
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[2],
            scalars=(
                _scalar("Intent", view.intent.display_text),
                _scalar(
                    "Expected output type",
                    view.expected_output_type.display_text,
                ),
            ),
            collections=(_qualifier_collection(view),),
        ),
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[3],
            scalars=(),
            collections=(_reference_collection(view),),
        ),
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[4],
            scalars=(),
            collections=(
                _constraint_collection(view),
                _conflict_collection(view),
            ),
        ),
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[5],
            scalars=(),
            collections=(_memory_collection(view),),
        ),
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[6],
            scalars=confidence_scalars,
            collections=(),
        ),
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[7],
            scalars=validation_scalars,
            collections=validation_collections,
        ),
        InspectionSectionPresentation(
            *_SECTION_IDENTITIES[8],
            scalars=_final_status_scalars(view),
            collections=(),
        ),
    )
    return ContextInspectionPresentationView(target.outcome.value, sections)


def inspection_result_presentation(
    result: InspectionResult,
    *,
    refreshed: bool,
) -> InspectionResultPresentation:
    """Map one matching safe result to its exact page state and status text."""

    if not isinstance(refreshed, bool):
        raise TypeError("Inspection refresh marker must be boolean.")
    if isinstance(result, ContextInspectionReadyResult):
        outcome = result.view.target.outcome
        prefix = (
            "Context inspection refreshed."
            if refreshed
            else "Context inspection loaded."
        )
        if outcome is InspectionRunOutcome.CLARIFICATION:
            state = ContextInspectionPageState.CLARIFICATION
            text = f"{prefix} Clarification is required."
        elif outcome is InspectionRunOutcome.CONTROLLED_FAILURE:
            state = ContextInspectionPageState.CONTROLLED_FAILURE
            text = f"{prefix} Processing ended with a controlled failure."
        else:
            state = ContextInspectionPageState.READY
            text = prefix
        return InspectionResultPresentation(
            state,
            text,
            text,
            context_inspection_presentation_view(result.view),
        )
    if isinstance(result, ContextInspectionEmptyResult):
        return InspectionResultPresentation(
            ContextInspectionPageState.EMPTY,
            result.safe_message,
            result.safe_message,
            None,
        )
    if isinstance(
        result,
        (ContextInspectionLoadFailureResult, InspectionExecutionFailureView),
    ):
        return InspectionResultPresentation(
            ContextInspectionPageState.LOAD_ERROR,
            result.safe_message,
            result.safe_message,
            None,
        )
    raise TypeError("Unknown closed inspection result.")


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
    "ContextInspectionPresentationView",
    "ContextInspectionPageState",
    "ExecutionKind",
    "ForegroundExecutionFailureView",
    "ForegroundTerminalEnvelope",
    "InspectionCollectionPresentation",
    "InspectionExecutionFailureView",
    "InspectionListItemPresentation",
    "InspectionResult",
    "InspectionResultPresentation",
    "InspectionScalarPresentation",
    "InspectionSectionPresentation",
    "InspectionTerminalEnvelope",
    "MonotonicCancellationToken",
    "Route",
    "ShellState",
    "TerminalPresentationView",
    "contained_foreground_result",
    "contained_inspection_result",
    "context_inspection_presentation_view",
    "inspection_result_presentation",
    "terminal_presentation_view",
]
