"""Logging bootstrap and redaction tests."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from context_for_ai.infrastructure.configuration import load_configuration
from context_for_ai.infrastructure.logging import bootstrap_logging


def test_logging_bootstrap_uses_redacted_structured_events(
    fixture_application_root: Path,
) -> None:
    configuration = load_configuration(application_root=fixture_application_root, environ={})
    trace_logger = bootstrap_logging(
        configuration.logging,
        configuration.configuration_fingerprint,
    )
    trace_logger.event(
        "redaction_check",
        stage="ACCEPTANCE",
        processing_run_id="run-123",
        api_key="secret-api-key",
        original_message="private user message",
        rendered_prompt="private prompt",
        model_response="private response",
    )
    logging.getLogger("context_for_ai").warning("authorization: another-secret")

    log_path = configuration.logging.directory / "context_for_ai.log"
    contents = log_path.read_text(encoding="utf-8")
    events = [json.loads(line) for line in contents.splitlines()]

    assert log_path.is_file()
    assert "secret-api-key" not in contents
    assert "private user message" not in contents
    assert "private prompt" not in contents
    assert "private response" not in contents
    assert "another-secret" not in contents
    assert events[-2]["event_name"] == "redaction_check"
    assert events[-2]["processing_run_id"] == "run-123"
    assert events[-1]["event_name"] == "logging_event"
    assert set(events[-1]) == {
        "timestamp",
        "level",
        "event_name",
        "stage",
        "configuration_fingerprint",
        "conversation_id",
        "user_message_id",
        "processing_run_id",
        "context_packet_id",
        "model_request_id",
        "model_response_id",
        "validation_result_id",
        "clarification_request_id",
        "memory_id",
        "memory_revision_id",
        "correction_attempt_number",
        "error_type",
    }
