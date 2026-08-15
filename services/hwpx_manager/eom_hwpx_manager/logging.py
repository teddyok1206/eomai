"""Structured HWPX integration logging without document content or secrets."""

from __future__ import annotations

import logging
from typing import Any


def log_hwpx_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    build_id: str | None = None,
    template_id: str | None = None,
    template_revision_id: str | None = None,
    input_sha256: str | None = None,
    output_sha256: str | None = None,
    artifact_id: str | None = None,
    artifact_revision_id: str | None = None,
    validation_type: str | None = None,
    validation_status: str | None = None,
    error_code: str | None = None,
    **extra: Any,
) -> None:
    logger.log(
        level,
        event,
        extra={
            "component": "hwpx_manager",
            "event": event,
            "build_id": build_id,
            "template_id": template_id,
            "template_revision_id": template_revision_id,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "artifact_id": artifact_id,
            "artifact_revision_id": artifact_revision_id,
            "validation_type": validation_type,
            "validation_status": validation_status,
            "error_code": error_code,
            **extra,
        },
    )
