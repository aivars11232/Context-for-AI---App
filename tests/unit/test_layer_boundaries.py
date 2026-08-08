"""Static dependency checks for production layers and the test-only model mock."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src" / "context_for_ai"
TESTS_ROOT = REPOSITORY_ROOT / "tests"
MOCK_PROVIDER_MODULE = "tests.fixtures.model_gateway"
MOCK_PROVIDER_PATH = TESTS_ROOT / "fixtures" / "model_gateway.py"
MOCK_COMPOSITION_PATH = TESTS_ROOT / "conftest.py"
MODEL_GATEWAY_MODULE = "context_for_ai.domain.ports.model_gateway"
MODEL_GATEWAY_SYMBOLS = frozenset(
    {
        "CancellationToken",
        "CompletedGeneration",
        "GenerationFailure",
        "GenerationOutcome",
        "GenerationRequest",
        "GenerationSettings",
        "InvalidProviderResponseFailure",
        "ModelCancelledFailure",
        "ModelGateway",
        "ModelNotFoundFailure",
        "ProviderUnavailableFailure",
        "TokenUsage",
        "ModelTimeoutFailure",
    }
)
FORBIDDEN_OUTWARD_ROOTS = frozenset(
    {
        "PyQt6",
        "PySide6",
        "aiohttp",
        "apsw",
        "http",
        "httpx",
        "ollama",
        "pysqlite3",
        "requests",
        "sqlite3",
        "urllib",
        "urllib3",
        "yaml",
    }
)
ALLOWED_PROJECT_PREFIXES = {
    "domain": ("context_for_ai.domain",),
    "application": (
        "context_for_ai.application",
        "context_for_ai.context_engine",
        "context_for_ai.domain",
    ),
    "context_engine": (
        "context_for_ai.context_engine",
        "context_for_ai.domain",
    ),
}
FORBIDDEN_QML_DEPENDENCY_TOKENS = frozenset(
    {
        "context_for_ai.context_engine",
        "context_for_ai.domain",
        "context_for_ai.infrastructure",
        "generationrequest",
        "modelgateway",
        "ollama",
        "tests.fixtures",
    }
)


@dataclass(frozen=True, slots=True)
class ImportReference:
    """An imported module and, for ``from`` imports, its imported symbol."""

    module: str
    symbol: str | None = None

    @property
    def qualified_name(self) -> str:
        if self.symbol is None:
            return self.module
        if not self.module:
            return self.symbol
        return f"{self.module}.{self.symbol}"


def _matches_prefix(value: str, prefix: str) -> bool:
    return value == prefix or value.startswith(f"{prefix}.")


def _resolve_relative_module(
    *, package_name: str, module: str | None, level: int
) -> str:
    if level == 0:
        return module or ""

    package_parts = package_name.split(".") if package_name else []
    parents_to_remove = level - 1
    if parents_to_remove >= len(package_parts):
        return f"{'.' * level}{module or ''}"

    base_parts = package_parts[: len(package_parts) - parents_to_remove]
    if module is not None:
        base_parts.extend(module.split("."))
    return ".".join(base_parts)


def import_references_from_source(
    source: str, *, package_name: str, filename: str = "<memory>"
) -> tuple[ImportReference, ...]:
    tree = ast.parse(source, filename=filename)
    references: list[ImportReference] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            references.extend(ImportReference(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_relative_module(
                package_name=package_name,
                module=node.module,
                level=node.level,
            )
            references.extend(
                ImportReference(module=module, symbol=alias.name)
                for alias in node.names
            )
    return tuple(references)


def _package_name_for_path(path: Path, *, root: Path, root_package: str) -> str:
    relative_parts = list(path.relative_to(root).with_suffix("").parts)
    if relative_parts[-1] == "__init__":
        relative_parts.pop()
    else:
        relative_parts.pop()
    return ".".join((root_package, *relative_parts))


def imported_references(
    path: Path, *, root: Path = SOURCE_ROOT, root_package: str = "context_for_ai"
) -> tuple[ImportReference, ...]:
    return import_references_from_source(
        path.read_text(encoding="utf-8"),
        package_name=_package_name_for_path(
            path,
            root=root,
            root_package=root_package,
        ),
        filename=str(path),
    )


def _is_model_gateway_reference(reference: ImportReference) -> bool:
    if _matches_prefix(reference.module, MODEL_GATEWAY_MODULE):
        return True
    if reference.symbol in MODEL_GATEWAY_SYMBOLS:
        return True
    if reference.module == "context_for_ai.domain.ports":
        return reference.symbol in {None, "*", "model_gateway"}
    return False


def _mock_provider_calls(path: Path) -> tuple[int, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "MockModelProvider":
            lines.append(node.lineno)
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "MockModelProvider"
        ):
            lines.append(node.lineno)
    return tuple(lines)


def test_import_reference_parser_resolves_absolute_and_relative_imports() -> None:
    references = import_references_from_source(
        "\n".join(
            (
                "import context_for_ai.infrastructure.ollama",
                "from ..domain.ports import ModelGateway",
                "from . import local_module",
            )
        ),
        package_name="context_for_ai.application",
    )

    assert tuple(reference.qualified_name for reference in references) == (
        "context_for_ai.infrastructure.ollama",
        "context_for_ai.domain.ports.ModelGateway",
        "context_for_ai.application.local_module",
    )


def test_model_timeout_failure_direct_imports_are_gateway_references() -> None:
    absolute_reference = import_references_from_source(
        "from context_for_ai.domain.ports import ModelTimeoutFailure",
        package_name="context_for_ai.context_engine",
    )[0]
    relative_reference = import_references_from_source(
        "from ..domain.ports import ModelTimeoutFailure",
        package_name="context_for_ai.context_engine",
    )[0]

    assert absolute_reference.qualified_name == (
        "context_for_ai.domain.ports.ModelTimeoutFailure"
    )
    assert relative_reference.qualified_name == (
        "context_for_ai.domain.ports.ModelTimeoutFailure"
    )
    assert _is_model_gateway_reference(absolute_reference)
    assert _is_model_gateway_reference(relative_reference)


def test_inward_layers_import_only_approved_project_layers_and_standard_library() -> None:
    violations: list[str] = []
    for layer, allowed_prefixes in ALLOWED_PROJECT_PREFIXES.items():
        layer_root = SOURCE_ROOT / layer
        if not layer_root.exists():
            continue
        for path in sorted(layer_root.rglob("*.py")):
            for reference in imported_references(path):
                imported_name = reference.qualified_name
                root = reference.module.partition(".")[0]
                if root in FORBIDDEN_OUTWARD_ROOTS:
                    violations.append(
                        f"{path.relative_to(SOURCE_ROOT)} imports {imported_name}"
                    )
                elif imported_name.startswith("context_for_ai") and not any(
                    _matches_prefix(imported_name, prefix)
                    for prefix in allowed_prefixes
                ):
                    violations.append(
                        f"{path.relative_to(SOURCE_ROOT)} imports {imported_name}"
                    )
                elif imported_name.startswith("tests."):
                    violations.append(
                        f"{path.relative_to(SOURCE_ROOT)} imports {imported_name}"
                    )

    assert violations == []


def test_domain_and_application_do_not_import_concrete_model_providers() -> None:
    violations: list[str] = []
    for layer in ("domain", "application"):
        for path in sorted((SOURCE_ROOT / layer).rglob("*.py")):
            for reference in imported_references(path):
                imported_name = reference.qualified_name.casefold()
                if "ollama" in imported_name or "mock_model" in imported_name:
                    violations.append(
                        f"{path.relative_to(SOURCE_ROOT)} imports "
                        f"{reference.qualified_name}"
                    )

    assert violations == []


def test_context_engine_has_no_model_gateway_dependency() -> None:
    violations: list[str] = []
    for path in sorted((SOURCE_ROOT / "context_engine").rglob("*.py")):
        for reference in imported_references(path):
            if _is_model_gateway_reference(reference):
                violations.append(
                    f"{path.relative_to(SOURCE_ROOT)} imports "
                    f"{reference.qualified_name}"
                )

    assert violations == []


def test_ui_project_imports_reach_only_the_application_layer() -> None:
    violations: list[str] = []
    for path in sorted((SOURCE_ROOT / "ui").rglob("*.py")):
        for reference in imported_references(path):
            imported_name = reference.qualified_name
            if imported_name.startswith("context_for_ai") and not _matches_prefix(
                imported_name, "context_for_ai.application"
            ):
                violations.append(
                    f"{path.relative_to(SOURCE_ROOT)} imports {imported_name}"
                )

    assert violations == []


def test_qml_has_no_inward_or_provider_dependency_tokens() -> None:
    violations: list[str] = []
    for path in sorted((SOURCE_ROOT / "ui").rglob("*.qml")):
        source = path.read_text(encoding="utf-8").casefold()
        for token in sorted(FORBIDDEN_QML_DEPENDENCY_TOKENS):
            if token.casefold() in source:
                violations.append(f"{path.relative_to(SOURCE_ROOT)} contains {token}")

    assert violations == []


def test_mock_provider_is_imported_and_constructed_only_by_test_composition() -> None:
    violations: list[str] = []
    composition_imports_provider = False
    composition_constructs_provider = False
    python_paths = tuple(sorted(SOURCE_ROOT.rglob("*.py"))) + tuple(
        sorted(TESTS_ROOT.rglob("*.py"))
    )

    for path in python_paths:
        if path.is_relative_to(SOURCE_ROOT):
            references = imported_references(path)
        else:
            references = imported_references(
                path,
                root=TESTS_ROOT,
                root_package="tests",
            )
        imports_provider = any(
            _matches_prefix(reference.qualified_name, MOCK_PROVIDER_MODULE)
            for reference in references
        )
        provider_calls = _mock_provider_calls(path)
        if path == MOCK_COMPOSITION_PATH:
            composition_imports_provider = imports_provider
            composition_constructs_provider = bool(provider_calls)
            continue
        if imports_provider:
            violations.append(f"{path.relative_to(REPOSITORY_ROOT)} imports mock provider")
        violations.extend(
            f"{path.relative_to(REPOSITORY_ROOT)}:{line} constructs MockModelProvider"
            for line in provider_calls
        )

    assert composition_imports_provider
    assert composition_constructs_provider
    assert violations == []


def test_mock_provider_fixture_imports_only_standard_library_and_domain_ports() -> None:
    violations: list[str] = []
    standard_library = frozenset(sys.stdlib_module_names) | {"__future__"}
    for reference in imported_references(
        MOCK_PROVIDER_PATH,
        root=TESTS_ROOT,
        root_package="tests",
    ):
        imported_name = reference.qualified_name
        root = reference.module.partition(".")[0]
        if root in FORBIDDEN_OUTWARD_ROOTS:
            violations.append(f"mock provider imports outward dependency {imported_name}")
        elif root == "context_for_ai" and not _matches_prefix(
            imported_name, "context_for_ai.domain.ports"
        ):
            violations.append(f"mock provider imports non-port project code {imported_name}")
        elif root != "context_for_ai" and root not in standard_library:
            violations.append(f"mock provider imports third-party code {imported_name}")

    assert violations == []


def test_concrete_infrastructure_is_imported_only_at_composition_boundaries() -> None:
    violations: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative_path = path.relative_to(SOURCE_ROOT)
        is_allowed_location = (
            relative_path == Path("main.py")
            or relative_path.parts[0] in {"bootstrap", "infrastructure"}
        )
        if is_allowed_location:
            continue
        for reference in imported_references(path):
            if _matches_prefix(
                reference.qualified_name, "context_for_ai.infrastructure"
            ):
                violations.append(
                    f"{relative_path} imports {reference.qualified_name}"
                )

    assert violations == []
