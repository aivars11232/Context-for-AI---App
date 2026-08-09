"""Read-only safe TASK-0017 validation and correction history projection."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Protocol

from context_for_ai.application.contracts import (
    CanonicalLabelView,
    CorrectionHistoryView,
    InspectValidationHistoryRequest,
    InspectValidationHistoryResult,
    InspectionCheckpoint,
    InspectionRunOutcome,
    InspectionScoreView,
    InspectionTargetView,
    SafeTerminalKind,
    SafeTerminalStatusView,
    SafeValidationEvidenceView,
    SafeValidationViolationView,
    ValidationAttemptFailureView,
    ValidationAttemptOutcome,
    ValidationAttemptReportView,
    ValidationHistoryAttemptView,
    ValidationHistoryCollection,
    ValidationHistoryEmptyResult,
    ValidationHistoryLoadFailureResult,
    ValidationHistoryReadyResult,
    ValidationHistoryView,
)
from context_for_ai.application.manual_settings import ReadOnlySnapshotBoundary
from context_for_ai.domain.entities import Message
from context_for_ai.domain.enums import (
    FailureCode,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    PipelineStage,
    ProcessingRunStatus,
    ValidationStatus,
)
from context_for_ai.domain.errors import DomainError
from context_for_ai.domain.lifecycle import (
    CorrectionAttempt,
    ModelRequest,
    ModelResponse,
    ProcessingRun,
    SafeFailure,
    ValidationResult,
)
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.ports.records import ContextPacketRecord
from context_for_ai.domain.ports.repositories import (
    ClarificationRepository,
    ContextPacketRepository,
    ConversationRepository,
    ConversationStateRepository,
    MessageRepository,
    ModelCallRepository,
    ProcessingRunRepository,
    ValidationRepository,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    UnitScore,
    canonical_decimal_string,
)


_OUTCOME_BY_STATUS = {
    ProcessingRunStatus.PERSISTED: InspectionRunOutcome.PROCESSING,
    ProcessingRunStatus.CONTEXT_READY: InspectionRunOutcome.PROCESSING,
    ProcessingRunStatus.GENERATING: InspectionRunOutcome.PROCESSING,
    ProcessingRunStatus.REVISING: InspectionRunOutcome.PROCESSING,
    ProcessingRunStatus.SUCCEEDED: InspectionRunOutcome.SUCCEEDED,
    ProcessingRunStatus.NEEDS_CLARIFICATION: InspectionRunOutcome.CLARIFICATION,
    ProcessingRunStatus.CONTROLLED_FAILURE: InspectionRunOutcome.CONTROLLED_FAILURE,
    ProcessingRunStatus.FAILED: InspectionRunOutcome.CONTROLLED_FAILURE,
    ProcessingRunStatus.CANCELLED: InspectionRunOutcome.CANCELLED,
}
_TERMINAL_FAILURE_STATUSES = frozenset(
    {
        ProcessingRunStatus.CONTROLLED_FAILURE,
        ProcessingRunStatus.FAILED,
        ProcessingRunStatus.CANCELLED,
    }
)
_TRANSPORT_FAILURE_STATUSES = frozenset(
    {
        ModelRequestStatus.TIMED_OUT,
        ModelRequestStatus.CANCELLED,
        ModelRequestStatus.FAILED,
    }
)


class _HistoryDataError(Exception):
    pass


class _HistoryProcessingRuns(ProcessingRunRepository, Protocol):
    def list_for_conversation(
        self, conversation_id: DomainId
    ) -> tuple[ProcessingRun, ...]: ...


class ValidationHistoryRepositories(Protocol):
    conversations: ConversationRepository
    conversation_states: ConversationStateRepository
    messages: MessageRepository
    processing_runs: _HistoryProcessingRuns
    context_packets: ContextPacketRepository
    model_calls: ModelCallRepository
    validations: ValidationRepository
    clarifications: ClarificationRepository


def _label(code: str) -> CanonicalLabelView:
    words = code.split("_")
    if any(not word for word in words):
        raise _HistoryDataError("A safe canonical code is invalid.")
    rendered = " ".join(word.lower() for word in words)
    return CanonicalLabelView(code, rendered[0].upper() + rendered[1:])


def _score(value: UnitScore | Decimal) -> InspectionScoreView:
    decimal = value.value if isinstance(value, UnitScore) else value
    return InspectionScoreView(
        canonical_decimal_string(decimal),
        format(decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), ".2f"),
    )


def _target_view(
    run: ProcessingRun,
    message: Message,
    checkpoint: InspectionCheckpoint,
) -> InspectionTargetView:
    try:
        outcome = _OUTCOME_BY_STATUS[run.status]
    except KeyError as error:
        raise _HistoryDataError("The processing status is not inspectable.") from error
    return InspectionTargetView(
        user_message_sequence=message.sequence_number,
        request_label=f"Request {message.sequence_number}",
        outcome=outcome,
        checkpoint=checkpoint,
        outcome_label=_label(outcome.value).display_label,
        checkpoint_label=_label(checkpoint.value).display_label,
    )


def _validation_report(validation: ValidationResult) -> ValidationAttemptReportView:
    return ValidationAttemptReportView(
        status=_label(validation.status.value),
        score=_score(validation.score),
        violations=tuple(
            SafeValidationViolationView(
                ordinal=violation.ordinal + 1,
                code=_label(violation.code.value),
                message=violation.message,
            )
            for violation in validation.violations
        ),
        evidence=tuple(
            SafeValidationEvidenceView(
                ordinal=evidence.ordinal + 1,
                check_id=_label(evidence.check_id.value),
                severity=_label(evidence.severity.value),
                outcome=_label(evidence.outcome.value),
                violation_code=(
                    None
                    if evidence.violation_code is None
                    else _label(evidence.violation_code.value)
                ),
                warning_code=(
                    None
                    if evidence.warning_code is None
                    else _label(evidence.warning_code.value)
                ),
                explanation=evidence.explanation,
            )
            for evidence in validation.evidence
        ),
    )


def _terminal_status(
    run: ProcessingRun,
    failures: tuple[SafeFailure, ...],
) -> SafeTerminalStatusView | None:
    terminal = tuple(failure for failure in failures if failure.is_terminal)
    if run.status not in _TERMINAL_FAILURE_STATUSES:
        if terminal:
            raise _HistoryDataError("A non-failure run has terminal failure evidence.")
        return None
    if len(terminal) != 1:
        raise _HistoryDataError("A terminal run requires one terminal failure.")
    failure = terminal[0]
    cancellation_codes = {
        FailureCode.CANCELLED_BY_USER,
        FailureCode.MODEL_CANCELLED,
    }
    if (
        failure.processing_run_id != run.id
        or run.completed_at != failure.created_at
        or (run.status is ProcessingRunStatus.CANCELLED)
        != (failure.error_code in cancellation_codes)
    ):
        raise _HistoryDataError("Terminal failure lineage is invalid.")
    kind = (
        SafeTerminalKind.CANCELLED
        if run.status is ProcessingRunStatus.CANCELLED
        else SafeTerminalKind.CONTROLLED_FAILURE
    )
    return SafeTerminalStatusView(
        kind=kind,
        kind_label=_label(kind.value).display_label,
        stage=_label(failure.stage.value),
        code=_label(failure.error_code.value),
        safe_message=failure.safe_message,
    )


class InspectValidationHistoryService:
    """Build one complete safe history for the latest accepted conversation run."""

    def __init__(
        self,
        *,
        repositories: ValidationHistoryRepositories,
        snapshots: ReadOnlySnapshotBoundary,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots

    def execute(
        self,
        request: InspectValidationHistoryRequest,
    ) -> InspectValidationHistoryResult:
        if not isinstance(request, InspectValidationHistoryRequest):
            raise TypeError(
                "InspectValidationHistoryService requires its request type."
            )
        try:
            with self._snapshots.snapshot():
                self._require_conversation(request.conversation_id)
                target = self._latest_target(request.conversation_id)
                if target is None:
                    return ValidationHistoryEmptyResult()
                run, message = target
                result = self._project(run, message)
            return result
        except (
            DomainError,
            PersistenceError,
            _HistoryDataError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return ValidationHistoryLoadFailureResult()

    def _require_conversation(self, conversation_id: DomainId) -> None:
        conversation = self._repositories.conversations.get(conversation_id)
        state = self._repositories.conversation_states.get(conversation_id)
        if (
            conversation is None
            or conversation.id != conversation_id
            or state is None
            or state.conversation_id != conversation_id
        ):
            raise _HistoryDataError("The requested conversation is incomplete.")

    def _latest_target(
        self,
        conversation_id: DomainId,
    ) -> tuple[ProcessingRun, Message] | None:
        runs = tuple(
            self._repositories.processing_runs.list_for_conversation(
                conversation_id
            )
        )
        if len({run.id for run in runs}) != len(runs):
            raise _HistoryDataError("Processing-run identities are not unique.")
        targets: list[tuple[int, ProcessingRun, Message]] = []
        for run in runs:
            message = self._repositories.messages.get(run.user_message_id)
            if (
                run.conversation_id != conversation_id
                or message is None
                or message.id != run.user_message_id
                or message.conversation_id != conversation_id
                or message.role is not MessageRole.USER
            ):
                raise _HistoryDataError("Processing-run message lineage is invalid.")
            targets.append((message.sequence_number, run, message))
        if not targets:
            return None
        sequences = tuple(sequence for sequence, _, _ in targets)
        if len(set(sequences)) != len(sequences):
            raise _HistoryDataError("Processing-run message sequence is ambiguous.")
        _, run, message = max(targets, key=lambda item: item[0])
        return run, message

    def _project(
        self,
        run: ProcessingRun,
        message: Message,
    ) -> ValidationHistoryReadyResult:
        requests = tuple(
            sorted(
                self._repositories.model_calls.list_requests_for_run(run.id),
                key=lambda item: (item.attempt_number, str(item.id)),
            )
        )
        if (
            len({item.id for item in requests}) != len(requests)
            or tuple(item.attempt_number for item in requests)
            != tuple(range(len(requests)))
            or any(item.processing_run_id != run.id for item in requests)
        ):
            raise _HistoryDataError("Model-request attempt lineage is invalid.")
        for model_request in requests:
            expected_purpose = (
                ModelRequestPurpose.INITIAL
                if model_request.attempt_number == 0
                else ModelRequestPurpose.REVISION
            )
            if model_request.purpose is not expected_purpose:
                raise _HistoryDataError("Model-request purpose is invalid.")

        packet = self._repositories.context_packets.get_for_run(run.id)
        if requests and (
            packet is None
            or any(
                item.context_packet_id != packet.packet.id for item in requests
            )
        ):
            raise _HistoryDataError("Model requests require their run packet.")

        corrections = tuple(
            sorted(
                self._repositories.model_calls.list_corrections_for_run(run.id),
                key=lambda item: item.attempt_number,
            )
        )
        if (
            tuple(item.attempt_number for item in corrections)
            != tuple(range(1, len(corrections) + 1))
            or len(corrections) > 2
            or any(item.processing_run_id != run.id for item in corrections)
        ):
            raise _HistoryDataError("Correction lineage is not contiguous.")

        responses: dict[DomainId, ModelResponse] = {}
        validations: dict[DomainId, ValidationResult] = {}
        attempt_views: list[ValidationHistoryAttemptView] = []
        correction_by_destination = {
            item.attempt_number: item for item in corrections
        }
        for model_request in requests:
            response = self._repositories.model_calls.get_response_for_request(
                model_request.id
            )
            validation: ValidationResult | None = None
            display_attempt = model_request.attempt_number + 1
            correction = correction_by_destination.get(model_request.attempt_number)
            correction_from_previous = (
                None if correction is None else correction.attempt_number
            )
            if model_request.status is ModelRequestStatus.PENDING:
                if response is not None:
                    raise _HistoryDataError("Pending request has a response.")
                outcome = ValidationAttemptOutcome.WAITING
                report = None
                display_text = "Validation has not completed for this attempt."
                failure = None
            elif model_request.status is ModelRequestStatus.IN_FLIGHT:
                if response is not None:
                    raise _HistoryDataError("In-flight request has a response.")
                outcome = ValidationAttemptOutcome.IN_PROGRESS
                report = None
                display_text = "Validation has not completed for this attempt."
                failure = None
            elif model_request.status is ModelRequestStatus.SUCCEEDED:
                if (
                    response is None
                    or response.model_request_id != model_request.id
                    or model_request.completed_at is None
                    or response.created_at != model_request.completed_at
                ):
                    raise _HistoryDataError(
                        "Succeeded request response lineage is invalid."
                    )
                validation = self._repositories.validations.get_for_response(
                    response.id
                )
                if (
                    validation is None
                    or validation.model_response_id != response.id
                    or validation.created_at != response.created_at
                ):
                    raise _HistoryDataError(
                        "Succeeded request validation lineage is invalid."
                    )
                responses[response.id] = response
                validations[response.id] = validation
                outcome = ValidationAttemptOutcome.VALIDATED
                report = _validation_report(validation)
                display_text = ""
                failure = None
            elif model_request.status in _TRANSPORT_FAILURE_STATUSES:
                if (
                    response is not None
                    or model_request.error_code is None
                    or model_request.safe_error_message is None
                ):
                    raise _HistoryDataError(
                        "Transport-failed request evidence is invalid."
                    )
                outcome = ValidationAttemptOutcome.TRANSPORT_FAILURE
                report = None
                display_text = "Validation was not applicable to this attempt."
                failure = ValidationAttemptFailureView(
                    stage=_label(PipelineStage.TRANSPORT.value),
                    code=_label(model_request.error_code),
                    safe_message=model_request.safe_error_message,
                )
            else:
                raise _HistoryDataError("Model-request status is not inspectable.")
            attempt_views.append(
                ValidationHistoryAttemptView(
                    attempt_number=display_attempt,
                    purpose=_label(model_request.purpose.value),
                    outcome=_label(outcome.value),
                    validation=report,
                    validation_display_text=display_text,
                    safe_transport_failure=failure,
                    correction_from_previous=correction_from_previous,
                )
            )

        listed_validations = tuple(
            self._repositories.validations.list_for_run(run.id)
        )
        if (
            len({item.id for item in listed_validations})
            != len(listed_validations)
            or {item.id for item in listed_validations}
            != {item.id for item in validations.values()}
        ):
            raise _HistoryDataError("Listed validation rows disagree with attempts.")

        request_by_id = {item.id: item for item in requests}
        for correction in corrections:
            revised = request_by_id.get(correction.revised_model_request_id)
            prior_response = responses.get(correction.prior_model_response_id)
            prior_request = (
                None
                if prior_response is None
                else request_by_id.get(prior_response.model_request_id)
            )
            prior_validation = (
                None
                if prior_response is None
                else validations.get(prior_response.id)
            )
            if (
                revised is None
                or revised.attempt_number != correction.attempt_number
                or prior_request is None
                or prior_request.attempt_number != correction.attempt_number - 1
                or prior_validation is None
                or prior_validation.status is not ValidationStatus.FAILED
                or correction.reasons != prior_validation.violations
            ):
                raise _HistoryDataError("Correction adjacency is invalid.")
        if len(requests) > 1 and len(corrections) != len(requests) - 1:
            raise _HistoryDataError("Revision requests lack correction rows.")

        clarification = self._repositories.clarifications.get_for_run(run.id)
        if run.status is ProcessingRunStatus.NEEDS_CLARIFICATION:
            if clarification is None or requests or corrections:
                raise _HistoryDataError("Clarification history is inconsistent.")
            checkpoint = InspectionCheckpoint.CLARIFICATION_COMMITTED
        elif clarification is not None:
            raise _HistoryDataError("Non-clarification run has clarification evidence.")
        elif validations:
            checkpoint = InspectionCheckpoint.VALIDATION_COMMITTED
        elif packet is not None:
            checkpoint = InspectionCheckpoint.CONTEXT_COMMITTED
        elif run.status in _TERMINAL_FAILURE_STATUSES:
            checkpoint = InspectionCheckpoint.TERMINAL_WITHOUT_CONTEXT
        else:
            checkpoint = InspectionCheckpoint.ACCEPTED

        failures = tuple(
            self._repositories.model_calls.list_failures_for_run(run.id)
        )
        if any(item.processing_run_id != run.id for item in failures):
            raise _HistoryDataError("Safe-failure lineage is invalid.")
        terminal = _terminal_status(run, failures)
        correction_views = tuple(
            CorrectionHistoryView(
                correction_number=item.attempt_number,
                from_attempt_number=item.attempt_number,
                to_attempt_number=item.attempt_number + 1,
            )
            for item in corrections
        )
        attempts = tuple(attempt_views)
        return ValidationHistoryReadyResult(
            ValidationHistoryView(
                target=_target_view(run, message, checkpoint),
                attempts=ValidationHistoryCollection(
                    attempts,
                    "" if attempts else "Validation has not started for this request.",
                ),
                corrections=correction_views,
                correction_count=len(correction_views),
                terminal_status=terminal,
            )
        )


__all__ = [
    "InspectValidationHistoryService",
    "ValidationHistoryRepositories",
]
