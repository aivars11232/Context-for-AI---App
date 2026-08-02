"""Provider-independent, fully buffered text-generation port."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from datetime import timedelta
from typing import Protocol

from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _non_negative_integer(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleInvariantError(f"{field_name} must be non-negative.")


@dataclass(frozen=True, slots=True)
class GenerationSettings:
    """Validated deterministic settings for one buffered provider call."""

    context_window_tokens: int
    request_timeout_seconds: int
    temperature: Decimal

    def __post_init__(self) -> None:
        if self.context_window_tokens < 1:
            raise LifecycleInvariantError(
                "GenerationSettings.context_window_tokens must be positive."
            )
        if self.request_timeout_seconds < 1:
            raise LifecycleInvariantError(
                "GenerationSettings.request_timeout_seconds must be positive."
            )
        if not Decimal(0) <= self.temperature <= Decimal(2):
            raise LifecycleInvariantError(
                "GenerationSettings.temperature must be between 0 and 2."
            )


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """One complete prompt plus trace identifiers for a provider call."""

    model_name: str
    rendered_prompt: str
    settings: GenerationSettings
    processing_run_id: DomainId
    context_packet_id: DomainId
    model_request_id: DomainId
    attempt_number: int

    def __post_init__(self) -> None:
        _required_text("GenerationRequest.model_name", self.model_name)
        if not isinstance(self.rendered_prompt, str):
            raise LifecycleInvariantError(
                "GenerationRequest.rendered_prompt must be text."
            )
        if self.attempt_number not in (0, 1, 2):
            raise LifecycleInvariantError(
                "GenerationRequest.attempt_number must be 0, 1, or 2."
            )


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Optional provider-reported token counts."""

    prompt_tokens: int | None
    generated_tokens: int | None
    total_tokens: int | None

    def __post_init__(self) -> None:
        for field_name in ("prompt_tokens", "generated_tokens", "total_tokens"):
            value = getattr(self, field_name)
            if value is not None:
                _non_negative_integer(f"TokenUsage.{field_name}", value)


@dataclass(frozen=True, slots=True)
class CompletedGeneration:
    """One fully buffered provider response; partial output is unrepresentable."""

    response_text: str
    provider_metadata: FrozenJsonObject
    elapsed: timedelta
    token_usage: TokenUsage | None

    def __post_init__(self) -> None:
        if not isinstance(self.response_text, str):
            raise LifecycleInvariantError(
                "CompletedGeneration.response_text must be text."
            )
        if not isinstance(self.provider_metadata, FrozenJsonObject):
            object.__setattr__(
                self,
                "provider_metadata",
                FrozenJsonObject(self.provider_metadata),
            )
        if not isinstance(self.elapsed, timedelta) or self.elapsed < timedelta(0):
            raise LifecycleInvariantError(
                "CompletedGeneration.elapsed must be a non-negative duration."
            )


class ModelGatewayError(Exception):
    """Base class for safe, provider-independent transport failures."""

    def __init__(self, safe_message: str, diagnostic_code: str) -> None:
        _required_text("ModelGatewayError.safe_message", safe_message)
        _required_text("ModelGatewayError.diagnostic_code", diagnostic_code)
        self.safe_message = safe_message
        self.diagnostic_code = diagnostic_code
        super().__init__(safe_message)


class ProviderUnavailableError(ModelGatewayError):
    """The configured local provider cannot be reached."""


class ModelNotFoundError(ModelGatewayError):
    """The configured local model is unavailable at the provider."""


class ModelTimeoutError(ModelGatewayError):
    """The bounded provider request exceeded its configured timeout."""


class ModelCancelledError(ModelGatewayError):
    """The foreground user request cancelled provider waiting."""


class InvalidProviderResponseError(ModelGatewayError):
    """The provider returned no valid complete text response."""


class CancellationToken(Protocol):
    """Expose thread-safe cooperative cancellation without Qt dependencies."""

    def is_cancelled(self) -> bool: ...


class ModelGateway(Protocol):
    """Generate exactly one complete response or raise one typed transport error."""

    def generate(
        self,
        request: GenerationRequest,
        cancellation_token: CancellationToken,
    ) -> CompletedGeneration: ...
