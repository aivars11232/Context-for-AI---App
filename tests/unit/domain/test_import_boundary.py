"""Static dependency-boundary test for the domain package."""

from __future__ import annotations

import ast
from pathlib import Path


DOMAIN_ROOT = Path(__file__).parents[3] / "src" / "context_for_ai" / "domain"
FORBIDDEN_EXTERNAL_ROOTS = frozenset(
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


def imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return tuple(modules)


def test_domain_has_no_forbidden_imports() -> None:
    violations: list[str] = []
    for path in sorted(DOMAIN_ROOT.rglob("*.py")):
        for module in imported_modules(path):
            root = module.partition(".")[0]
            imports_outer_project_layer = module.startswith("context_for_ai.") and not (
                module == "context_for_ai.domain"
                or module.startswith("context_for_ai.domain.")
            )
            if root in FORBIDDEN_EXTERNAL_ROOTS or imports_outer_project_layer:
                violations.append(f"{path.relative_to(DOMAIN_ROOT)} imports {module}")

    assert violations == []
