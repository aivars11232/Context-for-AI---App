"""Safe local logging bootstrap with a fixed redacted event shape."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any

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
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
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

    def event(
        self,
        event_name: str,
        *,
        stage: str = "ACCEPTANCE",
        level: int = logging.INFO,
        **fields: Any,
    ) -> None:
        """Record a safe event while silently excluding arbitrary content fields."""

        extra = {
            "event_name": event_name,
            "stage": stage,
            "configuration_fingerprint": self._configuration_fingerprint,
        }
        extra.update({field: fields.get(field) for field in _CORRELATION_FIELDS})
        self._logger.log(level, "structured event", extra=extra)


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
    trace_logger.event("logging_initialized")
    return trace_logger
