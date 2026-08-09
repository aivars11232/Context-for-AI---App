"""Contract tests for the composition-only assembly boundary."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import inspect
from typing import Protocol, get_type_hints

from context_for_ai.bootstrap import (
    ApplicationDependencies,
    ApplicationUseCases,
    CompositionRoot,
    DeterministicComponents,
    RepositoryPorts,
    SystemPorts,
)
from context_for_ai.domain.ports import (
    ClarificationRepository,
    ConstraintRepository,
    ContextPacketRepository,
    ConversationRepository,
    ConversationStateRepository,
    EntityRepository,
    EvaluationRepository,
    MemoryRepository,
    MessageRepository,
    ModelCallRepository,
    ProcessingRunRepository,
    ProjectRepository,
    ReferenceResolutionRepository,
    SettingsRepository,
    TaskRepository,
    TopicRepository,
    ValidationRepository,
)


REPOSITORY_TYPES = {
    ProjectRepository,
    ConversationRepository,
    TopicRepository,
    TaskRepository,
    ConversationStateRepository,
    MessageRepository,
    EntityRepository,
    ReferenceResolutionRepository,
    ConstraintRepository,
    MemoryRepository,
    ProcessingRunRepository,
    ContextPacketRepository,
    ModelCallRepository,
    ValidationRepository,
    ClarificationRepository,
    SettingsRepository,
    EvaluationRepository,
}


def test_composition_bundles_are_immutable_contract_records() -> None:
    for bundle in (
        RepositoryPorts,
        SystemPorts,
        DeterministicComponents,
        ApplicationDependencies,
        ApplicationUseCases,
    ):
        assert is_dataclass(bundle)
        assert bundle.__dataclass_params__.frozen is True
        assert "__slots__" in vars(bundle)


def test_repository_bundle_contains_every_repository_once() -> None:
    annotations = get_type_hints(RepositoryPorts)

    assert len(annotations) == len(REPOSITORY_TYPES)
    assert set(annotations.values()) == REPOSITORY_TYPES


def test_system_and_deterministic_bundles_cover_required_ports() -> None:
    assert {field.name for field in fields(SystemPorts)} == {
        "model_gateway",
        "clock",
        "id_generator",
        "configuration_loader",
        "trace_logger",
        "transactions",
    }
    assert {field.name for field in fields(DeterministicComponents)} == {
        "interpretation_engine",
        "reference_mention_extractor",
        "reference_resolver",
        "constraint_engine",
        "clarification_builder",
        "context_retriever",
        "context_packet_builder",
        "prompt_renderer",
        "response_validator",
        "correction_controller",
    }
    assert {field.name for field in fields(ApplicationDependencies)} == {
        "repositories",
        "system",
        "deterministic",
        "context_packet_stage",
    }


def test_composed_application_exposes_only_required_use_cases() -> None:
    assert {field.name for field in fields(ApplicationUseCases)} == {
        "process_user_message",
        "recover_processing_run",
        "inspect_context",
        "select_project",
        "apply_conversation_state_transition",
        "transition_task_status",
        "archive_project",
        "register_project",
        "register_topic",
        "register_task",
        "register_named_item",
        "create_memory",
        "get_memory",
        "list_memories",
        "edit_memory",
        "soft_delete_memory",
        "inspect_validation",
        "run_evaluation",
    }


def test_composition_root_constructs_internally_and_returns_inward_interfaces() -> None:
    assert issubclass(CompositionRoot, Protocol)
    signature = inspect.signature(CompositionRoot.compose)
    assert tuple(signature.parameters) == ("self",)
    assert get_type_hints(CompositionRoot.compose)["return"] is ApplicationUseCases
