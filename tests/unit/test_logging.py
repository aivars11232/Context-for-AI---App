"""Logging bootstrap and redaction tests."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from context_for_ai.domain.enums import FailureCode, PipelineStage
from context_for_ai.domain.ports.system import TraceEvent
from context_for_ai.domain.value_objects import DomainId
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
    run_id = DomainId("10000000-0000-4000-8000-000000000001")
    event_time = datetime(2026, 8, 2, 12, tzinfo=UTC)
    trace_logger.emit(
        TraceEvent(
            timestamp=event_time,
            level="INFO",
            event_name="run_failed",
            stage=PipelineStage.TRANSPORT,
            configuration_fingerprint=configuration.configuration_fingerprint,
            processing_run_id=run_id,
            error_type=FailureCode.MODEL_TIMEOUT,
        )
    )
    logging.getLogger("context_for_ai").warning("authorization: another-secret")

    log_path = configuration.logging.directory / "context_for_ai.log"
    contents = log_path.read_text(encoding="utf-8")
    events = [json.loads(line) for line in contents.splitlines()]

    assert log_path.is_file()
    assert "another-secret" not in contents
    assert events[-2]["event_name"] == "run_failed"
    assert events[-2]["timestamp"] == "2026-08-02T12:00:00Z"
    assert events[-2]["level"] == "INFO"
    assert events[-2]["stage"] == "TRANSPORT"
    assert events[-2]["processing_run_id"] == str(run_id)
    assert events[-2]["error_type"] == "MODEL_TIMEOUT"
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


def test_trace_logger_rejects_a_mismatched_configuration_fingerprint(
    fixture_application_root: Path,
) -> None:
    configuration = load_configuration(application_root=fixture_application_root, environ={})
    trace_logger = bootstrap_logging(
        configuration.logging,
        configuration.configuration_fingerprint,
    )

    with pytest.raises(ValueError, match="fingerprint"):
        trace_logger.emit(
            TraceEvent(
                timestamp=datetime(2026, 8, 2, 12, tzinfo=UTC),
                level="INFO",
                event_name="run_accepted",
                stage=PipelineStage.ACCEPTANCE,
                configuration_fingerprint="different-fingerprint",
            )
        )
