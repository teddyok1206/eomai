"""Metadata-only administrator commands for Orchestrator-owned preset validation."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from eom_identifiers import content_sha256, new_job_id
from eom_workflow import validate_control_contract
from eom_workflow.preset_model_validation import PresetModelValidationRequest
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ExecutionPresetValidationRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import JobRecord
from eom_orchestrator.preset_model_selection import require_model_only_successor, validated_preset
from eom_orchestrator.preset_policy import execution_preset_policy_sha256

TASK_TYPE = "preset_model_validation"
REQUEST_SCHEMA = "preset-model-validation-request"
PROTOCOL = "preset-model-validation/1.0"


def validated_request(row: ExecutionPresetValidationRecord) -> PresetModelValidationRequest:
    try:
        validate_control_contract(REQUEST_SCHEMA, row.canonical_request)
        request = PresetModelValidationRequest.model_validate(row.canonical_request)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_VALIDATION_REQUEST_INVALID", "invalid validation request"
        ) from exc
    if (
        content_sha256(row.canonical_request) != row.request_sha256
        or request.preset_revision_id != row.preset_revision_id
        or request.base_revision_id != row.base_revision_id
        or request.requested_by != row.requested_by
        or request.requested_at != row.requested_at
    ):
        raise ControlPlaneError(
            "CONTROL_VALIDATION_REQUEST_INVALID", "request identity or hash differs"
        )
    return request


def pinned_validation_revisions(
    session: Session, *, draft_revision_id: str, base_revision_id: str
) -> tuple[ExecutionPresetRevisionRecord, ExecutionPresetRevisionRecord]:
    draft = session.get(ExecutionPresetRevisionRecord, draft_revision_id)
    base = session.get(ExecutionPresetRevisionRecord, base_revision_id)
    logical = session.get(ExecutionPresetRecord, draft.preset_id) if draft is not None else None
    if (
        draft is None
        or base is None
        or logical is None
        or logical.state != "ACTIVE"
        or draft.state != "DRAFT"
        or base.state != "RELEASED"
        or base.preset_id != draft.preset_id
        or logical.current_revision_id != base.preset_revision_id
    ):
        raise ControlPlaneError("CONTROL_PRESET_BASE_STALE", "exact current baseline is required")
    require_model_only_successor(validated_preset(base), validated_preset(draft))
    return draft, base


def enqueue_preset_model_validation(
    session: Session,
    *,
    draft_revision_id: str,
    base_revision_id: str,
    expected_version: int,
    requested_by: str,
    request_key: str,
    requested_at: datetime,
) -> ExecutionPresetValidationRecord:
    """Serialize one metadata intent; only the Orchestrator can create its Job."""

    semantic_key = "preset-model-validation:" + content_sha256(
        {"actor": requested_by, "key": request_key}
    ).removeprefix("sha256:")
    lock_key = int.from_bytes(hashlib.sha256(semantic_key.encode()).digest()[:8], signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    existing = session.scalar(
        select(ExecutionPresetValidationRecord).where(
            ExecutionPresetValidationRecord.idempotency_key == semantic_key
        )
    )
    if existing is not None:
        request = validated_request(existing)
        draft = session.get(ExecutionPresetRevisionRecord, request.preset_revision_id)
        if (
            request.preset_revision_id != draft_revision_id
            or request.base_revision_id != base_revision_id
            or request.requested_by != requested_by
            or draft is None
            or draft.revision_number != expected_version
        ):
            raise ControlPlaneError(
                "CONTROL_VALIDATION_REPLAY_CONFLICT", "validation replay differs"
            )
        return existing
    draft, base = pinned_validation_revisions(
        session, draft_revision_id=draft_revision_id, base_revision_id=base_revision_id
    )
    if draft.revision_number != expected_version:
        raise ControlPlaneError("CONTROL_PRESET_VERSION_STALE", "draft revision version differs")
    request_document = PresetModelValidationRequest(
        preset_revision_id=draft.preset_revision_id,
        preset_content_sha256=draft.content_sha256,
        preset_policy_sha256=execution_preset_policy_sha256(draft.canonical_document),
        base_revision_id=base.preset_revision_id,
        base_content_sha256=base.content_sha256,
        requested_by=requested_by,
        requested_at=requested_at,
    ).model_dump(mode="json")
    validate_control_contract(REQUEST_SCHEMA, request_document)
    command = ExecutionPresetValidationRecord(
        validation_id=new_job_id(),
        preset_revision_id=draft_revision_id,
        base_revision_id=base_revision_id,
        requested_by=requested_by,
        idempotency_key=semantic_key,
        request_sha256=content_sha256(request_document),
        canonical_request=request_document,
        state="PENDING",
        requested_at=requested_at,
        completed_at=None,
        error_code=None,
    )
    session.add(command)
    session.flush()
    return command


def validation_status(session: Session, validation_id: str) -> dict[str, Any]:
    command = session.get(ExecutionPresetValidationRecord, validation_id)
    if command is None:
        raise ControlPlaneError("CONTROL_VALIDATION_MISSING", "validation is missing")
    request = validated_request(command)
    job = session.get(JobRecord, validation_id)
    evaluation = None
    if command.state == "SUCCEEDED":
        if (
            job is None
            or job.status != "SUCCEEDED"
            or job.task_type != TASK_TYPE
            or job.protocol_version != PROTOCOL
        ):
            raise ControlPlaneError("CONTROL_VALIDATION_EVIDENCE_MISMATCH", "accepted job differs")
        evaluation = session.scalar(
            select(ExecutionPresetEvaluationRecord).where(
                ExecutionPresetEvaluationRecord.report_artifact_revision_id == job.revision_id,
                ExecutionPresetEvaluationRecord.evaluated_preset_revision_id
                == request.preset_revision_id,
                ExecutionPresetEvaluationRecord.evaluated_policy_sha256
                == request.preset_policy_sha256,
                ExecutionPresetEvaluationRecord.outcome == "PASS",
                ExecutionPresetEvaluationRecord.scope == "NON_LIVE",
            )
        )
        if evaluation is None:
            raise ControlPlaneError(
                "CONTROL_VALIDATION_EVIDENCE_MISMATCH", "accepted evidence missing"
            )
    return {
        "validation_id": command.validation_id,
        "preset_revision_id": request.preset_revision_id,
        "base_revision_id": request.base_revision_id,
        "preset_policy_sha256": request.preset_policy_sha256,
        "status": {
            "PENDING": "QUEUED",
            "PROCESSING": "RUNNING",
            "SUCCEEDED": "SUCCEEDED",
            "FAILED": "FAILED",
        }[command.state],
        "scope": "NON_LIVE",
        "quality_evaluated": False,
        "error_code": command.error_code if command.state == "FAILED" else None,
        "evaluation_id": evaluation.evaluation_id if evaluation is not None else None,
        "cases_total": evaluation.cases_total if evaluation is not None else 0,
        "cases_passed": evaluation.cases_passed if evaluation is not None else 0,
        "completed_at": command.completed_at,
    }
