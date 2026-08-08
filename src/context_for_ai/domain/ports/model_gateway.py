"""Provider-independent, fully buffered text-generation port."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from context_for_ai.domain.enums import (
    FailureCode,
    ModelRequestStatus,
    ProcessingRunStatus,
)
from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.value_objects import DomainId, FrozenJsonObject


def _required_text(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleInvariantError(f"{field_name} must be non-empty text.")


def _non_negative_integer(field_name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleInvariantError(f"{field_name} must be non-negative.")


def _required_domain_id(field_name: str, value: DomainId) -> None:
    if not isinstance(value, DomainId):
        raise LifecycleInvariantError(f"{field_name} must be a domain ID.")


@dataclass(frozen=True, slots=True)
class GenerationSettings:
    """Validated deterministic settings for one buffered provider call."""

    context_window_tokens: int
    request_timeout_seconds: int
    temperature: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.context_window_tokens, int)
            or isinstance(self.context_window_tokens, bool)
            or self.context_window_tokens < 1024
        ):
            raise LifecycleInvariantError(
                "GenerationSettings.context_window_tokens must be an integer "
                "greater than or equal to 1024."
            )
        if (
            not isinstance(self.request_timeout_seconds, int)
            or isinstance(self.request_timeout_seconds, bool)
            or not 1 <= self.request_timeout_seconds <= 300
        ):
            raise LifecycleInvariantError(
                "GenerationSettings.request_timeout_seconds must be an integer "
                "between 1 and 300."
            )
        if (
            not isinstance(self.temperature, Decimal)
            or not self.temperature.is_finite()
            or not Decimal(0) <= self.temperature <= Decimal(2)
        ):
            raise LifecycleInvariantError(
                "GenerationSettings.temperature must be a finite Decimal between 0 and 2."
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
        if not isinstance(self.rendered_prompt, str) or not self.rendered_prompt:
            raise LifecycleInvariantError(
                "GenerationRequest.rendered_prompt must be non-empty text."
            )
        if not isinstance(self.settings, GenerationSettings):
            raise LifecycleInvariantError(
                "GenerationRequest.settings must be validated generation settings."
            )
        for field_name in (
            "processing_run_id",
            "context_packet_id",
            "model_request_id",
        ):
            _required_domain_id(
                f"GenerationRequest.{field_name}",
                getattr(self, field_name),
            )
        if (
            not isinstance(self.attempt_number, int)
            or isinstance(self.attempt_number, bool)
            or self.attempt_number not in (0, 1, 2)
        ):
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
        _required_text("CompletedGeneration.response_text", self.response_text)
        if not isinstance(self.provider_metadata, (FrozenJsonObject, Mapping)):
            raise LifecycleInvariantError(
                "CompletedGeneration.provider_metadata must be a JSON object."
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
        if self.token_usage is not None and not isinstance(
            self.token_usage, TokenUsage
        ):
            raise LifecycleInvariantError(
                "CompletedGeneration.token_usage must be typed token usage or null."
            )


@dataclass(frozen=True, slots=True)
class ProviderUnavailableFailure:
    """Canonical result when the configured local provider is unavailable."""

    diagnostic_code: str = field(init=False, default="PROVIDER_UNAVAILABLE")
    safe_message: str = field(
        init=False,
        default="The local model provider is unavailable.",
    )
    model_request_status: ModelRequestStatus = field(
        init=False,
        default=ModelRequestStatus.FAILED,
    )
    processing_run_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.FAILED,
    )
    failure_code: FailureCode = field(
        init=False,
        default=FailureCode.PROVIDER_UNAVAILABLE,
    )


@dataclass(frozen=True, slots=True)
class ModelNotFoundFailure:
    """Canonical result when the configured local model is unavailable."""

    diagnostic_code: str = field(init=False, default="MODEL_NOT_FOUND")
    safe_message: str = field(
        init=False,
        default="The configured local model is unavailable.",
    )
    model_request_status: ModelRequestStatus = field(
        init=False,
        default=ModelRequestStatus.FAILED,
    )
    processing_run_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.FAILED,
    )
    failure_code: FailureCode = field(
        init=False,
        default=FailureCode.MODEL_NOT_FOUND,
    )


@dataclass(frozen=True, slots=True)
class ModelTimeoutFailure:
    """Canonical result when the bounded provider request times out."""

    diagnostic_code: str = field(init=False, default="MODEL_TIMEOUT")
    safe_message: str = field(
        init=False,
        default="The local model request timed out.",
    )
    model_request_status: ModelRequestStatus = field(
        init=False,
        default=ModelRequestStatus.TIMED_OUT,
    )
    processing_run_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.FAILED,
    )
    failure_code: FailureCode = field(
        init=False,
        default=FailureCode.MODEL_TIMEOUT,
    )


@dataclass(frozen=True, slots=True)
class ModelCancelledFailure:
    """Canonical result when cancellation is observed inside the gateway."""

    diagnostic_code: str = field(init=False, default="MODEL_CANCELLED")
    safe_message: str = field(
        init=False,
        default="The local model request was cancelled.",
    )
    model_request_status: ModelRequestStatus = field(
        init=False,
        default=ModelRequestStatus.CANCELLED,
    )
    processing_run_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.CANCELLED,
    )
    failure_code: FailureCode = field(
        init=False,
        default=FailureCode.MODEL_CANCELLED,
    )


@dataclass(frozen=True, slots=True)
class InvalidProviderResponseFailure:
    """Canonical result when no valid complete provider envelope is available."""

    diagnostic_code: str = field(init=False, default="INVALID_PROVIDER_RESPONSE")
    safe_message: str = field(
        init=False,
        default="The local model provider returned an invalid response.",
    )
    model_request_status: ModelRequestStatus = field(
        init=False,
        default=ModelRequestStatus.FAILED,
    )
    processing_run_status: ProcessingRunStatus = field(
        init=False,
        default=ProcessingRunStatus.FAILED,
    )
    failure_code: FailureCode = field(
        init=False,
        default=FailureCode.INVALID_PROVIDER_RESPONSE,
    )


type GenerationFailure = (
    ProviderUnavailableFailure
    | ModelNotFoundFailure
    | ModelTimeoutFailure
    | ModelCancelledFailure
    | InvalidProviderResponseFailure
)

type GenerationOutcome = CompletedGeneration | GenerationFailure


class CancellationToken(Protocol):
    """Expose thread-safe cooperative cancellation without Qt dependencies."""

    def is_cancelled(self) -> bool: ...


class ModelGateway(Protocol):
    """Return one complete generation or provider-independent failure value."""

    def generate(
        self,
        request: GenerationRequest,
        cancellation_token: CancellationToken,
    ) -> GenerationOutcome: ...
