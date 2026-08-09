"""Package foundation and central test-selection tests."""

from decimal import Decimal
from pathlib import Path
import shlex
import tomllib

import pytest

from tests.fixtures.ollama_live import (
    OllamaLiveOptIn,
    classify_ollama_live_opt_in,
    load_live_ollama_case,
)


REPOSITORY_ROOT = Path(__file__).parents[2]


def test_package_imports() -> None:
    import context_for_ai
    import context_for_ai.domain as domain
    import context_for_ai.domain.ports as ports

    assert context_for_ai.__doc__ == "Context for AI local desktop application package."
    for name in (
        "MatchLocation",
        "ValidationEvidence",
        "ValidationOutcome",
        "ValidationSeverity",
        "ValidationWarningCode",
        "calculate_validation_score",
    ):
        assert hasattr(domain, name)
    for name in (
        "CorrectionExhausted",
        "CorrectionPlanRequest",
        "FailedCandidateLineage",
    ):
        assert hasattr(ports, name)
    assert not hasattr(ports, "RevisionEnvelope")


def test_default_pytest_selection_centrally_excludes_live_ollama() -> None:
    configuration = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    addopts = shlex.split(configuration["tool"]["pytest"]["ini_options"]["addopts"])

    assert "-m" in addopts
    assert addopts[addopts.index("-m") + 1] == "not ollama"


def test_qml_package_data_covers_root_and_arbitrary_nested_assets() -> None:
    configuration = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    patterns = configuration["tool"]["setuptools"]["package-data"][
        "context_for_ai"
    ]
    qml_root = REPOSITORY_ROOT / "src" / "context_for_ai" / "ui" / "qml"

    assert patterns == ["ui/qml/*.qml", "ui/qml/**/*.qml"]
    assert {
        path.relative_to(qml_root).as_posix()
        for path in qml_root.rglob("*.qml")
    } == {
        "Main.qml",
        "components/ChatPanel.qml",
    }


@pytest.mark.parametrize(
    ("environment", "expected"),
    (
        ({}, OllamaLiveOptIn.ABSENT),
        ({"CONTEXT_FOR_AI_RUN_OLLAMA": ""}, OllamaLiveOptIn.INVALID),
        ({"CONTEXT_FOR_AI_RUN_OLLAMA": "true"}, OllamaLiveOptIn.INVALID),
        ({"CONTEXT_FOR_AI_RUN_OLLAMA": "01"}, OllamaLiveOptIn.INVALID),
        ({"CONTEXT_FOR_AI_RUN_OLLAMA": " 1"}, OllamaLiveOptIn.INVALID),
        ({"CONTEXT_FOR_AI_RUN_OLLAMA": "1"}, OllamaLiveOptIn.ENABLED),
    ),
)
def test_live_ollama_opt_in_is_exact(
    environment: dict[str, str],
    expected: OllamaLiveOptIn,
) -> None:
    assert classify_ollama_live_opt_in(environment) is expected


def test_live_fixture_loads_six_file_configuration_with_only_allowed_overrides(
    fixture_application_root: Path,
) -> None:
    live_case = load_live_ollama_case(
        fixture_application_root,
        {
            "CONTEXT_FOR_AI_RUN_OLLAMA": "1",
            "CONTEXT_FOR_AI__MODEL__BASE_URL": "http://[::1]:22434/",
            "CONTEXT_FOR_AI__MODEL__NAME": "Live/Model:Q4",
            "CONTEXT_FOR_AI__MODEL__TEMPERATURE": "2",
            "OLLAMA_HOST": "http://remote.example:443",
            "HTTP_PROXY": "http://proxy.example:8080",
            "OLLAMA_API_KEY": "must-be-ignored",
        },
    )

    assert live_case.base_url == "http://[::1]:22434"
    assert live_case.model_name == "Live/Model:Q4"
    assert live_case.request.model_name == "Live/Model:Q4"
    assert live_case.request.settings.temperature == Decimal("0.0")


def test_live_module_is_marked_and_has_no_later_pipeline_imports() -> None:
    source = (
        REPOSITORY_ROOT / "tests" / "integration" / "test_ollama_adapter_live.py"
    ).read_text(encoding="utf-8")

    assert "pytestmark = pytest.mark.ollama" in source
    for prohibited in (
        "context_for_ai.application",
        "context_for_ai.context_engine",
        "context_for_ai.infrastructure.database",
        "context_for_ai.ui",
        "persistence",
        "correction",
        "ResponseValidator",
    ):
        assert prohibited not in source
