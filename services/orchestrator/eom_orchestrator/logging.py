"""Structured JSON logging with stable operational fields."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "job_id": getattr(record, "job_id", None),
            "worker_slot": getattr(record, "worker_slot", None),
            "component": getattr(record, "component", record.name),
            "event": getattr(record, "event", None),
            "error_code": getattr(record, "error_code", None),
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    job_id: str | None,
    worker_slot: str | None,
    component: str,
    event: str,
    error_code: str | None = None,
) -> None:
    logger.log(
        level,
        message,
        extra={
            "job_id": job_id,
            "worker_slot": worker_slot,
            "component": component,
            "event": event,
            "error_code": error_code,
        },
    )
