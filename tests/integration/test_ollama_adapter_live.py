"""Optional adapter-only integration with an explicitly enabled local daemon."""

from __future__ import annotations

from typing import Any

import pytest

from context_for_ai.domain.ports import CompletedGeneration


pytestmark = pytest.mark.ollama


def test_live_local_ollama_adapter_contract(live_ollama_adapter: Any) -> None:
    outcome = live_ollama_adapter.gateway.generate(
        live_ollama_adapter.request,
        live_ollama_adapter.new_cancellation_token(),
    )

    assert isinstance(outcome, CompletedGeneration), outcome
    assert outcome.response_text.strip()
    assert set(outcome.provider_metadata) == {
        "provider",
        "provider_version",
        "model_identity",
        "model_tag",
        "cloud_disable_source",
        "done_reason",
        "total_duration_ns",
        "load_duration_ns",
        "prompt_eval_duration_ns",
        "eval_duration_ns",
    }
    assert outcome.provider_metadata["provider"] == "ollama"
    assert outcome.provider_metadata["model_identity"] == (
        live_ollama_adapter.request.model_name
    )
    assert outcome.provider_metadata["cloud_disable_source"] in {
        "env",
        "config",
        "both",
    }
