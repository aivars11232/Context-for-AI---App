"""Isolated configuration and request data for optional live adapter checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum, unique
from pathlib import Path

from context_for_ai.domain.ports import GenerationRequest, GenerationSettings
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.infrastructure.configuration import load_configuration


OLLAMA_OPT_IN_VARIABLE = "CONTEXT_FOR_AI_RUN_OLLAMA"
_ALLOWED_LIVE_OVERRIDES = (
    "CONTEXT_FOR_AI__MODEL__BASE_URL",
    "CONTEXT_FOR_AI__MODEL__NAME",
)


@unique
class OllamaLiveOptIn(StrEnum):
    ABSENT = "ABSENT"
    INVALID = "INVALID"
    ENABLED = "ENABLED"


@dataclass(frozen=True, slots=True)
class LiveOllamaCase:
    """One normally validated model handoff and fixed adapter-only request."""

    base_url: str
    model_name: str
    request: GenerationRequest


def classify_ollama_live_opt_in(environ: Mapping[str, str]) -> OllamaLiveOptIn:
    """Classify absence, invalid presence, or the exact explicit opt-in."""

    if OLLAMA_OPT_IN_VARIABLE not in environ:
        return OllamaLiveOptIn.ABSENT
    if environ[OLLAMA_OPT_IN_VARIABLE] != "1":
        return OllamaLiveOptIn.INVALID
    return OllamaLiveOptIn.ENABLED


def load_live_ollama_case(
    application_root: Path,
    environ: Mapping[str, str],
) -> LiveOllamaCase:
    """Load all six files normally, admitting only documented model overrides."""

    loader_environment = {
        key: environ[key]
        for key in _ALLOWED_LIVE_OVERRIDES
        if key in environ
    }
    configuration = load_configuration(
        application_root=application_root,
        environ=loader_environment,
    )
    model = configuration.model
    request = GenerationRequest(
        model_name=model.name,
        rendered_prompt=(
            "Reply with one short plain-text confirmation that local inference "
            "completed."
        ),
        settings=GenerationSettings(
            context_window_tokens=model.context_window_tokens,
            request_timeout_seconds=model.request_timeout_seconds,
            temperature=Decimal(model.temperature),
        ),
        processing_run_id=DomainId("33000000-0000-4000-8000-000000000001"),
        context_packet_id=DomainId("33000000-0000-4000-8000-000000000002"),
        model_request_id=DomainId("33000000-0000-4000-8000-000000000003"),
        attempt_number=0,
    )
    return LiveOllamaCase(model.base_url, model.name, request)


__all__ = [
    "LiveOllamaCase",
    "OLLAMA_OPT_IN_VARIABLE",
    "OllamaLiveOptIn",
    "classify_ollama_live_opt_in",
    "load_live_ollama_case",
]
