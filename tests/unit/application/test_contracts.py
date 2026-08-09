"""Contract tests for presentation-facing application use cases."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
import inspect
from typing import Protocol, get_type_hints

import pytest

from context_for_ai.application import (
    ApplyConversationStateTransition,
    ApplyConversationStateTransitionInput,
    ApplyConversationStateTransitionOutput,
    ArchiveProject,
    ArchiveProjectInput,
    ArchiveProjectOutput,
    BusyErrorValue,
    BusyResult,
    CancellationCheckpoint,
    CancelledResult,
    ClarificationResult,
    ConcurrencyConflictErrorValue,
    ConcurrencyConflictResult,
    ConfigurationErrorValue,
    ConfigurationFailureResult,
    ControlledFailureError,
    ControlledFailureResult,
    CreateMemory,
    CreateMemoryInput,
    ContextPacketStage,
    EditMemory,
    EditMemoryInput,
    ForegroundApplicationScope,
    GetMemory,
    GetMemoryInput,
    IdempotencyKeyFactory,
    InspectValidation,
    InspectValidationInput,
    InspectValidationOutput,
    ListMemories,
    ListMemoriesInput,
    MemoryListOutput,
    MemoryOutput,
    ExistingRunResult,
    NoRecoveryRequiredResult,
    PersistenceErrorValue,
    PersistenceFailureResult,
    PrepareApplicationShell,
    PrepareApplicationShellRequest,
    PrepareApplicationShellResult,
    ProcessUserMessage,
    ProcessUserMessageRequest,
    ProcessUserMessageResult,
    PreparedOutputTransition,
    PreparedTaskTransition,
    PreparedTopicTransition,
    RunEvaluation,
    RunEvaluationInput,
    RunEvaluationOutput,
    RecoverProcessingRun,
    RecoverProcessingRunRequest,
    RecoveryCompletedResult,
    RecoveryRequiredResult,
    RecoveryResult,
    SelectProject,
    SelectProjectInput,
    SelectProjectOutput,
    ShellApplicationScopeFactory,
    ShellPreparationFailureKind,
    ShellPreparationFailureResult,
    ShellReadyResult,
    SoftDeleteMemory,
    SoftDeleteMemoryInput,
    TransitionTaskStatus,
    TransitionTaskStatusInput,
    TransitionTaskStatusOutput,
    SucceededResult,
    StartupApplicationScope,
    ValidationExhaustedErrorValue,
    ValidationExhaustedResult,
)
from context_for_ai.application.contracts import (
    RegisterNamedItem,
    RegisterNamedItemInput,
    RegisterNamedItemOutput,
    RegisterProject,
    RegisterProjectInput,
    RegisterProjectOutput,
    RegisterTask,
    RegisterTaskInput,
    RegisterTaskOutput,
    RegisterTopic,
    RegisterTopicInput,
    RegisterTopicOutput,
)
from context_for_ai.domain.entities import (
    ConversationState,
    Memory,
    MemoryRevision,
    MemorySource,
)
from context_for_ai.domain.enums import (
    FailureCode,
    IntentType,
    LocalActor,
    MemoryEffectiveStatus,
    MemoryRevisionOperation,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    OutputType,
    PipelineStage,
    ProcessingRunStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.lifecycle import SafeFailure
from context_for_ai.domain.policies import memory_revision_metadata
from context_for_ai.domain.ports.records import MemoryRecord
from context_for_ai.domain.ports.context import (
    ContextPacketBuildRequest,
    ContextPacketBuildResult,
)
from context_for_ai.domain.ports.model_gateway import CancellationToken
from context_for_ai.domain.value_objects import DomainId, UnitScore


USE_CASE_SIGNATURES = {
    SelectProject: (SelectProjectInput, SelectProjectOutput),
    ApplyConversationStateTransition: (
        ApplyConversationStateTransitionInput,
        ApplyConversationStateTransitionOutput,
    ),
    TransitionTaskStatus: (TransitionTaskStatusInput, TransitionTaskStatusOutput),
    ArchiveProject: (ArchiveProjectInput, ArchiveProjectOutput),
    RegisterProject: (RegisterProjectInput, RegisterProjectOutput),
    RegisterTopic: (RegisterTopicInput, RegisterTopicOutput),
    RegisterTask: (RegisterTaskInput, RegisterTaskOutput),
    RegisterNamedItem: (RegisterNamedItemInput, RegisterNamedItemOutput),
    CreateMemory: (CreateMemoryInput, MemoryOutput),
    GetMemory: (GetMemoryInput, MemoryOutput),
    ListMemories: (ListMemoriesInput, MemoryListOutput),
    EditMemory: (EditMemoryInput, MemoryOutput),
    SoftDeleteMemory: (SoftDeleteMemoryInput, MemoryOutput),
    InspectValidation: (InspectValidationInput, InspectValidationOutput),
    RunEvaluation: (RunEvaluationInput, RunEvaluationOutput),
}


PROCESS_RESULT_TYPES = {
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
}


PREPARATION_RESULT_TYPES = {
    ShellReadyResult,
    RecoveryRequiredResult,
    ShellPreparationFailureResult,
}


PROCESS_RESULT_FIELD_NAMES = {
    SucceededResult: {
        "result_kind",
        "processing_run_id",
        "user_message_id",
        "processing_status",
        "current_state",
        "context_packet_id",
        "latest_validation_result",
        "assistant_message_id",
        "assistant_text",
    },
    ExistingRunResult: {
        "result_kind",
        "processing_run_id",
        "user_message_id",
        "processing_status",
        "current_state",
        "context_packet_id",
        "latest_validation_result",
        "assistant_message_id",
        "assistant_text",
        "clarification",
        "safe_failure",
    },
    BusyResult: {
        "result_kind",
        "active_processing_run_id",
        "active_processing_status",
        "error",
    },
    ClarificationResult: {
        "result_kind",
        "processing_run_id",
        "user_message_id",
        "processing_status",
        "current_state",
        "context_packet_id",
        "latest_validation_result",
        "clarification",
    },
    CancelledResult: {
        "result_kind",
        "processing_run_id",
        "user_message_id",
        "processing_status",
        "current_state",
        "context_packet_id",
        "latest_validation_result",
        "cancellation_code",
        "checkpoint",
        "safe_failure",
        "failure_persisted",
    },
    ValidationExhaustedResult: {
        "result_kind",
        "processing_run_id",
        "user_message_id",
        "processing_status",
        "current_state",
        "context_packet_id",
        "latest_validation_result",
        "error",
        "safe_failure",
    },
    ConfigurationFailureResult: {"result_kind", "error"},
    PersistenceFailureResult: {
        "result_kind",
        "processing_run_id",
        "user_message_id",
        "processing_status",
        "current_state",
        "context_packet_id",
        "latest_validation_result",
        "error",
        "safe_failure",
        "failure_persisted",
    },
    ConcurrencyConflictResult: {
        "result_kind",
        "processing_run_id",
        "user_message_id",
        "processing_status",
        "current_state",
        "context_packet_id",
        "latest_validation_result",
        "error",
        "safe_failure",
    },
    ControlledFailureResult: {
        "result_kind",
        "processing_run_id",
        "user_message_id",
        "processing_status",
        "current_state",
        "context_packet_id",
        "latest_validation_result",
        "error",
        "safe_failure",
    },
}


def _id(value: int) -> DomainId:
    return DomainId(f"00000000-0000-0000-0000-{value:012d}")


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


def _state() -> ConversationState:
    return ConversationState(_id(100), None, None, None, None, (), 0, NOW)


def _failure(
    run_id: DomainId,
    code: FailureCode,
    *,
    stage: PipelineStage = PipelineStage.TERMINALIZATION,
    safe_message: str = "Safe failure.",
) -> SafeFailure:
    return SafeFailure(_id(900), run_id, stage, code, safe_message, {}, True, NOW)


def _memory_record(
    number: int,
    *,
    expires_at: datetime | None = None,
) -> MemoryRecord:
    created_at = NOW - timedelta(days=1)
    memory = Memory(
        _id(number),
        _id(100),
        None,
        MemoryType.PROJECT_FACT,
        MemoryScope.CONVERSATION,
        MemoryStatus.ACTIVE,
        f"Memory {number}",
        ("memory",),
        (),
        UnitScore("0.5"),
        UnitScore("1"),
        expires_at,
        created_at,
        created_at,
        None,
    )
    source = MemorySource(
        _id(number + 1000),
        memory.id,
        MemorySourceKind.MANUAL_ENTRY,
        None,
        "Created manually",
        created_at,
    )
    revision = MemoryRevision(
        _id(number + 2000),
        memory.id,
        1,
        MemoryRevisionOperation.CREATE,
        memory.content,
        memory_revision_metadata(memory, source.id),
        LocalActor.LOCAL_USER,
        created_at,
    )
    return MemoryRecord(memory, (source,), (revision,))


def test_every_required_use_case_has_one_typed_execute_contract() -> None:
    for use_case, (request_type, output_type) in USE_CASE_SIGNATURES.items():
        assert issubclass(use_case, Protocol)
        assert use_case._is_protocol is True
        public_methods = [
            name
            for name, method in inspect.getmembers(use_case, inspect.isfunction)
            if not name.startswith("_")
        ]
        assert public_methods == ["execute"]
        assert get_type_hints(use_case.execute) == {
            "request": request_type,
            "return": output_type,
        }


def test_processing_use_cases_require_one_caller_owned_cancellation_token() -> None:
    assert get_type_hints(ProcessUserMessage.execute) == {
        "request": ProcessUserMessageRequest,
        "cancellation_token": CancellationToken,
        "return": ProcessUserMessageResult,
    }
    assert get_type_hints(RecoverProcessingRun.execute) == {
        "request": RecoverProcessingRunRequest,
        "cancellation_token": CancellationToken,
        "return": RecoveryResult,
    }


def test_shell_preparation_has_one_closed_typed_execute_contract() -> None:
    assert issubclass(PrepareApplicationShell, Protocol)
    assert PrepareApplicationShell._is_protocol is True
    assert get_type_hints(PrepareApplicationShell.execute) == {
        "request": PrepareApplicationShellRequest,
        "return": PrepareApplicationShellResult,
    }
    assert set(PrepareApplicationShellResult.__value__.__args__) == (
        PREPARATION_RESULT_TYPES
    )


def test_context_packet_stage_uses_the_domain_build_contract_directly() -> None:
    assert issubclass(ContextPacketStage, Protocol)
    assert ContextPacketStage._is_protocol is True
    assert get_type_hints(ContextPacketStage.execute) == {
        "request": ContextPacketBuildRequest,
        "return": ContextPacketBuildResult,
    }


def test_use_case_inputs_and_outputs_are_frozen_slotted_dataclasses() -> None:
    dto_types = {
        dto
        for request_and_output in USE_CASE_SIGNATURES.values()
        for dto in request_and_output
    }
    dto_types.update(
        {
            PreparedTopicTransition,
            PreparedTaskTransition,
            PreparedOutputTransition,
            ProcessUserMessageRequest,
            RecoverProcessingRunRequest,
            NoRecoveryRequiredResult,
            RecoveryCompletedResult,
            PrepareApplicationShellRequest,
            *PREPARATION_RESULT_TYPES,
            BusyErrorValue,
            ConfigurationErrorValue,
            PersistenceErrorValue,
            ConcurrencyConflictErrorValue,
            ControlledFailureError,
            ValidationExhaustedErrorValue,
            *PROCESS_RESULT_TYPES,
        }
    )
    for dto_type in dto_types:
        assert is_dataclass(dto_type)
        assert dto_type.__dataclass_params__.frozen is True
        assert "__slots__" in vars(dto_type)


def test_shell_preparation_result_algebra_has_exact_closed_fields_and_messages() -> None:
    assert {item.name for item in fields(ShellReadyResult)} == {
        "result_kind",
        "conversation_id",
        "initial_conversation_created",
    }
    assert {item.name for item in fields(RecoveryRequiredResult)} == {
        "result_kind",
        "processing_run_id",
        "conversation_id",
    }
    assert {item.name for item in fields(ShellPreparationFailureResult)} == {
        "result_kind",
        "failure_kind",
        "code",
        "safe_message",
    }

    recovery_failure = ShellPreparationFailureResult(
        ShellPreparationFailureKind.RECOVERY_PREFLIGHT_FAILED
    )
    setup_failure = ShellPreparationFailureResult(
        ShellPreparationFailureKind.CONVERSATION_SETUP_FAILED
    )

    assert recovery_failure.result_kind == "SHELL_PREPARATION_FAILURE"
    assert recovery_failure.code is FailureCode.PERSISTENCE_ERROR
    assert recovery_failure.safe_message == (
        "Previous processing state could not be inspected safely."
    )
    assert setup_failure.safe_message == "A conversation could not be opened safely."
    with pytest.raises(LifecycleInvariantError, match="closed failure kind"):
        ShellPreparationFailureResult("RECOVERY_PREFLIGHT_FAILED")  # type: ignore[arg-type]


def test_shell_scope_and_idempotency_factory_protocols_are_exact() -> None:
    assert get_type_hints(StartupApplicationScope) == {
        "prepare_application_shell": PrepareApplicationShell,
    }
    assert get_type_hints(ForegroundApplicationScope) == {
        "process_user_message": ProcessUserMessage,
        "recover_processing_run": RecoverProcessingRun,
    }
    assert get_type_hints(ShellApplicationScopeFactory.open_startup_scope) == {
        "return": StartupApplicationScope,
    }
    assert get_type_hints(ShellApplicationScopeFactory.open_foreground_scope) == {
        "return": ForegroundApplicationScope,
    }
    assert get_type_hints(IdempotencyKeyFactory.new_key) == {"return": DomainId}


def test_public_process_result_algebra_has_exact_closed_variant_fields() -> None:
    assert set(ProcessUserMessageResult.__value__.__args__) == PROCESS_RESULT_TYPES
    for result_type, expected_names in PROCESS_RESULT_FIELD_NAMES.items():
        assert {item.name for item in fields(result_type)} == expected_names


def test_process_request_preserves_exact_text_without_normalization() -> None:
    text = "  leading é\ntrailing  "
    request = ProcessUserMessageRequest(_id(1), text, _id(2), None)

    assert request.user_text.encode("utf-8") == text.encode("utf-8")


def test_busy_result_contains_only_matching_global_active_run_data() -> None:
    output = BusyResult(
        active_processing_run_id=_id(1),
        active_processing_status=ProcessingRunStatus.GENERATING,
        error=BusyErrorValue(_id(1)),
    )

    assert output.result_kind == "BUSY"
    assert output.error.code == "BUSY"
    assert output.error.safe_message == "Another request is already being processed."
    with pytest.raises(LifecycleInvariantError, match="same active run"):
        BusyResult(
            _id(1),
            ProcessingRunStatus.GENERATING,
            BusyErrorValue(_id(2)),
        )


def test_busy_result_rejects_a_terminal_active_run() -> None:
    with pytest.raises(LifecycleInvariantError, match="non-terminal"):
        BusyResult(
            _id(1),
            ProcessingRunStatus.SUCCEEDED,
            BusyErrorValue(_id(1)),
        )


def test_preacceptance_cancelled_result_is_the_only_null_run_shape() -> None:
    result = CancelledResult(
        None,
        None,
        None,
        None,
        None,
        None,
        FailureCode.CANCELLED_BY_USER,
        CancellationCheckpoint.BEFORE_ACCEPTANCE,
        None,
        False,
    )

    assert result.result_kind == "CANCELLED"
    with pytest.raises(LifecycleInvariantError, match="cannot contain durable"):
        CancelledResult(
            _id(1),
            None,
            None,
            None,
            None,
            None,
            FailureCode.CANCELLED_BY_USER,
            CancellationCheckpoint.BEFORE_ACCEPTANCE,
            None,
            False,
        )


def test_accepted_cancelled_result_requires_matching_terminal_failure() -> None:
    run_id = _id(1)
    failure = _failure(
        run_id,
        FailureCode.CANCELLED_BY_USER,
        stage=PipelineStage.CONTEXT,
        safe_message="The request was cancelled.",
    )
    result = CancelledResult(
        run_id,
        _id(2),
        ProcessingRunStatus.CANCELLED,
        _state(),
        None,
        None,
        FailureCode.CANCELLED_BY_USER,
        CancellationCheckpoint.AFTER_ACCEPTANCE,
        failure,
        True,
    )

    assert result.failure_persisted is True
    with pytest.raises(LifecycleInvariantError, match="match and belong"):
        CancelledResult(
            run_id,
            _id(2),
            ProcessingRunStatus.CANCELLED,
            _state(),
            None,
            None,
            FailureCode.CANCELLED_BY_USER,
            CancellationCheckpoint.AFTER_ACCEPTANCE,
            _failure(run_id, FailureCode.MODEL_CANCELLED),
            True,
        )


def test_configuration_and_persistence_results_enforce_closed_shapes() -> None:
    result = ConfigurationFailureResult(
        ConfigurationErrorValue("models.yaml", "model.name")
    )
    assert result.error.safe_message == "The application configuration is invalid."
    with pytest.raises(LifecycleInvariantError, match="non-empty"):
        ConfigurationErrorValue("models.yaml", "")

    preacceptance = PersistenceFailureResult(
        None,
        None,
        None,
        None,
        None,
        None,
        PersistenceErrorValue(PipelineStage.ACCEPTANCE),
        None,
        False,
    )
    assert preacceptance.failure_persisted is False
    with pytest.raises(LifecycleInvariantError, match="cannot contain run data"):
        PersistenceFailureResult(
            None,
            _id(2),
            None,
            None,
            None,
            None,
            PersistenceErrorValue(PipelineStage.ACCEPTANCE),
            None,
            False,
        )


def test_controlled_failure_requires_matching_closed_failure_projection() -> None:
    run_id = _id(1)
    failure = _failure(
        run_id,
        FailureCode.PROCESS_RESTARTED,
        stage=PipelineStage.RECOVERY,
        safe_message="The interrupted model request cannot be safely repeated.",
    )
    result = ControlledFailureResult(
        run_id,
        _id(2),
        ProcessingRunStatus.FAILED,
        _state(),
        _id(3),
        None,
        ControlledFailureError(
            FailureCode.PROCESS_RESTARTED,
            "The interrupted model request cannot be safely repeated.",
        ),
        failure,
    )

    assert result.error.code is FailureCode.PROCESS_RESTARTED
    with pytest.raises(LifecycleInvariantError, match="closed result family"):
        ControlledFailureError(
            FailureCode.VALIDATION_EXHAUSTED,
            "The response did not pass validation.",
        )


def test_recovery_contract_is_empty_and_rejects_preacceptance_cancellation() -> None:
    assert fields(RecoverProcessingRunRequest) == ()
    assert NoRecoveryRequiredResult().result_kind == "NO_RECOVERY_REQUIRED"
    preacceptance = CancelledResult(
        None,
        None,
        None,
        None,
        None,
        None,
        FailureCode.CANCELLED_BY_USER,
        CancellationCheckpoint.BEFORE_ACCEPTANCE,
        None,
        False,
    )
    with pytest.raises(LifecycleInvariantError, match="identify the recovered run"):
        RecoveryCompletedResult(_id(1), preacceptance)


def test_prepared_control_transition_rejects_topic_or_task_proposals() -> None:
    with pytest.raises(LifecycleInvariantError, match="cannot carry"):
        ApplyConversationStateTransitionInput(
            conversation_id=_id(1),
            expected_state_version=0,
            task=PreparedTaskTransition(_id(2), UnitScore("0.8")),
            output=PreparedOutputTransition(
                IntentType.CONTINUE,
                OutputType.TEXT_ANSWER,
                UnitScore("0.8"),
            ),
        )


def test_named_item_registration_modes_are_exactly_declaration_or_explicit_ui() -> None:
    declaration = RegisterNamedItemInput(_id(1), _id(2), None, None)
    unscoped_ui = RegisterNamedItemInput(_id(1), None, " Architecture ", None)
    project_ui = RegisterNamedItemInput(_id(1), None, "Architecture", _id(3))

    assert declaration.declaration_message_id == _id(2)
    assert unscoped_ui.selected_project_id is None
    assert project_ui.selected_project_id == _id(3)
    with pytest.raises(LifecycleInvariantError, match="requires an explicit label"):
        RegisterNamedItemInput(_id(1), None, None, None)
    with pytest.raises(LifecycleInvariantError, match="cannot include UI"):
        RegisterNamedItemInput(_id(1), _id(2), "Architecture", None)
    with pytest.raises(LifecycleInvariantError, match="cannot include UI"):
        RegisterNamedItemInput(_id(1), _id(2), None, _id(3))


def test_memory_output_carries_one_valid_effective_status_evaluation() -> None:
    record = _memory_record(10, expires_at=NOW)

    output = MemoryOutput(record, NOW, MemoryEffectiveStatus.EXPIRED)

    assert output.record is record
    assert output.evaluated_at == NOW
    assert output.effective_status is MemoryEffectiveStatus.EXPIRED
    with pytest.raises(LifecycleInvariantError, match="evaluated memory state"):
        MemoryOutput(record, NOW, MemoryEffectiveStatus.ACTIVE)


def test_memory_list_output_freezes_records_with_one_shared_evaluation_time() -> None:
    active = MemoryOutput(
        _memory_record(20),
        NOW,
        MemoryEffectiveStatus.ACTIVE,
    )
    expired = MemoryOutput(
        _memory_record(21, expires_at=NOW),
        NOW,
        MemoryEffectiveStatus.EXPIRED,
    )

    output = MemoryListOutput([active, expired], NOW)  # type: ignore[arg-type]

    assert output.records == (active, expired)
    assert output.evaluated_at == NOW
    later = MemoryOutput(
        _memory_record(22),
        NOW + timedelta(seconds=1),
        MemoryEffectiveStatus.ACTIVE,
    )
    with pytest.raises(LifecycleInvariantError, match="share its evaluated_at"):
        MemoryListOutput((active, later), NOW)
