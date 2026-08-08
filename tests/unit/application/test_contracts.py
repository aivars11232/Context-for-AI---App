"""Contract tests for presentation-facing application use cases."""

from __future__ import annotations

from dataclasses import is_dataclass
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
    CreateMemory,
    CreateMemoryInput,
    EditMemory,
    EditMemoryInput,
    GetMemory,
    GetMemoryInput,
    InspectContext,
    InspectContextInput,
    InspectContextOutput,
    InspectValidation,
    InspectValidationInput,
    InspectValidationOutput,
    ListMemories,
    ListMemoriesInput,
    MemoryListOutput,
    MemoryOutput,
    ProcessResultKind,
    ProcessUserMessage,
    ProcessUserMessageInput,
    ProcessUserMessageOutput,
    PreparedOutputTransition,
    PreparedTaskTransition,
    PreparedTopicTransition,
    RunEvaluation,
    RunEvaluationInput,
    RunEvaluationOutput,
    SelectProject,
    SelectProjectInput,
    SelectProjectOutput,
    SoftDeleteMemory,
    SoftDeleteMemoryInput,
    TransitionTaskStatus,
    TransitionTaskStatusInput,
    TransitionTaskStatusOutput,
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
from context_for_ai.domain.entities import Memory, MemoryRevision, MemorySource
from context_for_ai.domain.enums import (
    IntentType,
    LocalActor,
    MemoryEffectiveStatus,
    MemoryRevisionOperation,
    MemoryScope,
    MemorySourceKind,
    MemoryStatus,
    MemoryType,
    OutputType,
    ProcessingRunStatus,
)
from context_for_ai.domain.errors import BusyError, LifecycleInvariantError
from context_for_ai.domain.policies import memory_revision_metadata
from context_for_ai.domain.ports.records import MemoryRecord
from context_for_ai.domain.value_objects import DomainId, UnitScore


USE_CASE_SIGNATURES = {
    ProcessUserMessage: (ProcessUserMessageInput, ProcessUserMessageOutput),
    InspectContext: (InspectContextInput, InspectContextOutput),
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


def _id(value: int) -> DomainId:
    return DomainId(f"00000000-0000-0000-0000-{value:012d}")


NOW = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)


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


def test_use_case_inputs_and_outputs_are_frozen_slotted_dataclasses() -> None:
    dto_types = {
        dto
        for request_and_output in USE_CASE_SIGNATURES.values()
        for dto in request_and_output
    }
    dto_types.update(
        {PreparedTopicTransition, PreparedTaskTransition, PreparedOutputTransition}
    )
    for dto_type in dto_types:
        assert is_dataclass(dto_type)
        assert dto_type.__dataclass_params__.frozen is True
        assert "__slots__" in vars(dto_type)


def test_busy_output_has_no_newly_accepted_run_data() -> None:
    output = ProcessUserMessageOutput(
        result_kind=ProcessResultKind.BUSY,
        active_processing_run_id=_id(1),
        active_processing_status=ProcessingRunStatus.GENERATING,
        busy_error=BusyError("A foreground run is active."),
    )

    assert output.processing_run_id is None
    assert output.user_message_id is None


def test_busy_output_rejects_a_terminal_active_run() -> None:
    with pytest.raises(LifecycleInvariantError, match="non-terminal"):
        ProcessUserMessageOutput(
            result_kind=ProcessResultKind.BUSY,
            active_processing_run_id=_id(1),
            active_processing_status=ProcessingRunStatus.SUCCEEDED,
            busy_error=BusyError("A foreground run is active."),
        )


def test_process_result_kind_is_exactly_the_documented_three_branches() -> None:
    assert {kind.value for kind in ProcessResultKind} == {
        "FINAL",
        "EXISTING_RUN",
        "BUSY",
    }


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
