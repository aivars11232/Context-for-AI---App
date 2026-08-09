"""Read-only historical context inspection and safe presentation projection."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Protocol, TypeVar

from context_for_ai.application.contracts import (
    ActiveStateItemView,
    ActiveStateKind,
    CanonicalLabelView,
    ClarificationInspectionView,
    ConfidenceInspectionView,
    ConflictInspectionView,
    ConflictRuleView,
    ConstraintConditionView,
    ConstraintInspectionView,
    ContextInspectionEmptyResult,
    ContextInspectionLoadFailureResult,
    ContextInspectionReadyResult,
    ContextInspectionView,
    InspectContextRequest,
    InspectContextResult,
    InspectionAvailability,
    InspectionCheckpoint,
    InspectionCollection,
    InspectionRunOutcome,
    InspectionScoreView,
    InspectionTargetView,
    InspectionValue,
    QualifierEvidenceView,
    ReferenceEvidenceView,
    ReferenceInspectionView,
    ReferenceMessageSourceView,
    RetrievedMemoryInspectionView,
    SafeTerminalKind,
    SafeTerminalStatusView,
    SafeValidationEvidenceView,
    SafeValidationViolationView,
    ValidationInspectionView,
)
from context_for_ai.domain.decisions import Constraint, ReferenceOutcome
from context_for_ai.domain.entities import Message
from context_for_ai.domain.enums import (
    ClarificationReason,
    ConstraintResolutionStatus,
    ConstraintSourceKind,
    FailureCode,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    ProcessingRunStatus,
    ReferenceStatus,
    ValidationStatus,
)
from context_for_ai.domain.errors import DomainError
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
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
    ConstraintRepository,
    ContextPacketRepository,
    ConversationRepository,
    ConversationStateRepository,
    MessageRepository,
    ModelCallRepository,
    ProcessingRunRepository,
    ProjectRepository,
    ReferenceResolutionRepository,
    TaskRepository,
    TopicRepository,
    ValidationRepository,
)
from context_for_ai.domain.value_objects import (
    DomainId,
    FrozenJsonObject,
    UnitScore,
    canonical_decimal_string,
    format_utc_timestamp,
)


_EMPTY_TEXT = "None recorded."
_NOT_APPLICABLE_TEXT = "Not applicable."
_UNAVAILABLE_TEXT = "Unavailable for this run."

_NON_TERMINAL_STATUSES = frozenset(
    {
        ProcessingRunStatus.PERSISTED,
        ProcessingRunStatus.CONTEXT_READY,
        ProcessingRunStatus.GENERATING,
        ProcessingRunStatus.REVISING,
    }
)
_FAILURE_TERMINAL_STATUSES = frozenset(
    {
        ProcessingRunStatus.CONTROLLED_FAILURE,
        ProcessingRunStatus.FAILED,
        ProcessingRunStatus.CANCELLED,
    }
)
_COMPLETED_STATUSES = frozenset(
    {
        ProcessingRunStatus.SUCCEEDED,
        ProcessingRunStatus.NEEDS_CLARIFICATION,
        *_FAILURE_TERMINAL_STATUSES,
    }
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

_EARLY_CLARIFICATION_REASONS = frozenset(
    {
        ClarificationReason.LOW_CONFIDENCE_INTERPRETATION,
        ClarificationReason.UNSUPPORTED_INTENT,
    }
)
_REFERENCE_CLARIFICATION_REASONS = frozenset(
    {
        ClarificationReason.AMBIGUOUS_REFERENCE,
        ClarificationReason.UNRESOLVED_REFERENCE,
    }
)
_CONSTRAINT_CLARIFICATION_REASONS = frozenset(
    {
        ClarificationReason.UNSUPPORTED_CONDITION,
        ClarificationReason.MATERIAL_ASSUMPTION,
    }
)


class _InspectionDataError(Exception):
    """A persisted inspection aggregate cannot form one complete safe view."""


class _InspectionProcessingRunRepository(ProcessingRunRepository, Protocol):
    def list_for_conversation(
        self,
        conversation_id: DomainId,
    ) -> tuple[ProcessingRun, ...]: ...


class _InspectionRepositories(Protocol):
    projects: ProjectRepository
    conversations: ConversationRepository
    topics: TopicRepository
    tasks: TaskRepository
    conversation_states: ConversationStateRepository
    messages: MessageRepository
    processing_runs: _InspectionProcessingRunRepository
    context_packets: ContextPacketRepository
    reference_resolutions: ReferenceResolutionRepository
    constraints: ConstraintRepository
    model_calls: ModelCallRepository
    validations: ValidationRepository
    clarifications: ClarificationRepository


class InspectionSnapshotBoundary(Protocol):
    """Open one connection-local read-only snapshot for the complete query."""

    def snapshot(self) -> AbstractContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class _Artifacts:
    run: ProcessingRun
    message: Message
    packet: ContextPacketRecord | None
    references: tuple[ReferenceOutcome, ...]
    constraints: tuple[Constraint, ...]
    requests: tuple[ModelRequest, ...]
    responses: tuple[ModelResponse | None, ...]
    validations: tuple[ValidationResult, ...]
    corrections: tuple[CorrectionAttempt, ...]
    failures: tuple[SafeFailure, ...]
    clarification: ClarificationRequest | None


T = TypeVar("T")


def _label(code: str) -> CanonicalLabelView:
    words = code.split("_")
    rendered = " ".join(word.lower() for word in words)
    return CanonicalLabelView(code, rendered[0].upper() + rendered[1:])


def _score(value: UnitScore | Decimal) -> InspectionScoreView:
    decimal = value.value if isinstance(value, UnitScore) else value
    return InspectionScoreView(
        canonical_decimal_string(decimal),
        format(decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN), ".2f"),
    )


def _available(value: T, display_text: str) -> InspectionValue[T]:
    return InspectionValue(InspectionAvailability.AVAILABLE, value, display_text)


def _not_applicable(
    display_text: str = _NOT_APPLICABLE_TEXT,
) -> InspectionValue[object]:
    return InspectionValue(InspectionAvailability.NOT_APPLICABLE, None, display_text)


def _unavailable() -> InspectionValue[object]:
    return InspectionValue(InspectionAvailability.UNAVAILABLE, None, _UNAVAILABLE_TEXT)


def _collection(values: tuple[T, ...]) -> InspectionCollection[T]:
    if values:
        return InspectionCollection(InspectionAvailability.AVAILABLE, values, "")
    return InspectionCollection(InspectionAvailability.EMPTY, (), _EMPTY_TEXT)


def _unavailable_collection() -> InspectionCollection[object]:
    return InspectionCollection(
        InspectionAvailability.UNAVAILABLE,
        (),
        _UNAVAILABLE_TEXT,
    )


def _object(value: object, name: str) -> FrozenJsonObject:
    if not isinstance(value, FrozenJsonObject):
        raise _InspectionDataError(f"{name} is not a persisted object.")
    return value


def _array(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise _InspectionDataError(f"{name} is not a persisted array.")
    return value


def _domain_id(value: object, name: str) -> DomainId:
    if not isinstance(value, str):
        raise _InspectionDataError(f"{name} is not a canonical identifier.")
    identifier = DomainId(value)
    if str(identifier) != value:
        raise _InspectionDataError(f"{name} is not a canonical identifier.")
    return identifier


class InspectContextService:
    """Load one latest-run snapshot and expose only the contracted safe view."""

    def __init__(
        self,
        *,
        repositories: _InspectionRepositories,
        snapshots: InspectionSnapshotBoundary,
    ) -> None:
        self._repositories = repositories
        self._snapshots = snapshots

    def execute(self, request: InspectContextRequest) -> InspectContextResult:
        if not isinstance(request, InspectContextRequest):
            raise TypeError("InspectContextService requires InspectContextRequest.")
        try:
            with self._snapshots.snapshot():
                self._require_conversation(request.conversation_id)
                target = self._latest_target(request.conversation_id)
                if target is None:
                    return ContextInspectionEmptyResult()
                run, message = target
                artifacts = self._load_artifacts(run, message)
                view = self._project(artifacts)
            return ContextInspectionReadyResult(view)
        except (
            DomainError,
            PersistenceError,
            _InspectionDataError,
            KeyError,
            ValueError,
        ):
            return ContextInspectionLoadFailureResult()

    def _require_conversation(self, conversation_id: DomainId) -> None:
        conversation = self._repositories.conversations.get(conversation_id)
        state = self._repositories.conversation_states.get(conversation_id)
        if (
            conversation is None
            or conversation.id != conversation_id
            or state is None
            or state.conversation_id != conversation_id
        ):
            raise _InspectionDataError("The requested conversation is incomplete.")

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
            raise _InspectionDataError("Processing-run identities are not unique.")

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
                raise _InspectionDataError("Processing-run message lineage is invalid.")
            targets.append((message.sequence_number, run, message))
        if not targets:
            return None

        sequences = [sequence for sequence, _, _ in targets]
        if len(set(sequences)) != len(sequences):
            raise _InspectionDataError("Processing-run message sequence is ambiguous.")
        _, run, message = max(targets, key=lambda item: item[0])
        return run, message

    def _load_artifacts(self, run: ProcessingRun, message: Message) -> _Artifacts:
        requests = tuple(
            sorted(
                self._repositories.model_calls.list_requests_for_run(run.id),
                key=lambda value: (value.attempt_number, str(value.id)),
            )
        )
        return _Artifacts(
            run=run,
            message=message,
            packet=self._repositories.context_packets.get_for_run(run.id),
            references=tuple(
                self._repositories.reference_resolutions.list_for_run(run.id)
            ),
            constraints=tuple(self._repositories.constraints.list_for_run(run.id)),
            requests=requests,
            responses=tuple(
                self._repositories.model_calls.get_response_for_request(value.id)
                for value in requests
            ),
            validations=tuple(self._repositories.validations.list_for_run(run.id)),
            corrections=tuple(
                self._repositories.model_calls.list_corrections_for_run(run.id)
            ),
            failures=tuple(
                self._repositories.model_calls.list_failures_for_run(run.id)
            ),
            clarification=self._repositories.clarifications.get_for_run(run.id),
        )

    def _project(self, artifacts: _Artifacts) -> ContextInspectionView:
        run = artifacts.run
        if run.status in _NON_TERMINAL_STATUSES:
            if run.completed_at is not None:
                raise _InspectionDataError("A non-terminal run is marked completed.")
        elif run.status in _COMPLETED_STATUSES:
            if run.completed_at is None:
                raise _InspectionDataError("A completed run lacks its completion time.")
        else:
            raise _InspectionDataError("The run status is not inspectable.")

        self._validate_common_lineage(artifacts)
        if run.status is ProcessingRunStatus.NEEDS_CLARIFICATION:
            return self._project_clarification(artifacts)
        if artifacts.packet is not None:
            return self._project_packet(artifacts)
        if run.status is ProcessingRunStatus.PERSISTED:
            return self._project_accepted(artifacts)
        if run.status in _FAILURE_TERMINAL_STATUSES:
            return self._project_terminal_without_context(artifacts)
        raise _InspectionDataError("The run lacks a required committed packet.")

    @staticmethod
    def _validate_common_lineage(artifacts: _Artifacts) -> None:
        run = artifacts.run
        message = artifacts.message
        if any(
            reference.processing_run_id != run.id
            or reference.message_id != message.id
            for reference in artifacts.references
        ):
            raise _InspectionDataError("Reference lineage does not match the target.")
        if any(
            constraint.processing_run_id != run.id
            or constraint.message_id != message.id
            for constraint in artifacts.constraints
        ):
            raise _InspectionDataError("Constraint lineage does not match the target.")
        if any(request.processing_run_id != run.id for request in artifacts.requests):
            raise _InspectionDataError("Model-request lineage does not match the target.")
        if any(
            correction.processing_run_id != run.id
            for correction in artifacts.corrections
        ):
            raise _InspectionDataError("Correction lineage does not match the target.")
        if any(failure.processing_run_id != run.id for failure in artifacts.failures):
            raise _InspectionDataError("Failure lineage does not match the target.")
        if (
            artifacts.clarification is not None
            and artifacts.clarification.processing_run_id != run.id
        ):
            raise _InspectionDataError("Clarification lineage does not match the target.")

    def _target(
        self,
        artifacts: _Artifacts,
        checkpoint: InspectionCheckpoint,
    ) -> InspectionTargetView:
        outcome = _OUTCOME_BY_STATUS[artifacts.run.status]
        return InspectionTargetView(
            artifacts.message.sequence_number,
            f"Request {artifacts.message.sequence_number}",
            outcome,
            checkpoint,
            _label(outcome.value).display_label,
            _label(checkpoint.value).display_label,
        )

    def _project_accepted(self, artifacts: _Artifacts) -> ContextInspectionView:
        if any(
            (
                artifacts.references,
                artifacts.constraints,
                artifacts.requests,
                artifacts.validations,
                artifacts.corrections,
                artifacts.failures,
            )
        ) or artifacts.clarification is not None:
            raise _InspectionDataError("An accepted-only run has later artifacts.")
        return ContextInspectionView(
            target=self._target(artifacts, InspectionCheckpoint.ACCEPTED),
            active_project=_unavailable(),
            active_topic=_unavailable(),
            active_task=_unavailable(),
            intent=_unavailable(),
            expected_output_type=_unavailable(),
            qualifier_evidence=_unavailable_collection(),
            references=_unavailable_collection(),
            constraints=_unavailable_collection(),
            conflicts=_unavailable_collection(),
            retrieved_memories=_unavailable_collection(),
            confidence=_unavailable(),
            validation=_unavailable(),
            correction_count=_unavailable(),
            clarification=_not_applicable(),
            terminal_status=_unavailable(),
        )

    def _project_terminal_without_context(
        self,
        artifacts: _Artifacts,
    ) -> ContextInspectionView:
        if any(
            (
                artifacts.references,
                artifacts.constraints,
                artifacts.requests,
                artifacts.validations,
                artifacts.corrections,
            )
        ) or artifacts.clarification is not None:
            raise _InspectionDataError("A context-free terminal run has later artifacts.")
        terminal = self._terminal_status(artifacts)
        return ContextInspectionView(
            target=self._target(
                artifacts,
                InspectionCheckpoint.TERMINAL_WITHOUT_CONTEXT,
            ),
            active_project=_unavailable(),
            active_topic=_unavailable(),
            active_task=_unavailable(),
            intent=_unavailable(),
            expected_output_type=_unavailable(),
            qualifier_evidence=_unavailable_collection(),
            references=_unavailable_collection(),
            constraints=_unavailable_collection(),
            conflicts=_unavailable_collection(),
            retrieved_memories=_unavailable_collection(),
            confidence=_unavailable(),
            validation=_not_applicable(),
            correction_count=_not_applicable(),
            clarification=_not_applicable(),
            terminal_status=_available(terminal, terminal.kind_label),
        )

    def _project_clarification(self, artifacts: _Artifacts) -> ContextInspectionView:
        clarification = artifacts.clarification
        if (
            clarification is None
            or artifacts.packet is not None
            or artifacts.requests
            or artifacts.validations
            or artifacts.corrections
            or artifacts.failures
        ):
            raise _InspectionDataError("Clarification artifacts are incomplete.")

        references = self._references(artifacts, packet_values=None)
        constraints, conflicts = self._constraints(artifacts, packet_values=None)
        reason = clarification.reason
        if reason in _EARLY_CLARIFICATION_REASONS:
            if artifacts.references or artifacts.constraints:
                raise _InspectionDataError("Early clarification has later evidence.")
            reference_value = _unavailable_collection()
            constraint_value = _unavailable_collection()
            conflict_value = _unavailable_collection()
        elif reason in _REFERENCE_CLARIFICATION_REASONS:
            if not artifacts.references or artifacts.constraints:
                raise _InspectionDataError("Reference clarification evidence is invalid.")
            reference_value = _collection(references)
            constraint_value = _unavailable_collection()
            conflict_value = _unavailable_collection()
        elif reason in _CONSTRAINT_CLARIFICATION_REASONS:
            if not artifacts.constraints or conflicts:
                raise _InspectionDataError("Constraint clarification evidence is invalid.")
            reference_value = _collection(references)
            constraint_value = _collection(constraints)
            conflict_value = _collection(conflicts)
        elif reason is ClarificationReason.HARD_CONSTRAINT_CONFLICT:
            if not artifacts.constraints or not conflicts:
                raise _InspectionDataError("Hard-conflict evidence is incomplete.")
            reference_value = _collection(references)
            constraint_value = _collection(constraints)
            conflict_value = _collection(conflicts)
        else:
            raise _InspectionDataError("Clarification reason is not inspectable.")

        safe_clarification = ClarificationInspectionView(
            _label(reason.value),
            clarification.question_text,
        )
        return ContextInspectionView(
            target=self._target(
                artifacts,
                InspectionCheckpoint.CLARIFICATION_COMMITTED,
            ),
            active_project=_unavailable(),
            active_topic=_unavailable(),
            active_task=_unavailable(),
            intent=_unavailable(),
            expected_output_type=_unavailable(),
            qualifier_evidence=_unavailable_collection(),
            references=reference_value,
            constraints=constraint_value,
            conflicts=conflict_value,
            retrieved_memories=_unavailable_collection(),
            confidence=_unavailable(),
            validation=_not_applicable(),
            correction_count=_not_applicable(),
            clarification=_available(
                safe_clarification,
                safe_clarification.reason.display_label,
            ),
            terminal_status=_not_applicable(),
        )

    def _project_packet(self, artifacts: _Artifacts) -> ContextInspectionView:
        packet_record = artifacts.packet
        if packet_record is None or artifacts.clarification is not None:
            raise _InspectionDataError("Packet checkpoint artifacts are inconsistent.")
        packet = packet_record.packet
        payload = packet.packet_json
        trace = _object(payload["trace"], "packet trace")
        request = _object(payload["request"], "packet request")
        if (
            packet.processing_run_id != artifacts.run.id
            or packet.message_id != artifacts.message.id
            or packet.configuration_fingerprint
            != artifacts.run.configuration_fingerprint
            or trace["processing_run_id"] != str(artifacts.run.id)
            or trace["conversation_id"] != str(artifacts.run.conversation_id)
            or trace["user_message_id"] != str(artifacts.message.id)
            or request["original_text"] != artifacts.message.original_text
        ):
            raise _InspectionDataError("Packet lineage does not match the target.")

        packet_references = _array(payload["references"], "packet references")
        packet_constraints = _array(payload["constraints"], "packet constraints")
        references = self._references(artifacts, packet_references)
        constraints, conflicts = self._constraints(artifacts, packet_constraints)
        if not constraints or conflicts:
            raise _InspectionDataError("A committed packet lacks canonical constraints.")

        validation = self._latest_validation(artifacts, packet.id)
        if validation is None:
            checkpoint = InspectionCheckpoint.CONTEXT_COMMITTED
            if artifacts.run.status in {
                ProcessingRunStatus.PERSISTED,
                ProcessingRunStatus.REVISING,
                ProcessingRunStatus.SUCCEEDED,
            }:
                raise _InspectionDataError("The run status requires another checkpoint.")
        else:
            checkpoint = InspectionCheckpoint.VALIDATION_COMMITTED
            if artifacts.run.status in {
                ProcessingRunStatus.PERSISTED,
                ProcessingRunStatus.CONTEXT_READY,
                ProcessingRunStatus.GENERATING,
            }:
                raise _InspectionDataError("The run status precedes committed validation.")
            if (
                artifacts.run.status is ProcessingRunStatus.SUCCEEDED
                and validation.value.status.code != ValidationStatus.PASSED.value
            ):
                raise _InspectionDataError("A succeeded run lacks passing validation.")

        terminal_value: InspectionValue[object]
        if artifacts.run.status in _FAILURE_TERMINAL_STATUSES:
            terminal = self._terminal_status(artifacts)
            terminal_value = _available(terminal, terminal.kind_label)
        else:
            if artifacts.failures:
                raise _InspectionDataError("A non-failure run has terminal failure data.")
            terminal_value = (
                _not_applicable()
                if artifacts.run.status is ProcessingRunStatus.SUCCEEDED
                else _unavailable()
            )

        active = _object(payload["active_state"], "packet active state")
        qualifier_values = _array(request["qualifiers"], "packet qualifiers")
        qualifiers = tuple(
            QualifierEvidenceView(
                ordinal=index,
                kind=_label(
                    str(_object(raw, "packet qualifier")["kind"])
                ),
                rule_id=str(_object(raw, "packet qualifier")["rule_id"]),
                matched_text=str(
                    _object(raw, "packet qualifier")["matched_text"]
                ),
            )
            for index, raw in enumerate(qualifier_values, start=1)
        )
        intent = _label(str(request["intent"]))
        output_type = _label(str(request["expected_output_type"]))
        confidence = self._confidence(payload)
        correction_count = len(artifacts.corrections)
        if correction_count > 2:
            raise _InspectionDataError("Correction count exceeds the MVP limit.")

        return ContextInspectionView(
            target=self._target(artifacts, checkpoint),
            active_project=self._active_owner(
                active["project_id"],
                ActiveStateKind.PROJECT,
                artifacts.run.conversation_id,
            ),
            active_topic=self._active_owner(
                active["topic_id"],
                ActiveStateKind.TOPIC,
                artifacts.run.conversation_id,
            ),
            active_task=self._active_owner(
                active["task_id"],
                ActiveStateKind.TASK,
                artifacts.run.conversation_id,
            ),
            intent=_available(intent, intent.display_label),
            expected_output_type=_available(output_type, output_type.display_label),
            qualifier_evidence=_collection(qualifiers),
            references=_collection(references),
            constraints=_collection(constraints),
            conflicts=_collection(conflicts),
            retrieved_memories=self._retrieved_memories(packet_record),
            confidence=_available(confidence, confidence.overall.display_text),
            validation=(
                _unavailable()
                if validation is None
                and artifacts.run.status not in _FAILURE_TERMINAL_STATUSES
                else _not_applicable()
                if validation is None
                else validation
            ),
            correction_count=_available(correction_count, str(correction_count)),
            clarification=_not_applicable(),
            terminal_status=terminal_value,
        )

    def _active_owner(
        self,
        raw_identifier: object,
        kind: ActiveStateKind,
        conversation_id: DomainId,
    ) -> InspectionValue[ActiveStateItemView]:
        if raw_identifier is None:
            text = {
                ActiveStateKind.PROJECT: "No active project.",
                ActiveStateKind.TOPIC: "No active topic.",
                ActiveStateKind.TASK: "No active task.",
            }[kind]
            return InspectionValue(InspectionAvailability.NOT_APPLICABLE, None, text)
        identifier = _domain_id(raw_identifier, f"active {kind.value.casefold()}")
        if kind is ActiveStateKind.PROJECT:
            owner = self._repositories.projects.get(identifier)
            display_name = None if owner is None else owner.name
        elif kind is ActiveStateKind.TOPIC:
            owner = self._repositories.topics.get(identifier)
            display_name = (
                None
                if owner is None or owner.conversation_id != conversation_id
                else owner.label
            )
        else:
            owner = self._repositories.tasks.get(identifier)
            display_name = (
                None
                if owner is None or owner.conversation_id != conversation_id
                else owner.title
            )
        if owner is None or owner.id != identifier or display_name is None:
            raise _InspectionDataError("A packet active-state owner is missing.")
        item = ActiveStateItemView(kind, display_name)
        return _available(item, item.display_name)

    def _references(
        self,
        artifacts: _Artifacts,
        packet_values: tuple[object, ...] | None,
    ) -> tuple[ReferenceInspectionView, ...]:
        ordered = tuple(
            sorted(artifacts.references, key=lambda value: value.mention_ordinal)
        )
        if [value.mention_ordinal for value in ordered] != list(range(len(ordered))):
            raise _InspectionDataError("Reference mention order is not contiguous.")
        if len({value.id for value in ordered}) != len(ordered):
            raise _InspectionDataError("Reference identities are not unique.")

        packet_by_id: dict[DomainId, FrozenJsonObject] | None = None
        if packet_values is not None:
            packet_by_id = {}
            for raw in packet_values:
                value = _object(raw, "packet reference")
                identifier = _domain_id(value["id"], "packet reference")
                if identifier in packet_by_id:
                    raise _InspectionDataError("Packet references are duplicated.")
                packet_by_id[identifier] = value
            if set(packet_by_id) != {value.id for value in ordered}:
                raise _InspectionDataError("Packet and stored references disagree.")

        projected: list[ReferenceInspectionView] = []
        for reference in ordered:
            packet_value = None if packet_by_id is None else packet_by_id[reference.id]
            if packet_value is not None:
                self._require_reference_agreement(reference, packet_value)
            source = (
                _not_applicable()
                if reference.source_message_id is None
                else self._available_message_source(
                    reference.source_message_id,
                    artifacts.run.conversation_id,
                )
            )
            evidence_values: list[ReferenceEvidenceView] = []
            for evidence in reference.candidate_evidence:
                if evidence.entity_source_message_id is not None:
                    self._message_source(
                        evidence.entity_source_message_id,
                        artifacts.run.conversation_id,
                    )
                evidence_message = None
                if evidence.evidence_message_id is not None:
                    evidence_message = self._message_source(
                        evidence.evidence_message_id,
                        artifacts.run.conversation_id,
                    )
                    if (
                        evidence.evidence_message_sequence
                        != evidence_message.message_sequence
                    ):
                        raise _InspectionDataError(
                            "Reference evidence message sequence disagrees."
                        )
                elif evidence.evidence_message_sequence is not None:
                    raise _InspectionDataError(
                        "Reference evidence sequence lacks its message."
                    )
                evidence_values.append(
                    ReferenceEvidenceView(
                        evidence.rank,
                        evidence.display_name,
                        (
                            None
                            if evidence.entity_type is None
                            else _label(evidence.entity_type.value)
                        ),
                        _score(evidence.score),
                        _label(evidence.rank_reason.value),
                        evidence_message,
                        evidence.is_active,
                        (
                            None
                            if evidence.is_active is None
                            else "Active"
                            if evidence.is_active
                            else "Inactive"
                        ),
                    )
                )

            if reference.status is ReferenceStatus.RESOLVED:
                winner = next(
                    (
                        evidence
                        for evidence in reference.candidate_evidence
                        if evidence.entity_id == reference.resolved_entity_id
                    ),
                    None,
                )
                if winner is None or winner.display_name is None:
                    raise _InspectionDataError("Resolved reference winner is missing.")
                resolved = _available(winner.display_name, winner.display_name)
            else:
                resolved = _not_applicable()
            status = _label(reference.status.value)
            projected.append(
                ReferenceInspectionView(
                    reference.mention_ordinal + 1,
                    reference.surface_text,
                    status,
                    resolved,
                    source,
                    _score(reference.confidence),
                    tuple(evidence_values),
                )
            )
        return tuple(projected)

    @staticmethod
    def _require_reference_agreement(
        reference: ReferenceOutcome,
        packet: FrozenJsonObject,
    ) -> None:
        evidence_values = _array(packet["evidence"], "packet reference evidence")
        if (
            packet["mention_ordinal"] != reference.mention_ordinal
            or packet["surface_text"] != reference.surface_text
            or packet["status"] != reference.status.value
            or packet["entity_id"]
            != (
                None
                if reference.resolved_entity_id is None
                else str(reference.resolved_entity_id)
            )
            or packet["source_message_id"]
            != (
                None
                if reference.source_message_id is None
                else str(reference.source_message_id)
            )
            or packet["confidence"] != reference.confidence.value
            or len(evidence_values) != len(reference.candidate_evidence)
        ):
            raise _InspectionDataError("Packet and stored reference disagree.")
        for raw, evidence in zip(
            evidence_values,
            reference.candidate_evidence,
            strict=True,
        ):
            value = _object(raw, "packet candidate evidence")
            expected = {
                "rank": evidence.rank,
                "entity_id": (
                    None if evidence.entity_id is None else str(evidence.entity_id)
                ),
                "entity_type": (
                    None if evidence.entity_type is None else evidence.entity_type.value
                ),
                "display_name": evidence.display_name,
                "normalized_name": evidence.normalized_name,
                "score": evidence.score.value,
                "rank_reason": evidence.rank_reason.value,
                "entity_source_message_id": (
                    None
                    if evidence.entity_source_message_id is None
                    else str(evidence.entity_source_message_id)
                ),
                "evidence_message_id": (
                    None
                    if evidence.evidence_message_id is None
                    else str(evidence.evidence_message_id)
                ),
                "evidence_message_sequence": evidence.evidence_message_sequence,
                "prior_mention_ordinal": evidence.prior_mention_ordinal,
                "is_active": evidence.is_active,
            }
            if any(value[key] != expected_value for key, expected_value in expected.items()):
                raise _InspectionDataError(
                    "Packet and stored reference evidence disagree."
                )

    def _message_source(
        self,
        message_id: DomainId,
        conversation_id: DomainId,
    ) -> ReferenceMessageSourceView:
        message = self._repositories.messages.get(message_id)
        if (
            message is None
            or message.id != message_id
            or message.conversation_id != conversation_id
        ):
            raise _InspectionDataError("Reference source message is missing.")
        return ReferenceMessageSourceView(
            message.sequence_number,
            f"Message {message.sequence_number}",
        )

    def _available_message_source(
        self,
        message_id: DomainId,
        conversation_id: DomainId,
    ) -> InspectionValue[ReferenceMessageSourceView]:
        value = self._message_source(message_id, conversation_id)
        return _available(value, value.display_text)

    def _constraints(
        self,
        artifacts: _Artifacts,
        packet_values: tuple[object, ...] | None,
    ) -> tuple[tuple[ConstraintInspectionView, ...], tuple[ConflictInspectionView, ...]]:
        ordered = tuple(sorted(artifacts.constraints, key=lambda value: value.ordinal))
        if [value.ordinal for value in ordered] != list(range(len(ordered))):
            raise _InspectionDataError("Constraint order is not contiguous.")
        if len({value.id for value in ordered}) != len(ordered):
            raise _InspectionDataError("Constraint identities are not unique.")

        packet_by_id: dict[DomainId, FrozenJsonObject] | None = None
        if packet_values is not None:
            packet_by_id = {}
            for raw in packet_values:
                value = _object(raw, "packet constraint")
                identifier = _domain_id(value["id"], "packet constraint")
                if identifier in packet_by_id:
                    raise _InspectionDataError("Packet constraints are duplicated.")
                packet_by_id[identifier] = value
            if set(packet_by_id) != {value.id for value in ordered}:
                raise _InspectionDataError("Packet and stored constraints disagree.")

        projected: list[ConstraintInspectionView] = []
        conflict_groups: dict[str, list[Constraint]] = {}
        for constraint in ordered:
            if constraint.source_kind is ConstraintSourceKind.CURRENT_MESSAGE and (
                constraint.source_text != artifacts.message.original_text
            ):
                raise _InspectionDataError("Current-message constraint source disagrees.")
            if packet_by_id is not None:
                self._require_constraint_agreement(
                    constraint,
                    packet_by_id[constraint.id],
                    artifacts,
                )
            if constraint.resolution_status is ConstraintResolutionStatus.CONFLICTING:
                if constraint.conflict_group_id is None:
                    raise _InspectionDataError("Conflicting constraint lacks its group.")
                conflict_groups.setdefault(constraint.conflict_group_id, []).append(
                    constraint
                )
            elif constraint.conflict_group_id is not None:
                raise _InspectionDataError("Non-conflicting constraint has a group.")

            condition = None
            if constraint.condition is not None:
                condition = ConstraintConditionView(
                    constraint.condition.grammar_version,
                    _label(constraint.condition.kind.value),
                    constraint.condition.expected_value,
                    _label(constraint.condition.evaluation.value),
                )
            projected.append(
                ConstraintInspectionView(
                    constraint.ordinal + 1,
                    _label(constraint.constraint_type.value),
                    (
                        None
                        if constraint.underlying_constraint_type is None
                        else _label(constraint.underlying_constraint_type.value)
                    ),
                    _label(constraint.scope.value),
                    constraint.normalized_rule,
                    constraint.priority,
                    _label(constraint.source_kind.value),
                    constraint.source_text,
                    _score(constraint.confidence),
                    _label(constraint.resolution_status.value),
                    condition,
                )
            )

        ordered_groups = sorted(
            conflict_groups.items(),
            key=lambda item: (
                min(value.ordinal for value in item[1]),
                item[0],
            ),
        )
        conflicts: list[ConflictInspectionView] = []
        for ordinal, (_, members) in enumerate(ordered_groups, start=1):
            ordered_members = sorted(members, key=lambda value: value.ordinal)
            if len(ordered_members) < 2:
                raise _InspectionDataError("Conflict group has fewer than two rules.")
            conflicts.append(
                ConflictInspectionView(
                    ordinal,
                    tuple(
                        ConflictRuleView(
                            member.ordinal + 1,
                            _label(member.constraint_type.value),
                            member.normalized_rule,
                            member.source_text,
                        )
                        for member in ordered_members
                    ),
                )
            )
        return tuple(projected), tuple(conflicts)

    @staticmethod
    def _require_constraint_agreement(
        constraint: Constraint,
        packet: FrozenJsonObject,
        artifacts: _Artifacts,
    ) -> None:
        condition = constraint.condition
        expected_condition = (
            None
            if condition is None
            else {
                "grammar_version": condition.grammar_version,
                "kind": condition.kind.value,
                "expected_value": condition.expected_value,
                "evaluation": condition.evaluation.value,
            }
        )
        packet_condition = packet["condition"]
        condition_agrees = (
            packet_condition is None
            if expected_condition is None
            else isinstance(packet_condition, FrozenJsonObject)
            and all(
                packet_condition[key] == value
                for key, value in expected_condition.items()
            )
        )
        if (
            packet["ordinal"] != constraint.ordinal
            or packet["type"] != constraint.constraint_type.value
            or packet["underlying_type"]
            != (
                None
                if constraint.underlying_constraint_type is None
                else constraint.underlying_constraint_type.value
            )
            or packet["scope"] != constraint.scope.value
            or packet["normalized_rule"] != constraint.normalized_rule
            or packet["priority"] != constraint.priority
            or packet["source_kind"] != constraint.source_kind.value
            or packet["confidence"] != constraint.confidence.value
            or packet["status"] != constraint.resolution_status.value
            or packet["conflict_group_id"] != constraint.conflict_group_id
            or not condition_agrees
        ):
            raise _InspectionDataError("Packet and stored constraint disagree.")

        source = _object(packet["source_evidence"], "packet constraint source")
        if (
            source["constraint_id"] != str(constraint.id)
            or source["source_created_at"]
            != format_utc_timestamp(constraint.created_at)
        ):
            raise _InspectionDataError("Packet constraint source lineage disagrees.")
        if constraint.source_kind is ConstraintSourceKind.CURRENT_MESSAGE and (
            source["source_message_id"] != str(artifacts.message.id)
            or source["source_message_sequence"]
            != artifacts.message.sequence_number
        ):
            raise _InspectionDataError("Packet current-message lineage disagrees.")

    def _retrieved_memories(
        self,
        packet: ContextPacketRecord,
    ) -> InspectionCollection[RetrievedMemoryInspectionView]:
        snapshots = _array(packet.packet.packet_json["retrieval"], "packet retrieval")
        if len(snapshots) != len(packet.retrieval_results):
            raise _InspectionDataError("Packet retrieval rows are incomplete.")
        projected: list[RetrievedMemoryInspectionView] = []
        for raw, result in zip(snapshots, packet.retrieval_results, strict=True):
            snapshot = _object(raw, "packet selected memory")
            if (
                snapshot["memory_id"] != str(result.memory_id)
                or snapshot["rank"] != result.rank
                or snapshot["score"] != result.score.value
                or snapshot["reasons"] != result.reasons
            ):
                raise _InspectionDataError("Packet retrieval evidence disagrees.")
            projected.append(
                RetrievedMemoryInspectionView(
                    result.rank + 1,
                    str(snapshot["content"]),
                    _label(str(snapshot["scope"])),
                    _score(snapshot["confidence"]),
                    _score(result.score),
                    result.reasons,
                )
            )
        return _collection(tuple(projected))

    @staticmethod
    def _confidence(payload: FrozenJsonObject) -> ConfidenceInspectionView:
        value = _object(payload["confidence"], "packet confidence")
        reference = value["references"]
        retrieval = value["retrieval"]
        return ConfidenceInspectionView(
            _score(value["overall"]),
            _score(value["interpretation"]),
            (
                _not_applicable()
                if reference is None
                else _available(_score(reference), _score(reference).display_text)
            ),
            (
                _not_applicable()
                if retrieval is None
                else _available(_score(retrieval), _score(retrieval).display_text)
            ),
        )

    def _latest_validation(
        self,
        artifacts: _Artifacts,
        packet_id: DomainId,
    ) -> InspectionValue[ValidationInspectionView] | None:
        requests = artifacts.requests
        if len({request.id for request in requests}) != len(requests):
            raise _InspectionDataError("Model-request identities are not unique.")
        if [request.attempt_number for request in requests] != list(
            range(len(requests))
        ):
            raise _InspectionDataError("Model-request attempts are not contiguous.")
        if any(request.context_packet_id != packet_id for request in requests):
            raise _InspectionDataError("Model request names another packet.")
        for request in requests:
            expected_purpose = (
                ModelRequestPurpose.INITIAL
                if request.attempt_number == 0
                else ModelRequestPurpose.REVISION
            )
            if request.purpose is not expected_purpose:
                raise _InspectionDataError("Model-request purpose disagrees with attempt.")

        if len(artifacts.responses) != len(requests):
            raise _InspectionDataError("Model-response lookup is incomplete.")
        response_ids: set[DomainId] = set()
        linked: list[tuple[ModelRequest, ModelResponse, ValidationResult]] = []
        for request, response in zip(requests, artifacts.responses, strict=True):
            if response is None:
                if request.status is ModelRequestStatus.SUCCEEDED:
                    raise _InspectionDataError("Succeeded model request lacks a response.")
                continue
            if (
                request.status is not ModelRequestStatus.SUCCEEDED
                or response.model_request_id != request.id
                or response.id in response_ids
                or request.completed_at is None
                or response.created_at != request.completed_at
            ):
                raise _InspectionDataError("Model response lineage is invalid.")
            response_ids.add(response.id)
            validation = self._repositories.validations.get_for_response(response.id)
            if (
                validation is None
                or validation.model_response_id != response.id
                or validation.created_at != response.created_at
            ):
                raise _InspectionDataError("Validation lineage is invalid.")
            if response.assistant_message_id is not None:
                if (
                    validation.status is not ValidationStatus.PASSED
                    or artifacts.run.status is not ProcessingRunStatus.SUCCEEDED
                ):
                    raise _InspectionDataError(
                        "Only a passed succeeded response may link an assistant message."
                    )
                assistant = self._repositories.messages.get(
                    response.assistant_message_id
                )
                if (
                    assistant is None
                    or assistant.id != response.assistant_message_id
                    or assistant.conversation_id != artifacts.run.conversation_id
                    or assistant.role is not MessageRole.ASSISTANT
                    or assistant.original_text.encode("utf-8")
                    != response.response_text.encode("utf-8")
                ):
                    raise _InspectionDataError("Assistant-message lineage is invalid.")
            linked.append((request, response, validation))

        if artifacts.run.status is ProcessingRunStatus.SUCCEEDED:
            if not linked:
                raise _InspectionDataError("Succeeded run lacks validated response lineage.")
            _, final_response, _ = max(
                linked,
                key=lambda value: value[0].attempt_number,
            )
            if final_response.assistant_message_id is None:
                raise _InspectionDataError("Succeeded run lacks its assistant link.")

        listed_by_id = {validation.id: validation for validation in artifacts.validations}
        if len(listed_by_id) != len(artifacts.validations) or set(listed_by_id) != {
            validation.id for _, _, validation in linked
        }:
            raise _InspectionDataError("Listed validation rows disagree with lineage.")

        corrections = tuple(
            sorted(artifacts.corrections, key=lambda value: value.attempt_number)
        )
        if [value.attempt_number for value in corrections] != list(
            range(1, len(corrections) + 1)
        ) or len(corrections) > 2:
            raise _InspectionDataError("Correction attempts are not contiguous.")
        request_by_id = {request.id: request for request in requests}
        response_by_id = {response.id: response for _, response, _ in linked}
        validation_by_response = {
            response.id: validation for _, response, validation in linked
        }
        for correction in corrections:
            revised = request_by_id.get(correction.revised_model_request_id)
            prior = response_by_id.get(correction.prior_model_response_id)
            if (
                revised is None
                or revised.attempt_number != correction.attempt_number
                or prior is None
            ):
                raise _InspectionDataError("Correction request lineage is invalid.")
            prior_request = request_by_id.get(prior.model_request_id)
            prior_validation = validation_by_response.get(prior.id)
            if (
                prior_request is None
                or prior_request.attempt_number != correction.attempt_number - 1
                or prior_validation is None
                or prior_validation.status is not ValidationStatus.FAILED
                or correction.reasons != prior_validation.violations
            ):
                raise _InspectionDataError("Correction validation lineage is invalid.")
        if len(requests) > 1 and len(corrections) != len(requests) - 1:
            raise _InspectionDataError("Revision requests lack correction rows.")

        policy = _object(
            artifacts.packet.packet.packet_json["response_policy"],  # type: ignore[union-attr]
            "packet response policy",
        )
        limit = policy["correction_limit"]
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit not in (0, 1, 2)
            or len(corrections) > limit
        ):
            raise _InspectionDataError("Correction count exceeds packet policy.")

        if not linked:
            return None
        request, _, validation = max(linked, key=lambda value: value[0].attempt_number)
        view = ValidationInspectionView(
            request.attempt_number + 1,
            _label(validation.status.value),
            _score(validation.score),
            tuple(
                SafeValidationViolationView(
                    violation.ordinal + 1,
                    _label(violation.code.value),
                    violation.message,
                )
                for violation in validation.violations
            ),
            tuple(
                SafeValidationEvidenceView(
                    evidence.ordinal + 1,
                    _label(evidence.check_id.value),
                    _label(evidence.severity.value),
                    _label(evidence.outcome.value),
                    (
                        None
                        if evidence.violation_code is None
                        else _label(evidence.violation_code.value)
                    ),
                    (
                        None
                        if evidence.warning_code is None
                        else _label(evidence.warning_code.value)
                    ),
                    evidence.explanation,
                )
                for evidence in validation.evidence
            ),
        )
        return _available(view, view.status.display_label)

    @staticmethod
    def _terminal_status(artifacts: _Artifacts) -> SafeTerminalStatusView:
        if len(artifacts.failures) != 1:
            raise _InspectionDataError("Terminal run requires one safe failure.")
        failure = artifacts.failures[0]
        cancellation_codes = {
            FailureCode.CANCELLED_BY_USER,
            FailureCode.MODEL_CANCELLED,
        }
        if (
            not failure.is_terminal
            or artifacts.run.completed_at != failure.created_at
            or (
                artifacts.run.status is ProcessingRunStatus.CANCELLED
            ) != (failure.error_code in cancellation_codes)
        ):
            raise _InspectionDataError("Terminal failure lineage is invalid.")
        kind = (
            SafeTerminalKind.CANCELLED
            if artifacts.run.status is ProcessingRunStatus.CANCELLED
            else SafeTerminalKind.CONTROLLED_FAILURE
        )
        return SafeTerminalStatusView(
            kind,
            _label(kind.value).display_label,
            _label(failure.stage.value),
            _label(failure.error_code.value),
            failure.safe_message,
        )


__all__ = ["InspectContextService", "InspectionSnapshotBoundary"]
