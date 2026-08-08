"""Buffered local-only Ollama implementation of the canonical model gateway."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import time

from context_for_ai.domain.errors import LifecycleInvariantError
from context_for_ai.domain.ports.model_gateway import (
    CancellationToken,
    CompletedGeneration,
    GenerationFailure,
    GenerationOutcome,
    GenerationRequest,
    InvalidProviderResponseFailure,
    ModelCancelledFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ProviderUnavailableFailure,
)
from context_for_ai.infrastructure.configuration.ollama_model import (
    InvalidOllamaEndpoint,
    InvalidOllamaModelIdentity,
    normalize_ollama_endpoint,
    normalize_ollama_model_identity,
)
from context_for_ai.infrastructure.ollama.transport import (
    OllamaHttpRequest,
    OllamaHttpResponse,
    OllamaTransport,
    OllamaTransportCancelled,
    OllamaTransportFailure,
    OllamaTransportTimeout,
    StandardLibraryOllamaTransport,
)
from context_for_ai.infrastructure.ollama.wire import (
    OllamaWireError,
    ParsedGenerationResponse,
    encode_generate_request,
    encode_show_request,
    parse_generation_response,
    parse_show_response,
    parse_status_response,
    parse_version_response,
)


_FAILURE_TYPES = (
    ProviderUnavailableFailure,
    ModelNotFoundFailure,
    ModelTimeoutFailure,
    ModelCancelledFailure,
    InvalidProviderResponseFailure,
)


class OllamaModelProvider:
    """Perform one uncached, fully buffered local Ollama sequence per call."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        *,
        transport: OllamaTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        try:
            endpoint = normalize_ollama_endpoint(base_url)
        except InvalidOllamaEndpoint as error:
            raise LifecycleInvariantError(
                "OllamaModelProvider requires a validated loopback endpoint."
            ) from error
        try:
            model = normalize_ollama_model_identity(model_name)
        except InvalidOllamaModelIdentity as error:
            raise LifecycleInvariantError(
                "OllamaModelProvider requires a validated local model identity."
            ) from error

        self._model_identity = model.value
        self._monotonic = monotonic
        self._transport = (
            transport
            if transport is not None
            else StandardLibraryOllamaTransport(endpoint, monotonic=monotonic)
        )

    def generate(
        self,
        request: GenerationRequest,
        cancellation_token: CancellationToken,
    ) -> GenerationOutcome:
        """Return one complete generation or one canonical content-free failure."""

        if cancellation_token.is_cancelled():
            return ModelCancelledFailure()
        started_at = self._monotonic()
        self._validate_request_model(request)
        deadline = started_at + request.settings.request_timeout_seconds

        version_observation = self._exchange(
            OllamaHttpRequest("GET", "/api/version"),
            stage="version",
            deadline=deadline,
            cancellation_token=cancellation_token,
        )
        if isinstance(version_observation, _FAILURE_TYPES):
            return version_observation
        if version_observation.status != 200:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        try:
            provider_version = parse_version_response(
                _required_body(version_observation),
                version_observation.media_type,
            )
        except OllamaWireError:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        except Exception:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )

        status_observation = self._exchange(
            OllamaHttpRequest("GET", "/api/status"),
            stage="status",
            deadline=deadline,
            cancellation_token=cancellation_token,
        )
        if isinstance(status_observation, _FAILURE_TYPES):
            return status_observation
        if status_observation.status != 200:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        try:
            cloud_disable_source = parse_status_response(
                _required_body(status_observation),
                status_observation.media_type,
            )
        except OllamaWireError:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        except Exception:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )

        show_observation = self._exchange(
            OllamaHttpRequest(
                "POST",
                "/api/show",
                encode_show_request(self._model_identity),
            ),
            stage="show",
            deadline=deadline,
            cancellation_token=cancellation_token,
        )
        if isinstance(show_observation, _FAILURE_TYPES):
            return show_observation
        if show_observation.status == 404:
            return self._terminal_failure(
                ModelNotFoundFailure(), cancellation_token, deadline
            )
        if show_observation.status != 200:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        try:
            show_response = parse_show_response(
                _required_body(show_observation),
                show_observation.media_type,
            )
        except OllamaWireError:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        except Exception:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        if show_response.is_remote:
            return self._terminal_failure(
                ModelNotFoundFailure(), cancellation_token, deadline
            )

        try:
            generate_body = encode_generate_request(request, self._model_identity)
        except OllamaWireError as error:
            raise LifecycleInvariantError(
                "GenerationRequest.rendered_prompt must be JSON encodable."
            ) from error
        generate_observation = self._exchange(
            OllamaHttpRequest(
                "POST",
                "/api/generate",
                generate_body,
            ),
            stage="generate",
            deadline=deadline,
            cancellation_token=cancellation_token,
        )
        if isinstance(generate_observation, _FAILURE_TYPES):
            return generate_observation
        if generate_observation.status == 404:
            return self._terminal_failure(
                ModelNotFoundFailure(), cancellation_token, deadline
            )
        if generate_observation.status != 200:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        try:
            parsed = parse_generation_response(
                _required_body(generate_observation),
                generate_observation.media_type,
                model_identity=self._model_identity,
                provider_version=provider_version,
                cloud_disable_source=cloud_disable_source,
            )
        except OllamaWireError:
            return self._terminal_failure(
                InvalidProviderResponseFailure(), cancellation_token, deadline
            )
        except Exception:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )
        return self._completed_generation(
            parsed,
            cancellation_token=cancellation_token,
            started_at=started_at,
            deadline=deadline,
        )

    def _validate_request_model(self, request: GenerationRequest) -> None:
        if not isinstance(request, GenerationRequest):
            raise LifecycleInvariantError(
                "OllamaModelProvider requires a canonical generation request."
            )
        try:
            request_model = normalize_ollama_model_identity(request.model_name)
        except InvalidOllamaModelIdentity as error:
            raise LifecycleInvariantError(
                "GenerationRequest.model_name must be a valid configured model."
            ) from error
        if request_model.value != self._model_identity:
            raise LifecycleInvariantError(
                "GenerationRequest.model_name must match the bound provider model."
            )

    def _exchange(
        self,
        request: OllamaHttpRequest,
        *,
        stage: str,
        deadline: float,
        cancellation_token: CancellationToken,
    ) -> OllamaHttpResponse | GenerationFailure:
        checkpoint = self._checkpoint(cancellation_token, deadline)
        if checkpoint is not None:
            return checkpoint
        try:
            response = self._transport.exchange(
                request,
                deadline=deadline,
                cancellation_token=cancellation_token,
            )
        except OllamaTransportCancelled:
            return ModelCancelledFailure()
        except OllamaTransportTimeout:
            return self._terminal_failure(
                ModelTimeoutFailure(), cancellation_token, deadline
            )
        except OllamaTransportFailure as error:
            failure: GenerationFailure
            if stage == "generate" and error.response_status == 200:
                failure = InvalidProviderResponseFailure()
            else:
                failure = ProviderUnavailableFailure()
            return self._terminal_failure(failure, cancellation_token, deadline)
        except AssertionError:
            raise
        except Exception:
            return self._terminal_failure(
                ProviderUnavailableFailure(), cancellation_token, deadline
            )

        checkpoint = self._checkpoint(cancellation_token, deadline)
        if checkpoint is not None:
            return checkpoint
        if response.status in (408, 504):
            return self._terminal_failure(
                ModelTimeoutFailure(), cancellation_token, deadline
            )
        return response

    def _completed_generation(
        self,
        parsed: ParsedGenerationResponse,
        *,
        cancellation_token: CancellationToken,
        started_at: float,
        deadline: float,
    ) -> GenerationOutcome:
        checkpoint = self._checkpoint(cancellation_token, deadline)
        if checkpoint is not None:
            return checkpoint
        publication_time = self._monotonic()
        if cancellation_token.is_cancelled():
            return ModelCancelledFailure()
        if publication_time >= deadline:
            if cancellation_token.is_cancelled():
                return ModelCancelledFailure()
            return ModelTimeoutFailure()
        outcome = CompletedGeneration(
            response_text=parsed.response_text,
            provider_metadata=parsed.provider_metadata,
            elapsed=timedelta(seconds=max(0.0, publication_time - started_at)),
            token_usage=parsed.token_usage,
        )
        if cancellation_token.is_cancelled():
            return ModelCancelledFailure()
        final_publication_time = self._monotonic()
        if cancellation_token.is_cancelled():
            return ModelCancelledFailure()
        if final_publication_time >= deadline:
            if cancellation_token.is_cancelled():
                return ModelCancelledFailure()
            return ModelTimeoutFailure()
        if final_publication_time != publication_time:
            outcome = CompletedGeneration(
                response_text=parsed.response_text,
                provider_metadata=parsed.provider_metadata,
                elapsed=timedelta(
                    seconds=max(0.0, final_publication_time - started_at)
                ),
                token_usage=parsed.token_usage,
            )
        if cancellation_token.is_cancelled():
            return ModelCancelledFailure()
        return outcome

    def _terminal_failure(
        self,
        failure: GenerationFailure,
        cancellation_token: CancellationToken,
        deadline: float,
    ) -> GenerationFailure:
        if cancellation_token.is_cancelled():
            return ModelCancelledFailure()
        if self._monotonic() >= deadline:
            if cancellation_token.is_cancelled():
                return ModelCancelledFailure()
            return ModelTimeoutFailure()
        if cancellation_token.is_cancelled():
            return ModelCancelledFailure()
        return failure

    def _checkpoint(
        self,
        cancellation_token: CancellationToken,
        deadline: float,
    ) -> ModelCancelledFailure | ModelTimeoutFailure | None:
        if cancellation_token.is_cancelled():
            return ModelCancelledFailure()
        if self._monotonic() >= deadline:
            if cancellation_token.is_cancelled():
                return ModelCancelledFailure()
            return ModelTimeoutFailure()
        return None


def _required_body(response: OllamaHttpResponse) -> bytes:
    if not isinstance(response.body, bytes):
        raise OllamaWireError
    return response.body


__all__ = ["OllamaModelProvider"]
