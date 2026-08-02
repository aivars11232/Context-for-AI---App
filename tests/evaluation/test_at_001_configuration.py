"""Acceptance-ID coverage for TASK-0001 / AT-001 configuration failure safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import read_yaml, write_yaml
from context_for_ai.infrastructure.configuration import ConfigurationError
from context_for_ai.main import bootstrap_application


def test_at_001_invalid_configuration_fails_with_a_typed_redacted_error(
    fixture_application_root: Path,
) -> None:
    logging_path = fixture_application_root / "config" / "logging.yaml"
    logging_document = read_yaml(logging_path)
    logging_document["logging"]["level"] = "SECRET_INVALID_LEVEL"
    write_yaml(logging_path, logging_document)

    with pytest.raises(ConfigurationError) as error:
        bootstrap_application(application_root=fixture_application_root, environ={})

    assert "logging.yaml:logging.level" in str(error.value)
    assert "SECRET_INVALID_LEVEL" not in str(error.value)
