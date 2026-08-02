"""Deterministic loading and validation for the local YAML configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any
import unicodedata
from urllib.parse import urlparse

import yaml

from .errors import ConfigurationError


_CONFIG_FILES: tuple[tuple[str, str], ...] = (
    ("app.yaml", "app"),
    ("models.yaml", "model"),
    ("context.yaml", "context"),
    ("memory.yaml", "memory"),
    ("validation.yaml", "validation"),
    ("logging.yaml", "logging"),
)
_CONFIG_FILE_NAMES = frozenset(file_name for file_name, _ in _CONFIG_FILES)
_BOOTSTRAP_KEYS = frozenset({"CONTEXT_FOR_AI_ENV", "CONTEXT_FOR_AI_CONFIG_DIR"})
_BOOTSTRAP_ENVS = frozenset({"development", "test", "production"})

_SUPPORTED_INTENTS = (
    "ANSWER",
    "EXPLAIN",
    "DESCRIBE",
    "PLAN",
    "ANALYZE",
    "RESEARCH",
    "DEBUG",
    "EDIT_TEXT",
    "CONTINUE",
    "CORRECT",
)
_QUALIFIER_KINDS = frozenset(
    {
        "ONLY",
        "EXACTLY",
        "APPROXIMATE",
        "PROHIBITION",
        "PRESERVATION",
        "SUBSTITUTION",
        "PRIOR_REFERENCE",
        "SEQUENTIAL",
    }
)
_MODEL_OUTPUT_TYPES = frozenset(
    {
        "TEXT_ANSWER",
        "TEXT_EXPLANATION",
        "TEXT_DESCRIPTION",
        "TEXT_PLAN",
        "TEXT_ANALYSIS",
        "TEXT_CODE",
        "TEXT_COMPARISON",
    }
)
_OUTPUT_TYPE_OVERRIDES: dict[str, frozenset[str]] = {
    "ANSWER": frozenset({"TEXT_ANSWER", "TEXT_COMPARISON"}),
    "EDIT_TEXT": frozenset({"TEXT_ANSWER", "TEXT_CODE"}),
    "EXPLAIN": frozenset({"TEXT_EXPLANATION"}),
    "DESCRIBE": frozenset({"TEXT_DESCRIPTION"}),
    "PLAN": frozenset({"TEXT_PLAN"}),
    "ANALYZE": frozenset({"TEXT_ANALYSIS"}),
    "RESEARCH": frozenset({"TEXT_ANALYSIS"}),
    "DEBUG": frozenset({"TEXT_ANALYSIS"}),
    "CONTINUE": frozenset(),
    "CORRECT": frozenset(),
}
_OUTPUT_SHAPES = frozenset(
    {"NON_EMPTY_TEXT", "NUMBERED_LIST", "FENCED_CODE", "COMPARISON_LIST"}
)
_QUALIFIER_BASELINES: dict[str, frozenset[str]] = {
    "ONLY": frozenset({"only"}),
    "EXACTLY": frozenset({"exactly"}),
    "APPROXIMATE": frozenset({"roughly", "could", "might"}),
    "PROHIBITION": frozenset({"do not"}),
    "PRESERVATION": frozenset({"without changing"}),
    "SUBSTITUTION": frozenset({"instead of"}),
    "PRIOR_REFERENCE": frozenset({"same as before"}),
    "SEQUENTIAL": frozenset({"one at a time"}),
}
_PRESERVE_VERB_BASELINE = frozenset(
    {"add", "remove", "replace", "change", "modify", "delete", "move"}
)
_ACTION_MARKER_BASELINE = frozenset(
    {"TOOL_CALL:", "ACTION_EXECUTED:", "IMAGE_RESULT:"}
)


@dataclass(frozen=True, slots=True)
class AppSettings:
    environment: str
    data_directory: Path
    foreground_run_limit: int


@dataclass(frozen=True, slots=True)
class ModelSettings:
    provider: str
    base_url: str
    name: str
    context_window_tokens: int
    request_timeout_seconds: int
    temperature: float


@dataclass(frozen=True, slots=True)
class IntentRule:
    id: str
    intent: str
    output_type: str | None
    phrases: tuple[str, ...]
    priority: int


@dataclass(frozen=True, slots=True)
class QualifierRule:
    id: str
    qualifier: str
    phrases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextSettings:
    tokenizer_estimator: str
    maximum_prompt_tokens: int
    reserved_response_tokens: int
    recent_message_limit: int
    retrieved_memory_limit: int
    minimum_relevance_score: float
    topic_stack_limit: int
    rule_set_version: str
    conditional_grammar_version: str
    intent_rules: tuple[IntentRule, ...]
    qualifier_rules: tuple[QualifierRule, ...]


@dataclass(frozen=True, slots=True)
class MemorySettings:
    allow_manual_create: bool
    allow_manual_edit: bool
    allow_manual_soft_delete: bool
    automatic_mutation: bool


@dataclass(frozen=True, slots=True)
class OutputShapeRule:
    id: str
    output_type: str
    shape: str


@dataclass(frozen=True, slots=True)
class ValidationSettings:
    max_revisions: int
    rule_set_version: str
    output_shape_rules: tuple[OutputShapeRule, ...]
    preserve_change_verb_list_id: str
    preserve_change_verbs: tuple[str, ...]
    action_markers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str
    directory: Path
    retention_days: int
    include_content: bool


@dataclass(frozen=True, slots=True)
class ApplicationConfiguration:
    """The fully validated, path-resolved configuration used by the process."""

    app: AppSettings
    model: ModelSettings
    context: ContextSettings
    memory: MemorySettings
    validation: ValidationSettings
    logging: LoggingSettings
    configuration_directory: Path
    configuration_fingerprint: str

    @property
    def fingerprint(self) -> str:
        """Backward-friendly concise name for the configuration fingerprint."""

        return self.configuration_fingerprint


@dataclass(frozen=True, slots=True)
class _OverrideSpec:
    section: str
    field: str
    scalar_type: str


_OVERRIDE_SPECS: dict[tuple[str, str], _OverrideSpec] = {
    ("APP", "ENVIRONMENT"): _OverrideSpec("app", "environment", "enum"),
    ("APP", "DATA_DIRECTORY"): _OverrideSpec("app", "data_directory", "path"),
    ("MODEL", "NAME"): _OverrideSpec("model", "name", "string"),
    ("MODEL", "BASE_URL"): _OverrideSpec("model", "base_url", "string"),
    ("MODEL", "CONTEXT_WINDOW_TOKENS"): _OverrideSpec(
        "model", "context_window_tokens", "integer"
    ),
    ("MODEL", "REQUEST_TIMEOUT_SECONDS"): _OverrideSpec(
        "model", "request_timeout_seconds", "integer"
    ),
    ("MODEL", "TEMPERATURE"): _OverrideSpec("model", "temperature", "decimal"),
    ("CONTEXT", "MAXIMUM_PROMPT_TOKENS"): _OverrideSpec(
        "context", "maximum_prompt_tokens", "integer"
    ),
    ("CONTEXT", "RESERVED_RESPONSE_TOKENS"): _OverrideSpec(
        "context", "reserved_response_tokens", "integer"
    ),
    ("CONTEXT", "RECENT_MESSAGE_LIMIT"): _OverrideSpec(
        "context", "recent_message_limit", "integer"
    ),
    ("CONTEXT", "RETRIEVED_MEMORY_LIMIT"): _OverrideSpec(
        "context", "retrieved_memory_limit", "integer"
    ),
    ("CONTEXT", "MINIMUM_RELEVANCE_SCORE"): _OverrideSpec(
        "context", "minimum_relevance_score", "decimal"
    ),
    ("VALIDATION", "MAX_REVISIONS"): _OverrideSpec(
        "validation", "max_revisions", "integer"
    ),
    ("LOGGING", "LEVEL"): _OverrideSpec("logging", "level", "enum"),
    ("LOGGING", "DIRECTORY"): _OverrideSpec("logging", "directory", "path"),
    ("LOGGING", "RETENTION_DAYS"): _OverrideSpec(
        "logging", "retention_days", "integer"
    ),
}


class _DuplicateYamlKeyError(Exception):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise _DuplicateYamlKeyError from error
        if duplicate:
            raise _DuplicateYamlKeyError
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def resolve_application_root(
    entry_module: Path | None = None, executable: Path | None = None
) -> Path:
    """Resolve the source-checkout root independently of the process directory."""

    anchor = (entry_module or Path(__file__)).resolve()
    start = anchor if anchor.is_dir() else anchor.parent
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return (executable or Path(sys.executable)).resolve().parent


def load_configuration(
    *,
    application_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ApplicationConfiguration:
    """Load the single allowed YAML configuration set with documented precedence."""

    root = (
        Path(application_root).resolve()
        if application_root is not None
        else resolve_application_root()
    )
    environment = dict(os.environ if environ is None else environ)
    bootstrap_values = _read_bootstrap_environment(root)
    config_directory = _resolve_configuration_directory(
        root,
        _environment_or_bootstrap(
            environment, bootstrap_values, "CONTEXT_FOR_AI_CONFIG_DIR"
        ),
    )
    raw_sections = _load_yaml_sections(config_directory)
    _apply_process_overrides(raw_sections, environment)
    configuration = _validate_configuration(raw_sections, config_directory)

    expected_environment = _environment_or_bootstrap(
        environment, bootstrap_values, "CONTEXT_FOR_AI_ENV"
    )
    expected_environment = expected_environment or "development"
    if expected_environment not in _BOOTSTRAP_ENVS:
        raise ConfigurationError(
            "bootstrap",
            "CONTEXT_FOR_AI_ENV",
            "development, test, or production",
        )
    if configuration.app.environment != expected_environment:
        raise ConfigurationError(
            "app.yaml",
            "app.environment",
            "a value that matches CONTEXT_FOR_AI_ENV",
        )
    return configuration


def _read_bootstrap_environment(application_root: Path) -> dict[str, str]:
    dotenv_path = application_root / ".env"
    if not dotenv_path.exists():
        return {}
    if not dotenv_path.is_file():
        raise ConfigurationError(".env", "", "a UTF-8 KEY=VALUE file")
    try:
        lines = dotenv_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ConfigurationError(".env", "", "a readable UTF-8 KEY=VALUE file") from error

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = raw_line.partition("=")
        if not separator or not key or key != key.strip():
            raise ConfigurationError(".env", f"line {line_number}", "KEY=VALUE syntax")
        if key not in _BOOTSTRAP_KEYS:
            raise ConfigurationError(
                ".env",
                key,
                "CONTEXT_FOR_AI_ENV or CONTEXT_FOR_AI_CONFIG_DIR",
            )
        if key in values:
            raise ConfigurationError(".env", key, "one unique bootstrap entry")
        values[key] = value.strip()
    return values


def _environment_or_bootstrap(
    environment: Mapping[str, str], bootstrap_values: Mapping[str, str], key: str
) -> str | None:
    value = environment.get(key)
    if value is not None:
        return value.strip() if isinstance(value, str) else None
    return bootstrap_values.get(key)


def _resolve_configuration_directory(application_root: Path, configured: str | None) -> Path:
    raw_path = configured if configured is not None else "config"
    directory = _resolve_local_path(
        raw_path,
        application_root,
        "bootstrap",
        "CONTEXT_FOR_AI_CONFIG_DIR",
    )
    if not directory.is_dir():
        raise ConfigurationError(
            "bootstrap",
            "CONTEXT_FOR_AI_CONFIG_DIR",
            "an existing local configuration directory",
        )
    yaml_files = {
        child.name
        for child in directory.iterdir()
        if child.is_file() and child.suffix in {".yaml", ".yml"}
    }
    if yaml_files != _CONFIG_FILE_NAMES:
        raise ConfigurationError(
            "bootstrap",
            "CONTEXT_FOR_AI_CONFIG_DIR",
            "a directory containing exactly the six required YAML files",
        )
    return directory


def _resolve_local_path(
    value: Any, base_directory: Path, file_name: str, key: str
) -> Path:
    if not isinstance(value, str):
        raise ConfigurationError(file_name, key, "a non-empty local path")
    stripped = value.strip()
    if (
        not stripped
        or "\x00" in stripped
        or "://" in stripped
        or stripped.lower().startswith("file:")
        or stripped.startswith("~")
    ):
        raise ConfigurationError(file_name, key, "a non-empty local path")
    path = Path(stripped)
    if not path.is_absolute():
        path = base_directory / path
    try:
        return path.resolve(strict=False)
    except OSError as error:
        raise ConfigurationError(file_name, key, "a resolvable local path") from error


def _load_yaml_sections(configuration_directory: Path) -> dict[str, dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    for file_name, root_key in _CONFIG_FILES:
        path = configuration_directory / file_name
        try:
            document = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
        except (OSError, UnicodeError, yaml.YAMLError, _DuplicateYamlKeyError) as error:
            raise ConfigurationError(file_name, "", "valid UTF-8 YAML with unique keys") from error
        if not isinstance(document, dict) or set(document) != {root_key}:
            raise ConfigurationError(file_name, root_key, f"exactly one {root_key} root section")
        section = document[root_key]
        if not isinstance(section, dict):
            raise ConfigurationError(file_name, root_key, "a mapping")
        sections[root_key] = section
    return sections


def _apply_process_overrides(
    raw_sections: dict[str, dict[str, Any]], environment: Mapping[str, str]
) -> None:
    for env_key in sorted(environment):
        if not env_key.startswith("CONTEXT_FOR_AI__"):
            continue
        parts = env_key.split("__")
        if (
            len(parts) != 3
            or parts[0] != "CONTEXT_FOR_AI"
            or not parts[1]
            or not parts[2]
            or parts[1] != parts[1].upper()
            or parts[2] != parts[2].upper()
        ):
            raise ConfigurationError(
                "environment",
                env_key,
                "CONTEXT_FOR_AI__SECTION__KEY with uppercase components",
            )
        specification = _OVERRIDE_SPECS.get((parts[1], parts[2]))
        if specification is None:
            raise ConfigurationError("environment", env_key, "a supported scalar override")
        raw_value = environment[env_key]
        raw_sections[specification.section][specification.field] = _coerce_override(
            raw_value, specification.scalar_type, env_key
        )


def _coerce_override(value: Any, scalar_type: str, env_key: str) -> Any:
    if not isinstance(value, str):
        raise ConfigurationError("environment", env_key, "a non-empty scalar value")
    raw = value.strip()
    if not raw or raw.lower() in {"null", "~", "nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        raise ConfigurationError("environment", env_key, "a non-empty finite scalar value")
    if (raw.startswith("[") and raw.endswith("]")) or (
        raw.startswith("{") and raw.endswith("}")
    ):
        raise ConfigurationError("environment", env_key, "a scalar value, not a collection")
    if scalar_type == "integer":
        if not re.fullmatch(r"[+-]?[0-9]+", raw):
            raise ConfigurationError("environment", env_key, "a base-10 integer")
        return int(raw, 10)
    if scalar_type == "decimal":
        if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|[0-9]+)", raw):
            raise ConfigurationError("environment", env_key, "a finite base-10 decimal")
        try:
            decimal = Decimal(raw)
        except InvalidOperation as error:
            raise ConfigurationError("environment", env_key, "a finite base-10 decimal") from error
        if not decimal.is_finite():
            raise ConfigurationError("environment", env_key, "a finite base-10 decimal")
        return float(decimal)
    if raw in {"true", "false", "True", "False", "TRUE", "FALSE"}:
        raise ConfigurationError("environment", env_key, "the target scalar type")
    return raw


def _validate_configuration(
    sections: Mapping[str, Mapping[str, Any]], configuration_directory: Path
) -> ApplicationConfiguration:
    app_values = _section_values(
        "app.yaml",
        "app",
        sections["app"],
        allowed=("environment", "data_directory", "foreground_run_limit"),
        required=("data_directory", "foreground_run_limit"),
        defaults={"environment": "development"},
    )
    app_environment = _enum(
        app_values["environment"], "app.yaml", "app.environment", _BOOTSTRAP_ENVS
    )
    app_data_directory = _resolve_local_path(
        app_values["data_directory"], configuration_directory, "app.yaml", "app.data_directory"
    )
    foreground_run_limit = _integer(
        app_values["foreground_run_limit"],
        "app.yaml",
        "app.foreground_run_limit",
        minimum=1,
        maximum=1,
    )
    app = AppSettings(app_environment, app_data_directory, foreground_run_limit)

    model_values = _section_values(
        "models.yaml",
        "model",
        sections["model"],
        allowed=(
            "provider",
            "base_url",
            "name",
            "context_window_tokens",
            "request_timeout_seconds",
            "temperature",
        ),
        required=("provider", "base_url", "name", "context_window_tokens"),
        defaults={"request_timeout_seconds": 60, "temperature": 0.0},
    )
    provider = _enum(model_values["provider"], "models.yaml", "model.provider", {"ollama"})
    base_url = _loopback_http_url(
        model_values["base_url"], "models.yaml", "model.base_url"
    )
    name = _non_empty_string(model_values["name"], "models.yaml", "model.name")
    context_window_tokens = _integer(
        model_values["context_window_tokens"],
        "models.yaml",
        "model.context_window_tokens",
        minimum=1024,
    )
    request_timeout_seconds = _integer(
        model_values["request_timeout_seconds"],
        "models.yaml",
        "model.request_timeout_seconds",
        minimum=1,
        maximum=300,
    )
    temperature = _number(
        model_values["temperature"], "models.yaml", "model.temperature", minimum=0.0, maximum=2.0
    )
    model = ModelSettings(
        provider,
        base_url,
        name,
        context_window_tokens,
        request_timeout_seconds,
        temperature,
    )

    context_values = _section_values(
        "context.yaml",
        "context",
        sections["context"],
        allowed=(
            "tokenizer_estimator",
            "maximum_prompt_tokens",
            "reserved_response_tokens",
            "recent_message_limit",
            "retrieved_memory_limit",
            "minimum_relevance_score",
            "topic_stack_limit",
            "rule_set_version",
            "conditional_grammar_version",
            "intent_rules",
            "qualifier_rules",
        ),
        required=(
            "tokenizer_estimator",
            "maximum_prompt_tokens",
            "topic_stack_limit",
            "rule_set_version",
            "conditional_grammar_version",
            "intent_rules",
            "qualifier_rules",
        ),
        defaults={
            "reserved_response_tokens": 512,
            "recent_message_limit": 20,
            "retrieved_memory_limit": 12,
            "minimum_relevance_score": 0.35,
        },
    )
    tokenizer_estimator = _enum(
        context_values["tokenizer_estimator"],
        "context.yaml",
        "context.tokenizer_estimator",
        {"conservative_utf8_v1"},
    )
    maximum_prompt_tokens = _integer(
        context_values["maximum_prompt_tokens"],
        "context.yaml",
        "context.maximum_prompt_tokens",
        minimum=256,
    )
    reserved_response_tokens = _integer(
        context_values["reserved_response_tokens"],
        "context.yaml",
        "context.reserved_response_tokens",
        minimum=128,
    )
    if maximum_prompt_tokens + reserved_response_tokens > model.context_window_tokens:
        raise ConfigurationError(
            "context.yaml",
            "context.maximum_prompt_tokens",
            "maximum_prompt_tokens + reserved_response_tokens not exceeding model.context_window_tokens",
        )
    recent_message_limit = _integer(
        context_values["recent_message_limit"],
        "context.yaml",
        "context.recent_message_limit",
        minimum=1,
        maximum=100,
    )
    retrieved_memory_limit = _integer(
        context_values["retrieved_memory_limit"],
        "context.yaml",
        "context.retrieved_memory_limit",
        minimum=0,
        maximum=50,
    )
    minimum_relevance_score = _number(
        context_values["minimum_relevance_score"],
        "context.yaml",
        "context.minimum_relevance_score",
        minimum=0.0,
        maximum=1.0,
    )
    topic_stack_limit = _integer(
        context_values["topic_stack_limit"],
        "context.yaml",
        "context.topic_stack_limit",
        minimum=10,
        maximum=10,
    )
    rule_set_version = _non_empty_string(
        context_values["rule_set_version"], "context.yaml", "context.rule_set_version"
    )
    conditional_grammar_version = _enum(
        context_values["conditional_grammar_version"],
        "context.yaml",
        "context.conditional_grammar_version",
        {"mvp-condition-v1"},
    )
    intent_rules = _intent_rules(context_values["intent_rules"])
    qualifier_rules = _qualifier_rules(context_values["qualifier_rules"])
    context = ContextSettings(
        tokenizer_estimator,
        maximum_prompt_tokens,
        reserved_response_tokens,
        recent_message_limit,
        retrieved_memory_limit,
        minimum_relevance_score,
        topic_stack_limit,
        rule_set_version,
        conditional_grammar_version,
        intent_rules,
        qualifier_rules,
    )

    memory_values = _section_values(
        "memory.yaml",
        "memory",
        sections["memory"],
        allowed=(
            "allow_manual_create",
            "allow_manual_edit",
            "allow_manual_soft_delete",
            "automatic_mutation",
        ),
        required=(
            "allow_manual_create",
            "allow_manual_edit",
            "allow_manual_soft_delete",
            "automatic_mutation",
        ),
        defaults={},
    )
    allow_manual_create = _boolean(
        memory_values["allow_manual_create"], "memory.yaml", "memory.allow_manual_create"
    )
    allow_manual_edit = _boolean(
        memory_values["allow_manual_edit"], "memory.yaml", "memory.allow_manual_edit"
    )
    allow_manual_soft_delete = _boolean(
        memory_values["allow_manual_soft_delete"],
        "memory.yaml",
        "memory.allow_manual_soft_delete",
    )
    automatic_mutation = _boolean(
        memory_values["automatic_mutation"], "memory.yaml", "memory.automatic_mutation"
    )
    if not (allow_manual_create and allow_manual_edit and allow_manual_soft_delete and not automatic_mutation):
        raise ConfigurationError(
            "memory.yaml",
            "memory",
            "the fixed manual-only MVP memory flags",
        )
    memory = MemorySettings(
        allow_manual_create,
        allow_manual_edit,
        allow_manual_soft_delete,
        automatic_mutation,
    )

    validation_values = _section_values(
        "validation.yaml",
        "validation",
        sections["validation"],
        allowed=(
            "max_revisions",
            "rule_set_version",
            "output_shape_rules",
            "preserve_change_verb_list_id",
            "preserve_change_verbs",
            "action_markers",
        ),
        required=(
            "rule_set_version",
            "output_shape_rules",
            "preserve_change_verb_list_id",
            "preserve_change_verbs",
            "action_markers",
        ),
        defaults={"max_revisions": 2},
    )
    max_revisions = _integer(
        validation_values["max_revisions"],
        "validation.yaml",
        "validation.max_revisions",
        minimum=0,
        maximum=2,
    )
    validation_rule_set_version = _non_empty_string(
        validation_values["rule_set_version"], "validation.yaml", "validation.rule_set_version"
    )
    output_shape_rules = _output_shape_rules(validation_values["output_shape_rules"])
    preserve_change_verb_list_id = _identifier(
        validation_values["preserve_change_verb_list_id"],
        "validation.yaml",
        "validation.preserve_change_verb_list_id",
    )
    preserve_change_verbs = _preserve_verbs(validation_values["preserve_change_verbs"])
    action_markers = _action_markers(validation_values["action_markers"])
    validation = ValidationSettings(
        max_revisions,
        validation_rule_set_version,
        output_shape_rules,
        preserve_change_verb_list_id,
        preserve_change_verbs,
        action_markers,
    )

    logging_values = _section_values(
        "logging.yaml",
        "logging",
        sections["logging"],
        allowed=("level", "directory", "retention_days", "include_content"),
        required=("directory", "include_content"),
        defaults={"level": "INFO", "retention_days": 30},
    )
    logging_level = _enum(
        logging_values["level"], "logging.yaml", "logging.level", {"DEBUG", "INFO", "WARNING", "ERROR"}
    )
    logging_directory = _resolve_local_path(
        logging_values["directory"], configuration_directory, "logging.yaml", "logging.directory"
    )
    retention_days = _integer(
        logging_values["retention_days"],
        "logging.yaml",
        "logging.retention_days",
        minimum=1,
        maximum=365,
    )
    include_content = _boolean(
        logging_values["include_content"], "logging.yaml", "logging.include_content"
    )
    if include_content:
        raise ConfigurationError("logging.yaml", "logging.include_content", "the fixed value false")
    logging_settings = LoggingSettings(
        logging_level, logging_directory, retention_days, include_content
    )

    provisional = ApplicationConfiguration(
        app=app,
        model=model,
        context=context,
        memory=memory,
        validation=validation,
        logging=logging_settings,
        configuration_directory=configuration_directory,
        configuration_fingerprint="",
    )
    fingerprint = _configuration_fingerprint(provisional)
    return ApplicationConfiguration(
        app=app,
        model=model,
        context=context,
        memory=memory,
        validation=validation,
        logging=logging_settings,
        configuration_directory=configuration_directory,
        configuration_fingerprint=fingerprint,
    )


def _section_values(
    file_name: str,
    section_name: str,
    raw_section: Mapping[str, Any],
    *,
    allowed: tuple[str, ...],
    required: tuple[str, ...],
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw_section, Mapping):
        raise ConfigurationError(file_name, section_name, "a mapping")
    unknown = sorted(str(key) for key in raw_section if key not in allowed)
    if unknown:
        raise ConfigurationError(file_name, f"{section_name}.{unknown[0]}", "a documented key")
    values = dict(raw_section)
    for key in allowed:
        if key in values:
            continue
        if key in defaults:
            values[key] = defaults[key]
        elif key in required:
            raise ConfigurationError(file_name, f"{section_name}.{key}", "a required key")
    return values


def _rule_values(
    file_name: str,
    location: str,
    raw_rule: Any,
    *,
    allowed: tuple[str, ...],
    required: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(raw_rule, Mapping):
        raise ConfigurationError(file_name, location, "a mapping")
    unknown = sorted(str(key) for key in raw_rule if key not in allowed)
    if unknown:
        raise ConfigurationError(file_name, f"{location}.{unknown[0]}", "a documented key")
    values = dict(raw_rule)
    for key in required:
        if key not in values:
            raise ConfigurationError(file_name, f"{location}.{key}", "a required key")
    return values


def _non_empty_string(value: Any, file_name: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(file_name, key, "a non-empty string")
    return value.strip()


def _identifier(value: Any, file_name: str, key: str) -> str:
    identifier = _non_empty_string(value, file_name, key)
    if identifier != value:
        raise ConfigurationError(file_name, key, "a normalized non-empty identifier")
    return identifier


def _enum(value: Any, file_name: str, key: str, allowed: set[str] | frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        options = ", ".join(sorted(allowed))
        raise ConfigurationError(file_name, key, options)
    return value


def _boolean(value: Any, file_name: str, key: str) -> bool:
    if type(value) is not bool:
        raise ConfigurationError(file_name, key, "a boolean")
    return value


def _integer(
    value: Any,
    file_name: str,
    key: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        range_label = f"an integer {minimum}..{maximum}" if maximum is not None else f"an integer >= {minimum}"
        raise ConfigurationError(file_name, key, range_label)
    return value


def _number(
    value: Any,
    file_name: str,
    key: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ConfigurationError(file_name, key, f"a finite number {minimum}..{maximum}")
    number = float(value)
    if number < minimum or number > maximum:
        raise ConfigurationError(file_name, key, f"a number {minimum}..{maximum}")
    return number


def _loopback_http_url(value: Any, file_name: str, key: str) -> str:
    raw = _non_empty_string(value, file_name, key)
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError(file_name, key, "an HTTP loopback URL with a port") from error
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ConfigurationError(file_name, key, "an HTTP loopback URL with a port")
    hostname = parsed.hostname.lower()
    if hostname != "localhost":
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise ConfigurationError(file_name, key, "an HTTP loopback URL with a port")
    return raw.rstrip("/")


def _normalised_phrase(value: Any, file_name: str, key: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(file_name, key, "a normalized non-empty string")
    normalized = " ".join(unicodedata.normalize("NFC", value).casefold().split())
    if not normalized or value != normalized:
        raise ConfigurationError(file_name, key, "a normalized non-empty string")
    return normalized


def _list(value: Any, file_name: str, key: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError(file_name, key, "a non-empty list")
    return value


def _intent_rules(value: Any) -> tuple[IntentRule, ...]:
    raw_rules = _list(value, "context.yaml", "context.intent_rules")
    rules: list[IntentRule] = []
    seen_ids: set[str] = set()
    phrase_intents: dict[tuple[str, int], str] = {}
    covered_intents: set[str] = set()
    for index, raw_rule in enumerate(raw_rules):
        location = f"context.intent_rules[{index}]"
        rule = _rule_values(
            "context.yaml",
            location,
            raw_rule,
            allowed=("id", "intent", "output_type", "phrases", "priority"),
            required=("id", "intent", "phrases", "priority"),
        )
        identifier = _identifier(rule["id"], "context.yaml", f"{location}.id")
        if identifier in seen_ids:
            raise ConfigurationError("context.yaml", f"{location}.id", "a unique rule id")
        seen_ids.add(identifier)
        intent = _enum(
            rule["intent"], "context.yaml", f"{location}.intent", frozenset(_SUPPORTED_INTENTS)
        )
        output_type = rule.get("output_type")
        if output_type is not None:
            output_type = _enum(
                output_type,
                "context.yaml",
                f"{location}.output_type",
                _OUTPUT_TYPE_OVERRIDES[intent],
            )
        phrases = tuple(
            _normalised_phrase(phrase, "context.yaml", f"{location}.phrases[{phrase_index}]")
            for phrase_index, phrase in enumerate(_list(rule["phrases"], "context.yaml", f"{location}.phrases"))
        )
        if len(set(phrases)) != len(phrases):
            raise ConfigurationError("context.yaml", f"{location}.phrases", "unique normalized phrases")
        priority = _integer(
            rule["priority"], "context.yaml", f"{location}.priority", minimum=1, maximum=100
        )
        for phrase in phrases:
            phrase_key = (phrase, priority)
            existing_intent = phrase_intents.get(phrase_key)
            if existing_intent is not None and existing_intent != intent:
                raise ConfigurationError(
                    "context.yaml",
                    f"{location}.phrases",
                    "no duplicate normalized phrase at one priority for different intents",
                )
            phrase_intents[phrase_key] = intent
        covered_intents.add(intent)
        rules.append(IntentRule(identifier, intent, output_type, phrases, priority))
    missing = sorted(set(_SUPPORTED_INTENTS) - covered_intents)
    if missing:
        raise ConfigurationError(
            "context.yaml",
            "context.intent_rules",
            f"coverage for supported intent {missing[0]}",
        )
    return tuple(rules)


def _qualifier_rules(value: Any) -> tuple[QualifierRule, ...]:
    raw_rules = _list(value, "context.yaml", "context.qualifier_rules")
    rules: list[QualifierRule] = []
    seen_ids: set[str] = set()
    phrases_by_qualifier: dict[str, set[str]] = {kind: set() for kind in _QUALIFIER_KINDS}
    phrase_owners: dict[str, str] = {}
    for index, raw_rule in enumerate(raw_rules):
        location = f"context.qualifier_rules[{index}]"
        rule = _rule_values(
            "context.yaml",
            location,
            raw_rule,
            allowed=("id", "qualifier", "phrases"),
            required=("id", "qualifier", "phrases"),
        )
        identifier = _identifier(rule["id"], "context.yaml", f"{location}.id")
        if identifier in seen_ids:
            raise ConfigurationError("context.yaml", f"{location}.id", "a unique rule id")
        seen_ids.add(identifier)
        qualifier = _enum(
            rule["qualifier"], "context.yaml", f"{location}.qualifier", _QUALIFIER_KINDS
        )
        phrases = tuple(
            _normalised_phrase(phrase, "context.yaml", f"{location}.phrases[{phrase_index}]")
            for phrase_index, phrase in enumerate(_list(rule["phrases"], "context.yaml", f"{location}.phrases"))
        )
        if len(set(phrases)) != len(phrases):
            raise ConfigurationError("context.yaml", f"{location}.phrases", "unique normalized phrases")
        for phrase in phrases:
            owner = phrase_owners.get(phrase)
            if owner is not None and owner != qualifier:
                raise ConfigurationError(
                    "context.yaml",
                    f"{location}.phrases",
                    "phrases with one canonical qualifier effect",
                )
            if phrase in phrases_by_qualifier[qualifier]:
                raise ConfigurationError("context.yaml", f"{location}.phrases", "unique normalized phrases")
            phrase_owners[phrase] = qualifier
            phrases_by_qualifier[qualifier].add(phrase)
        rules.append(QualifierRule(identifier, qualifier, phrases))
    for qualifier, baseline in _QUALIFIER_BASELINES.items():
        if not baseline.issubset(phrases_by_qualifier[qualifier]):
            raise ConfigurationError(
                "context.yaml",
                "context.qualifier_rules",
                f"baseline phrases for {qualifier}",
            )
    return tuple(rules)


def _output_shape_rules(value: Any) -> tuple[OutputShapeRule, ...]:
    raw_rules = _list(value, "validation.yaml", "validation.output_shape_rules")
    rules: list[OutputShapeRule] = []
    seen_ids: set[str] = set()
    seen_output_types: set[str] = set()
    for index, raw_rule in enumerate(raw_rules):
        location = f"validation.output_shape_rules[{index}]"
        rule = _rule_values(
            "validation.yaml",
            location,
            raw_rule,
            allowed=("id", "output_type", "shape"),
            required=("id", "output_type", "shape"),
        )
        identifier = _identifier(rule["id"], "validation.yaml", f"{location}.id")
        if identifier in seen_ids:
            raise ConfigurationError("validation.yaml", f"{location}.id", "a unique rule id")
        seen_ids.add(identifier)
        output_type = _enum(
            rule["output_type"],
            "validation.yaml",
            f"{location}.output_type",
            _MODEL_OUTPUT_TYPES,
        )
        if output_type in seen_output_types:
            raise ConfigurationError(
                "validation.yaml", f"{location}.output_type", "one rule per output type"
            )
        seen_output_types.add(output_type)
        shape = _enum(rule["shape"], "validation.yaml", f"{location}.shape", _OUTPUT_SHAPES)
        rules.append(OutputShapeRule(identifier, output_type, shape))
    missing = sorted(_MODEL_OUTPUT_TYPES - seen_output_types)
    if missing:
        raise ConfigurationError(
            "validation.yaml",
            "validation.output_shape_rules",
            f"one rule for output type {missing[0]}",
        )
    return tuple(rules)


def _preserve_verbs(value: Any) -> tuple[str, ...]:
    raw_values = _list(value, "validation.yaml", "validation.preserve_change_verbs")
    verbs = tuple(
        _normalised_phrase(item, "validation.yaml", f"validation.preserve_change_verbs[{index}]")
        for index, item in enumerate(raw_values)
    )
    if any(" " in verb for verb in verbs) or len(set(verbs)) != len(verbs):
        raise ConfigurationError(
            "validation.yaml", "validation.preserve_change_verbs", "unique normalized lowercase tokens"
        )
    if not _PRESERVE_VERB_BASELINE.issubset(verbs):
        raise ConfigurationError(
            "validation.yaml", "validation.preserve_change_verbs", "the required baseline verbs"
        )
    return verbs


def _action_markers(value: Any) -> tuple[str, ...]:
    raw_values = _list(value, "validation.yaml", "validation.action_markers")
    markers: list[str] = []
    for index, marker in enumerate(raw_values):
        key = f"validation.action_markers[{index}]"
        if not isinstance(marker, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*:", marker):
            raise ConfigurationError("validation.yaml", key, "a literal uppercase marker")
        markers.append(marker)
    if len(set(markers)) != len(markers):
        raise ConfigurationError("validation.yaml", "validation.action_markers", "unique markers")
    if not _ACTION_MARKER_BASELINE.issubset(markers):
        raise ConfigurationError(
            "validation.yaml", "validation.action_markers", "the required baseline markers"
        )
    return tuple(markers)


def _configuration_fingerprint(configuration: ApplicationConfiguration) -> str:
    payload = {
        "app": configuration.app,
        "model": configuration.model,
        "context": configuration.context,
        "memory": configuration.memory,
        "validation": configuration.validation,
        "logging": configuration.logging,
    }
    normalized = _fingerprint_value(payload)
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _fingerprint_value(getattr(value, field.name))
            for field in fields(value)
            if field.name not in {"configuration_directory", "configuration_fingerprint"}
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_fingerprint_value(item) for item in value]
    if isinstance(value, list):
        return [_fingerprint_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _fingerprint_value(item) for key, item in value.items()}
    if isinstance(value, float):
        return format(value, ".17g")
    return value
