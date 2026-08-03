"""Contract tests for presentation-facing application use cases."""

from __future__ import annotations

from dataclasses import is_dataclass
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
from context_for_ai.domain.enums import IntentType, OutputType, ProcessingRunStatus
from context_for_ai.domain.errors import BusyError, LifecycleInvariantError
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
