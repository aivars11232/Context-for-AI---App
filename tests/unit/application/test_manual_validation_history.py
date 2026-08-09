"""Focused TASK-0017 safe validation-history projection tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from context_for_ai.application.contracts import (
    InspectValidationHistoryRequest,
    ValidationHistoryEmptyResult,
    ValidationHistoryReadyResult,
)
from context_for_ai.application.manual_validation_history import (
    InspectValidationHistoryService,
)
from context_for_ai.domain.entities import Conversation, ConversationState, Message
from context_for_ai.domain.enums import (
    ClarificationReason,
    MessageRole,
    ModelRequestPurpose,
    ModelRequestStatus,
    ProcessingRunStatus,
    ProviderKind,
    ValidationStatus,
)
from context_for_ai.domain.lifecycle import (
    ClarificationRequest,
    ModelRequest,
    ModelResponse,
    ProcessingRun,
)
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject, UnitScore


NOW = datetime(2026, 8, 9, 14, 0, tzinfo=UTC)


def identifier(number: int) -> DomainId:
    return DomainId(f"73000000-0000-4000-8000-{number:012d}")


class _Snapshot:
    def __init__(self) -> None:
        self.active = False
        self.entries = 0

    @contextmanager
    def snapshot(self):  # type: ignore[no-untyped-def]
        assert not self.active
        self.active = True
        self.entries += 1
        try:
            yield
        finally:
            self.active = False


class _Lookup:
    def __init__(self, snapshot: _Snapshot, values, *, state=False):  # type: ignore[no-untyped-def]
        self.snapshot = snapshot
        self.values = {
            (item.conversation_id if state else item.id): item for item in values
        }

    def get(self, value):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return self.values.get(value)


class _Runs:
    def __init__(self, snapshot: _Snapshot, values):  # type: ignore[no-untyped-def]
        self.snapshot = snapshot
        self.values = tuple(values)

    def list_for_conversation(self, conversation_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return tuple(item for item in self.values if item.conversation_id == conversation_id)


class _Packets:
    def __init__(self, snapshot: _Snapshot, values):  # type: ignore[no-untyped-def]
        self.snapshot = snapshot
        self.values = dict(values)

    def get_for_run(self, run_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return self.values.get(run_id)


class _ModelCalls:
    def __init__(self, snapshot, requests=(), responses=(), corrections=(), failures=()):  # type: ignore[no-untyped-def]
        self.snapshot = snapshot
        self.requests = tuple(requests)
        self.responses = tuple(responses)
        self.corrections = tuple(corrections)
        self.failures = tuple(failures)

    def list_requests_for_run(self, run_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return tuple(item for item in self.requests if item.processing_run_id == run_id)

    def get_response_for_request(self, request_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return next((item for item in self.responses if item.model_request_id == request_id), None)

    def list_corrections_for_run(self, run_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return tuple(item for item in self.corrections if item.processing_run_id == run_id)

    def list_failures_for_run(self, run_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return tuple(item for item in self.failures if item.processing_run_id == run_id)


class _Validations:
    def __init__(self, snapshot, run_id=None, values=()):  # type: ignore[no-untyped-def]
        self.snapshot = snapshot
        self.run_id = run_id
        self.values = tuple(values)

    def get_for_response(self, response_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return next((item for item in self.values if item.model_response_id == response_id), None)

    def list_for_run(self, run_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return self.values if run_id == self.run_id else ()


class _Clarifications:
    def __init__(self, snapshot, values=()):  # type: ignore[no-untyped-def]
        self.snapshot = snapshot
        self.values = tuple(values)

    def get_for_run(self, run_id):  # type: ignore[no-untyped-def]
        assert self.snapshot.active
        return next((item for item in self.values if item.processing_run_id == run_id), None)


def _base():  # type: ignore[no-untyped-def]
    conversation = Conversation(identifier(1), None, "History", NOW, NOW)
    state = ConversationState(conversation.id, None, None, None, None, (), 0, NOW)
    return conversation, state


def _message(conversation, number, sequence):  # type: ignore[no-untyped-def]
    return Message(
        identifier(number),
        conversation.id,
        MessageRole.USER,
        f"unsafe-user-{number}",
        NOW + timedelta(seconds=sequence),
        sequence,
    )


def _run(conversation, message, number, status=ProcessingRunStatus.PERSISTED):  # type: ignore[no-untyped-def]
    terminal = status not in {
        ProcessingRunStatus.PERSISTED,
        ProcessingRunStatus.CONTEXT_READY,
        ProcessingRunStatus.GENERATING,
        ProcessingRunStatus.REVISING,
    }
    return ProcessingRun(
        identifier(number),
        conversation.id,
        message.id,
        f"key-{number}",
        status,
        0,
        "f" * 64,
        NOW,
        NOW + timedelta(minutes=1) if terminal else None,
    )


def _service(
    *,
    conversation,
    state,
    messages=(),
    runs=(),
    packets=(),
    requests=(),
    responses=(),
    validations=(),
    corrections=(),
    failures=(),
    clarifications=(),
):  # type: ignore[no-untyped-def]
    snapshot = _Snapshot()
    repositories = SimpleNamespace(
        conversations=_Lookup(snapshot, (conversation,)),
        conversation_states=_Lookup(snapshot, (state,), state=True),
        messages=_Lookup(snapshot, messages),
        processing_runs=_Runs(snapshot, runs),
        context_packets=_Packets(snapshot, packets),
        model_calls=_ModelCalls(
            snapshot,
            requests,
            responses,
            corrections,
            failures,
        ),
        validations=_Validations(
            snapshot,
            None if not runs else runs[-1].id,
            validations,
        ),
        clarifications=_Clarifications(snapshot, clarifications),
    )
    return InspectValidationHistoryService(
        repositories=repositories,
        snapshots=snapshot,
    ), snapshot


def test_no_accepted_run_is_empty_in_one_snapshot() -> None:
    conversation, state = _base()
    service, snapshot = _service(conversation=conversation, state=state)

    result = service.execute(InspectValidationHistoryRequest(conversation.id))

    assert isinstance(result, ValidationHistoryEmptyResult)
    assert snapshot.entries == 1


def test_latest_target_uses_user_message_sequence_not_run_time() -> None:
    conversation, state = _base()
    older_message = _message(conversation, 10, 2)
    latest_message = _message(conversation, 11, 7)
    later_started_older = replace(
        _run(conversation, older_message, 20),
        started_at=NOW + timedelta(hours=2),
    )
    latest = _run(conversation, latest_message, 21)
    service, _ = _service(
        conversation=conversation,
        state=state,
        messages=(older_message, latest_message),
        runs=(later_started_older, latest),
    )

    result = service.execute(InspectValidationHistoryRequest(conversation.id))

    assert isinstance(result, ValidationHistoryReadyResult)
    assert result.view.target.user_message_sequence == 7
    assert result.view.attempts.items == ()
    assert result.view.attempts.display_text == (
        "Validation has not started for this request."
    )


def test_clarification_is_ready_with_zero_attempts_and_corrections() -> None:
    conversation, state = _base()
    source = _message(conversation, 10, 1)
    run = _run(
        conversation,
        source,
        20,
        ProcessingRunStatus.NEEDS_CLARIFICATION,
    )
    clarification = ClarificationRequest(
        identifier(30),
        run.id,
        ClarificationReason.UNSUPPORTED_INTENT,
        "Please clarify.",
        FrozenJsonObject({"safe": True}),
        NOW,
    )
    service, _ = _service(
        conversation=conversation,
        state=state,
        messages=(source,),
        runs=(run,),
        clarifications=(clarification,),
    )

    result = service.execute(InspectValidationHistoryRequest(conversation.id))

    assert isinstance(result, ValidationHistoryReadyResult)
    assert result.view.target.outcome.value == "CLARIFICATION"
    assert result.view.correction_count == 0
    assert result.view.attempts.items == ()


def test_attempts_and_correction_project_safely_without_candidate_or_provider_data() -> None:
    conversation, state = _base()
    source = _message(conversation, 10, 3)
    run = replace(
        _run(conversation, source, 20),
        status=ProcessingRunStatus.REVISING,
    )
    packet_id = identifier(40)
    packet = SimpleNamespace(packet=SimpleNamespace(id=packet_id))
    first_request = ModelRequest(
        identifier(50),
        run.id,
        packet_id,
        ModelRequestPurpose.INITIAL,
        0,
        ProviderKind.OLLAMA,
        "UNSAFE_MODEL_SENTINEL",
        ModelRequestStatus.SUCCEEDED,
        "UNSAFE_PROMPT_SENTINEL",
        FrozenJsonObject({"unsafe": "UNSAFE_REQUEST_SENTINEL"}),
        NOW,
        NOW + timedelta(seconds=1),
        None,
        None,
    )
    response = ModelResponse(
        identifier(51),
        first_request.id,
        "UNSAFE_RESPONSE_SENTINEL",
        FrozenJsonObject({"provider": "UNSAFE_PROVIDER_SENTINEL"}),
        None,
        first_request.completed_at,
    )
    validation = SimpleNamespace(
        id=identifier(52),
        model_response_id=response.id,
        status=ValidationStatus.FAILED,
        score=UnitScore("0.4"),
        violations=(),
        evidence=(),
        created_at=response.created_at,
    )
    revised = ModelRequest(
        identifier(53),
        run.id,
        packet_id,
        ModelRequestPurpose.REVISION,
        1,
        ProviderKind.OLLAMA,
        "UNSAFE_MODEL_SENTINEL",
        ModelRequestStatus.FAILED,
        "UNSAFE_CORRECTION_PROMPT_SENTINEL",
        FrozenJsonObject({"unsafe": True}),
        NOW + timedelta(seconds=2),
        NOW + timedelta(seconds=3),
        "MODEL_TRANSPORT_FAILED",
        "The local model request failed safely.",
    )
    correction = SimpleNamespace(
        processing_run_id=run.id,
        attempt_number=1,
        prior_model_response_id=response.id,
        revised_model_request_id=revised.id,
        reasons=validation.violations,
    )
    service, _ = _service(
        conversation=conversation,
        state=state,
        messages=(source,),
        runs=(run,),
        packets=((run.id, packet),),
        requests=(first_request, revised),
        responses=(response,),
        validations=(validation,),
        corrections=(correction,),
    )

    result = service.execute(InspectValidationHistoryRequest(conversation.id))

    assert isinstance(result, ValidationHistoryReadyResult)
    assert tuple(item.outcome.code for item in result.view.attempts.items) == (
        "VALIDATED",
        "TRANSPORT_FAILURE",
    )
    assert result.view.attempts.items[1].correction_from_previous == 1
    assert result.view.corrections[0].display_text == (
        "Correction 1: attempt 1 to attempt 2."
    )
    rendered = repr(result)
    for sentinel in (
        "UNSAFE_MODEL_SENTINEL",
        "UNSAFE_PROMPT_SENTINEL",
        "UNSAFE_REQUEST_SENTINEL",
        "UNSAFE_RESPONSE_SENTINEL",
        "UNSAFE_PROVIDER_SENTINEL",
        "UNSAFE_CORRECTION_PROMPT_SENTINEL",
    ):
        assert sentinel not in rendered
