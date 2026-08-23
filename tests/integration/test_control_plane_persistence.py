from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any
from uuid import uuid4

import eom_catalog_service.models  # noqa: F401
import eom_hwpx_manager.models  # noqa: F401
import eom_identity_service.models  # noqa: F401
import eom_workflow_runner.models  # noqa: F401
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from eom_identifiers import (
    new_auth_binding_id,
    new_capability_snapshot_id,
    new_capacity_policy_id,
    new_capacity_policy_revision_id,
    new_execution_preset_id,
    new_execution_preset_revision_id,
    new_instruction_bundle_id,
    new_instruction_bundle_revision_id,
    new_job_id,
    new_logical_artifact_id,
    new_reference_bundle_id,
    new_reference_bundle_revision_id,
    new_revision_id,
)
from eom_orchestrator.capability_observer import (
    REQUIRED_EXEC_HELP_FLAGS,
    ReviewedCapabilityPolicy,
    record_reviewed_capability_snapshot,
)
from eom_orchestrator.capacity_controller import (
    CodexCapacityController,
    LeaseClaim,
    set_auth_binding_operational_state,
)
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexCapabilitySnapshotRecord,
    ExecutionBundleRevisionRecord,
    WorkerLeaseEventRecord,
    WorkerLeaseRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    ResolvedPlanDependencyEvidence,
    acquire_worker_lease,
    begin_expired_lease_reconciliation,
    compute_control_document_hash,
    publish_bundle_revision,
    publish_capacity_policy_revision,
    publish_execution_preset_revision,
    record_auth_health,
    record_bundle_revision,
    record_capability_snapshot,
    record_capacity_policy_revision,
    record_execution_preset_revision,
    terminalize_worker_lease,
    worker_lease_view,
)
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.execution_resolver import (
    ExecutionStepRequirement,
    resolve_execution_plan,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    Base,
    JobRecord,
    ProtocolVersionRecord,
    WorkerSlotRecord,
)
from eom_orchestrator.protocol import protocol_schema_hash
from eom_orchestrator.repository import ensure_protocol_version, upsert_worker_slot
from eom_orchestrator.worker_systemd import WorkerUnitActivity
from eom_workflow import ControlArtifactPointer
from eom_workflow.control_plane import WorkerRole
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _self_hash(document: dict[str, Any], field: str) -> dict[str, Any]:
    document[field] = compute_control_document_hash(document, field)
    return document


def _seed_protocols_and_slots(session: Session) -> None:
    ensure_protocol_version(session, "1.0.1", protocol_schema_hash())
    ensure_protocol_version(
        session, "workflow-role/1.3.0", role_schema_bundle_hash("workflow-role/1.3.0")
    )
    roles = ("authoring", "review", "image", "item_management", "support")
    for number, role in enumerate(roles, start=1):
        upsert_worker_slot(
            session,
            slot_id=f"{number:02d}",
            linux_user=f"eom-cdx-{number:02d}",
            role=role,
            enabled=True,
            gpu=role == "image",
        )
    session.flush()


def _artifact_pointer(
    session: Session,
    *,
    schema_ref: str,
    media_type: str,
    logical_name: str,
) -> ControlArtifactPointer:
    job_id = new_job_id()
    artifact_id = new_logical_artifact_id()
    revision_id = new_revision_id()
    digest = "sha256:" + uuid4().hex * 2
    session.add(
        JobRecord(
            job_id=job_id,
            protocol_version="1.0.1",
            idempotency_key=f"phase2-artifact-{uuid4().hex}",
            request_hash="sha256:" + uuid4().hex * 2,
            task_type="control_plane_fixture",
            request={"fixture": True},
            status="SUCCEEDED",
            logical_artifact_id=artifact_id,
            revision_id=revision_id,
        )
    )
    session.flush()
    session.add(
        ArtifactRecord(
            logical_artifact_id=artifact_id,
            job_id=job_id,
            artifact_type="control_plane_fixture",
            approved=True,
        )
    )
    session.flush()
    session.add(
        ArtifactRevisionRecord(
            revision_id=revision_id,
            logical_artifact_id=artifact_id,
            job_id=job_id,
            content_hash=digest,
            manifest_hash="sha256:" + uuid4().hex * 2,
            content_bytes=32,
            nas_path=f"/disposable/control/{artifact_id}/{revision_id}",
            manifest={
                "primary_file": logical_name,
                "files": [
                    {
                        "file_name": logical_name,
                        "sha256": digest,
                        "schema_ref": schema_ref,
                        "media_type": media_type,
                    }
                ],
            },
            result={"fixture": True},
            approved=True,
        )
    )
    session.flush()
    return ControlArtifactPointer(
        artifact_id=artifact_id,
        artifact_revision_id=revision_id,
        sha256=digest,
        schema_ref=schema_ref,
        media_type=media_type,
        logical_name=logical_name,
    )


def _bundle_documents(
    session: Session,
) -> tuple[
    dict[str, Any],
    ControlArtifactPointer,
    dict[str, Any],
    ControlArtifactPointer,
]:
    instruction_id = new_instruction_bundle_id()
    instruction_revision_id = new_instruction_bundle_revision_id()
    instruction_member = _artifact_pointer(
        session,
        schema_ref="eom://schemas/workflow/instruction-member/1.0",
        media_type="text/markdown",
        logical_name="AGENTS.md",
    )
    instruction_manifest = _artifact_pointer(
        session,
        schema_ref="eom://schemas/workflow/instruction-bundle-manifest/1.0",
        media_type="application/json",
        logical_name="instruction-manifest.json",
    )
    instruction = _self_hash(
        {
            "schema_version": "instruction-bundle-manifest/1.0",
            "bundle_id": instruction_id,
            "bundle_revision_id": instruction_revision_id,
            "revision_number": 1,
            "state": "RELEASED",
            "components": [
                {
                    "layer": "PLATFORM",
                    "relative_path": "instructions/AGENTS.md",
                    "artifact": instruction_member.model_dump(mode="json"),
                }
            ],
            "content_sha256": "sha256:" + "0" * 64,
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        },
        "content_sha256",
    )

    reference_id = new_reference_bundle_id()
    reference_revision_id = new_reference_bundle_revision_id()
    reference_member = _artifact_pointer(
        session,
        schema_ref="eom://schemas/knowledge/reference-markdown/1.0",
        media_type="text/markdown",
        logical_name="curriculum.md",
    )
    reference_manifest = _artifact_pointer(
        session,
        schema_ref="eom://schemas/workflow/reference-bundle-manifest/1.0",
        media_type="application/json",
        logical_name="reference-manifest.json",
    )
    reference = _self_hash(
        {
            "schema_version": "reference-bundle-manifest/1.0",
            "bundle_id": reference_id,
            "bundle_revision_id": reference_revision_id,
            "revision_number": 1,
            "state": "RELEASED",
            "entries": [
                {
                    "reference_key": "curriculum",
                    "source_class": "CURRICULUM",
                    "relative_path": "references/curriculum.md",
                    "source_logical_id": "document_" + "1" * 32,
                    "source_revision_id": "documentrev_" + "2" * 32,
                    "rights_policy_revision_id": "rightsrev_" + "3" * 32,
                    "artifact": reference_member.model_dump(mode="json"),
                }
            ],
            "content_sha256": "sha256:" + "0" * 64,
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        },
        "content_sha256",
    )
    return instruction, instruction_manifest, reference, reference_manifest


def _workflow(session: Session) -> WorkflowInstanceRecord:
    suffix = uuid4().hex
    definition_key = f"generic-item-development-{suffix}"
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + suffix,
        definition_key=definition_key,
        definition_version="1.4.0",
        schema_version="1.0",
        canonical_definition={"fixture": True},
        definition_hash="sha256:" + uuid4().hex * 2,
        active=True,
        source_path=f"disposable/{definition_key}.v1.4.yaml",
    )
    session.add(definition)
    session.flush()
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + uuid4().hex,
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        protocol_version="1.1.0",
        role_schema_version="workflow-role/1.3.0",
        state="REQUESTED",
        stage="AUTHORING",
        current_step_key="authoring",
        request_payload={"fixture": True},
        initial_request={"fixture": True},
        runtime_context={},
        idempotency_key=f"phase2-workflow-{suffix}",
        request_hash="sha256:" + uuid4().hex * 2,
        lock_version=1,
        rework_cycle_count=0,
        created_actor_type="system",
        created_actor_id="phase2-test",
    )
    session.add(workflow)
    session.flush()
    return workflow


def _job(
    session: Session, *, workflow_id: str, role: str = "authoring", attempt: int = 1
) -> JobRecord:
    step_run_id = "steprun_" + uuid4().hex
    job = JobRecord(
        job_id=new_job_id(),
        protocol_version="workflow-role/1.3.0",
        idempotency_key=f"phase2-job-{uuid4().hex}",
        request_hash="sha256:" + uuid4().hex * 2,
        task_type=f"workflow_{role}",
        request={
            "workflow_id": workflow_id,
            "step_run_id": step_run_id,
            "role": role,
            "attempt": attempt,
        },
        status="QUEUED",
        logical_artifact_id=new_logical_artifact_id(),
        revision_id=new_revision_id(),
    )
    session.add(job)
    session.flush()
    session.add(
        WorkflowStepRunRecord(
            step_run_id=step_run_id,
            workflow_id=workflow_id,
            step_key=role,
            attempt=attempt,
            step_type="agent",
            worker_role=role,
            result_schema="authoring-result@4.0",
            state="RUNNING",
            platform_job_id=job.job_id,
            input_pointer_manifest={},
            output_pointer_manifest=None,
        )
    )
    session.flush()
    return job


def _complete_control_plane(
    session: Session,
    *,
    roles: tuple[WorkerRole, ...] = (WorkerRole.AUTHORING,),
) -> tuple[str, str, str]:
    _seed_protocols_and_slots(session)
    instruction, instruction_artifact, reference, reference_artifact = _bundle_documents(session)
    instruction_record = record_bundle_revision(
        session,
        bundle_key=f"platform-{uuid4().hex}",
        manifest_artifact=instruction_artifact,
        document=instruction,
        created_by="phase2-test",
    )
    reference_record = record_bundle_revision(
        session,
        bundle_key=f"references-{uuid4().hex}",
        manifest_artifact=reference_artifact,
        document=reference,
        created_by="phase2-test",
    )
    publish_bundle_revision(
        session,
        bundle_id=instruction_record.bundle_id,
        bundle_revision_id=instruction_record.bundle_revision_id,
    )
    publish_bundle_revision(
        session,
        bundle_id=reference_record.bundle_id,
        bundle_revision_id=reference_record.bundle_revision_id,
    )

    capacity_id = new_capacity_policy_id()
    capacity_revision_id = new_capacity_policy_revision_id()
    capacity = _self_hash(
        {
            "schema_version": "worker-capacity-policy/1.0",
            "capacity_policy_id": capacity_id,
            "capacity_policy_revision_id": capacity_revision_id,
            "revision_number": 1,
            "state": "RELEASED",
            "max_configured_slots": 5,
            "max_active_codex": 3,
            "max_active_per_slot": 1,
            "max_active_gpu": 1,
            "max_active_knowledge_analysis": 1,
            "pools": [
                {
                    "pool_key": role.value,
                    "roles": [role.value],
                    "slot_keys": [
                        "slot"
                        + {
                            WorkerRole.AUTHORING: "01",
                            WorkerRole.REVIEW: "02",
                            WorkerRole.IMAGE: "03",
                            WorkerRole.ITEM_MANAGEMENT: "04",
                            WorkerRole.SUPPORT: "05",
                        }[role]
                    ],
                    "max_active": 1,
                }
                for role in roles
            ],
            "content_sha256": "sha256:" + "0" * 64,
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        },
        "content_sha256",
    )
    record_capacity_policy_revision(
        session,
        policy_key=f"host-{uuid4().hex}",
        document=capacity,
        created_by="phase2-test",
    )
    publish_capacity_policy_revision(
        session,
        capacity_policy_id=capacity_id,
        capacity_policy_revision_id=capacity_revision_id,
    )

    preset_id = new_execution_preset_id()
    preset_revision_id = new_execution_preset_revision_id()
    instruction_pointer = {
        "bundle_id": instruction_record.bundle_id,
        "bundle_revision_id": instruction_record.bundle_revision_id,
        "manifest_artifact": instruction_artifact.model_dump(mode="json"),
        "manifest_sha256": instruction_artifact.sha256,
    }
    reference_pointer = {
        "bundle_id": reference_record.bundle_id,
        "bundle_revision_id": reference_record.bundle_revision_id,
        "manifest_artifact": reference_artifact.model_dump(mode="json"),
        "manifest_sha256": reference_artifact.sha256,
    }
    preset = _self_hash(
        {
            "schema_version": "execution-preset-revision/1.0",
            "preset_id": preset_id,
            "preset_revision_id": preset_revision_id,
            "revision_number": 1,
            "state": "RELEASED",
            "display_name": "Phase 2 standard",
            "description": "Disposable control-plane persistence fixture.",
            "role_policies": [
                {
                    "role": role.value,
                    "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
                    "instruction_bundle": instruction_pointer,
                    "reference_bundle": reference_pointer,
                    "worker_pool_key": role.value,
                    "timeout_seconds": 1800,
                    "sandbox": "read-only",
                    "network": "disabled",
                }
                for role in roles
            ],
            "capacity_policy_revision_id": capacity_revision_id,
            "general_knowledge_policy": "ALLOW_WITH_PROVENANCE",
            "compatible_workflow_protocols": ["workflow-role/1.3.0"],
            "content_sha256": "sha256:" + "0" * 64,
            "created_at": NOW.isoformat().replace("+00:00", "Z"),
        },
        "content_sha256",
    )
    preset_key = f"standard-{uuid4().hex}"
    record_execution_preset_revision(
        session,
        preset_key=preset_key,
        document=preset,
        created_by="phase2-test",
    )
    publish_execution_preset_revision(
        session,
        preset_id=preset_id,
        preset_revision_id=preset_revision_id,
    )

    workflow = _workflow(session)
    content_pack_release_id = "packrel_" + uuid4().hex
    content_pack_hash = "sha256:" + uuid4().hex * 2
    dependencies = ResolvedPlanDependencyEvidence(
        workflow_id=workflow.workflow_id,
        workflow_definition_key=workflow.definition_key,
        workflow_definition_version=workflow.definition_version,
        workflow_definition_sha256=workflow.definition_hash,
        workflow_role_schema_version=workflow.role_schema_version,
        content_pack_release_id=content_pack_release_id,
        content_pack_sha256=content_pack_hash,
    )
    first_plan = resolve_execution_plan(
        session,
        preset_key=preset_key,
        dependencies=dependencies,
        steps=tuple(ExecutionStepRequirement(role.value, role) for role in roles),
        resolved_at=NOW,
    )
    replay = resolve_execution_plan(
        session,
        preset_key=preset_key,
        dependencies=dependencies,
        steps=tuple(ExecutionStepRequirement(role.value, role) for role in roles),
        resolved_at=NOW + timedelta(days=1),
    )
    assert replay == first_plan
    assert first_plan.steps[0].model == "gpt-5.6-terra"
    assert first_plan.steps[0].reasoning_effort == "high"

    slot_by_role = {
        WorkerRole.AUTHORING: "01",
        WorkerRole.REVIEW: "02",
        WorkerRole.IMAGE: "03",
        WorkerRole.ITEM_MANAGEMENT: "04",
        WorkerRole.SUPPORT: "05",
    }
    for role in roles:
        slot_id = slot_by_role[role]
        existing_binding = session.scalar(
            select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == slot_id)
        )
        if existing_binding is None:
            binding_id = new_auth_binding_id()
            health = {
                "schema_version": "codex-auth-health-view/1.0",
                "binding_id": binding_id,
                "slot_key": f"slot{slot_id}",
                "account_label": f"phase2-slot{slot_id}",
                "state": "READY",
                "reason_code": None,
                "codex_cli_version": "0.147.0",
                "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                "valid_until": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
            record_auth_health(session, document=health)
        else:
            assert existing_binding.state == "READY"
            assert existing_binding.codex_cli_version == "0.147.0"
            binding_id = existing_binding.binding_id
        capability = _self_hash(
            {
                "schema_version": "codex-capability-snapshot/1.0",
                "capability_snapshot_id": new_capability_snapshot_id(),
                "binding_id": binding_id,
                "codex_cli_version": "0.147.0",
                "source": "LOCAL_OBSERVATION",
                "capabilities": [
                    {
                        "model": "gpt-5.6-terra",
                        "reasoning_efforts": ["high"],
                        "state": "AVAILABLE",
                    }
                ],
                "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                "valid_until": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "snapshot_sha256": "sha256:" + "0" * 64,
            },
            "snapshot_sha256",
        )
        record_capability_snapshot(session, document=capability)
    session.flush()
    return first_plan.plan_id, workflow.workflow_id, instruction_record.bundle_revision_id


def test_control_plane_records_are_idempotent_immutable_and_capacity_bounded(
    db_session: Session,
) -> None:
    plan_id, workflow_id, bundle_revision_id = _complete_control_plane(db_session)
    first_job = _job(db_session, workflow_id=workflow_id)
    lease = acquire_worker_lease(
        db_session,
        plan_id=plan_id,
        step_key="authoring",
        job_id=first_job.job_id,
        attempt=1,
        workload_class="CODEX",
        acquired_at=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=30),
    )
    assert worker_lease_view(lease).slot_key == "slot01"
    assert (
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key="authoring",
            job_id=first_job.job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=1),
            ttl=timedelta(minutes=30),
        ).lease_id
        == lease.lease_id
    )
    second_job = _job(db_session, workflow_id=workflow_id, attempt=2)
    with pytest.raises(ControlPlaneError) as exhausted:
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key="authoring",
            job_id=second_job.job_id,
            attempt=2,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=2),
            ttl=timedelta(minutes=30),
        )
    assert exhausted.value.code == "CONTROL_CAPACITY_EXHAUSTED"
    terminalize_worker_lease(
        db_session,
        lease_id=lease.lease_id,
        terminal_state="RELEASED",
        reason_code="WORKER_EXITED",
        released_at=NOW + timedelta(minutes=3),
    )
    second = acquire_worker_lease(
        db_session,
        plan_id=plan_id,
        step_key="authoring",
        job_id=second_job.job_id,
        attempt=2,
        workload_class="CODEX",
        acquired_at=NOW + timedelta(minutes=4),
        ttl=timedelta(minutes=5),
    )
    begin_expired_lease_reconciliation(
        db_session,
        lease_id=second.lease_id,
        observed_at=NOW + timedelta(minutes=10),
    )
    assert second.state == "RECONCILING"
    terminalize_worker_lease(
        db_session,
        lease_id=second.lease_id,
        terminal_state="EXPIRED",
        reason_code="PROCESS_ABSENT",
        released_at=NOW + timedelta(minutes=10),
    )
    events = list(
        db_session.scalars(
            select(WorkerLeaseEventRecord)
            .where(WorkerLeaseEventRecord.lease_id == second.lease_id)
            .order_by(WorkerLeaseEventRecord.sequence)
        )
    )
    assert [event.new_state for event in events] == ["ACTIVE", "RECONCILING", "EXPIRED"]

    revision = db_session.get(ExecutionBundleRevisionRecord, bundle_revision_id)
    assert revision is not None
    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        revision.content_sha256 = "sha256:" + "f" * 64
        db_session.flush()


def test_concurrent_claims_create_only_one_held_lease(integration_engine: Engine) -> None:
    sessions = build_session_factory(integration_engine)
    with transaction(sessions) as session:
        plan_id, workflow_id, _ = _complete_control_plane(session)
        job = _job(session, workflow_id=workflow_id)
        job_ids = (job.job_id, job.job_id)
    barrier = Barrier(2)

    def claim(job_id: str) -> str:
        barrier.wait(timeout=5)
        try:
            with transaction(sessions) as session:
                lease = acquire_worker_lease(
                    session,
                    plan_id=plan_id,
                    step_key="authoring",
                    job_id=job_id,
                    attempt=1,
                    workload_class="CODEX",
                    acquired_at=NOW + timedelta(minutes=1),
                    ttl=timedelta(minutes=30),
                )
                return lease.lease_id
        except ControlPlaneError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, job_ids))
    assert len(set(outcomes)) == 1
    assert outcomes[0].startswith("workerlease_")
    with sessions() as session:
        held = list(
            session.scalars(
                select(WorkerLeaseRecord).where(
                    WorkerLeaseRecord.workflow_id == workflow_id,
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                )
            )
        )
    assert len(held) == 1
    with transaction(sessions) as session:
        terminalize_worker_lease(
            session,
            lease_id=held[0].lease_id,
            terminal_state="RELEASED",
            reason_code="TEST_CLEANUP",
            released_at=NOW + timedelta(minutes=2),
        )


def test_global_capacity_never_exceeds_three_active_leases(db_session: Session) -> None:
    roles = (
        WorkerRole.AUTHORING,
        WorkerRole.REVIEW,
        WorkerRole.ITEM_MANAGEMENT,
        WorkerRole.SUPPORT,
    )
    plan_id, workflow_id, _ = _complete_control_plane(db_session, roles=roles)
    jobs = {role: _job(db_session, workflow_id=workflow_id, role=role.value) for role in roles}
    for offset, role in enumerate(roles[:3], start=1):
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key=role.value,
            job_id=jobs[role].job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=offset),
            ttl=timedelta(minutes=30),
        )

    with pytest.raises(ControlPlaneError) as captured:
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key=WorkerRole.SUPPORT.value,
            job_id=jobs[WorkerRole.SUPPORT].job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=4),
            ttl=timedelta(minutes=30),
        )
    assert captured.value.code == "CONTROL_CAPACITY_EXHAUSTED"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(WorkerLeaseRecord)
            .where(WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")))
        )
        == 3
    )


def test_knowledge_analysis_capacity_is_one_across_pools(db_session: Session) -> None:
    roles = (WorkerRole.AUTHORING, WorkerRole.REVIEW)
    plan_id, workflow_id, _ = _complete_control_plane(db_session, roles=roles)
    authoring_job = _job(db_session, workflow_id=workflow_id, role="authoring")
    review_job = _job(db_session, workflow_id=workflow_id, role="review")
    acquire_worker_lease(
        db_session,
        plan_id=plan_id,
        step_key="authoring",
        job_id=authoring_job.job_id,
        attempt=1,
        workload_class="KNOWLEDGE_ANALYSIS",
        acquired_at=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=30),
    )

    with pytest.raises(ControlPlaneError) as captured:
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key="review",
            job_id=review_job.job_id,
            attempt=1,
            workload_class="KNOWLEDGE_ANALYSIS",
            acquired_at=NOW + timedelta(minutes=2),
            ttl=timedelta(minutes=30),
        )
    assert captured.value.code == "CONTROL_KNOWLEDGE_CAPACITY_EXHAUSTED"


def test_gpu_capacity_is_one_across_distinct_role_pools(db_session: Session) -> None:
    roles = (WorkerRole.IMAGE, WorkerRole.ITEM_MANAGEMENT)
    plan_id, workflow_id, _ = _complete_control_plane(db_session, roles=roles)
    second_gpu_slot = db_session.get(WorkerSlotRecord, "04")
    assert second_gpu_slot is not None
    second_gpu_slot.gpu = True
    db_session.flush()
    image_job = _job(db_session, workflow_id=workflow_id, role="image")
    management_job = _job(db_session, workflow_id=workflow_id, role="item_management")
    acquire_worker_lease(
        db_session,
        plan_id=plan_id,
        step_key="image",
        job_id=image_job.job_id,
        attempt=1,
        workload_class="CODEX",
        acquired_at=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=30),
    )

    with pytest.raises(ControlPlaneError) as captured:
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key="item_management",
            job_id=management_job.job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=2),
            ttl=timedelta(minutes=30),
        )
    assert captured.value.code == "CONTROL_ELIGIBLE_SLOT_UNAVAILABLE"


def test_reviewed_capability_snapshot_and_drain_fail_closed(db_session: Session) -> None:
    plan_id, workflow_id, _ = _complete_control_plane(db_session)
    binding = db_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
    )
    assert binding is not None
    policy = ReviewedCapabilityPolicy.model_validate(
        {
            "version": 1,
            "expected_codex_cli_version": "0.147.0",
            "models": [
                {
                    "model": "gpt-5.6-terra",
                    "reasoning_efforts": ["medium", "high", "xhigh"],
                }
            ],
        }
    )

    snapshot = record_reviewed_capability_snapshot(
        db_session,
        binding_id=binding.binding_id,
        policy=policy,
        observed_at=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=15),
        cli_observation=("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
    )

    assert snapshot.source == "OPERATOR_ASSERTED"
    assert snapshot.snapshot_sha256.startswith("sha256:")
    assert (
        db_session.get(CodexCapabilitySnapshotRecord, snapshot.capability_snapshot_id) is snapshot
    )

    drained = set_auth_binding_operational_state(
        db_session,
        binding_id=binding.binding_id,
        state="DRAINING",
        reason_code="OPERATOR_DRAIN",
        observed_at=NOW + timedelta(minutes=2),
        ttl=timedelta(minutes=15),
    )
    assert drained.state == "DRAINING"
    job = _job(db_session, workflow_id=workflow_id)
    with pytest.raises(ControlPlaneError) as captured:
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key="authoring",
            job_id=job.job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=3),
            ttl=timedelta(minutes=10),
        )
    assert captured.value.code == "CONTROL_ELIGIBLE_SLOT_UNAVAILABLE"


def test_auth_failure_after_claim_holds_existing_lease_without_interrupt(
    db_session: Session,
) -> None:
    plan_id, workflow_id, _ = _complete_control_plane(db_session)
    job = _job(db_session, workflow_id=workflow_id)
    lease = acquire_worker_lease(
        db_session,
        plan_id=plan_id,
        step_key="authoring",
        job_id=job.job_id,
        attempt=1,
        workload_class="CODEX",
        acquired_at=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=30),
    )
    binding = db_session.get(CodexAuthBindingRecord, lease.binding_id)
    assert binding is not None
    record_auth_health(
        db_session,
        document={
            "schema_version": "codex-auth-health-view/1.0",
            "binding_id": binding.binding_id,
            "slot_key": "slot01",
            "account_label": binding.account_label,
            "state": "AUTH_REQUIRED",
            "reason_code": "CODEX_LOGIN_REQUIRED",
            "codex_cli_version": "0.147.0",
            "observed_at": (NOW + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "valid_until": (NOW + timedelta(minutes=17)).isoformat().replace("+00:00", "Z"),
        },
    )

    replay = acquire_worker_lease(
        db_session,
        plan_id=plan_id,
        step_key="authoring",
        job_id=job.job_id,
        attempt=1,
        workload_class="CODEX",
        acquired_at=NOW + timedelta(minutes=3),
        ttl=timedelta(minutes=30),
    )

    assert replay.lease_id == lease.lease_id
    assert replay.state == "ACTIVE"
    assert replay.released_at is None


@pytest.mark.parametrize(
    ("process_state", "expected_lease_state", "expected_reason"),
    (
        ("ABSENT", "EXPIRED", "PROCESS_ABSENT"),
        ("RUNNING", "RECONCILING", "PROCESS_STILL_RUNNING"),
        ("UNKNOWN", "RECONCILING", "PROCESS_STATE_UNKNOWN"),
    ),
)
def test_capacity_controller_reconciles_exact_unit_before_slot_reuse(
    db_session: Session,
    process_state: str,
    expected_lease_state: str,
    expected_reason: str,
) -> None:
    plan_id, workflow_id, _ = _complete_control_plane(db_session)
    job = _job(db_session, workflow_id=workflow_id)
    job_id = job.job_id
    sessions = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    observed_units: list[tuple[str, str]] = []

    def inspect(slot: Any, inspected_job_id: str) -> WorkerUnitActivity:
        observed_units.append((slot.slot_id, inspected_job_id))
        return WorkerUnitActivity(
            process_state,
            f"eom-worker-{slot.slot_id}@{inspected_job_id}.service",
            None,
        )

    controller = CodexCapacityController(sessions, activity_inspector=inspect)
    baseline = controller.metrics(observed_at=NOW + timedelta(minutes=1))
    claimed = controller.claim(
        LeaseClaim(
            plan_id=plan_id,
            step_key="authoring",
            job_id=job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=1),
            ttl=timedelta(seconds=30),
        )
    )

    outcomes = controller.reconcile_expired(observed_at=NOW + timedelta(minutes=2))

    assert observed_units == [("01", job_id)]
    assert len(outcomes) == 1
    assert outcomes[0].lease_id == claimed.lease_id
    assert outcomes[0].lease_state == expected_lease_state
    assert outcomes[0].reason_code == expected_reason
    with sessions() as session:
        persisted = session.get(WorkerLeaseRecord, claimed.lease_id)
        assert persisted is not None and persisted.state == expected_lease_state
        events = tuple(
            session.scalars(
                select(WorkerLeaseEventRecord)
                .where(WorkerLeaseEventRecord.lease_id == claimed.lease_id)
                .order_by(WorkerLeaseEventRecord.sequence)
            )
        )
        assert tuple(event.new_state for event in events) == (
            "ACTIVE",
            "RECONCILING",
        ) + (("EXPIRED",) if process_state == "ABSENT" else ())

    metrics = controller.metrics(observed_at=NOW + timedelta(minutes=2))
    assert metrics.queued_jobs == baseline.queued_jobs
    assert metrics.failed_jobs == baseline.failed_jobs
    assert metrics.active_leases == baseline.active_leases
    assert metrics.reconciling_leases == baseline.reconciling_leases + (
        0 if process_state == "ABSENT" else 1
    )
    assert metrics.released_leases == baseline.released_leases
    assert metrics.expired_leases == baseline.expired_leases + (
        1 if process_state == "ABSENT" else 0
    )
    assert metrics.held_gpu_leases == baseline.held_gpu_leases
    assert metrics.held_knowledge_analysis_leases == baseline.held_knowledge_analysis_leases
    assert metrics.oldest_queued_seconds is not None
    assert (metrics.oldest_held_seconds is not None) == (process_state != "ABSENT")


def test_reconciling_lease_is_reinspected_after_controller_restart(
    db_session: Session,
) -> None:
    plan_id, workflow_id, _ = _complete_control_plane(db_session)
    job = _job(db_session, workflow_id=workflow_id)
    job_id = job.job_id
    sessions = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    states = iter(("RUNNING", "ABSENT"))

    def inspect(slot: Any, inspected_job_id: str) -> WorkerUnitActivity:
        state = next(states)
        return WorkerUnitActivity(
            state,
            f"eom-worker-{slot.slot_id}@{inspected_job_id}.service",
            None,
        )

    controller = CodexCapacityController(sessions, activity_inspector=inspect)
    claimed = controller.claim(
        LeaseClaim(
            plan_id=plan_id,
            step_key="authoring",
            job_id=job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=1),
            ttl=timedelta(seconds=30),
        )
    )

    first = controller.reconcile_expired(observed_at=NOW + timedelta(minutes=2))
    second = controller.reconcile_expired(observed_at=NOW + timedelta(minutes=3))

    assert first[0].lease_state == "RECONCILING"
    assert second[0].lease_state == "EXPIRED"
    with sessions() as session:
        lease = session.get(WorkerLeaseRecord, claimed.lease_id)
        assert lease is not None and lease.state == "EXPIRED"


def test_capacity_controller_does_not_allow_manual_ready_state(db_session: Session) -> None:
    _complete_control_plane(db_session)
    binding = db_session.scalar(select(CodexAuthBindingRecord))
    assert binding is not None

    with pytest.raises(ValueError, match="DRAINING or DISABLED"):
        set_auth_binding_operational_state(
            db_session,
            binding_id=binding.binding_id,
            state="READY",
            reason_code="OPERATOR_READY",
            observed_at=NOW + timedelta(minutes=1),
            ttl=timedelta(minutes=15),
        )


def test_historical_protocol_rows_remain_byte_identical(db_session: Session) -> None:
    _seed_protocols_and_slots(db_session)
    old = db_session.get(ProtocolVersionRecord, "workflow-role/1.2.0")
    if old is not None:
        assert old.schema_sha256 == role_schema_bundle_hash("workflow-role/1.2.0")
    current = db_session.get(ProtocolVersionRecord, "workflow-role/1.3.0")
    assert current is not None
    assert current.schema_sha256 == role_schema_bundle_hash("workflow-role/1.3.0")
    assert db_session.get(WorkerSlotRecord, "01") is not None


def test_alembic_head_matches_composed_sqlalchemy_metadata(integration_engine: Engine) -> None:
    with integration_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, Base.metadata)
    assert differences == []
