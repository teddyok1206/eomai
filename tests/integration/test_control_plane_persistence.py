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
from eom_orchestrator.control_models import (
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
from eom_workflow import ControlArtifactPointer
from eom_workflow.control_plane import WorkerRole
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import Engine, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

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
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + suffix,
        definition_key="generic-item-development",
        definition_version="1.4.0",
        schema_version="1.0",
        canonical_definition={"fixture": True},
        definition_hash="sha256:" + uuid4().hex * 2,
        active=True,
        source_path="config/workflows/generic-item-development.v1.4.yaml",
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


def _complete_control_plane(session: Session) -> tuple[str, str, str]:
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
                    "pool_key": "authoring",
                    "roles": ["authoring"],
                    "slot_keys": ["slot01"],
                    "max_active": 1,
                }
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
                    "role": "authoring",
                    "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "high"}],
                    "instruction_bundle": instruction_pointer,
                    "reference_bundle": reference_pointer,
                    "worker_pool_key": "authoring",
                    "timeout_seconds": 1800,
                    "sandbox": "read-only",
                    "network": "disabled",
                }
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
        steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
        resolved_at=NOW,
    )
    replay = resolve_execution_plan(
        session,
        preset_key=preset_key,
        dependencies=dependencies,
        steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
        resolved_at=NOW + timedelta(days=1),
    )
    assert replay == first_plan
    assert first_plan.steps[0].model == "gpt-5.6-terra"
    assert first_plan.steps[0].reasoning_effort == "high"

    binding_id = new_auth_binding_id()
    health = {
        "schema_version": "codex-auth-health-view/1.0",
        "binding_id": binding_id,
        "slot_key": "slot01",
        "account_label": "phase2-slot01",
        "state": "READY",
        "reason_code": None,
        "codex_cli_version": "0.147.0",
        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
        "valid_until": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    record_auth_health(session, document=health)
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
