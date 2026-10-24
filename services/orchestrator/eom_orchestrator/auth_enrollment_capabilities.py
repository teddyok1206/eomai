"""Automatic, exact-assignment execution proofs after fixed-slot device login.

Reuses the released compatibility request/result/report contracts and canonical
file-set publisher. There is no new queue, credential reader or policy-file writer.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from eom_identifiers import content_sha256, new_codex_control_command_id
from eom_workflow.codex_compatibility import (
    CodexCompatibilityCase,
    CodexCompatibilityRequest,
)
from eom_workflow.control_plane import (
    CodexModelCatalogSnapshot,
    CodexUsageObservationV2,
    ReasoningEffort,
)
from sqlalchemy import Connection, Engine, and_, func, select
from sqlalchemy.orm import Session

from eom_orchestrator.auth_enrollment import MODEL_VERIFICATION_REASON
from eom_orchestrator.auth_enrollment_capability_admission import (
    enrollment_candidate_pairs,
    enrollment_compatibility_run_id,
    load_enrollment_model_verification_report,
)
from eom_orchestrator.capability_observer import UnverifiedCapabilityAssignment
from eom_orchestrator.codex_compatibility_maintenance import CodexCompatibilityMaintenance
from eom_orchestrator.codex_runtime_compatibility import (
    execute_pinned_codex_compatibility,
    load_checkpointed_codex_compatibility_request,
)
from eom_orchestrator.control_models import (
    CodexAuthAssignmentRevisionRecord,
    CodexAuthBindingRecord,
    CodexAuthEnrollmentRecord,
    WorkerCapacityPolicyRecord,
    WorkerCapacityPolicyRevisionRecord,
    WorkerCapacityPoolRecord,
    WorkerCapacityPoolSlotRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import JobRecord, WorkerSlotRecord
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import SYSTEMCTL, SYSTEMCTL_ENV
from eom_orchestrator.worker_usage import observe_worker_usage

if TYPE_CHECKING:
    from eom_orchestrator.reviewed_capability_policy import ReviewedCapabilityPolicy


def catalog_visible_candidate_pairs(
    pairs: tuple[tuple[str, ReasoningEffort], ...], catalog: CodexModelCatalogSnapshot
) -> tuple[tuple[str, ReasoningEffort], ...]:
    """Discovery only: visible native pairs remain unadmitted until live probe PASS."""

    if catalog.state != "OBSERVED":
        raise ControlPlaneError(
            "CODEX_MODEL_CATALOG_UNAVAILABLE", "fresh model discovery unavailable"
        )
    visible = {
        (name, effort)
        for model in catalog.models
        if not model.hidden and {"text", "image"} <= set(model.input_modalities)
        for name in {model.id, model.model}
        for effort in model.supported_reasoning_efforts
    }
    return tuple(pair for pair in pairs if pair in visible)


def _require_enrollment_binding(
    session: Session, enrollment_id: str, case: CodexCompatibilityCase
) -> None:
    enrollment = session.get(CodexAuthEnrollmentRecord, enrollment_id)
    binding = session.get(CodexAuthBindingRecord, case.binding_id)
    assignment = session.get(CodexAuthAssignmentRevisionRecord, case.assignment_revision_id)
    if (
        enrollment is None
        or enrollment.state != "VERIFYING"
        or enrollment.binding_id != case.binding_id
        or binding is None
        or binding.state != "DRAINING"
        or binding.reason_code != MODEL_VERIFICATION_REASON
        or binding.worker_slot_id != case.slot_id
        or binding.current_assignment_revision_id != case.assignment_revision_id
        or binding.resource_version != case.expected_resource_version
        or assignment is None
        or assignment.enrollment_id != enrollment_id
        or assignment.binding_id != case.binding_id
    ):
        raise ControlPlaneError(
            "CONTROL_COMPATIBILITY_BINDING_CHANGED", "automatic verification binding changed"
        )


def _assert_slot_idle(slot_id: str) -> None:
    completed = subprocess.run(
        (
            str(SYSTEMCTL),
            "list-units",
            "--no-pager",
            "--no-legend",
            "--plain",
            "--all",
            "--type=service",
            "--state=active,activating,deactivating,reloading",
            f"eom-worker-{slot_id}@*.service",
            f"eom-worker-support-{slot_id}@*.service",
            f"eom-worker-document-review-{slot_id}@*.service",
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        check=False,
        env=SYSTEMCTL_ENV,
    )
    if completed.returncode != 0 or completed.stderr or completed.stdout.strip():
        raise ControlPlaneError("CODEX_AUTH_VERIFICATION_BUSY", "enrollment worker is not idle")


def run_enrollment_model_verification(
    engine: Engine,
    *,
    enrollment_id: str,
    assignment_revision_id: str,
    policy: ReviewedCapabilityPolicy,
    settings: Settings,
) -> None:
    """Run the existing bounded synthetic probe; do not stop any producer or worker.

    The host capacity lock prevents new claims during this rare enrollment operation.
    Already-running work continues. DRAINING excludes ordinary work on the target.
    """

    sessions = build_session_factory(engine)
    run_id = enrollment_compatibility_run_id(assignment_revision_id, policy)
    checkpointed = load_checkpointed_codex_compatibility_request(settings, run_id)
    with sessions() as session:
        enrollment = session.get(CodexAuthEnrollmentRecord, enrollment_id)
        assignment = session.get(CodexAuthAssignmentRevisionRecord, assignment_revision_id)
        if enrollment is None or assignment is None or assignment.enrollment_id != enrollment_id:
            raise ControlPlaneError(
                "CONTROL_AUTH_BINDING_MISSING", "verification assignment missing"
            )
        binding = session.get(CodexAuthBindingRecord, enrollment.binding_id)
        if binding is None or settings.runtime_source_commit is None:
            raise ControlPlaneError("CONTROL_AUTH_BINDING_MISSING", "verification binding missing")
        if (
            load_enrollment_model_verification_report(session, binding=binding, policy=policy)
            is not None
        ):
            return
        if (
            checkpointed is None
            and session.scalar(select(JobRecord.job_id).where(JobRecord.idempotency_key == run_id))
            is not None
        ):
            raise ControlPlaneError(
                "CONTROL_COMPATIBILITY_EXECUTION_UNCERTAIN", "publication checkpoint missing"
            )
        pairs = enrollment_candidate_pairs(
            policy, binding_id=binding.binding_id, slot_id=binding.worker_slot_id
        )
        if not pairs or len(pairs) > 64:
            raise ControlPlaneError(
                "CONTROL_CAPABILITY_BINDING_UNVERIFIED", "no bounded model candidates"
            )
        if checkpointed is None:
            slot_record = session.get(WorkerSlotRecord, binding.worker_slot_id)
            if slot_record is None:
                raise ControlPlaneError("CONTROL_AUTH_SLOT_MISSING", "verification slot missing")
            slot = WorkerSlot.model_validate(
                {
                    "slot_id": slot_record.slot_id,
                    "linux_user": slot_record.linux_user,
                    "role": slot_record.role,
                    "enabled": slot_record.enabled,
                    "gpu": slot_record.gpu,
                }
            )
        request = CodexCompatibilityRequest(
            run_id=run_id,
            source_commit=settings.runtime_source_commit,
            created_at=assignment.assigned_at,
            expires_at=enrollment.expires_at,
            max_model_calls=len(pairs),
            cases=tuple(
                CodexCompatibilityCase.model_validate(
                    dict(
                        case_id="compatcase_"
                        + content_sha256(
                            {"run": run_id, "model": model, "effort": effort}
                        ).removeprefix("sha256:")[:32],
                        slot_id=binding.worker_slot_id,
                        binding_id=binding.binding_id,
                        assignment_revision_id=assignment_revision_id,
                        expected_resource_version=binding.resource_version,
                        model=model,
                        reasoning_effort=effort,
                    )
                )
                for model, effort in pairs
            ),
        )
        _require_enrollment_binding(session, enrollment_id, request.cases[0])
        if checkpointed is not None:
            candidate_pairs = set(pairs)
            if (
                checkpointed.run_id != run_id
                or checkpointed.source_commit != settings.runtime_source_commit
                or checkpointed.created_at != assignment.assigned_at
                or any(
                    case.binding_id != binding.binding_id
                    or case.assignment_revision_id != assignment_revision_id
                    or case.slot_id != binding.worker_slot_id
                    or (case.model, case.reasoning_effort) not in candidate_pairs
                    for case in checkpointed.cases
                )
            ):
                raise ControlPlaneError(
                    "CONTROL_COMPATIBILITY_REPLAY_CONFLICT", "assignment checkpoint differs"
                )
            request = checkpointed

    if checkpointed is None:
        # The fixed read helper runs outside the DB transaction. Visibility only
        # narrows candidates; it never turns catalog metadata into execution PASS.
        usage = observe_worker_usage(
            slot=slot, command_id=new_codex_control_command_id(), binding_id=binding.binding_id
        )
        if (
            not isinstance(usage, CodexUsageObservationV2)
            or usage.model_catalog.codex_cli_version != policy.expected_codex_cli_version
            or usage.model_catalog.observed_at < assignment.assigned_at
        ):
            raise ControlPlaneError(
                "CODEX_MODEL_CATALOG_UNAVAILABLE", "fresh assignment model catalog required"
            )
        visible = set(catalog_visible_candidate_pairs(pairs, usage.model_catalog))
        selected = tuple(
            case for case in request.cases if (case.model, case.reasoning_effort) in visible
        )
        if not selected:
            raise UnverifiedCapabilityAssignment(
                binding_id=binding.binding_id, assignment_revision_id=assignment_revision_id
            )
        request = request.model_copy(update={"cases": selected, "max_model_calls": len(selected)})

    def require_binding(case: CodexCompatibilityCase) -> None:
        with sessions() as session:
            _require_enrollment_binding(session, enrollment_id, case)

    def database_reader(connection: Connection) -> None:
        # The shared host fence is already held, so production claim counts cannot
        # increase between this check and the diagnostic invocation.
        with Session(bind=connection) as session:
            _require_enrollment_binding(session, enrollment_id, request.cases[0])
            held = int(
                session.scalar(
                    select(func.count())
                    .select_from(WorkerLeaseRecord)
                    .where(WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")))
                )
                or 0
            )
            target_held = session.scalar(
                select(WorkerLeaseRecord.lease_id)
                .where(
                    WorkerLeaseRecord.binding_id == request.cases[0].binding_id,
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                )
                .limit(1)
            )
            ceilings = tuple(
                session.scalars(
                    select(WorkerCapacityPolicyRevisionRecord.max_active_codex)
                    .join(
                        WorkerCapacityPolicyRecord,
                        WorkerCapacityPolicyRecord.current_revision_id
                        == WorkerCapacityPolicyRevisionRecord.capacity_policy_revision_id,
                    )
                    .where(
                        WorkerCapacityPolicyRevisionRecord.state == "RELEASED",
                        WorkerCapacityPolicyRecord.state == "ACTIVE",
                    )
                )
            )
            if target_held is not None or not ceilings or held >= min(ceilings):
                raise ControlPlaneError("CODEX_AUTH_VERIFICATION_BUSY", "worker capacity is full")
            pools = session.execute(
                select(WorkerCapacityPoolRecord.max_active, func.count(WorkerLeaseRecord.lease_id))
                .join(
                    WorkerCapacityPoolSlotRecord,
                    and_(
                        WorkerCapacityPoolSlotRecord.capacity_policy_revision_id
                        == WorkerCapacityPoolRecord.capacity_policy_revision_id,
                        WorkerCapacityPoolSlotRecord.pool_key == WorkerCapacityPoolRecord.pool_key,
                    ),
                )
                .join(
                    WorkerCapacityPolicyRecord,
                    WorkerCapacityPolicyRecord.current_revision_id
                    == WorkerCapacityPoolRecord.capacity_policy_revision_id,
                )
                .outerjoin(
                    WorkerLeaseRecord,
                    and_(
                        WorkerLeaseRecord.capacity_policy_revision_id
                        == WorkerCapacityPoolRecord.capacity_policy_revision_id,
                        WorkerLeaseRecord.pool_key == WorkerCapacityPoolRecord.pool_key,
                        WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                    ),
                )
                .where(
                    WorkerCapacityPoolSlotRecord.slot_id == request.cases[0].slot_id,
                    WorkerCapacityPolicyRecord.state == "ACTIVE",
                )
                .group_by(
                    WorkerCapacityPoolRecord.capacity_policy_revision_id,
                    WorkerCapacityPoolRecord.pool_key,
                    WorkerCapacityPoolRecord.max_active,
                )
            ).all()
            if not pools or any(count >= maximum for maximum, count in pools):
                raise ControlPlaneError("CODEX_AUTH_VERIFICATION_BUSY", "worker pool is full")

    execute_pinned_codex_compatibility(
        engine,
        request,
        settings=settings,
        worker=None,
        fence_factory=lambda: CodexCompatibilityMaintenance(
            engine,
            host_reader=lambda: _assert_slot_idle(request.cases[0].slot_id),
            database_reader=database_reader,
        ),
        require_binding=require_binding,
    )
