"""Credential-free Codex device-auth enrollment transactions and state machine."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    new_codex_auth_assignment_revision_id,
    new_codex_auth_enrollment_id,
)
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_workflow import (
    CodexAuthEnrollmentRequest,
    CodexAuthEnrollmentStatus,
    validate_control_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from eom_orchestrator.control_models import (
    CodexAuthAssignmentRevisionRecord,
    CodexAuthBindingRecord,
    CodexAuthEnrollmentRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{15,95}$", re.ASCII)
ACTIVE_STATES = (
    "REQUESTED",
    "DRAINING",
    "READY_FOR_LOGIN",
    "WAITING_FOR_USER",
    "VERIFYING",
)
TERMINAL_STATES = ("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")
ENROLLMENT_TTL = timedelta(minutes=15)
PROCESSOR_LEASE_TTL = timedelta(seconds=30)
POLL_INTERVAL = timedelta(seconds=2)
MAX_DOCUMENT_BYTES = 16 * 1024

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "REQUESTED": frozenset({"DRAINING", "FAILED", "EXPIRED"}),
    "DRAINING": frozenset({"READY_FOR_LOGIN", "FAILED", "EXPIRED"}),
    "READY_FOR_LOGIN": frozenset({"WAITING_FOR_USER", "VERIFYING", "FAILED", "EXPIRED"}),
    "WAITING_FOR_USER": frozenset({"VERIFYING", "FAILED", "EXPIRED"}),
    "VERIFYING": frozenset({"SUCCEEDED", "FAILED", "EXPIRED"}),
}


def build_codex_auth_enrollment_request(
    *,
    binding_id: str,
    expected_binding_resource_version: int,
    slot_key: str,
    requested_account_label: str,
    requested_by_operator_id: str,
    requested_by_api_session_id: str,
    requested_at: datetime,
) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "codex-auth-enrollment-request/1.0",
        "enrollment_id": new_codex_auth_enrollment_id(),
        "binding_id": binding_id,
        "expected_binding_resource_version": expected_binding_resource_version,
        "slot_key": slot_key,
        "requested_account_label": requested_account_label,
        "requested_by_operator_id": requested_by_operator_id,
        "requested_by_api_session_id": requested_by_api_session_id,
        "requested_at": requested_at,
        "expires_at": requested_at + ENROLLMENT_TTL,
        "request_sha256": "sha256:" + "0" * 64,
    }
    normalized = CodexAuthEnrollmentRequest.model_validate(document).model_dump(mode="json")
    normalized["request_sha256"] = compute_control_document_hash(normalized, "request_sha256")
    return normalized


def create_codex_auth_enrollment(
    session: Session,
    *,
    document: dict[str, object],
    idempotency_key: str,
) -> CodexAuthEnrollmentRecord:
    if IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None:
        raise ControlPlaneError(
            "CODEX_AUTH_IDEMPOTENCY_KEY_INVALID", "auth enrollment idempotency key is invalid"
        )
    try:
        validate_control_contract("codex-auth-enrollment-request", document)
        request = CodexAuthEnrollmentRequest.model_validate(document)
    except (JsonSchemaValidationError, PydanticValidationError, ValueError) as exc:
        raise ControlPlaneError(
            "CODEX_AUTH_ENROLLMENT_INVALID", "Codex auth enrollment request is invalid"
        ) from exc
    normalized = request.model_dump(mode="json")
    if request.request_sha256 != compute_control_document_hash(normalized, "request_sha256"):
        raise ControlPlaneError(
            "CODEX_AUTH_ENROLLMENT_HASH_MISMATCH", "auth enrollment request hash differs"
        )
    if len(canonical_json_bytes(normalized)) > MAX_DOCUMENT_BYTES:
        raise ControlPlaneError(
            "CODEX_AUTH_ENROLLMENT_INVALID", "auth enrollment request exceeds its fixed bound"
        )
    existing = session.scalar(
        select(CodexAuthEnrollmentRecord).where(
            CodexAuthEnrollmentRecord.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.binding_id != request.binding_id
            or existing.expected_binding_resource_version
            != request.expected_binding_resource_version
            or existing.requested_account_label != request.requested_account_label
            or existing.requested_by_operator_id != request.requested_by_operator_id
            or existing.requested_by_api_session_id != request.requested_by_api_session_id
        ):
            raise ControlPlaneError(
                "CODEX_AUTH_IDEMPOTENCY_CONFLICT",
                "idempotency key belongs to another auth enrollment",
            )
        return existing
    binding = session.get(CodexAuthBindingRecord, request.binding_id, with_for_update=True)
    if binding is None or f"slot{binding.worker_slot_id}" != request.slot_key:
        raise ControlPlaneError("CONTROL_AUTH_BINDING_MISSING", "auth binding is missing")
    if binding.resource_version != request.expected_binding_resource_version:
        raise ControlPlaneError("CONTROL_RESOURCE_VERSION_CONFLICT", "auth binding version changed")
    active = session.scalar(
        select(CodexAuthEnrollmentRecord.enrollment_id).where(
            CodexAuthEnrollmentRecord.binding_id == request.binding_id,
            CodexAuthEnrollmentRecord.state.in_(ACTIVE_STATES),
        )
    )
    if active is not None:
        raise ControlPlaneError(
            "CODEX_AUTH_ENROLLMENT_ALREADY_ACTIVE", "binding already has an active enrollment"
        )
    if held_lease_exists(session, binding_id=request.binding_id):
        raise ControlPlaneError(
            "CODEX_AUTH_SLOT_BUSY",
            "auth enrollment requires an idle worker slot",
        )
    operator = session.get(OperatorRecord, request.requested_by_operator_id)
    api_session = session.get(ApiSessionRecord, request.requested_by_api_session_id)
    if operator is None or operator.status != "ACTIVE":
        raise ControlPlaneError("CONTROL_OPERATOR_INVALID", "requesting operator is unavailable")
    if (
        api_session is None
        or api_session.operator_id != operator.operator_id
        or api_session.revoked_at is not None
        or api_session.absolute_expires_at <= request.requested_at
        or api_session.idle_expires_at <= request.requested_at
    ):
        raise ControlPlaneError(
            "CODEX_AUTH_SESSION_INVALID", "requesting API session is unavailable"
        )
    record = CodexAuthEnrollmentRecord(
        enrollment_id=request.enrollment_id,
        binding_id=request.binding_id,
        expected_binding_resource_version=request.expected_binding_resource_version,
        requested_account_label=request.requested_account_label,
        requested_by_operator_id=request.requested_by_operator_id,
        requested_by_api_session_id=request.requested_by_api_session_id,
        idempotency_key=idempotency_key,
        request_sha256=request.request_sha256,
        canonical_document=normalized,
        state="REQUESTED",
        lease_owner=None,
        lease_expires_at=None,
        next_action_at=request.requested_at,
        challenge_revealed_at=None,
        login_unit_started_at=None,
        assignment_revision_id=None,
        error_code=None,
        requested_at=request.requested_at,
        started_at=None,
        expires_at=request.expires_at,
        completed_at=None,
        resource_version=1,
    )
    session.add(record)
    session.flush()
    return record


def mark_codex_device_login_started(
    session: Session,
    *,
    enrollment_id: str,
    lease_owner: str,
    started_at: datetime,
) -> bool:
    """Persist the single launch boundary before invoking systemd.

    A false result means this enrollment already crossed the boundary. The
    caller must observe the existing fixed unit/handoff and must never launch
    it again.
    """

    record = session.get(CodexAuthEnrollmentRecord, enrollment_id, with_for_update=True)
    if record is None or record.state != "READY_FOR_LOGIN":
        raise ControlPlaneError(
            "CODEX_AUTH_ENROLLMENT_STATE_CHANGED", "auth enrollment state changed"
        )
    if record.lease_owner != lease_owner or record.lease_expires_at is None:
        raise ControlPlaneError("CODEX_AUTH_ENROLLMENT_LEASE_LOST", "auth enrollment lease is lost")
    if record.login_unit_started_at is not None:
        return False
    if started_at < record.requested_at or started_at >= record.expires_at:
        raise ControlPlaneError(
            "CODEX_AUTH_ENROLLMENT_EXPIRED", "auth enrollment cannot start device login"
        )
    record.login_unit_started_at = started_at
    record.resource_version += 1
    session.flush()
    return True


def claim_due_codex_auth_enrollment(
    session: Session,
    *,
    lease_owner: str,
    claimed_at: datetime,
) -> CodexAuthEnrollmentRecord | None:
    if not lease_owner or len(lease_owner) > 128:
        raise ValueError("auth enrollment lease owner is invalid")
    candidate = session.scalar(
        select(CodexAuthEnrollmentRecord)
        .where(
            CodexAuthEnrollmentRecord.state.in_(ACTIVE_STATES),
            CodexAuthEnrollmentRecord.next_action_at <= claimed_at,
            or_(
                CodexAuthEnrollmentRecord.lease_owner.is_(None),
                CodexAuthEnrollmentRecord.lease_expires_at <= claimed_at,
            ),
        )
        .order_by(
            CodexAuthEnrollmentRecord.next_action_at,
            CodexAuthEnrollmentRecord.requested_at,
            CodexAuthEnrollmentRecord.enrollment_id,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if candidate is None:
        return None
    candidate.lease_owner = lease_owner
    candidate.lease_expires_at = claimed_at + PROCESSOR_LEASE_TTL
    session.flush()
    return candidate


def transition_codex_auth_enrollment(
    session: Session,
    *,
    enrollment_id: str,
    lease_owner: str,
    target_state: str,
    transitioned_at: datetime,
    error_code: str | None = None,
    assignment_revision_id: str | None = None,
    next_action_at: datetime | None = None,
) -> CodexAuthEnrollmentRecord:
    record = session.get(CodexAuthEnrollmentRecord, enrollment_id, with_for_update=True)
    if record is None:
        raise ControlPlaneError("CODEX_AUTH_ENROLLMENT_MISSING", "auth enrollment is missing")
    if record.lease_owner != lease_owner or record.lease_expires_at is None:
        raise ControlPlaneError("CODEX_AUTH_ENROLLMENT_LEASE_LOST", "auth enrollment lease is lost")
    if target_state not in ALLOWED_TRANSITIONS.get(record.state, frozenset()):
        raise ControlPlaneError(
            "CODEX_AUTH_ENROLLMENT_TRANSITION_INVALID", "auth enrollment transition is invalid"
        )
    terminal = target_state in TERMINAL_STATES
    failed = target_state in {"FAILED", "CANCELLED", "EXPIRED"}
    if failed != (error_code is not None):
        raise ValueError("failed auth enrollment transition requires a reason")
    if (target_state == "SUCCEEDED") != (assignment_revision_id is not None):
        raise ValueError("successful auth enrollment transition requires an assignment")
    if terminal != (next_action_at is None):
        raise ValueError("terminal auth enrollment transition cannot have another action")
    record.state = target_state
    record.error_code = error_code
    record.assignment_revision_id = assignment_revision_id
    record.next_action_at = next_action_at
    record.completed_at = transitioned_at if terminal else None
    record.started_at = record.started_at or transitioned_at
    record.lease_owner = None
    record.lease_expires_at = None
    record.resource_version += 1
    session.flush()
    return record


def defer_codex_auth_enrollment(
    session: Session,
    *,
    enrollment_id: str,
    lease_owner: str,
    next_action_at: datetime,
) -> CodexAuthEnrollmentRecord:
    record = session.get(CodexAuthEnrollmentRecord, enrollment_id, with_for_update=True)
    if record is None or record.state not in ACTIVE_STATES:
        raise ControlPlaneError("CODEX_AUTH_ENROLLMENT_MISSING", "auth enrollment is unavailable")
    if record.lease_owner != lease_owner:
        raise ControlPlaneError("CODEX_AUTH_ENROLLMENT_LEASE_LOST", "auth enrollment lease is lost")
    record.next_action_at = next_action_at
    record.lease_owner = None
    record.lease_expires_at = None
    session.flush()
    return record


def record_challenge_revealed(
    session: Session,
    *,
    enrollment_id: str,
    api_session_id: str,
    revealed_at: datetime,
) -> CodexAuthEnrollmentRecord:
    record = session.get(CodexAuthEnrollmentRecord, enrollment_id, with_for_update=True)
    if record is None:
        raise ControlPlaneError("CODEX_AUTH_ENROLLMENT_MISSING", "auth enrollment is missing")
    if record.requested_by_api_session_id != api_session_id:
        raise ControlPlaneError(
            "CODEX_AUTH_SESSION_MISMATCH", "auth enrollment belongs to another session"
        )
    if record.state != "WAITING_FOR_USER" or revealed_at >= record.expires_at:
        raise ControlPlaneError(
            "CODEX_AUTH_CHALLENGE_NOT_AVAILABLE", "device challenge is unavailable"
        )
    if record.challenge_revealed_at is not None:
        raise ControlPlaneError(
            "CODEX_AUTH_CHALLENGE_ALREADY_REVEALED", "device challenge was already revealed"
        )
    record.challenge_revealed_at = revealed_at
    record.resource_version += 1
    session.flush()
    return record


def create_auth_assignment_revision(
    session: Session,
    *,
    enrollment: CodexAuthEnrollmentRecord,
    codex_cli_version: str,
    assigned_at: datetime,
) -> CodexAuthAssignmentRevisionRecord:
    existing = session.scalar(
        select(CodexAuthAssignmentRevisionRecord).where(
            CodexAuthAssignmentRevisionRecord.enrollment_id == enrollment.enrollment_id
        )
    )
    if existing is not None:
        return existing
    revision_number = (
        int(
            session.scalar(
                select(
                    func.coalesce(func.max(CodexAuthAssignmentRevisionRecord.revision_number), 0)
                ).where(CodexAuthAssignmentRevisionRecord.binding_id == enrollment.binding_id)
            )
            or 0
        )
        + 1
    )
    assignment_revision_id = new_codex_auth_assignment_revision_id()
    canonical = {
        "assignment_revision_id": assignment_revision_id,
        "binding_id": enrollment.binding_id,
        "revision_number": revision_number,
        "enrollment_id": enrollment.enrollment_id,
        "account_label": enrollment.requested_account_label,
        "login_method": "CHATGPT_DEVICE_CODE",
        "codex_cli_version": codex_cli_version,
        "assigned_by_operator_id": enrollment.requested_by_operator_id,
        "assigned_at": assigned_at,
    }
    record = CodexAuthAssignmentRevisionRecord(
        **canonical,
        assignment_sha256=content_sha256(canonical),
    )
    session.add(record)
    session.flush()
    return record


def held_lease_exists(session: Session, *, binding_id: str) -> bool:
    return (
        session.scalar(
            select(func.count())
            .select_from(WorkerLeaseRecord)
            .where(
                WorkerLeaseRecord.binding_id == binding_id,
                WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
            )
        )
        or 0
    ) > 0


def enrollment_status_document(
    record: CodexAuthEnrollmentRecord, *, challenge_available: bool
) -> dict[str, object]:
    value = CodexAuthEnrollmentStatus(
        enrollment_id=record.enrollment_id,
        binding_id=record.binding_id,
        slot_key=str(record.canonical_document["slot_key"]),
        requested_account_label=record.requested_account_label,
        state=record.state,  # type: ignore[arg-type]
        challenge_available=challenge_available,
        challenge_revealed_at=record.challenge_revealed_at,
        assignment_revision_id=record.assignment_revision_id,
        error_code=record.error_code,
        requested_at=record.requested_at,
        started_at=record.started_at,
        expires_at=record.expires_at,
        completed_at=record.completed_at,
        resource_version=record.resource_version,
    )
    document = value.model_dump(mode="json")
    validate_control_contract("codex-auth-enrollment-status", document)
    return document


def utc_now() -> datetime:
    return datetime.now(UTC)


EnrollmentTargetState = Literal[
    "DRAINING",
    "READY_FOR_LOGIN",
    "WAITING_FOR_USER",
    "VERIFYING",
    "SUCCEEDED",
    "FAILED",
    "EXPIRED",
]
