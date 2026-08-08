"""Strict, side-effect-free normalization for configured Ollama identity."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import unicodedata
from urllib.parse import urlsplit


class InvalidOllamaEndpoint(ValueError):
    """Report a value that is not a direct numeric-loopback HTTP endpoint."""


class InvalidOllamaModelIdentity(ValueError):
    """Report a value outside the one-model local Ollama grammar."""


@dataclass(frozen=True, slots=True)
class NormalizedOllamaEndpoint:
    """One direct numeric-loopback endpoint, split for transport construction."""

    base_url: str
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class NormalizedOllamaModelIdentity:
    """One case-sensitive normalized model identity and its explicit tag."""

    value: str
    tag: str


def normalize_ollama_endpoint(value: object) -> NormalizedOllamaEndpoint:
    """Validate and normalize one direct numeric-loopback HTTP endpoint."""

    if (
        not isinstance(value, str)
        or not value
        or not value.startswith("http://")
        or "%" in value
        or "\\" in value
        or "?" in value
        or "#" in value
        or any(
            character.isspace() or unicodedata.category(character) == "Cc"
            for character in value
        )
    ):
        raise InvalidOllamaEndpoint

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise InvalidOllamaEndpoint from error

    if (
        parsed.scheme != "http"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        raise InvalidOllamaEndpoint

    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as error:
        raise InvalidOllamaEndpoint from error
    if not address.is_loopback:
        raise InvalidOllamaEndpoint

    host = address.compressed
    serialized_host = f"[{host}]" if address.version == 6 else host
    return NormalizedOllamaEndpoint(
        base_url=f"http://{serialized_host}:{port}",
        host=host,
        port=port,
    )


def normalize_ollama_model_identity(
    value: object,
) -> NormalizedOllamaModelIdentity:
    """Validate one model reference and append the default tag when omitted."""

    if (
        not isinstance(value, str)
        or not value
        or any(
            character.isspace() or unicodedata.category(character) == "Cc"
            for character in value
        )
    ):
        raise InvalidOllamaModelIdentity

    segments = value.split("/")
    if any(not segment for segment in segments):
        raise InvalidOllamaModelIdentity
    if any(":" in segment for segment in segments[:-1]):
        raise InvalidOllamaModelIdentity

    final_segment = segments[-1]
    if final_segment.count(":") > 1:
        raise InvalidOllamaModelIdentity
    if ":" in final_segment:
        model, tag = final_segment.split(":", 1)
        if not model or not tag:
            raise InvalidOllamaModelIdentity
        normalized = value
    else:
        tag = "latest"
        normalized = f"{value}:latest"

    ascii_folded_tag = tag.translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )
    if ascii_folded_tag == "cloud" or ascii_folded_tag.endswith("-cloud"):
        raise InvalidOllamaModelIdentity

    return NormalizedOllamaModelIdentity(normalized, tag)


__all__ = [
    "InvalidOllamaEndpoint",
    "InvalidOllamaModelIdentity",
    "NormalizedOllamaEndpoint",
    "NormalizedOllamaModelIdentity",
    "normalize_ollama_endpoint",
    "normalize_ollama_model_identity",
]
