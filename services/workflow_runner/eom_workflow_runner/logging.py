"""Structured logging fields for workflow execution."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

WORKFLOW_LOG_FIELDS = (
    "workflow_id",
    "workflow_definition",
    "workflow_state",
    "step_key",
    "step_run_id",
    "attempt",
    "job_id",
    "worker_slot",
    "command_id",
    "approval_request_id",
    "actor_type",
    "actor_id",
    "error_code",
)


class WorkflowJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "event": getattr(record, "event", None),
            "message": record.getMessage(),
        }
        payload.update({field: getattr(record, field, None) for field in WORKFLOW_LOG_FIELDS})
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_workflow_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(WorkflowJsonFormatter())
    logger = logging.getLogger("eom.workflow")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def log_workflow_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    event: str,
    **fields: object,
) -> None:
    allowed = {key: value for key, value in fields.items() if key in WORKFLOW_LOG_FIELDS}
    logger.log(level, message, extra={"component": "workflow_runner", "event": event, **allowed})
