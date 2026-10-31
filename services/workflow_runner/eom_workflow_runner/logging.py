"""Structured logging fields for workflow execution."""

from __future__ import annotations

import json
import logging
import re
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
    "cause_type",
    "cause_code",
    "cause_site",
    "cause_sqlstate",
)


def workflow_failure_metadata(error: BaseException) -> dict[str, str]:
    """Bounded technical cause only; never exception text, locals, SQL or payloads."""
    current = error
    seen = {id(current)}
    for _ in range(4):
        related = current.__cause__ or current.__context__
        if related is None or id(related) in seen:
            break
        seen.add(id(related))
        current = related
    result: dict[str, str] = {}
    name = type(current).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,95}", name):
        result["cause_type"] = name
    for attribute, key, pattern in (
        ("code", "cause_code", r"[A-Z][A-Z0-9_]{1,95}"),
        ("sqlstate", "cause_sqlstate", r"[A-Z0-9]{5}"),
    ):
        try:
            value = getattr(current, attribute, None)
        except Exception:
            # Diagnostics must not replace the original failure if a future
            # exception type implements an unavailable diagnostic property.
            continue
        if isinstance(value, str) and re.fullmatch(pattern, value):
            result[key] = value
    frame = current.__traceback__
    for _ in range(64):
        if frame is None:
            break
        module = frame.tb_frame.f_globals.get("__name__")
        if isinstance(module, str) and re.fullmatch(r"eom_[a-z0-9_.]{1,120}", module):
            result["cause_site"] = f"{module}:{frame.tb_lineno}"
        frame = frame.tb_next
    return result


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
