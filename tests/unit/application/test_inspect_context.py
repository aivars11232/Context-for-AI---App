"""Focused TASK-0016 application-query tests without SQLite or Qt."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from context_for_ai.application.contracts import (
    ContextInspectionEmptyResult,
    ContextInspectionLoadFailureResult,
    ContextInspectionReadyResult,
    InspectContextRequest,
    InspectionAvailability,
    InspectionCheckpoint,
    InspectionRunOutcome,
)
from context_for_ai.application.inspect_context import InspectContextService
from context_for_ai.context_engine.context_packet import DeterministicContextPacketBuilder
from context_for_ai.context_engine.response_validation import (
    DeterministicResponseValidator,
)
from context_for_ai.domain.decisions import (
    Constraint,
    ConstraintDecision,
    ConstraintPacketLineage,
    ConstraintSourceEvidence,
    InterpretationDecision,
    QualifierMatch,
    ReferenceCandidateEvidence,
    ReferenceOutcome,
    RequestInterpretation,
    ResponsePolicy,
    RetrievalResult,
)
from context_for_ai.domain.entities import (
    Conversation,
    ConversationState,
    ConversationTask,
    Memory,
    Message,
    Project,
    Topic,
)
from context_for_ai.domain.enums import (
    ClarificationReason,
    ConstraintResolutionStatus,
    ConstraintScope,
    ConstraintSourceKind,
    ConstraintType,
    EntityType,
    FailureCode,
    IntentType,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    OutputType,
    PipelineStage,
    ProcessingRunStatus,
    ProjectStatus,
    ProviderKind,
    QualifierKind,
    ReferenceRankReason,
    ReferenceStatus,
    TaskStatus,
)
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
    CorrectionAttempt,
    ModelRequest,
    ModelResponse,
    ProcessingRun,
    SafeFailure,
)
from context_for_ai.domain.policies import PriorityBand
from context_for_ai.domain.ports.configuration import (
    OutputShapeRule,
    ValidationConfigurationSnapshot,
)
from context_for_ai.domain.ports.context import (
    ContextPacketBuildRequest,
    ContextPacketBuildSuccess,
    RetrievalDecision,
    ValidationRequest,
)
from context_for_ai.domain.ports.errors import PersistenceError
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"91000000-0000-4000-8000-{number:012d}")


@dataclass
class SnapshotBoundary:
    active: bool = False
    entries: int = 0
    exits: int = 0

    @contextmanager
    def snapshot(self):
        assert not self.active
        self.active = True
        self.entries += 1
        try:
            yield
        finally:
            self.active = False
            self.exits += 1


class LookupRepository:
    def __init__(self, snapshot: SnapshotBoundary, values: tuple[object, ...]) -> None:
        self._snapshot = snapshot
        self._values = {getattr(value, "id"): value for value in values}

    def get(self, identifier: DomainId):
        assert self._snapshot.active
        return self._values.get(identifier)


class ConversationStateLookup:
    def __init__(
        self,
        snapshot: SnapshotBoundary,
        values: tuple[ConversationState, ...],
    ) -> None:
        self._snapshot = snapshot
        self._values = {value.conversation_id: value for value in values}

    def get(self, identifier: DomainId):
        assert self._snapshot.active
        return self._values.get(identifier)


class RunRepository:
    def __init__(
        self,
        snapshot: SnapshotBoundary,
        values: tuple[ProcessingRun, ...],
    ) -> None:
        self._snapshot = snapshot
        self._values = values

    def list_for_conversation(self, conversation_id: DomainId):
        assert self._snapshot.active
        return tuple(
            value for value in self._values if value.conversation_id == conversation_id
        )


class RunLinkedRepository:
    def __init__(self, snapshot: SnapshotBoundary, values: tuple[object, ...] = ()) -> None:
        self._snapshot = snapshot
        self._values = values

    def list_for_run(self, processing_run_id: DomainId):
        assert self._snapshot.active
        return tuple(
            value
            for value in self._values
            if getattr(value, "processing_run_id", None) == processing_run_id
        )


class PacketRepository:
    def __init__(self, snapshot: SnapshotBoundary, values: tuple[object, ...] = ()) -> None:
        self._snapshot = snapshot
        self._values = values

    def get_for_run(self, processing_run_id: DomainId):
        assert self._snapshot.active
        return next(
            (
                value
                for value in self._values
                if value.packet.processing_run_id == processing_run_id
            ),
            None,
        )


class ModelCallRepository:
    def __init__(
        self,
        snapshot: SnapshotBoundary,
        *,
        requests: tuple[ModelRequest, ...] = (),
        responses: tuple[ModelResponse, ...] = (),
        corrections: tuple[object, ...] = (),
        failures: tuple[object, ...] = (),
    ) -> None:
        self._snapshot = snapshot
        self._requests = requests
        self._responses = responses
        self._corrections = corrections
        self._failures = failures

    def list_requests_for_run(self, processing_run_id: DomainId):
        assert self._snapshot.active
        return tuple(
            value
            for value in self._requests
            if value.processing_run_id == processing_run_id
        )

    def get_response_for_request(self, model_request_id: DomainId):
        assert self._snapshot.active
        return next(
            (
                value
                for value in self._responses
                if value.model_request_id == model_request_id
            ),
            None,
        )

    def list_corrections_for_run(self, processing_run_id: DomainId):
        assert self._snapshot.active
        return tuple(
            value
            for value in self._corrections
            if value.processing_run_id == processing_run_id
        )

    def list_failures_for_run(self, processing_run_id: DomainId):
        assert self._snapshot.active
        return tuple(
            value
            for value in self._failures
            if value.processing_run_id == processing_run_id
        )


class ValidationRepository:
    def __init__(
        self,
        snapshot: SnapshotBoundary,
        run_id: DomainId | None = None,
        values: tuple[object, ...] = (),
    ) -> None:
        self._snapshot = snapshot
        self._run_id = run_id
        self._values = values

    def list_for_run(self, processing_run_id: DomainId):
        assert self._snapshot.active
        return self._values if processing_run_id == self._run_id else ()

    def get_for_response(self, model_response_id: DomainId):
        assert self._snapshot.active
        return next(
            (
                value
                for value in self._values
                if value.model_response_id == model_response_id
            ),
            None,
        )


class ClarificationRepository:
    def __init__(self, snapshot: SnapshotBoundary, values: tuple[object, ...] = ()) -> None:
        self._snapshot = snapshot
        self._values = values

    def get_for_run(self, processing_run_id: DomainId):
        assert self._snapshot.active
        return next(
            (
                value
                for value in self._values
                if value.processing_run_id == processing_run_id
            ),
            None,
        )


def conversation(number: int = 1) -> Conversation:
    return Conversation(identifier(number), None, None, NOW, NOW)


def state(value: Conversation) -> ConversationState:
    return ConversationState(value.id, None, None, None, None, (), 0, NOW)


def message(
    value: Conversation,
    number: int,
    sequence: int,
    *,
    role: MessageRole = MessageRole.USER,
) -> Message:
    return Message(
        identifier(number),
        value.id,
        role,
        f"request-{number}",
        NOW + timedelta(seconds=sequence),
        sequence,
    )


def run(
    value: Conversation,
    source: Message,
    number: int,
    *,
    started_offset: int = 0,
) -> ProcessingRun:
    return ProcessingRun(
        identifier(number),
        value.id,
        source.id,
        f"key-{number}",
        ProcessingRunStatus.PERSISTED,
        0,
        "configuration-fingerprint",
        NOW + timedelta(minutes=started_offset),
        None,
    )


def service_fixture(
    *,
    conversations: tuple[Conversation, ...],
    states: tuple[ConversationState, ...],
    messages: tuple[Message, ...] = (),
    runs: tuple[ProcessingRun, ...] = (),
    projects: tuple[Project, ...] = (),
    topics: tuple[Topic, ...] = (),
    tasks: tuple[ConversationTask, ...] = (),
    packets: tuple[object, ...] = (),
    references: tuple[ReferenceOutcome, ...] = (),
    constraints: tuple[Constraint, ...] = (),
    model_requests: tuple[ModelRequest, ...] = (),
    model_responses: tuple[ModelResponse, ...] = (),
    validations: tuple[object, ...] = (),
    corrections: tuple[object, ...] = (),
    failures: tuple[object, ...] = (),
    clarifications: tuple[object, ...] = (),
):
    snapshots = SnapshotBoundary()
    repositories = SimpleNamespace(
        projects=LookupRepository(snapshots, projects),
        conversations=LookupRepository(snapshots, conversations),
        topics=LookupRepository(snapshots, topics),
        tasks=LookupRepository(snapshots, tasks),
        conversation_states=ConversationStateLookup(snapshots, states),
        messages=LookupRepository(snapshots, messages),
        processing_runs=RunRepository(snapshots, runs),
        context_packets=PacketRepository(snapshots, packets),
        reference_resolutions=RunLinkedRepository(snapshots, references),
        constraints=RunLinkedRepository(snapshots, constraints),
        model_calls=ModelCallRepository(
            snapshots,
            requests=model_requests,
            responses=model_responses,
            corrections=corrections,
            failures=failures,
        ),
        validations=ValidationRepository(
            snapshots,
            None if not runs else runs[-1].id,
            validations,
        ),
        clarifications=ClarificationRepository(snapshots, clarifications),
    )
    return InspectContextService(
        repositories=repositories,
        snapshots=snapshots,
    ), snapshots, repositories


def validation_configuration() -> ValidationConfigurationSnapshot:
    output_types = tuple(
        value
        for value in OutputType
        if value not in {OutputType.CLARIFICATION, OutputType.CONTROLLED_FAILURE}
    )
    return ValidationConfigurationSnapshot(
        "configuration-fingerprint",
        2,
        "validation-v1",
        tuple(
            OutputShapeRule(
                f"shape-{value.value.casefold()}",
                value,
                "NON_EMPTY_TEXT",
            )
            for value in output_types
        ),
        "preserve-v1",
        ("change", "remove"),
        ("TOOL_CALL:", "ACTION_EXECUTED:"),
    )


def rich_packet_fixture() -> SimpleNamespace:
    selected = Conversation(identifier(1), identifier(2), "Inspection", NOW, NOW)
    project = Project(
        identifier(2),
        "Current canonical project",
        None,
        ProjectStatus.ACTIVE,
        NOW,
        NOW,
    )
    topic = Topic(
        identifier(3),
        selected.id,
        "Planning",
        "planning",
        NOW,
        NOW,
    )
    task = ConversationTask(
        identifier(4),
        selected.id,
        topic.id,
        "Write the plan",
        TaskStatus.OPEN,
        NOW,
        NOW,
    )
    source = Message(
        identifier(10),
        selected.id,
        MessageRole.USER,
        "Explain the Planner briefly.",
        NOW,
        4,
    )
    accepted = ProcessingRun(
        identifier(20),
        selected.id,
        source.id,
        "rich-key",
        ProcessingRunStatus.PERSISTED,
        0,
        "configuration-fingerprint",
        NOW,
        None,
    )
    historical_state = ConversationState(
        selected.id,
        topic.id,
        task.id,
        None,
        OutputType.TEXT_EXPLANATION,
        (topic.id,),
        1,
        NOW,
    )
    qualifier = QualifierMatch(
        QualifierKind.APPROXIMATE,
        "qualifier.approximate",
        "briefly",
    )
    interpretation = InterpretationDecision(
        RequestInterpretation(
            accepted.id,
            source.id,
            IntentType.EXPLAIN,
            OutputType.TEXT_EXPLANATION,
            "intent.explain",
            (qualifier,),
            UnitScore("0.9"),
            "matched explain",
            NOW,
        ),
        "context-rules-v1",
        (),
        None,
        None,
        (),
        None,
        None,
    )
    candidate = ReferenceCandidateEvidence(
        1,
        identifier(31),
        EntityType.NAMED_ITEM,
        "Planner",
        "planner",
        UnitScore("1"),
        ReferenceRankReason.EXACT_NAME,
        None,
        source.id,
        source.sequence_number,
        None,
        True,
    )
    reference = ReferenceOutcome(
        identifier(30),
        accepted.id,
        source.id,
        0,
        "Planner",
        ReferenceStatus.RESOLVED,
        candidate.entity_id,
        source.id,
        UnitScore("1"),
        (candidate,),
        NOW,
    )
    constraint = Constraint(
        identifier(40),
        accepted.id,
        source.id,
        0,
        ConstraintType.FORBIDDEN,
        None,
        ConstraintScope.CURRENT_RESPONSE,
        "MUST_NOT_EXECUTE:IMAGE_OR_ACTION",
        PriorityBand.CURRENT_HARD.value,
        ConstraintSourceKind.DERIVED_OUTPUT_POLICY,
        "MVP text-only/no-actions policy",
        UnitScore("0.9"),
        ConstraintResolutionStatus.ACTIVE,
        None,
        None,
        NOW,
    )
    constraint_evidence = ConstraintSourceEvidence(
        constraint.id,
        "EXECUTE:IMAGE_OR_ACTION",
        ("policy.text-only",),
        ("text-only/no-actions",),
        None,
        NOW,
        ("1000", "0"),
    )
    constraint_decision = ConstraintDecision(
        (constraint,),
        (constraint_evidence,),
        (),
        ResponsePolicy(OutputType.TEXT_EXPLANATION, "context-rules-v1"),
        None,
        None,
    )
    memory = Memory(
        identifier(50),
        None,
        None,
        MemoryType.PROJECT_FACT,
        MemoryScope.GLOBAL,
        MemoryStatus.ACTIVE,
        "Remember the selected immutable planning fact.",
        ("planning",),
        (),
        UnitScore("0.5"),
        UnitScore("0.805"),
        None,
        NOW,
        NOW,
        None,
    )
    reasons = (
        "project_match=0",
        "topic_match=0",
        "keyword_jaccard=0.5",
        "recency=1",
        "importance=0.5",
        "scope_match=1",
        "correction_match=0",
    )
    packet_id = identifier(60)
    retrieval = RetrievalResult(
        identifier(61),
        packet_id,
        memory.id,
        0,
        UnitScore("0.8"),
        reasons,
        NOW,
    )
    build_result = DeterministicContextPacketBuilder().build(
        ContextPacketBuildRequest(
            packet_id,
            accepted,
            source,
            historical_state,
            project.id,
            topic,
            interpretation,
            (reference,),
            constraint_decision,
            (
                ConstraintPacketLineage(
                    constraint.id,
                    None,
                    None,
                    None,
                    None,
                    (),
                ),
            ),
            RetrievalDecision((retrieval,), (), retrieval.score),
            (memory,),
            16384,
            12000,
            512,
            validation_configuration(),
            NOW,
        )
    )
    assert isinstance(build_result, ContextPacketBuildSuccess)
    packet = build_result.record

    candidate_time = NOW + timedelta(minutes=1)
    request = ModelRequest(
        identifier(70),
        accepted.id,
        packet.packet.id,
        ModelRequestPurpose.INITIAL,
        0,
        ProviderKind.OLLAMA,
        "unsafe-provider-model",
        ModelRequestStatus.SUCCEEDED,
        "UNSAFE_RENDERED_PROMPT_SENTINEL",
        FrozenJsonObject({"unsafe_request": "UNSAFE_REQUEST_SENTINEL"}),
        NOW + timedelta(seconds=30),
        candidate_time,
        None,
        None,
    )
    assistant = Message(
        identifier(71),
        selected.id,
        MessageRole.ASSISTANT,
        "Planning response UNSAFE_RESPONSE_SENTINEL.",
        candidate_time + timedelta(seconds=1),
        5,
    )
    response = ModelResponse(
        identifier(72),
        request.id,
        assistant.original_text,
        FrozenJsonObject({"unsafe_metadata": "UNSAFE_PROVIDER_SENTINEL"}),
        assistant.id,
        candidate_time,
    )
    validation = DeterministicResponseValidator().validate(
        ValidationRequest(
            packet.packet,
            response.id,
            identifier(73),
            response.response_text,
            candidate_time,
        )
    )
    completed = replace(
        accepted,
        status=ProcessingRunStatus.SUCCEEDED,
        completed_at=candidate_time + timedelta(seconds=1),
    )
    return SimpleNamespace(
        conversation=selected,
        project=project,
        topic=topic,
        task=task,
        state=historical_state,
        source=source,
        assistant=assistant,
        run=completed,
        packet=packet,
        reference=reference,
        constraint=constraint,
        request=request,
        response=response,
        validation=validation,
        reasons=reasons,
    )


def clarification_fixture(reason: ClarificationReason) -> SimpleNamespace:
    selected = conversation(101)
    source = message(selected, 102, 6)
    completed_at = NOW + timedelta(minutes=1)
    accepted = ProcessingRun(
        identifier(103),
        selected.id,
        source.id,
        f"clarification-{reason.value}",
        ProcessingRunStatus.NEEDS_CLARIFICATION,
        0,
        "configuration-fingerprint",
        NOW,
        completed_at,
    )
    references: tuple[ReferenceOutcome, ...] = ()
    constraints: tuple[Constraint, ...] = ()
    if reason in {
        ClarificationReason.AMBIGUOUS_REFERENCE,
        ClarificationReason.UNRESOLVED_REFERENCE,
    }:
        placeholder = ReferenceCandidateEvidence(
            1,
            None,
            None,
            None,
            None,
            UnitScore(0),
            ReferenceRankReason.NO_CANDIDATE,
            None,
            None,
            None,
            None,
            None,
        )
        references = (
            ReferenceOutcome(
                identifier(104),
                accepted.id,
                source.id,
                0,
                "missing item",
                ReferenceStatus.UNRESOLVED,
                None,
                None,
                UnitScore(0),
                (placeholder,),
                completed_at,
            ),
        )
    elif reason in {
        ClarificationReason.UNSUPPORTED_CONDITION,
        ClarificationReason.MATERIAL_ASSUMPTION,
        ClarificationReason.HARD_CONSTRAINT_CONFLICT,
    }:
        count = 2 if reason is ClarificationReason.HARD_CONSTRAINT_CONFLICT else 1
        constraints = tuple(
            Constraint(
                identifier(110 + ordinal),
                accepted.id,
                source.id,
                ordinal,
                ConstraintType.REQUIRED if ordinal == 0 else ConstraintType.FORBIDDEN,
                None,
                ConstraintScope.CURRENT_RESPONSE,
                (
                    "MUST_USE:SAFE_FORMAT"
                    if ordinal == 0
                    else "MUST_NOT_USE:SAFE_FORMAT"
                ),
                PriorityBand.CURRENT_HARD.value,
                ConstraintSourceKind.CURRENT_MESSAGE,
                source.original_text,
                UnitScore("0.9"),
                (
                    ConstraintResolutionStatus.CONFLICTING
                    if count == 2
                    else ConstraintResolutionStatus.ACTIVE
                ),
                "hidden-conflict-group" if count == 2 else None,
                None,
                completed_at,
            )
            for ordinal in range(count)
        )
    clarification = ClarificationRequest(
        identifier(120),
        accepted.id,
        reason,
        f"Question for {reason.value}?",
        FrozenJsonObject({"unsafe_detail": "UNSAFE_CLARIFICATION_SENTINEL"}),
        completed_at,
    )
    return SimpleNamespace(
        conversation=selected,
        state=state(selected),
        source=source,
        run=accepted,
        references=references,
        constraints=constraints,
        clarification=clarification,
    )


def corrected_packet_fixture() -> SimpleNamespace:
    rich = rich_packet_fixture()
    failed_time = NOW + timedelta(seconds=30)
    first_request = replace(
        rich.request,
        id=identifier(130),
        started_at=NOW + timedelta(seconds=10),
        completed_at=failed_time,
    )
    first_response = ModelResponse(
        identifier(131),
        first_request.id,
        "",
        FrozenJsonObject({"unsafe": "UNSAFE_FAILED_CANDIDATE_METADATA"}),
        None,
        failed_time,
    )
    first_validation = DeterministicResponseValidator().validate(
        ValidationRequest(
            rich.packet.packet,
            first_response.id,
            identifier(132),
            first_response.response_text,
            failed_time,
        )
    )
    final_time = NOW + timedelta(minutes=1)
    revised_request = replace(
        rich.request,
        id=identifier(133),
        purpose=ModelRequestPurpose.REVISION,
        attempt_number=1,
        started_at=NOW + timedelta(seconds=45),
        completed_at=final_time,
    )
    final_response = replace(
        rich.response,
        id=identifier(134),
        model_request_id=revised_request.id,
        created_at=final_time,
    )
    final_validation = DeterministicResponseValidator().validate(
        ValidationRequest(
            rich.packet.packet,
            final_response.id,
            identifier(135),
            final_response.response_text,
            final_time,
        )
    )
    correction = CorrectionAttempt(
        identifier(136),
        rich.run.id,
        1,
        first_response.id,
        revised_request.id,
        first_validation.violations,
        NOW + timedelta(seconds=45),
    )
    completed_run = replace(
        rich.run,
        completed_at=rich.assistant.created_at,
    )
    return SimpleNamespace(
        **{
            **vars(rich),
            "run": completed_run,
            "requests": (first_request, revised_request),
            "responses": (first_response, final_response),
            "validations": (first_validation, final_validation),
            "correction": correction,
        }
    )


def test_existing_conversation_without_run_returns_exact_empty_inside_snapshot() -> None:
    selected = conversation()
    service, snapshots, _ = service_fixture(
        conversations=(selected,),
        states=(state(selected),),
    )

    result = service.execute(InspectContextRequest(selected.id))

    assert result == ContextInspectionEmptyResult()
    assert result.safe_message == (
        "No processed request is available for this conversation."
    )
    assert snapshots.entries == snapshots.exits == 1
    assert snapshots.active is False


def test_latest_target_uses_greatest_linked_user_sequence_not_time_or_uuid() -> None:
    selected = conversation()
    later_sequence = message(selected, 20, 8)
    earlier_sequence = message(selected, 30, 2)
    newer_started_run = run(
        selected,
        earlier_sequence,
        40,
        started_offset=20,
    )
    older_started_run = run(selected, later_sequence, 50)
    service, snapshots, _ = service_fixture(
        conversations=(selected,),
        states=(state(selected),),
        messages=(earlier_sequence, later_sequence),
        runs=(newer_started_run, older_started_run),
    )

    result = service.execute(InspectContextRequest(selected.id))

    assert isinstance(result, ContextInspectionReadyResult)
    assert result.view.target.user_message_sequence == 8
    assert result.view.target.request_label == "Request 8"
    assert result.view.target.outcome is InspectionRunOutcome.PROCESSING
    assert result.view.target.checkpoint is InspectionCheckpoint.ACCEPTED
    assert result.view.active_project.availability is InspectionAvailability.UNAVAILABLE
    assert result.view.references.availability is InspectionAvailability.UNAVAILABLE
    assert result.view.clarification.availability is InspectionAvailability.NOT_APPLICABLE
    assert result.view.terminal_status.availability is InspectionAvailability.UNAVAILABLE
    assert snapshots.entries == snapshots.exits == 1


@pytest.mark.parametrize("defect", ["duplicate_sequence", "non_user"])
def test_invalid_target_message_lineage_returns_whole_load_failure(defect: str) -> None:
    selected = conversation()
    first = message(selected, 20, 3)
    second = message(
        selected,
        21,
        3 if defect == "duplicate_sequence" else 4,
        role=MessageRole.USER if defect == "duplicate_sequence" else MessageRole.ASSISTANT,
    )
    service, snapshots, _ = service_fixture(
        conversations=(selected,),
        states=(state(selected),),
        messages=(first, second),
        runs=(run(selected, first, 30), run(selected, second, 31)),
    )

    result = service.execute(InspectContextRequest(selected.id))

    assert result == ContextInspectionLoadFailureResult()
    assert result.code == "INSPECTION_LOAD_FAILED"
    assert result.safe_message == "Context inspection could not be loaded safely."
    assert snapshots.entries == snapshots.exits == 1


@pytest.mark.parametrize("missing", ["conversation", "state"])
def test_missing_conversation_or_required_state_is_not_empty(missing: str) -> None:
    selected = conversation()
    service, _, _ = service_fixture(
        conversations=() if missing == "conversation" else (selected,),
        states=() if missing == "state" else (state(selected),),
    )

    result = service.execute(InspectContextRequest(selected.id))

    assert result == ContextInspectionLoadFailureResult()


def test_repository_failure_returns_safe_load_failure_and_closes_snapshot() -> None:
    selected = conversation()
    service, snapshots, repositories = service_fixture(
        conversations=(selected,),
        states=(state(selected),),
    )

    def fail(_: DomainId):
        assert snapshots.active
        raise PersistenceError("UNSAFE DATABASE PATH /tmp/private.sqlite")

    repositories.processing_runs.list_for_conversation = fail

    result = service.execute(InspectContextRequest(selected.id))

    assert result == ContextInspectionLoadFailureResult()
    assert "private" not in result.safe_message
    assert snapshots.entries == snapshots.exits == 1
    assert snapshots.active is False


def test_wrong_request_type_remains_a_programming_error() -> None:
    selected = conversation()
    service, snapshots, _ = service_fixture(
        conversations=(selected,),
        states=(state(selected),),
    )

    with pytest.raises(TypeError, match="InspectContextRequest"):
        service.execute(object())  # type: ignore[arg-type]

    assert snapshots.entries == 0


def test_packet_and_latest_validation_project_one_complete_redacted_safe_view() -> None:
    rich = rich_packet_fixture()
    service, snapshots, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source, rich.assistant),
        runs=(rich.run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=(rich.task,),
        packets=(rich.packet,),
        references=(rich.reference,),
        constraints=(rich.constraint,),
        model_requests=(rich.request,),
        model_responses=(rich.response,),
        validations=(rich.validation,),
    )

    result = service.execute(InspectContextRequest(rich.conversation.id))

    assert isinstance(result, ContextInspectionReadyResult)
    view = result.view
    assert view.target.request_label == "Request 4"
    assert view.target.outcome is InspectionRunOutcome.SUCCEEDED
    assert view.target.checkpoint is InspectionCheckpoint.VALIDATION_COMMITTED
    assert view.target.outcome_label == "Succeeded"
    assert view.target.checkpoint_label == "Validation committed"

    assert view.active_project.value.display_name == "Current canonical project"
    assert view.active_topic.value.display_name == "Planning"
    assert view.active_task.value.display_name == "Write the plan"
    assert view.intent.value.code == "EXPLAIN"
    assert view.intent.display_text == "Explain"
    assert view.expected_output_type.value.code == "TEXT_EXPLANATION"
    assert view.expected_output_type.display_text == "Text explanation"

    assert view.qualifier_evidence.availability is InspectionAvailability.AVAILABLE
    assert [value.ordinal for value in view.qualifier_evidence.items] == [1]
    assert view.qualifier_evidence.items[0].matched_text == "briefly"
    assert view.references.availability is InspectionAvailability.AVAILABLE
    reference = view.references.items[0]
    assert reference.mention_number == 1
    assert reference.resolved_display_name.value == "Planner"
    assert reference.source_message.value.display_text == "Message 4"
    assert reference.evidence[0].candidate_type.code == "NAMED_ITEM"
    assert reference.evidence[0].score.display_text == "1.00"
    assert reference.evidence[0].activity_display_text == "Active"

    assert view.constraints.availability is InspectionAvailability.AVAILABLE
    constraint = view.constraints.items[0]
    assert constraint.ordinal == 1
    assert constraint.type.code == "FORBIDDEN"
    assert constraint.source_text == "MVP text-only/no-actions policy"
    assert view.conflicts.availability is InspectionAvailability.EMPTY
    assert view.conflicts.display_text == "None recorded."

    assert view.retrieved_memories.availability is InspectionAvailability.AVAILABLE
    memory = view.retrieved_memories.items[0]
    assert memory.rank == 1
    assert memory.content == "Remember the selected immutable planning fact."
    assert memory.memory_confidence.canonical_decimal == "0.805"
    assert memory.memory_confidence.display_text == "0.80"
    assert memory.retrieval_score.display_text == "0.80"
    assert memory.reasons == rich.reasons

    assert view.confidence.value.overall.canonical_decimal == "0.91"
    assert view.confidence.value.overall.display_text == "0.91"
    assert view.confidence.value.references.value.display_text == "1.00"
    assert view.validation.availability is InspectionAvailability.AVAILABLE
    assert view.validation.value.attempt_number == 1
    assert view.validation.value.status.code == "PASSED"
    assert view.validation.value.score.display_text == "1.00"
    assert view.validation.value.violations == ()
    assert view.validation.value.evidence
    assert view.correction_count.value == 0
    assert view.correction_count.display_text == "0"
    assert view.clarification.availability is InspectionAvailability.NOT_APPLICABLE
    assert view.terminal_status.availability is InspectionAvailability.NOT_APPLICABLE

    safe_rendering = repr(result)
    for unsafe in (
        "UNSAFE_RENDERED_PROMPT_SENTINEL",
        "UNSAFE_REQUEST_SENTINEL",
        "UNSAFE_RESPONSE_SENTINEL",
        "UNSAFE_PROVIDER_SENTINEL",
        "unsafe-provider-model",
    ):
        assert unsafe not in safe_rendering
    assert snapshots.entries == snapshots.exits == 1


@pytest.mark.parametrize("defect", ["text_mismatch", "missing_final_link"])
def test_succeeded_assistant_linkage_must_be_complete_and_byte_exact(
    defect: str,
) -> None:
    rich = rich_packet_fixture()
    assistant = (
        replace(rich.assistant, original_text="different assistant bytes")
        if defect == "text_mismatch"
        else rich.assistant
    )
    response = (
        replace(rich.response, assistant_message_id=None)
        if defect == "missing_final_link"
        else rich.response
    )
    service, _, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source, assistant),
        runs=(rich.run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=(rich.task,),
        packets=(rich.packet,),
        references=(rich.reference,),
        constraints=(rich.constraint,),
        model_requests=(rich.request,),
        model_responses=(response,),
        validations=(rich.validation,),
    )

    result = service.execute(InspectContextRequest(rich.conversation.id))

    assert result == ContextInspectionLoadFailureResult()


def test_failed_validation_candidate_cannot_carry_an_assistant_link() -> None:
    rich = corrected_packet_fixture()
    invalid_first_response = replace(
        rich.responses[0],
        response_text=rich.assistant.original_text,
        assistant_message_id=rich.assistant.id,
    )
    service, _, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source, rich.assistant),
        runs=(rich.run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=(rich.task,),
        packets=(rich.packet,),
        references=(rich.reference,),
        constraints=(rich.constraint,),
        model_requests=rich.requests,
        model_responses=(invalid_first_response, rich.responses[1]),
        validations=rich.validations,
        corrections=(rich.correction,),
    )

    result = service.execute(InspectContextRequest(rich.conversation.id))

    assert result == ContextInspectionLoadFailureResult()


def test_context_committed_checkpoint_has_exact_pre_validation_availability() -> None:
    rich = rich_packet_fixture()
    context_ready_run = replace(
        rich.run,
        status=ProcessingRunStatus.CONTEXT_READY,
        completed_at=None,
    )
    service, _, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source,),
        runs=(context_ready_run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=(rich.task,),
        packets=(rich.packet,),
        references=(rich.reference,),
        constraints=(rich.constraint,),
    )

    result = service.execute(InspectContextRequest(rich.conversation.id))

    assert isinstance(result, ContextInspectionReadyResult)
    view = result.view
    assert view.target.checkpoint is InspectionCheckpoint.CONTEXT_COMMITTED
    assert view.target.outcome is InspectionRunOutcome.PROCESSING
    assert view.active_project.availability is InspectionAvailability.AVAILABLE
    assert view.intent.availability is InspectionAvailability.AVAILABLE
    assert view.qualifier_evidence.availability is InspectionAvailability.AVAILABLE
    assert view.references.availability is InspectionAvailability.AVAILABLE
    assert view.constraints.availability is InspectionAvailability.AVAILABLE
    assert view.conflicts.availability is InspectionAvailability.EMPTY
    assert view.retrieved_memories.availability is InspectionAvailability.AVAILABLE
    assert view.confidence.availability is InspectionAvailability.AVAILABLE
    assert view.validation.availability is InspectionAvailability.UNAVAILABLE
    assert view.validation.display_text == "Unavailable for this run."
    assert view.correction_count.availability is InspectionAvailability.AVAILABLE
    assert view.correction_count.display_text == "0"
    assert view.clarification.availability is InspectionAvailability.NOT_APPLICABLE
    assert view.terminal_status.availability is InspectionAvailability.UNAVAILABLE


@pytest.mark.parametrize("defect", ["reference_disagreement", "missing_owner"])
def test_packet_row_disagreement_or_missing_active_owner_is_whole_load_failure(
    defect: str,
) -> None:
    rich = rich_packet_fixture()
    references = (
        replace(rich.reference, surface_text="disagrees with packet"),
    ) if defect == "reference_disagreement" else (rich.reference,)
    tasks = () if defect == "missing_owner" else (rich.task,)
    service, _, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source, rich.assistant),
        runs=(rich.run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=tasks,
        packets=(rich.packet,),
        references=references,
        constraints=(rich.constraint,),
        model_requests=(rich.request,),
        model_responses=(rich.response,),
        validations=(rich.validation,),
    )

    result = service.execute(InspectContextRequest(rich.conversation.id))

    assert result == ContextInspectionLoadFailureResult()


@pytest.mark.parametrize(
    ("reason", "expected_availability"),
    [
        (
            ClarificationReason.LOW_CONFIDENCE_INTERPRETATION,
            (
                InspectionAvailability.UNAVAILABLE,
                InspectionAvailability.UNAVAILABLE,
                InspectionAvailability.UNAVAILABLE,
            ),
        ),
        (
            ClarificationReason.UNSUPPORTED_INTENT,
            (
                InspectionAvailability.UNAVAILABLE,
                InspectionAvailability.UNAVAILABLE,
                InspectionAvailability.UNAVAILABLE,
            ),
        ),
        (
            ClarificationReason.AMBIGUOUS_REFERENCE,
            (
                InspectionAvailability.AVAILABLE,
                InspectionAvailability.UNAVAILABLE,
                InspectionAvailability.UNAVAILABLE,
            ),
        ),
        (
            ClarificationReason.UNRESOLVED_REFERENCE,
            (
                InspectionAvailability.AVAILABLE,
                InspectionAvailability.UNAVAILABLE,
                InspectionAvailability.UNAVAILABLE,
            ),
        ),
        (
            ClarificationReason.UNSUPPORTED_CONDITION,
            (
                InspectionAvailability.EMPTY,
                InspectionAvailability.AVAILABLE,
                InspectionAvailability.EMPTY,
            ),
        ),
        (
            ClarificationReason.MATERIAL_ASSUMPTION,
            (
                InspectionAvailability.EMPTY,
                InspectionAvailability.AVAILABLE,
                InspectionAvailability.EMPTY,
            ),
        ),
        (
            ClarificationReason.HARD_CONSTRAINT_CONFLICT,
            (
                InspectionAvailability.EMPTY,
                InspectionAvailability.AVAILABLE,
                InspectionAvailability.AVAILABLE,
            ),
        ),
    ],
)
def test_clarification_reason_controls_exact_evidence_availability(
    reason: ClarificationReason,
    expected_availability: tuple[
        InspectionAvailability,
        InspectionAvailability,
        InspectionAvailability,
    ],
) -> None:
    fixture = clarification_fixture(reason)
    service, _, _ = service_fixture(
        conversations=(fixture.conversation,),
        states=(fixture.state,),
        messages=(fixture.source,),
        runs=(fixture.run,),
        references=fixture.references,
        constraints=fixture.constraints,
        clarifications=(fixture.clarification,),
    )

    result = service.execute(InspectContextRequest(fixture.conversation.id))

    assert isinstance(result, ContextInspectionReadyResult)
    view = result.view
    assert view.target.outcome is InspectionRunOutcome.CLARIFICATION
    assert view.target.checkpoint is InspectionCheckpoint.CLARIFICATION_COMMITTED
    assert (
        view.references.availability,
        view.constraints.availability,
        view.conflicts.availability,
    ) == expected_availability
    assert view.clarification.availability is InspectionAvailability.AVAILABLE
    assert view.clarification.value.reason.code == reason.value
    assert view.clarification.value.question_text == f"Question for {reason.value}?"
    assert view.validation.availability is InspectionAvailability.NOT_APPLICABLE
    assert view.correction_count.availability is InspectionAvailability.NOT_APPLICABLE
    assert view.terminal_status.availability is InspectionAvailability.NOT_APPLICABLE
    assert "UNSAFE_CLARIFICATION_SENTINEL" not in repr(result)
    if reason is ClarificationReason.HARD_CONSTRAINT_CONFLICT:
        assert len(view.conflicts.items) == 1
        assert [value.constraint_ordinal for value in view.conflicts.items[0].rules] == [
            1,
            2,
        ]


@pytest.mark.parametrize(
    ("status", "expected_outcome", "expected_kind"),
    [
        (
            ProcessingRunStatus.CONTROLLED_FAILURE,
            InspectionRunOutcome.CONTROLLED_FAILURE,
            "CONTROLLED_FAILURE",
        ),
        (
            ProcessingRunStatus.CANCELLED,
            InspectionRunOutcome.CANCELLED,
            "CANCELLED",
        ),
    ],
)
def test_terminal_without_context_exposes_only_one_safe_terminal_status(
    status: ProcessingRunStatus,
    expected_outcome: InspectionRunOutcome,
    expected_kind: str,
) -> None:
    selected = conversation(201)
    source = message(selected, 202, 9)
    completed_at = NOW + timedelta(minutes=2)
    terminal_run = ProcessingRun(
        identifier(203),
        selected.id,
        source.id,
        f"terminal-{status.value}",
        status,
        0,
        "configuration-fingerprint",
        NOW,
        completed_at,
    )
    error_code = (
        FailureCode.CANCELLED_BY_USER
        if status is ProcessingRunStatus.CANCELLED
        else FailureCode.CONTEXT_CONSTRUCTION_FAILED
    )
    failure = SafeFailure(
        identifier(204),
        terminal_run.id,
        PipelineStage.CONTEXT,
        error_code,
        "The exact safe terminal message.",
        FrozenJsonObject({"unsafe": "UNSAFE_TERMINAL_DETAIL"}),
        True,
        completed_at,
    )
    service, _, _ = service_fixture(
        conversations=(selected,),
        states=(state(selected),),
        messages=(source,),
        runs=(terminal_run,),
        failures=(failure,),
    )

    result = service.execute(InspectContextRequest(selected.id))

    assert isinstance(result, ContextInspectionReadyResult)
    view = result.view
    assert view.target.outcome is expected_outcome
    assert view.target.checkpoint is InspectionCheckpoint.TERMINAL_WITHOUT_CONTEXT
    assert view.validation.availability is InspectionAvailability.NOT_APPLICABLE
    assert view.correction_count.availability is InspectionAvailability.NOT_APPLICABLE
    assert view.terminal_status.availability is InspectionAvailability.AVAILABLE
    assert view.terminal_status.value.kind.value == expected_kind
    assert view.terminal_status.value.code.code == error_code.value
    assert view.terminal_status.value.safe_message == "The exact safe terminal message."
    assert "UNSAFE_TERMINAL_DETAIL" not in repr(result)


def test_packet_stage_model_cancellation_is_a_safe_cancelled_terminal_view() -> None:
    rich = rich_packet_fixture()
    completed_at = NOW + timedelta(minutes=2)
    cancelled_run = replace(
        rich.run,
        status=ProcessingRunStatus.CANCELLED,
        completed_at=completed_at,
    )
    cancelled_request = replace(
        rich.request,
        status=ModelRequestStatus.CANCELLED,
        completed_at=completed_at,
        error_code="MODEL_CANCELLED",
        safe_error_message="The model request was cancelled.",
    )
    failure = SafeFailure(
        identifier(205),
        cancelled_run.id,
        PipelineStage.TRANSPORT,
        FailureCode.MODEL_CANCELLED,
        "The model request was cancelled.",
        FrozenJsonObject({"unsafe": "UNSAFE_MODEL_CANCEL_DETAIL"}),
        True,
        completed_at,
    )
    service, _, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source,),
        runs=(cancelled_run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=(rich.task,),
        packets=(rich.packet,),
        references=(rich.reference,),
        constraints=(rich.constraint,),
        model_requests=(cancelled_request,),
        failures=(failure,),
    )

    result = service.execute(InspectContextRequest(rich.conversation.id))

    assert isinstance(result, ContextInspectionReadyResult)
    assert result.view.target.outcome is InspectionRunOutcome.CANCELLED
    assert result.view.target.checkpoint is InspectionCheckpoint.CONTEXT_COMMITTED
    assert result.view.validation.availability is InspectionAvailability.NOT_APPLICABLE
    assert result.view.terminal_status.value.kind.value == "CANCELLED"
    assert result.view.terminal_status.value.code.code == "MODEL_CANCELLED"
    assert "UNSAFE_MODEL_CANCEL_DETAIL" not in repr(result)


def test_latest_validation_uses_greatest_request_attempt_and_counts_corrections() -> None:
    rich = corrected_packet_fixture()
    service, _, _ = service_fixture(
        conversations=(rich.conversation,),
        states=(rich.state,),
        messages=(rich.source, rich.assistant),
        runs=(rich.run,),
        projects=(rich.project,),
        topics=(rich.topic,),
        tasks=(rich.task,),
        packets=(rich.packet,),
        references=(rich.reference,),
        constraints=(rich.constraint,),
        model_requests=rich.requests,
        model_responses=rich.responses,
        validations=rich.validations,
        corrections=(rich.correction,),
    )

    result = service.execute(InspectContextRequest(rich.conversation.id))

    assert isinstance(result, ContextInspectionReadyResult)
    assert result.view.validation.value.attempt_number == 2
    assert result.view.validation.value.status.code == "PASSED"
    assert result.view.correction_count.value == 1
    assert result.view.target.checkpoint is InspectionCheckpoint.VALIDATION_COMMITTED
    assert "UNSAFE_FAILED_CANDIDATE_METADATA" not in repr(result)
