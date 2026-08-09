"""Safe local logging bootstrap with a fixed redacted event shape."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any

from context_for_ai.domain.enums import PipelineStage
from context_for_ai.domain.ports.system import TraceEvent
from context_for_ai.infrastructure.configuration.loader import LoggingSettings


_CORRELATION_FIELDS = (
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
)


class RedactedJsonFormatter(logging.Formatter):
    """Render only the documented safe trace metadata, never a log message."""

    def format(self, record: logging.LogRecord) -> str:
        event_timestamp = getattr(record, "trace_timestamp", None)
        payload: dict[str, Any] = {
            "timestamp": (
                datetime.fromtimestamp(record.created, UTC)
                if event_timestamp is None
                else event_timestamp
            )
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "event_name": getattr(record, "event_name", "logging_event"),
            "stage": getattr(record, "stage", "ACCEPTANCE"),
            "configuration_fingerprint": getattr(
                record, "configuration_fingerprint", None
            ),
        }
        payload.update(
            {field: getattr(record, field, None) for field in _CORRELATION_FIELDS}
        )
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class TraceLogger:
    """Emit only allow-listed structured metadata to the local log."""

    def __init__(self, logger: logging.Logger, configuration_fingerprint: str) -> None:
        self._logger = logger
        self._configuration_fingerprint = configuration_fingerprint

    def emit(self, event: TraceEvent) -> None:
        """Record exactly one typed, pre-redacted trace event."""

        if event.configuration_fingerprint != self._configuration_fingerprint:
            raise ValueError(
                "Trace event configuration fingerprint does not match this logger."
            )
        extra = {
            "trace_timestamp": event.timestamp,
            "event_name": event.event_name,
            "stage": event.stage.value,
            "configuration_fingerprint": event.configuration_fingerprint,
        }
        extra.update(
            {
                field: (
                    None
                    if (value := getattr(event, field)) is None
                    else value.value
                    if field == "error_type"
                    else value
                    if field == "correction_attempt_number"
                    else str(value)
                )
                for field in _CORRELATION_FIELDS
            }
        )
        self._logger.log(
            logging.getLevelNamesMapping()[event.level],
            "structured event",
            extra=extra,
        )


def bootstrap_logging(
    settings: LoggingSettings, configuration_fingerprint: str
) -> TraceLogger:
    """Initialize the local redacted log destination from validated settings."""

    if settings.include_content:
        raise ValueError("Logging settings must disable content logging")
    settings.directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("context_for_ai")
    logger.setLevel(getattr(logging, settings.level))
    logger.propagate = False
    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    log_path = Path(settings.directory) / "context_for_ai.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(getattr(logging, settings.level))
    handler.setFormatter(RedactedJsonFormatter())
    logger.addHandler(handler)

    trace_logger = TraceLogger(logger, configuration_fingerprint)
    trace_logger.emit(
        TraceEvent(
            timestamp=datetime.now(UTC),
            level="INFO",
            event_name="logging_initialized",
            stage=PipelineStage.ACCEPTANCE,
            configuration_fingerprint=configuration_fingerprint,
        )
    )
    return trace_logger
