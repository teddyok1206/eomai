"""Structured logs for observability operations without payload disclosure."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "component": "eom_observe",
            "event": getattr(record, "event", None),
            "request_id": getattr(record, "request_id", None),
            "snapshot_id": getattr(record, "snapshot_id", None),
            "stream_client_id": getattr(record, "stream_client_id", None),
            "workflow_id": getattr(record, "workflow_id", None),
            "job_id": getattr(record, "job_id", None),
            "worker_role": getattr(record, "worker_role", None),
            "query_duration_ms": getattr(record, "query_duration_ms", None),
            "snapshot_duration_ms": getattr(record, "snapshot_duration_ms", None),
            "client_count": getattr(record, "client_count", None),
            "http_status": getattr(record, "http_status", None),
            "error_code": getattr(record, "error_code", None),
        }
        return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
