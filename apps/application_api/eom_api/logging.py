"""Structured JSON logging without request payloads or credentials."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "component": "eom_api",
            "event": getattr(record, "event", record.getMessage()),
        }
        for key in (
            "request_id",
            "operation_id",
            "operator_id",
            "session_id",
            "route_template",
            "http_method",
            "http_status",
            "permission",
            "target_type",
            "target_id",
            "duration_ms",
            "error_code",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("eom_api")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
