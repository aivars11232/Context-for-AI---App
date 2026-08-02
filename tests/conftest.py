"""Shared isolated configuration fixtures for TASK-0001 tests."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import pytest
import yaml


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "complete_configuration"


@pytest.fixture
def fixture_application_root(tmp_path: Path) -> Path:
    """Return a private application root containing the versioned YAML fixture."""

    application_root = tmp_path / "application-root"
    shutil.copytree(FIXTURE_ROOT, application_root)
    return application_root


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
