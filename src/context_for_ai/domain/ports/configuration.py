"""Provider-independent configuration records and loading port."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol
import unicodedata

from context_for_ai.domain.enums import IntentType, OutputType, ProviderKind, QualifierKind
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import UnitScore


type EnvironmentName = Literal["development", "test", "production"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
type OutputShape = Literal[
    "NON_EMPTY_TEXT", "NUMBERED_LIST", "FENCED_CODE", "COMPARISON_LIST"
]
type UnsupportedRequestCategory = Literal["IMAGE_GENERATION", "EXTERNAL_ACTION"]


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
class UnsupportedRequestRule:
    """One validated deterministic unsupported image/action rule."""

    id: str
    category: UnsupportedRequestCategory
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
    unsupported_request_rules: tuple[UnsupportedRequestRule, ...]


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


_MODEL_ELIGIBLE_OUTPUT_TYPES = frozenset(
    {
        OutputType.TEXT_ANSWER,
        OutputType.TEXT_EXPLANATION,
        OutputType.TEXT_DESCRIPTION,
        OutputType.TEXT_PLAN,
        OutputType.TEXT_ANALYSIS,
        OutputType.TEXT_CODE,
        OutputType.TEXT_COMPARISON,
    }
)
_OUTPUT_SHAPES = frozenset(
    {"NON_EMPTY_TEXT", "NUMBERED_LIST", "FENCED_CODE", "COMPARISON_LIST"}
)


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


@dataclass(frozen=True, slots=True)
class ValidationConfigurationSnapshot:
    """Closed packet projection of normalized validation configuration."""

    configuration_fingerprint: str
    max_revisions: int
    rule_set_version: str
    output_shape_rules: tuple[OutputShapeRule, ...]
    preserve_change_verb_list_id: str
    preserve_change_verbs: tuple[str, ...]
    action_markers: tuple[str, ...]

    def __post_init__(self) -> None:
        _required_text(
            "ValidationConfigurationSnapshot.configuration_fingerprint",
            self.configuration_fingerprint,
        )
        if (
            not isinstance(self.max_revisions, int)
            or isinstance(self.max_revisions, bool)
            or self.max_revisions not in range(3)
        ):
            raise LifecycleInvariantError(
                "ValidationConfigurationSnapshot.max_revisions must be 0, 1, or 2."
            )
        _required_text(
            "ValidationConfigurationSnapshot.rule_set_version",
            self.rule_set_version,
        )
        _required_text(
            "ValidationConfigurationSnapshot.preserve_change_verb_list_id",
            self.preserve_change_verb_list_id,
        )

        rules = tuple(self.output_shape_rules)
        if any(not isinstance(rule, OutputShapeRule) for rule in rules):
            raise LifecycleInvariantError(
                "ValidationConfigurationSnapshot requires typed output-shape rules."
            )
        if len({rule.id for rule in rules}) != len(rules):
            raise LifecycleInvariantError("Output-shape rule IDs must be unique.")
        if (
            len(rules) != len(_MODEL_ELIGIBLE_OUTPUT_TYPES)
            or len({rule.output_type for rule in rules}) != len(rules)
            or {rule.output_type for rule in rules} != _MODEL_ELIGIBLE_OUTPUT_TYPES
        ):
            raise LifecycleInvariantError(
                "ValidationConfigurationSnapshot requires one rule per model output type."
            )
        for rule in rules:
            _required_text("OutputShapeRule.id", rule.id)
            if not isinstance(rule.output_type, OutputType):
                raise LifecycleInvariantError(
                    "OutputShapeRule.output_type must be canonical."
                )
            if not isinstance(rule.shape, str) or rule.shape not in _OUTPUT_SHAPES:
                raise LifecycleInvariantError(
                    "OutputShapeRule.shape must be canonical."
                )

        verbs = tuple(self.preserve_change_verbs)
        markers = tuple(self.action_markers)
        if not verbs or len(set(verbs)) != len(verbs):
            raise LifecycleInvariantError(
                "Preserve-change verbs must be a non-empty unique ordered collection."
            )
        if any(
            not isinstance(verb, str)
            or not verb
            or verb != unicodedata.normalize("NFC", verb).casefold()
            or any(character.isspace() for character in verb)
            for verb in verbs
        ):
            raise LifecycleInvariantError(
                "Preserve-change verbs must be normalized non-empty tokens."
            )
        if not markers or len(set(markers)) != len(markers):
            raise LifecycleInvariantError(
                "Action markers must be a non-empty unique ordered collection."
            )
        for marker in markers:
            _required_text("ValidationConfigurationSnapshot.action_marker", marker)

        object.__setattr__(self, "output_shape_rules", rules)
        object.__setattr__(self, "preserve_change_verbs", verbs)
        object.__setattr__(self, "action_markers", markers)


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
