"""Durable, credential-free Codex control-command queue transactions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal

from eom_identifiers import canonical_json_bytes, new_codex_control_command_id
from eom_identity_service.models import OperatorRecord
from eom_workflow import (
    CodexControlCommand,
    CodexControlCommandResult,
    CodexControlCommandResultV2,
    CodexUsageObservation,
    validate_control_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import CodexAuthBindingRecord, CodexControlCommandRecord
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,95}$", re.ASCII)
MAX_COMMAND_ATTEMPTS = 3
MAX_RESULT_BYTES = 64 * 1024


def build_codex_control_command(
    *,
    command_type: Literal["OBSERVE", "ENABLE", "DRAIN", "DISABLE"],
    binding_id: str,
    expected_resource_version: int,
    requested_by_operator_id: str,
    requested_at: datetime,
    reason_code: str | None,
) -> dict[str, object]:
    """Construct one self-hashed command without accepting execution internals."""

    document: dict[str, object] = {
        "schema_version": "codex-control-command/1.0",
        "command_id": new_codex_control_command_id(),
        "command_type": command_type,
        "binding_id": binding_id,
        "expected_resource_version": expected_resource_version,
        "requested_by_operator_id": requested_by_operator_id,
        "requested_at": requested_at,
        "reason_code": reason_code,
        "request_sha256": "sha256:" + "0" * 64,
    }
    normalized = CodexControlCommand.model_validate(document).model_dump(mode="json")
    normalized["request_sha256"] = compute_control_document_hash(normalized, "request_sha256")
    return normalized


def enqueue_codex_control_command(
    session: Session,
    *,
    document: dict[str, object],
    idempotency_key: str,
) -> CodexControlCommandRecord:
    """Persist one idempotent command after exact operator/binding preconditions."""

    if IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None:
        raise ControlPlaneError(
            "CONTROL_IDEMPOTENCY_KEY_INVALID", "control command idempotency key is invalid"
        )
    try:
        validate_control_contract("codex-control-command", document)
        command = CodexControlCommand.model_validate(document)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CONTROL_COMMAND_INVALID", "Codex control command is invalid"
        ) from exc
    normalized = command.model_dump(mode="json")
    if command.request_sha256 != compute_control_document_hash(normalized, "request_sha256"):
        raise ControlPlaneError(
            "CONTROL_COMMAND_HASH_MISMATCH", "Codex control command hash differs"
        )
    existing = session.scalar(
        select(CodexControlCommandRecord).where(
            CodexControlCommandRecord.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.request_sha256 != command.request_sha256
            or existing.canonical_document != normalized
        ):
            raise ControlPlaneError(
                "CONTROL_IDEMPOTENCY_CONFLICT",
                "idempotency key is bound to another control command",
            )
        return existing
    binding = session.get(CodexAuthBindingRecord, command.binding_id, with_for_update=True)
    if binding is None:
        raise ControlPlaneError("CONTROL_AUTH_BINDING_MISSING", "auth binding is missing")
    if binding.resource_version != command.expected_resource_version:
        raise ControlPlaneError("CONTROL_RESOURCE_VERSION_CONFLICT", "auth binding version changed")
    operator = session.get(OperatorRecord, command.requested_by_operator_id)
    if operator is None or operator.status != "ACTIVE":
        raise ControlPlaneError("CONTROL_OPERATOR_INVALID", "requesting operator is unavailable")
    record = CodexControlCommandRecord(
        command_id=command.command_id,
        command_type=command.command_type,
        binding_id=command.binding_id,
        expected_resource_version=command.expected_resource_version,
        requested_by_operator_id=command.requested_by_operator_id,
        idempotency_key=idempotency_key,
        request_sha256=command.request_sha256,
        canonical_document=normalized,
        state="PENDING",
        attempts=0,
        lease_owner=None,
        lease_expires_at=None,
        result_resource_version=None,
        result_document=None,
        error_code=None,
        requested_at=command.requested_at,
        processed_at=None,
    )
    session.add(record)
    session.flush()
    return record


def claim_next_codex_control_command(
    session: Session,
    *,
    lease_owner: str,
    claimed_at: datetime,
    lease_ttl: timedelta,
) -> CodexControlCommandRecord | None:
    """Claim one FIFO command, reclaiming only expired nonterminal attempts."""

    if not lease_owner or len(lease_owner) > 128:
        raise ValueError("control command lease owner is invalid")
    if claimed_at.tzinfo is None or claimed_at.utcoffset() != timedelta(0):
        raise ValueError("control command claim time must use UTC")
    if not timedelta(seconds=15) <= lease_ttl <= timedelta(minutes=5):
        raise ValueError("control command lease TTL is outside the reviewed bound")

    exhausted = tuple(
        session.scalars(
            select(CodexControlCommandRecord)
            .where(
                CodexControlCommandRecord.state == "PROCESSING",
                CodexControlCommandRecord.attempts >= MAX_COMMAND_ATTEMPTS,
                CodexControlCommandRecord.lease_expires_at <= claimed_at,
            )
            .order_by(
                CodexControlCommandRecord.requested_at,
                CodexControlCommandRecord.command_id,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for record in exhausted:
        _terminalize_record(
            record,
            outcome="FAILED",
            result_resource_version=None,
            binding_state=None,
            reason_code="CONTROL_COMMAND_ATTEMPTS_EXHAUSTED",
            processed_at=claimed_at,
        )

    candidate = session.scalar(
        select(CodexControlCommandRecord)
        .where(
            CodexControlCommandRecord.attempts < MAX_COMMAND_ATTEMPTS,
            or_(
                CodexControlCommandRecord.state == "PENDING",
                and_(
                    CodexControlCommandRecord.state == "PROCESSING",
                    CodexControlCommandRecord.lease_expires_at <= claimed_at,
                ),
            ),
        )
        .order_by(
            CodexControlCommandRecord.requested_at,
            CodexControlCommandRecord.command_id,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if candidate is None:
        session.flush()
        return None
    candidate.state = "PROCESSING"
    candidate.attempts += 1
    candidate.lease_owner = lease_owner
    candidate.lease_expires_at = claimed_at + lease_ttl
    candidate.result_resource_version = None
    candidate.result_document = None
    candidate.error_code = None
    candidate.processed_at = None
    session.flush()
    return candidate


def terminalize_codex_control_command(
    session: Session,
    *,
    command_id: str,
    lease_owner: str,
    outcome: Literal["SUCCEEDED", "FAILED"],
    result_resource_version: int | None,
    binding_state: str | None,
    reason_code: str | None,
    processed_at: datetime,
    usage_observation: CodexUsageObservation | None = None,
) -> CodexControlCommandRecord:
    """Commit one schema-valid terminal result for the exact active claim owner."""

    record = session.execute(
        select(CodexControlCommandRecord)
        .where(CodexControlCommandRecord.command_id == command_id)
        .with_for_update()
    ).scalar_one_or_none()
    if record is None:
        raise ControlPlaneError("CONTROL_COMMAND_MISSING", "control command is missing")
    if record.state in {"SUCCEEDED", "FAILED"}:
        return record
    if record.state != "PROCESSING" or record.lease_owner != lease_owner:
        raise ControlPlaneError(
            "CONTROL_COMMAND_LEASE_LOST", "control command is not owned by this processor"
        )
    _terminalize_record(
        record,
        outcome=outcome,
        result_resource_version=result_resource_version,
        binding_state=binding_state,
        reason_code=reason_code,
        processed_at=processed_at,
        usage_observation=usage_observation,
    )
    session.flush()
    return record


def _terminalize_record(
    record: CodexControlCommandRecord,
    *,
    outcome: Literal["SUCCEEDED", "FAILED"],
    result_resource_version: int | None,
    binding_state: str | None,
    reason_code: str | None,
    processed_at: datetime,
    usage_observation: CodexUsageObservation | None = None,
) -> None:
    result: dict[str, object] = {
        "schema_version": (
            "codex-control-command-result/1.1"
            if usage_observation is not None
            else "codex-control-command-result/1.0"
        ),
        "command_id": record.command_id,
        "command_type": record.command_type,
        "binding_id": record.binding_id,
        "outcome": outcome,
        "result_resource_version": result_resource_version,
        "binding_state": binding_state,
        "reason_code": reason_code,
        "processed_at": processed_at,
        "result_sha256": "sha256:" + "0" * 64,
    }
    if usage_observation is not None:
        result["usage_observation"] = usage_observation.model_dump(mode="json")
    result_type = (
        CodexControlCommandResultV2 if usage_observation is not None else CodexControlCommandResult
    )
    schema_name = (
        "codex-control-command-result-v2"
        if usage_observation is not None
        else "codex-control-command-result"
    )
    normalized = result_type.model_validate(result).model_dump(mode="json")
    normalized["result_sha256"] = compute_control_document_hash(normalized, "result_sha256")
    try:
        validate_control_contract(schema_name, normalized)
    except JsonSchemaValidationError as exc:
        raise ControlPlaneError(
            "CONTROL_COMMAND_RESULT_INVALID", "control command result is invalid"
        ) from exc
    if len(canonical_json_bytes(normalized)) > MAX_RESULT_BYTES:
        raise ControlPlaneError(
            "CONTROL_COMMAND_RESULT_TOO_LARGE", "control command result exceeds size limit"
        )
    record.state = outcome
    record.lease_owner = None
    record.lease_expires_at = None
    record.result_resource_version = result_resource_version
    record.result_document = normalized
    record.error_code = reason_code
    record.processed_at = processed_at
