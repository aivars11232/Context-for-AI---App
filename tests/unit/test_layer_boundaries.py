"""Static import checks for inward dependency direction and adapter composition."""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE_ROOT = Path(__file__).parents[2] / "src" / "context_for_ai"
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


def imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return tuple(modules)


def test_inward_layers_import_only_approved_project_layers_and_standard_library() -> None:
    violations: list[str] = []
    for layer, allowed_prefixes in ALLOWED_PROJECT_PREFIXES.items():
        layer_root = SOURCE_ROOT / layer
        if not layer_root.exists():
            continue
        for path in sorted(layer_root.rglob("*.py")):
            for module in imported_modules(path):
                root = module.partition(".")[0]
                if root in FORBIDDEN_OUTWARD_ROOTS:
                    violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
                elif module.startswith("context_for_ai.") and not module.startswith(
                    allowed_prefixes
                ):
                    violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")

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
        for module in imported_modules(path):
            if module == "context_for_ai.infrastructure" or module.startswith(
                "context_for_ai.infrastructure."
            ):
                violations.append(f"{relative_path} imports {module}")

    assert violations == []
