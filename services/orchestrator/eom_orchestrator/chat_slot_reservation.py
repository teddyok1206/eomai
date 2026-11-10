"""One existing chat-capacity row reserves a fixed physical identity, not a second queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement, SQLColumnExpression

from eom_orchestrator.capability_snapshot_queries import (
    current_assignment_snapshot_clause,
    latest_binding_snapshot_clause,
)
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexAuthEnrollmentRecord,
    CodexCapabilityEntryRecord,
    CodexCapabilitySnapshotRecord,
    CodexControlCommandRecord,
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.general_chat_models import GeneralChatCapacityRecord, GeneralChatTurnRecord
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.models import JobRecord, WorkerSlotRecord

# Existing EOMCAP host fence; exported by control_service for historical callers.
WORKER_HOST_CAPACITY_LOCK_ID = 0x454F4D4341500001
_ACTIVE_ENROLLMENTS = ("REQUESTED", "DRAINING", "READY_FOR_LOGIN", "WAITING_FOR_USER", "VERIFYING")


def reserved_chat_slot_id(session: Session) -> str | None:
    return session.scalar(
        select(GeneralChatCapacityRecord.worker_slot_id).where(
            GeneralChatCapacityRecord.slot_key == "chat"
        )
    )


def ordinary_slot_allowed_clause(slot_id: SQLColumnExpression[str]) -> ColumnElement[bool]:
    return ~exists().where(GeneralChatCapacityRecord.worker_slot_id == slot_id)


def active_chat_slot_clause(slot_id: SQLColumnExpression[str]) -> ColumnElement[bool]:
    # Expired unknown execution is still busy, just like a reconciling worker lease.
    return exists().where(
        GeneralChatCapacityRecord.worker_slot_id == slot_id,
        GeneralChatCapacityRecord.active_turn_id.is_not(None),
    )


def lock_reserved_chat_capacity(
    session: Session, worker_slot_id: str
) -> GeneralChatCapacityRecord | None:
    """Control already holds binding; chat holds capacity and only SELECTs binding."""
    return session.scalar(
        select(GeneralChatCapacityRecord)
        .where(GeneralChatCapacityRecord.worker_slot_id == worker_slot_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def binding_has_active_chat(session: Session, binding_id: str) -> bool:
    return (
        session.scalar(
            select(
                exists().where(
                    CodexAuthBindingRecord.binding_id == binding_id,
                    active_chat_slot_clause(CodexAuthBindingRecord.worker_slot_id),
                )
            )
        )
        is True
    )


def active_reserved_chat_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(GeneralChatCapacityRecord)
            .where(
                GeneralChatCapacityRecord.worker_slot_id.is_not(None),
                GeneralChatCapacityRecord.active_turn_id.is_not(None),
            )
        )
        or 0
    )


def require_chat_host_capacity(session: Session) -> None:
    """The existing host lock must be held; preserve current released host ceilings."""
    ceiling = session.scalar(
        select(func.min(WorkerCapacityPolicyRevisionRecord.max_active_codex))
        .join(
            WorkerCapacityPolicyRecord,
            WorkerCapacityPolicyRecord.current_revision_id
            == WorkerCapacityPolicyRevisionRecord.capacity_policy_revision_id,
        )
        .where(
            WorkerCapacityPolicyRecord.state == "ACTIVE",
            WorkerCapacityPolicyRevisionRecord.state == "RELEASED",
        )
    )
    held = int(
        session.scalar(
            select(func.count())
            .select_from(WorkerLeaseRecord)
            .where(WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")))
        )
        or 0
    )
    if ceiling is None or held + active_reserved_chat_count(session) >= ceiling:
        raise ChatError("GENERAL_CHAT_NOT_READY")


def reserve_chat_slot(session: Session, *, worker_slot_id: str = "06") -> bool:
    """Activate after the operator proves fixed worker units quiescent; no auth mutation."""
    if worker_slot_id != "06":
        raise ChatError("GENERAL_CHAT_SLOT_INVALID")
    session.execute(select(func.pg_advisory_xact_lock(WORKER_HOST_CAPACITY_LOCK_ID)))
    binding = session.scalar(
        select(CodexAuthBindingRecord)
        .where(CodexAuthBindingRecord.worker_slot_id == worker_slot_id)
        .with_for_update()
    )
    capacity = session.scalar(
        select(GeneralChatCapacityRecord)
        .where(GeneralChatCapacityRecord.slot_key == "chat")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if capacity is None or binding is None:
        raise ChatError("GENERAL_CHAT_NOT_READY")
    if capacity.worker_slot_id == worker_slot_id:
        return False
    if capacity.worker_slot_id is not None:
        raise ChatError("GENERAL_CHAT_SLOT_CONFLICT")
    if (
        capacity.active_turn_id is not None
        or session.scalar(
            select(
                exists().where(
                    WorkerLeaseRecord.worker_slot_id == worker_slot_id,
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                )
            )
        )
        or session.scalar(
            select(
                exists().where(
                    JobRecord.worker_slot_id == worker_slot_id,
                    JobRecord.status.in_(("CLAIMED", "RUNNING", "VALIDATING_RESULT", "COMMITTING")),
                )
            )
        )
    ):
        raise ChatError("GENERAL_CHAT_SLOT_BUSY")
    _require_no_binding_operation(session, binding.binding_id)
    capacity.worker_slot_id = worker_slot_id
    session.flush()
    return True


def _require_no_binding_operation(session: Session, binding_id: str) -> None:
    if session.scalar(
        select(
            exists().where(
                CodexAuthEnrollmentRecord.binding_id == binding_id,
                CodexAuthEnrollmentRecord.state.in_(_ACTIVE_ENROLLMENTS),
            )
        )
    ) or session.scalar(
        select(
            exists().where(
                CodexControlCommandRecord.binding_id == binding_id,
                CodexControlCommandRecord.state.in_(("PENDING", "PROCESSING")),
            )
        )
    ):
        raise ChatError("GENERAL_CHAT_NOT_READY")


@dataclass(frozen=True)
class ReservedChatBinding:
    slot_id: str
    binding_id: str
    assignment_revision_id: str


def require_reserved_chat_admission(
    session: Session,
    capacity: GeneralChatCapacityRecord,
    *,
    now: datetime,
    model: str | None = None,
    turn: GeneralChatTurnRecord | None = None,
) -> ReservedChatBinding | None:
    """Called under capacity lock; uses SELECT-only identity/capability projections."""
    if capacity.worker_slot_id is None:
        if turn is not None and turn.worker_slot_id is not None:
            raise ChatError("GENERAL_CHAT_NOT_READY")
        return None
    row = session.execute(
        select(
            CodexAuthBindingRecord.binding_id,
            CodexAuthBindingRecord.current_assignment_revision_id,
        )
        .join(WorkerSlotRecord, WorkerSlotRecord.slot_id == CodexAuthBindingRecord.worker_slot_id)
        .where(
            WorkerSlotRecord.slot_id == capacity.worker_slot_id,
            WorkerSlotRecord.enabled.is_(True),
            CodexAuthBindingRecord.state == "READY",
            CodexAuthBindingRecord.valid_until > now,
            CodexAuthBindingRecord.current_assignment_revision_id.is_not(None),
        )
    ).one_or_none()
    if row is None:
        raise ChatError("GENERAL_CHAT_NOT_READY")
    binding = ReservedChatBinding(
        capacity.worker_slot_id, row.binding_id, row.current_assignment_revision_id
    )
    if turn is None:
        _require_no_binding_operation(session, binding.binding_id)
    elif (turn.worker_slot_id, turn.auth_binding_id, turn.auth_assignment_revision_id) != (
        binding.slot_id,
        binding.binding_id,
        binding.assignment_revision_id,
    ):
        raise ChatError("GENERAL_CHAT_NOT_READY")
    capabilities = (
        select(CodexCapabilityEntryRecord.capability_snapshot_id)
        .join(
            CodexCapabilitySnapshotRecord,
            CodexCapabilitySnapshotRecord.capability_snapshot_id
            == CodexCapabilityEntryRecord.capability_snapshot_id,
        )
        .join(
            CodexAuthBindingRecord,
            CodexAuthBindingRecord.binding_id == CodexCapabilitySnapshotRecord.binding_id,
        )
        .where(
            CodexAuthBindingRecord.binding_id == binding.binding_id,
            CodexCapabilitySnapshotRecord.valid_until > now,
            CodexCapabilitySnapshotRecord.codex_cli_version
            == CodexAuthBindingRecord.codex_cli_version,
            CodexCapabilityEntryRecord.state == "AVAILABLE",
            current_assignment_snapshot_clause(),
            latest_binding_snapshot_clause(),
        )
    )
    if model is not None:
        capabilities = capabilities.where(CodexCapabilityEntryRecord.model == model)
    if session.scalar(capabilities.limit(1)) is None:
        raise ChatError("GENERAL_CHAT_NOT_READY")
    return binding
