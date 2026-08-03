"""Configuration contract tests for TASK-0001."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from conftest import read_yaml, write_yaml
from context_for_ai.infrastructure.configuration import (
    ConfigurationError,
    load_configuration,
    resolve_application_root,
)


def test_complete_valid_configuration_loads(fixture_application_root: Path) -> None:
    configuration = load_configuration(application_root=fixture_application_root, environ={})

    assert configuration.app.environment == "development"
    assert configuration.model.name == "fixture-model"
    assert configuration.context.maximum_prompt_tokens == 2048
    assert configuration.context.rule_set_version == "mvp-context-rules-v2"
    assert {
        rule.category for rule in configuration.context.unsupported_request_rules
    } == {"IMAGE_GENERATION", "EXTERNAL_ACTION"}
    assert configuration.app.data_directory == fixture_application_root / "data"
    assert configuration.logging.directory == fixture_application_root / "data" / "logs"
    assert len(configuration.configuration_fingerprint) == 64


def test_default_and_explicit_configuration_directory_resolution(
    fixture_application_root: Path,
) -> None:
    default_configuration = load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    alternative_directory = fixture_application_root / "alternate-config"
    shutil.copytree(fixture_application_root / "config", alternative_directory)

    explicit_configuration = load_configuration(
        application_root=fixture_application_root,
        environ={
            "CONTEXT_FOR_AI_ENV": "development",
            "CONTEXT_FOR_AI_CONFIG_DIR": "alternate-config",
        },
    )

    assert default_configuration.configuration_directory == fixture_application_root / "config"
    assert explicit_configuration.configuration_directory == alternative_directory


def test_source_checkout_root_resolution(fixture_application_root: Path) -> None:
    entry_module = fixture_application_root / "src" / "context_for_ai" / "main.py"
    entry_module.parent.mkdir(parents=True)
    (fixture_application_root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")

    assert resolve_application_root(entry_module=entry_module) == fixture_application_root


def test_dotenv_bootstrap_values_fill_missing_process_environment(
    fixture_application_root: Path,
) -> None:
    alternate_directory = fixture_application_root / "test-config"
    shutil.copytree(fixture_application_root / "config", alternate_directory)
    app_path = alternate_directory / "app.yaml"
    app_document = read_yaml(app_path)
    app_document["app"]["environment"] = "test"
    write_yaml(app_path, app_document)
    (fixture_application_root / ".env").write_text(
        "CONTEXT_FOR_AI_ENV=test\nCONTEXT_FOR_AI_CONFIG_DIR=test-config\n",
        encoding="utf-8",
    )

    dotenv_configuration = load_configuration(
        application_root=fixture_application_root,
        environ={},
    )
    process_configuration = load_configuration(
        application_root=fixture_application_root,
        environ={
            "CONTEXT_FOR_AI_ENV": "development",
            "CONTEXT_FOR_AI_CONFIG_DIR": "config",
        },
    )

    assert dotenv_configuration.app.environment == "test"
    assert dotenv_configuration.configuration_directory == alternate_directory
    assert process_configuration.app.environment == "development"
    assert process_configuration.configuration_directory == fixture_application_root / "config"


def test_scalar_process_overrides_are_coerced_and_path_resolved(
    fixture_application_root: Path,
) -> None:
    configuration = load_configuration(
        application_root=fixture_application_root,
        environ={
            "CONTEXT_FOR_AI_ENV": "test",
            "CONTEXT_FOR_AI__APP__ENVIRONMENT": "test",
            "CONTEXT_FOR_AI__APP__DATA_DIRECTORY": "override-data",
            "CONTEXT_FOR_AI__MODEL__CONTEXT_WINDOW_TOKENS": "8192",
            "CONTEXT_FOR_AI__MODEL__TEMPERATURE": "0.25",
            "CONTEXT_FOR_AI__CONTEXT__MAXIMUM_PROMPT_TOKENS": "3000",
            "CONTEXT_FOR_AI__CONTEXT__MINIMUM_RELEVANCE_SCORE": "0.40",
            "CONTEXT_FOR_AI__VALIDATION__MAX_REVISIONS": "1",
            "CONTEXT_FOR_AI__LOGGING__DIRECTORY": "override-logs",
            "CONTEXT_FOR_AI__LOGGING__RETENTION_DAYS": "14",
        },
    )

    assert configuration.app.environment == "test"
    assert configuration.app.data_directory == fixture_application_root / "config" / "override-data"
    assert configuration.model.context_window_tokens == 8192
    assert configuration.model.temperature == 0.25
    assert configuration.context.maximum_prompt_tokens == 3000
    assert configuration.context.minimum_relevance_score == 0.4
    assert configuration.validation.max_revisions == 1
    assert configuration.logging.directory == fixture_application_root / "config" / "override-logs"
    assert configuration.logging.retention_days == 14


def test_same_intent_duplicate_phrase_at_one_priority_is_valid(
    fixture_application_root: Path,
) -> None:
    context_path = fixture_application_root / "config" / "context.yaml"
    context_document = read_yaml(context_path)
    context_document["context"]["intent_rules"].append(
        {
            "id": "answer-alias",
            "intent": "ANSWER",
            "phrases": ["answer"],
            "priority": 50,
        }
    )
    write_yaml(context_path, context_document)

    configuration = load_configuration(application_root=fixture_application_root, environ={})

    assert len(configuration.context.intent_rules) == 11


def test_cross_intent_duplicate_phrase_at_one_priority_is_rejected(
    fixture_application_root: Path,
) -> None:
    context_path = fixture_application_root / "config" / "context.yaml"
    context_document = read_yaml(context_path)
    context_document["context"]["intent_rules"][1]["phrases"] = ["answer"]
    write_yaml(context_path, context_document)

    with pytest.raises(ConfigurationError) as error:
        load_configuration(application_root=fixture_application_root, environ={})

    assert "context.yaml:context.intent_rules[1].phrases" in str(error.value)


def test_unsupported_request_rules_validate_category_and_phrase_ownership(
    fixture_application_root: Path,
) -> None:
    context_path = fixture_application_root / "config" / "context.yaml"
    context_document = read_yaml(context_path)
    rules = context_document["context"]["unsupported_request_rules"]
    rules[1]["phrases"].append("generate an image")
    write_yaml(context_path, context_document)

    with pytest.raises(ConfigurationError) as error:
        load_configuration(application_root=fixture_application_root, environ={})

    assert "context.yaml:context.unsupported_request_rules[1].phrases" in str(
        error.value
    )


def test_unsupported_request_rules_require_each_canonical_baseline(
    fixture_application_root: Path,
) -> None:
    context_path = fixture_application_root / "config" / "context.yaml"
    context_document = read_yaml(context_path)
    context_document["context"]["unsupported_request_rules"][0]["phrases"] = [
        "draw an image"
    ]
    write_yaml(context_path, context_document)

    with pytest.raises(ConfigurationError) as error:
        load_configuration(application_root=fixture_application_root, environ={})

    assert "baseline phrases for IMAGE_GENERATION" in str(error.value)


@pytest.mark.parametrize(
    ("file_name", "mutate", "expected_location"),
    [
        (
            "app.yaml",
            lambda document: document["app"].update({"unexpected": "ignored"}),
            "app.yaml:app.unexpected",
        ),
        (
            "models.yaml",
            lambda document: document["model"].update({"context_window_tokens": 12}),
            "models.yaml:model.context_window_tokens",
        ),
        (
            "context.yaml",
            lambda document: document["context"].update(
                {"qualifier_rules": document["context"]["qualifier_rules"][:-1]}
            ),
            "context.yaml:context.qualifier_rules",
        ),
        (
            "validation.yaml",
            lambda document: document["validation"].update(
                {"output_shape_rules": document["validation"]["output_shape_rules"][:-1]}
            ),
            "validation.yaml:validation.output_shape_rules",
        ),
    ],
)
def test_invalid_configuration_fixture_fails_with_typed_redacted_error(
    fixture_application_root: Path,
    file_name: str,
    mutate: object,
    expected_location: str,
) -> None:
    path = fixture_application_root / "config" / file_name
    document = read_yaml(path)
    mutate(document)  # type: ignore[operator]
    write_yaml(path, document)

    with pytest.raises(ConfigurationError) as error:
        load_configuration(application_root=fixture_application_root, environ={})

    assert expected_location in str(error.value)
    assert "fixture-model" not in str(error.value)


@pytest.mark.parametrize(
    "environment",
    [
        {"CONTEXT_FOR_AI__MEMORY__ALLOW_MANUAL_CREATE": "false"},
        {"CONTEXT_FOR_AI__MODEL__TEMPERATURE": "NaN"},
        {"CONTEXT_FOR_AI__MODEL__NAME": "[not-a-scalar]"},
    ],
)
def test_invalid_process_override_fails_before_startup(
    fixture_application_root: Path,
    environment: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_configuration(application_root=fixture_application_root, environ=environment)

    assert "environment:CONTEXT_FOR_AI__" in str(error.value)
