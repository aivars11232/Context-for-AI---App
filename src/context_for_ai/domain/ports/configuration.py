"""Provider-independent configuration records and loading port."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from context_for_ai.domain.enums import IntentType, OutputType, ProviderKind, QualifierKind
from context_for_ai.domain.value_objects import UnitScore


type EnvironmentName = Literal["development", "test", "production"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
type OutputShape = Literal[
    "NON_EMPTY_TEXT", "NUMBERED_LIST", "FENCED_CODE", "COMPARISON_LIST"
]


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    """Validated process-level application settings."""

    environment: EnvironmentName
    data_directory: Path
    foreground_run_limit: int


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """Validated single-provider text-generation settings."""

    provider: ProviderKind
    base_url: str
    name: str
    context_window_tokens: int
    request_timeout_seconds: int
    temperature: Decimal


@dataclass(frozen=True, slots=True)
class IntentRule:
    """One validated deterministic intent configuration rule."""

    id: str
    intent: IntentType
    output_type: OutputType | None
    phrases: tuple[str, ...]
    priority: int


@dataclass(frozen=True, slots=True)
class QualifierRule:
    """One validated deterministic qualifier configuration rule."""

    id: str
    qualifier: QualifierKind
    phrases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextSettings:
    """Validated deterministic context-construction settings."""

    tokenizer_estimator: str
    maximum_prompt_tokens: int
    reserved_response_tokens: int
    recent_message_limit: int
    retrieved_memory_limit: int
    minimum_relevance_score: UnitScore
    topic_stack_limit: int
    rule_set_version: str
    conditional_grammar_version: str
    intent_rules: tuple[IntentRule, ...]
    qualifier_rules: tuple[QualifierRule, ...]


@dataclass(frozen=True, slots=True)
class MemorySettings:
    """Validated explicit-only memory mutation settings."""

    allow_manual_create: bool
    allow_manual_edit: bool
    allow_manual_soft_delete: bool
    automatic_mutation: bool


@dataclass(frozen=True, slots=True)
class OutputShapeRule:
    """One validated output-type to deterministic-shape mapping."""

    id: str
    output_type: OutputType
    shape: OutputShape


@dataclass(frozen=True, slots=True)
class ValidationSettings:
    """Validated deterministic response-validation settings."""

    max_revisions: int
    rule_set_version: str
    output_shape_rules: tuple[OutputShapeRule, ...]
    preserve_change_verb_list_id: str
    preserve_change_verbs: tuple[str, ...]
    action_markers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    """Validated local structured-logging settings."""

    level: LogLevel
    directory: Path
    retention_days: int
    include_content: Literal[False]


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    """The complete validated, path-resolved process configuration."""

    app: ApplicationSettings
    model: ModelSettings
    context: ContextSettings
    memory: MemorySettings
    validation: ValidationSettings
    logging: LoggingSettings
    configuration_directory: Path
    configuration_fingerprint: str


class ConfigurationLoader(Protocol):
    """Load one complete configuration without exposing YAML to callers."""

    def load(self) -> ConfigurationSnapshot: ...
