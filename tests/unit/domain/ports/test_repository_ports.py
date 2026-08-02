"""Contract tests for the canonical inward repository protocols."""

from __future__ import annotations

import ast
from collections import Counter
import inspect
from pathlib import Path
from typing import Protocol, get_type_hints

from context_for_ai.domain.lifecycle import ClarificationRequest
from context_for_ai.domain.ports import (
    ClarificationRepository,
    ContextPacketRecord,
    ContextPacketRepository,
)
from context_for_ai.domain.ports import repositories
from context_for_ai.domain.value_objects import DomainId


PORT_ROOT = Path(__file__).parents[4] / "src" / "context_for_ai" / "domain" / "ports"
REQUIRED_REPOSITORIES = frozenset(
    {
        "ProjectRepository",
        "ConversationRepository",
        "TopicRepository",
        "TaskRepository",
        "ConversationStateRepository",
        "MessageRepository",
        "EntityRepository",
        "ReferenceResolutionRepository",
        "ConstraintRepository",
        "MemoryRepository",
        "ProcessingRunRepository",
        "ContextPacketRepository",
        "ModelCallRepository",
        "ValidationRepository",
        "ClarificationRepository",
        "SettingsRepository",
        "EvaluationRepository",
    }
)


def test_every_required_repository_is_defined_once_in_port_layer() -> None:
    definitions: Counter[str] = Counter()
    for path in sorted(PORT_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        definitions.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name.endswith("Repository")
        )

    assert definitions == Counter({name: 1 for name in REQUIRED_REPOSITORIES})


def test_repository_contracts_are_protocols_with_typed_methods() -> None:
    for name in REQUIRED_REPOSITORIES:
        repository = getattr(repositories, name)
        assert issubclass(repository, Protocol)
        assert repository._is_protocol is True
        for method_name, method in inspect.getmembers(
            repository, predicate=inspect.isfunction
        ):
            if method_name.startswith("_"):
                continue
            signature = inspect.signature(method)
            assert signature.return_annotation is not inspect.Signature.empty
            assert all(
                parameter.annotation is not inspect.Parameter.empty
                for parameter_name, parameter in signature.parameters.items()
                if parameter_name != "self"
            )


def test_clarification_repository_exposes_one_per_run_contract() -> None:
    add_hints = get_type_hints(ClarificationRepository.add)
    get_hints = get_type_hints(ClarificationRepository.get_for_run)

    assert add_hints == {"clarification": ClarificationRequest, "return": type(None)}
    assert get_hints == {
        "processing_run_id": DomainId,
        "return": ClarificationRequest | None,
    }


def test_context_packet_repository_uses_complete_retrieval_record() -> None:
    add_hints = get_type_hints(ContextPacketRepository.add)
    get_hints = get_type_hints(ContextPacketRepository.get)
    get_for_run_hints = get_type_hints(ContextPacketRepository.get_for_run)

    assert add_hints == {"record": ContextPacketRecord, "return": type(None)}
    assert get_hints == {
        "context_packet_id": DomainId,
        "return": ContextPacketRecord | None,
    }
    assert get_for_run_hints == {
        "processing_run_id": DomainId,
        "return": ContextPacketRecord | None,
    }
