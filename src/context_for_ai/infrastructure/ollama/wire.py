"""Strict request and response codecs for the native Ollama HTTP API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
import json
from typing import Never

from context_for_ai.domain.errors import DomainValidationError
from context_for_ai.domain.ports.model_gateway import GenerationRequest, TokenUsage
from context_for_ai.domain.value_objects import FrozenJsonObject, canonical_json
from context_for_ai.infrastructure.configuration.ollama_model import (
    InvalidOllamaModelIdentity,
    normalize_ollama_model_identity,
)


_MISSING = object()
_DURATION_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)


class OllamaWireError(ValueError):
    """Identify a response that violates the bounded Ollama wire contract."""


@dataclass(frozen=True, slots=True)
class ParsedShowResponse:
    """Retain only whether a valid provider remote marker was observed."""

    is_remote: bool


@dataclass(frozen=True, slots=True)
class ParsedGenerationResponse:
    """Retain only the allowlisted fields from one complete terminal envelope."""

    response_text: str
    provider_metadata: FrozenJsonObject
    token_usage: TokenUsage | None


def encode_show_request(model_identity: str) -> bytes:
    """Encode the exact configured-model existence request."""

    return _encode_json_object({"model": model_identity, "verbose": False})


def encode_generate_request(
    request: GenerationRequest,
    model_identity: str,
) -> bytes:
    """Encode one non-streaming generation request without float conversion."""

    return _encode_json_object(
        {
            "model": model_identity,
            "prompt": request.rendered_prompt,
            "stream": False,
            "raw": True,
            "think": False,
            "truncate": False,
            "shift": False,
            "options": {
                "num_ctx": request.settings.context_window_tokens,
                "temperature": request.settings.temperature,
            },
        }
    )


def parse_version_response(body: bytes, media_type: str | None) -> str:
    """Validate one complete daemon-health body and return its exact version."""

    payload = _parse_json_object(body, media_type)
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise OllamaWireError
    return version


def parse_status_response(body: bytes, media_type: str | None) -> str:
    """Validate the daemon's native cloud-disabled attestation."""

    payload = _parse_json_object(body, media_type)
    cloud = payload.get("cloud")
    if not isinstance(cloud, Mapping) or cloud.get("disabled") is not True:
        raise OllamaWireError
    source = cloud.get("source")
    if not isinstance(source, str) or source not in {"env", "config", "both"}:
        raise OllamaWireError
    return source


def parse_show_response(
    body: bytes,
    media_type: str | None,
) -> ParsedShowResponse:
    """Validate one model-details body without retaining provider details."""

    payload = _parse_json_object(body, media_type)
    remote_values = tuple(
        payload.get(field_name, _MISSING)
        for field_name in ("remote_model", "remote_host")
    )
    if any(isinstance(value, str) and value != "" for value in remote_values):
        return ParsedShowResponse(is_remote=True)
    if any(value not in (_MISSING, None, "") for value in remote_values):
        raise OllamaWireError
    return ParsedShowResponse(is_remote=False)


def parse_generation_response(
    body: bytes,
    media_type: str | None,
    *,
    model_identity: str,
    provider_version: str,
    cloud_disable_source: str,
) -> ParsedGenerationResponse:
    """Validate and project one complete terminal generation envelope."""

    payload = _parse_json_object(body, media_type)
    _validate_terminal_model(payload.get("model"), model_identity)

    response_text = payload.get("response")
    if not isinstance(response_text, str) or not response_text.strip():
        raise OllamaWireError
    if payload.get("done") is not True:
        raise OllamaWireError

    for field_name in ("remote_model", "remote_host", "thinking"):
        value = payload.get(field_name, _MISSING)
        if value not in (_MISSING, None, ""):
            raise OllamaWireError
    for field_name in ("tool_calls", "logprobs", "context"):
        value = payload.get(field_name, _MISSING)
        if value not in (_MISSING, None, []):
            raise OllamaWireError
    for field_name in ("error", "image", "_debug_info"):
        if payload.get(field_name, None) is not None:
            raise OllamaWireError

    done_reason = _optional_string(payload, "done_reason")
    durations = {
        field_name: _optional_non_negative_integer(payload, field_name)
        for field_name in _DURATION_FIELDS
    }
    prompt_tokens = _optional_non_negative_integer(payload, "prompt_eval_count")
    generated_tokens = _optional_non_negative_integer(payload, "eval_count")
    token_usage = _token_usage(prompt_tokens, generated_tokens)

    try:
        normalized_model = normalize_ollama_model_identity(model_identity)
    except InvalidOllamaModelIdentity as error:
        raise OllamaWireError from error
    metadata = FrozenJsonObject(
        {
            "provider": "ollama",
            "provider_version": provider_version,
            "model_identity": normalized_model.value,
            "model_tag": normalized_model.tag,
            "cloud_disable_source": cloud_disable_source,
            "done_reason": done_reason,
            "total_duration_ns": durations["total_duration"],
            "load_duration_ns": durations["load_duration"],
            "prompt_eval_duration_ns": durations["prompt_eval_duration"],
            "eval_duration_ns": durations["eval_duration"],
        }
    )
    return ParsedGenerationResponse(response_text, metadata, token_usage)


def is_json_media_type(value: str | None) -> bool:
    """Return whether a Content-Type denotes JSON with optional parameters."""

    if not isinstance(value, str):
        return False
    base_type = value.split(";", 1)[0].strip().lower()
    return base_type == "application/json" or (
        base_type.startswith("application/") and base_type.endswith("+json")
    )


def _encode_json_object(value: Mapping[str, object]) -> bytes:
    try:
        return canonical_json(value).encode("utf-8")
    except (DomainValidationError, UnicodeEncodeError) as error:
        raise OllamaWireError from error


def _parse_json_object(body: bytes, media_type: str | None) -> dict[str, object]:
    if not is_json_media_type(media_type) or not isinstance(body, bytes):
        raise OllamaWireError
    try:
        text = body.decode("utf-8", errors="strict")
        decoder = json.JSONDecoder(
            object_pairs_hook=_unique_object,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=_reject_json_constant,
        )
        start = json.decoder.WHITESPACE.match(text, 0).end()
        value, end = decoder.raw_decode(text, start)
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise OllamaWireError from error
    if json.decoder.WHITESPACE.match(text, end).end() != len(text):
        raise OllamaWireError
    if not isinstance(value, dict):
        raise OllamaWireError
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_json_constant(_raw: str) -> Never:
    raise ValueError("non-finite JSON number")


def _validate_terminal_model(value: object, model_identity: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise OllamaWireError
    try:
        actual = normalize_ollama_model_identity(value).value
        expected = normalize_ollama_model_identity(model_identity).value
    except InvalidOllamaModelIdentity as error:
        raise OllamaWireError from error
    if actual != expected:
        raise OllamaWireError


def _optional_string(payload: Mapping[str, object], field_name: str) -> str | None:
    value = payload.get(field_name, _MISSING)
    if value in (_MISSING, None, ""):
        return None
    if not isinstance(value, str):
        raise OllamaWireError
    return value


def _optional_non_negative_integer(
    payload: Mapping[str, object],
    field_name: str,
) -> int | None:
    value = payload.get(field_name, _MISSING)
    if value is _MISSING or value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OllamaWireError
    return value


def _token_usage(
    prompt_tokens: int | None,
    generated_tokens: int | None,
) -> TokenUsage | None:
    if prompt_tokens is None and generated_tokens is None:
        return None
    total_tokens = (
        prompt_tokens + generated_tokens
        if prompt_tokens is not None and generated_tokens is not None
        else None
    )
    return TokenUsage(prompt_tokens, generated_tokens, total_tokens)


__all__ = [
    "OllamaWireError",
    "ParsedGenerationResponse",
    "ParsedShowResponse",
    "encode_generate_request",
    "encode_show_request",
    "is_json_media_type",
    "parse_generation_response",
    "parse_show_response",
    "parse_status_response",
    "parse_version_response",
]
