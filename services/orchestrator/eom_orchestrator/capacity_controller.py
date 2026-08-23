"""Deterministic Codex lease admission, drain operations, and crash reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from eom_workflow.control_plane import CodexAuthHealthView, WorkerLeaseView
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    acquire_worker_lease,
    begin_expired_lease_reconciliation,
    record_auth_health,
    terminalize_worker_lease,
    worker_lease_view,
)
from eom_orchestrator.database import transaction
from eom_orchestrator.models import JobRecord, WorkerSlotRecord
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import (
    WorkerUnitActivity,
    inspect_worker_unit_activity,
)


@dataclass(frozen=True)
class LeaseClaim:
    plan_id: str
    step_key: str
    job_id: str
    attempt: int
    workload_class: Literal["CODEX", "KNOWLEDGE_ANALYSIS"]
    acquired_at: datetime
    ttl: timedelta


@dataclass(frozen=True)
class LeaseReconciliationOutcome:
    lease_id: str
    unit_name: str
    process_state: str
    lease_state: str
    reason_code: str | None


@dataclass(frozen=True)
class CapacityMetrics:
    queued_jobs: int
    failed_jobs: int
    active_leases: int
    reconciling_leases: int
    released_leases: int
    expired_leases: int
    held_gpu_leases: int
    held_knowledge_analysis_leases: int
    oldest_queued_seconds: int | None
    oldest_held_seconds: int | None


class CodexCapacityController:
    """Application service around short DB transactions and read-only unit inspection."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        activity_inspector: Callable[[WorkerSlot, str], WorkerUnitActivity] = (
            inspect_worker_unit_activity
        ),
    ) -> None:
        self.sessions = sessions
        self.activity_inspector = activity_inspector

    def claim(self, claim: LeaseClaim) -> WorkerLeaseView:
        with transaction(self.sessions) as session:
            lease = acquire_worker_lease(
                session,
                plan_id=claim.plan_id,
                step_key=claim.step_key,
                job_id=claim.job_id,
                attempt=claim.attempt,
                workload_class=claim.workload_class,
                acquired_at=claim.acquired_at,
                ttl=claim.ttl,
            )
            return worker_lease_view(lease)

    def release(
        self,
        *,
        lease_id: str,
        reason_code: str,
        released_at: datetime,
    ) -> WorkerLeaseView:
        with transaction(self.sessions) as session:
            lease = terminalize_worker_lease(
                session,
                lease_id=lease_id,
                terminal_state="RELEASED",
                reason_code=reason_code,
                released_at=released_at,
            )
            return worker_lease_view(lease)

    def reconcile_expired(self, *, observed_at: datetime) -> tuple[LeaseReconciliationOutcome, ...]:
        with self.sessions() as session:
            lease_ids = tuple(
                session.scalars(
                    select(WorkerLeaseRecord.lease_id)
                    .where(
                        (WorkerLeaseRecord.state == "RECONCILING")
                        | (
                            (WorkerLeaseRecord.state == "ACTIVE")
                            & (WorkerLeaseRecord.expires_at <= observed_at)
                        )
                    )
                    .order_by(WorkerLeaseRecord.expires_at, WorkerLeaseRecord.lease_id)
                )
            )
        outcomes: list[LeaseReconciliationOutcome] = []
        for lease_id in lease_ids:
            try:
                with transaction(self.sessions) as session:
                    lease = begin_expired_lease_reconciliation(
                        session, lease_id=lease_id, observed_at=observed_at
                    )
                    slot_record = session.get(WorkerSlotRecord, lease.worker_slot_id)
                    if slot_record is None:
                        raise ControlPlaneError(
                            "CONTROL_LEASE_SLOT_MISSING", "lease worker slot is missing"
                        )
                    slot = _worker_slot(slot_record)
                    job_id = lease.job_id
            except ControlPlaneError as exc:
                outcomes.append(
                    LeaseReconciliationOutcome(
                        lease_id,
                        "",
                        "UNKNOWN",
                        "RECONCILING",
                        exc.code,
                    )
                )
                continue
            activity = self.activity_inspector(slot, job_id)
            if activity.state == "ABSENT":
                with transaction(self.sessions) as session:
                    terminalize_worker_lease(
                        session,
                        lease_id=lease_id,
                        terminal_state="EXPIRED",
                        reason_code="PROCESS_ABSENT",
                        released_at=observed_at,
                    )
                outcomes.append(
                    LeaseReconciliationOutcome(
                        lease_id,
                        activity.unit_name,
                        activity.state,
                        "EXPIRED",
                        "PROCESS_ABSENT",
                    )
                )
            else:
                outcomes.append(
                    LeaseReconciliationOutcome(
                        lease_id,
                        activity.unit_name,
                        activity.state,
                        "RECONCILING",
                        (
                            "PROCESS_STILL_RUNNING"
                            if activity.state == "RUNNING"
                            else "PROCESS_STATE_UNKNOWN"
                        ),
                    )
                )
        return tuple(outcomes)

    def metrics(self, *, observed_at: datetime) -> CapacityMetrics:
        with self.sessions() as session:
            queued = session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.status == "QUEUED")
            )
            failed = session.scalar(
                select(func.count()).select_from(JobRecord).where(JobRecord.status == "FAILED")
            )
            oldest = session.scalar(
                select(func.min(JobRecord.created_at)).where(JobRecord.status == "QUEUED")
            )
            oldest_held = session.scalar(
                select(func.min(WorkerLeaseRecord.acquired_at)).where(
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING"))
                )
            )
            active = session.scalar(
                select(func.count())
                .select_from(WorkerLeaseRecord)
                .where(WorkerLeaseRecord.state == "ACTIVE")
            )
            reconciling = session.scalar(
                select(func.count())
                .select_from(WorkerLeaseRecord)
                .where(WorkerLeaseRecord.state == "RECONCILING")
            )
            released = session.scalar(
                select(func.count())
                .select_from(WorkerLeaseRecord)
                .where(WorkerLeaseRecord.state == "RELEASED")
            )
            expired = session.scalar(
                select(func.count())
                .select_from(WorkerLeaseRecord)
                .where(WorkerLeaseRecord.state == "EXPIRED")
            )
            held_gpu = session.scalar(
                select(func.count())
                .select_from(WorkerLeaseRecord)
                .join(
                    WorkerSlotRecord,
                    WorkerSlotRecord.slot_id == WorkerLeaseRecord.worker_slot_id,
                )
                .where(
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                    WorkerSlotRecord.gpu.is_(True),
                )
            )
            held_analysis = session.scalar(
                select(func.count())
                .select_from(WorkerLeaseRecord)
                .where(
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                    WorkerLeaseRecord.workload_class == "KNOWLEDGE_ANALYSIS",
                )
            )
        age = None if oldest is None else max(0, int((observed_at - oldest).total_seconds()))
        held_age = (
            None
            if oldest_held is None
            else max(0, int((observed_at - oldest_held).total_seconds()))
        )
        return CapacityMetrics(
            queued_jobs=int(queued or 0),
            failed_jobs=int(failed or 0),
            active_leases=int(active or 0),
            reconciling_leases=int(reconciling or 0),
            released_leases=int(released or 0),
            expired_leases=int(expired or 0),
            held_gpu_leases=int(held_gpu or 0),
            held_knowledge_analysis_leases=int(held_analysis or 0),
            oldest_queued_seconds=age,
            oldest_held_seconds=held_age,
        )


def set_auth_binding_operational_state(
    session: Session,
    *,
    binding_id: str,
    state: str,
    reason_code: str,
    observed_at: datetime,
    ttl: timedelta,
) -> CodexAuthBindingRecord:
    """Drain or disable a binding; READY is only produced by an actual probe."""

    if state not in {"DRAINING", "DISABLED"}:
        raise ValueError("manual authentication state must be DRAINING or DISABLED")
    if ttl <= timedelta(0) or ttl > timedelta(hours=1):
        raise ValueError("authentication operational-state TTL is outside the reviewed bound")
    binding = session.get(CodexAuthBindingRecord, binding_id)
    if binding is None:
        raise ControlPlaneError("CONTROL_AUTH_BINDING_MISSING", "auth binding is missing")
    document = CodexAuthHealthView.model_validate(
        {
            "schema_version": "codex-auth-health-view/1.0",
            "binding_id": binding.binding_id,
            "slot_key": f"slot{binding.worker_slot_id}",
            "account_label": binding.account_label,
            "state": state,
            "reason_code": reason_code,
            "codex_cli_version": binding.codex_cli_version or "0.0.0",
            "observed_at": observed_at,
            "valid_until": observed_at + ttl,
        }
    ).model_dump(mode="json")
    return record_auth_health(session, document=document)


def _worker_slot(record: WorkerSlotRecord) -> WorkerSlot:
    return WorkerSlot(
        slot_id=record.slot_id,  # type: ignore[arg-type]
        linux_user=record.linux_user,  # type: ignore[arg-type]
        role=record.role,  # type: ignore[arg-type]
        enabled=record.enabled,
        gpu=record.gpu,
    )
