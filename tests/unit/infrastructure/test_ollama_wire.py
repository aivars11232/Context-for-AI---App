"""Unit coverage for the private native-Ollama wire codec."""

from __future__ import annotations

from decimal import Decimal
import json

import pytest

from context_for_ai.domain.ports import GenerationRequest, GenerationSettings, TokenUsage
from context_for_ai.domain.value_objects import DomainId
from context_for_ai.infrastructure.ollama.wire import (
    OllamaWireError,
    encode_generate_request,
    encode_show_request,
    is_json_media_type,
    parse_generation_response,
    parse_show_response,
    parse_status_response,
    parse_version_response,
)


MODEL = "registry.example/team/model:Q4"
MEDIA_TYPE = "application/json; charset=utf-8"


def _request() -> GenerationRequest:
    return GenerationRequest(
        model_name=MODEL,
        rendered_prompt="  exact prompt\nwith μ and \"quotes\"  ",
        settings=GenerationSettings(
            context_window_tokens=8192,
            request_timeout_seconds=30,
            temperature=Decimal("0.12345678901234567890123456789"),
        ),
        processing_run_id=DomainId("12000000-0000-4000-8000-000000000001"),
        context_packet_id=DomainId("12000000-0000-4000-8000-000000000002"),
        model_request_id=DomainId("12000000-0000-4000-8000-000000000003"),
        attempt_number=0,
    )


def _body(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _generation(**overrides: object) -> bytes:
    value: dict[str, object] = {
        "model": MODEL,
        "response": "  exact answer\n",
        "done": True,
    }
    value.update(overrides)
    return _body(value)


def _parse_generation(body: bytes):
    return parse_generation_response(
        body,
        MEDIA_TYPE,
        model_identity=MODEL,
        provider_version="0.16.2",
        cloud_disable_source="both",
    )


def test_show_request_has_only_the_exact_semantic_fields() -> None:
    assert json.loads(encode_show_request(MODEL)) == {
        "model": MODEL,
        "verbose": False,
    }


def test_generation_request_preserves_prompt_and_exact_decimal_number() -> None:
    encoded = encode_generate_request(_request(), MODEL)

    assert json.loads(encoded, parse_float=Decimal) == {
        "model": MODEL,
        "prompt": "  exact prompt\nwith μ and \"quotes\"  ",
        "stream": False,
        "raw": True,
        "think": False,
        "truncate": False,
        "shift": False,
        "options": {
            "num_ctx": 8192,
            "temperature": Decimal("0.12345678901234567890123456789"),
        },
    }
    assert b'"temperature":0.12345678901234567890123456789' in encoded


@pytest.mark.parametrize(
    "media_type",
    (
        "application/json",
        "Application/JSON; Charset=UTF-8",
        "application/problem+json",
    ),
)
def test_json_media_types_accept_ordinary_parameters(media_type: str) -> None:
    assert is_json_media_type(media_type)


@pytest.mark.parametrize(
    "media_type",
    (None, "", "text/json", "text/plain", "application/xml"),
)
def test_non_json_media_types_are_rejected(media_type: str | None) -> None:
    assert not is_json_media_type(media_type)


def test_version_retains_the_exact_validated_string_and_ignores_unknown_fields() -> None:
    assert (
        parse_version_response(
            _body({"version": " v0.16.2 ", "ignored": {"secret": "discard"}}),
            MEDIA_TYPE,
        )
        == " v0.16.2 "
    )


@pytest.mark.parametrize(
    ("body", "media_type"),
    (
        (b"{}", MEDIA_TYPE),
        (_body({"version": "   "}), MEDIA_TYPE),
        (_body({"version": 16}), MEDIA_TYPE),
        (b'{"version":"1"} trailing', MEDIA_TYPE),
        (b'{"version":"1","version":"2"}', MEDIA_TYPE),
        (b'{"version":"1"}', "text/plain"),
        (b"[]", MEDIA_TYPE),
        (b"\xff", MEDIA_TYPE),
    ),
)
def test_version_rejects_incomplete_or_malformed_contracts(
    body: bytes,
    media_type: str,
) -> None:
    with pytest.raises(OllamaWireError):
        parse_version_response(body, media_type)


@pytest.mark.parametrize("source", ("env", "config", "both"))
def test_status_requires_the_exact_cloud_disabled_attestation(source: str) -> None:
    assert (
        parse_status_response(
            _body({"cloud": {"disabled": True, "source": source, "ignored": 1}}),
            MEDIA_TYPE,
        )
        == source
    )


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"cloud": None},
        {"cloud": {"disabled": False, "source": "env"}},
        {"cloud": {"disabled": 1, "source": "env"}},
        {"cloud": {"disabled": True, "source": "none"}},
        {"cloud": {"disabled": True}},
    ),
)
def test_status_fails_closed_for_every_other_attestation(
    payload: dict[str, object],
) -> None:
    with pytest.raises(OllamaWireError):
        parse_status_response(_body(payload), MEDIA_TYPE)


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"remote_model": None, "remote_host": ""},
        {"remote_model": "", "remote_host": None, "unknown": "ignored"},
    ),
)
def test_show_accepts_only_local_empty_remote_markers(
    payload: dict[str, object],
) -> None:
    assert not parse_show_response(_body(payload), MEDIA_TYPE).is_remote


def test_show_reports_a_nonempty_remote_marker_without_retaining_it() -> None:
    parsed = parse_show_response(
        _body({"remote_model": "secret-provider/model", "remote_host": 42}),
        MEDIA_TYPE,
    )

    assert parsed.is_remote
    assert not hasattr(parsed, "remote_model")
    assert not hasattr(parsed, "remote_host")


@pytest.mark.parametrize("value", (False, 0, [], {}, True))
def test_show_rejects_wrong_remote_marker_types(value: object) -> None:
    with pytest.raises(OllamaWireError):
        parse_show_response(_body({"remote_model": value}), MEDIA_TYPE)


def test_terminal_generation_projects_only_exact_allowlisted_values() -> None:
    parsed = _parse_generation(
        _generation(
            done_reason="stop",
            total_duration=100,
            load_duration=None,
            prompt_eval_duration=30,
            eval_duration=70,
            prompt_eval_count=12,
            eval_count=7,
            created_at="discarded",
            unknown={"provider_secret": "discarded"},
        )
    )

    assert parsed.response_text == "  exact answer\n"
    assert dict(parsed.provider_metadata) == {
        "provider": "ollama",
        "provider_version": "0.16.2",
        "model_identity": MODEL,
        "model_tag": "Q4",
        "cloud_disable_source": "both",
        "done_reason": "stop",
        "total_duration_ns": 100,
        "load_duration_ns": None,
        "prompt_eval_duration_ns": 30,
        "eval_duration_ns": 70,
    }
    assert parsed.token_usage == TokenUsage(12, 7, 19)


@pytest.mark.parametrize(
    ("counts", "expected"),
    (
        ({}, None),
        ({"prompt_eval_count": None, "eval_count": None}, None),
        ({"prompt_eval_count": 4}, TokenUsage(4, None, None)),
        ({"eval_count": 6}, TokenUsage(None, 6, None)),
    ),
)
def test_token_usage_is_normalized_independently(
    counts: dict[str, object],
    expected: TokenUsage | None,
) -> None:
    assert _parse_generation(_generation(**counts)).token_usage == expected


@pytest.mark.parametrize("done_reason", (_MISSING := object(), None, ""))
def test_empty_done_reason_normalizes_to_null(done_reason: object) -> None:
    additions = {} if done_reason is _MISSING else {"done_reason": done_reason}

    assert _parse_generation(_generation(**additions)).provider_metadata[
        "done_reason"
    ] is None


@pytest.mark.parametrize(
    "overrides",
    (
        {"model": "different:latest"},
        {"model": 7},
        {"response": "   \n"},
        {"response": 7},
        {"done": False},
        {"done": 1},
        {"remote_model": "remote"},
        {"remote_host": False},
        {"thinking": "reasoning"},
        {"tool_calls": [{}]},
        {"logprobs": {}},
        {"context": [1]},
        {"error": "provider detail"},
        {"image": "content"},
        {"_debug_info": {}},
        {"done_reason": 7},
        {"total_duration": -1},
        {"load_duration": True},
        {"prompt_eval_duration": 1.5},
        {"eval_duration": "1"},
        {"prompt_eval_count": -1},
        {"eval_count": False},
    ),
)
def test_terminal_generation_rejects_every_prohibited_or_malformed_field(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(OllamaWireError):
        _parse_generation(_generation(**overrides))


@pytest.mark.parametrize(
    "body",
    (
        b'{"model":"registry.example/team/model:Q4","response":"ok","done":true',
        b'{"model":"registry.example/team/model:Q4","response":"ok","done":true}{}',
        b'[{}]',
        b'{"done":true,"done":true}',
    ),
)
def test_terminal_generation_rejects_truncated_trailing_or_non_object_json(
    body: bytes,
) -> None:
    with pytest.raises(OllamaWireError):
        _parse_generation(body)


def test_terminal_model_normalizes_only_an_omitted_latest_tag() -> None:
    parsed = parse_generation_response(
        _body({"model": "fixture-model", "response": "ok", "done": True}),
        MEDIA_TYPE,
        model_identity="fixture-model:latest",
        provider_version="1",
        cloud_disable_source="env",
    )

    assert parsed.provider_metadata["model_identity"] == "fixture-model:latest"
