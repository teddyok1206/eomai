from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import eom_catalog_service.knowledge_graph_models
import eom_catalog_service.legacy_usage_models
import eom_catalog_service.models  # noqa: F401
import eom_hwpx_manager.models  # noqa: F401
import eom_identity_service.models  # noqa: F401
import eom_orchestrator.knowledge_analysis_models  # noqa: F401
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
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_orchestrator.auth_enrollment import (
    build_codex_auth_enrollment_request,
    claim_due_codex_auth_enrollment,
    create_auth_assignment_revision,
    create_codex_auth_enrollment,
    enrollment_status_document,
    mark_codex_device_login_started,
    transition_codex_auth_enrollment,
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
from eom_orchestrator.control_bootstrap import (
    KnowledgeAnalysisBootstrapResult,
    StandardBootstrapResult,
    bootstrap_knowledge_analysis_control_plane,
    bootstrap_standard_control_plane,
)
from eom_orchestrator.control_command_processor import (
    AUTH_OBSERVATION_TTL,
    AUTOMATIC_OBSERVATION_CHECK_INTERVAL,
    AUTOMATIC_OBSERVATION_REFRESH_LEAD,
    CAPABILITY_OBSERVATION_TTL,
    CodexControlCommandProcessor,
)
from eom_orchestrator.control_commands import (
    build_codex_control_command,
    claim_next_codex_control_command,
    enqueue_codex_control_command,
    terminalize_codex_control_command,
)
from eom_orchestrator.control_models import (
    CodexAuthAssignmentRevisionRecord,
    CodexAuthBindingRecord,
    CodexAuthEnrollmentRecord,
    CodexAuthHealthEventRecord,
    CodexCapabilityEntryRecord,
    CodexCapabilitySnapshotRecord,
    CodexControlCommandRecord,
    ExecutionBundleRevisionRecord,
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    WorkerCapacityPolicyRecord,
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
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
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
from eom_orchestrator.preset_lifecycle import (
    create_execution_preset_draft,
    deprecate_execution_preset,
    execution_preset_policy_sha256,
    record_execution_preset_evaluation,
    release_execution_preset,
)
from eom_orchestrator.protocol import protocol_schema_hash
from eom_orchestrator.repository import ensure_protocol_version, upsert_worker_slot
from eom_orchestrator.settings import Settings
from eom_orchestrator.worker_auth import WorkerAuthObservation
from eom_orchestrator.worker_registry import FIXED_WORKER_SLOT_IDS
from eom_orchestrator.worker_systemd import WorkerUnitActivity
from eom_workflow import ControlArtifactPointer
from eom_workflow.control_plane import WorkerRole
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    claim_next_command,
    claimable_command_exists,
    enqueue_command,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _self_hash(document: dict[str, Any], field: str) -> dict[str, Any]:
    document[field] = compute_control_document_hash(document, field)
    return document


def _seed_protocols_and_slots(
    session: Session,
    *,
    additional_slots: dict[WorkerRole, str] | None = None,
) -> None:
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
    for role, slot_id in (additional_slots or {}).items():
        upsert_worker_slot(
            session,
            slot_id=slot_id,
            linux_user=f"eom-cdx-{slot_id}",
            role=role.value,
            enabled=True,
            gpu=role is WorkerRole.IMAGE,
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
    slot_id_by_role: dict[WorkerRole, str] | None = None,
) -> tuple[str, str, str]:
    resolved_slot_ids = {
        WorkerRole.AUTHORING: "01",
        WorkerRole.REVIEW: "02",
        WorkerRole.IMAGE: "03",
        WorkerRole.ITEM_MANAGEMENT: "04",
        WorkerRole.SUPPORT: "05",
        **(slot_id_by_role or {}),
    }
    _seed_protocols_and_slots(session, additional_slots=slot_id_by_role)
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
                    "slot_keys": ["slot" + resolved_slot_ids[role]],
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

    for role in roles:
        slot_id = resolved_slot_ids[role]
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
        # This test commits across independent connections. Use a disposable slot identity so
        # its durable fixture cannot collide with the fixed slot01 bootstrap contract below.
        plan_id, workflow_id, _ = _complete_control_plane(
            session,
            slot_id_by_role={WorkerRole.AUTHORING: "11"},
        )
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


def test_global_capacity_counts_held_leases_across_policy_revisions(
    db_session: Session,
) -> None:
    plans: list[tuple[str, str, WorkerRole]] = []
    for role in (
        WorkerRole.AUTHORING,
        WorkerRole.REVIEW,
        WorkerRole.ITEM_MANAGEMENT,
        WorkerRole.SUPPORT,
    ):
        plan_id, workflow_id, _ = _complete_control_plane(db_session, roles=(role,))
        plans.append((plan_id, workflow_id, role))

    for offset, (plan_id, workflow_id, role) in enumerate(plans[:3], start=1):
        job = _job(db_session, workflow_id=workflow_id, role=role.value)
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key=role.value,
            job_id=job.job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=offset),
            ttl=timedelta(minutes=30),
        )

    plan_id, workflow_id, role = plans[3]
    fourth_job = _job(db_session, workflow_id=workflow_id, role=role.value)
    with pytest.raises(ControlPlaneError) as captured:
        acquire_worker_lease(
            db_session,
            plan_id=plan_id,
            step_key=role.value,
            job_id=fourth_job.job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=4),
            ttl=timedelta(minutes=30),
        )
    assert captured.value.code == "CONTROL_CAPACITY_EXHAUSTED"


def test_concurrent_cross_policy_claims_share_one_host_capacity_lock(
    integration_engine: Engine,
) -> None:
    sessions = build_session_factory(integration_engine)
    plans: list[tuple[str, str, WorkerRole]] = []
    disposable_slots = {
        WorkerRole.AUTHORING: "21",
        WorkerRole.REVIEW: "22",
        WorkerRole.ITEM_MANAGEMENT: "24",
        WorkerRole.SUPPORT: "25",
    }
    with transaction(sessions) as session:
        for role in (
            WorkerRole.AUTHORING,
            WorkerRole.REVIEW,
            WorkerRole.ITEM_MANAGEMENT,
            WorkerRole.SUPPORT,
        ):
            plan_id, workflow_id, _ = _complete_control_plane(
                session,
                roles=(role,),
                slot_id_by_role={role: disposable_slots[role]},
            )
            plans.append((plan_id, workflow_id, role))
        jobs = [
            _job(session, workflow_id=workflow_id, role=role.value)
            for _, workflow_id, role in plans
        ]

    for offset in range(2):
        plan_id, _, role = plans[offset]
        with transaction(sessions) as session:
            acquire_worker_lease(
                session,
                plan_id=plan_id,
                step_key=role.value,
                job_id=jobs[offset].job_id,
                attempt=1,
                workload_class="CODEX",
                acquired_at=NOW + timedelta(minutes=offset + 1),
                ttl=timedelta(minutes=30),
            )

    barrier = Barrier(2)

    def claim(index: int) -> str:
        plan_id, _, role = plans[index]
        barrier.wait(timeout=5)
        try:
            with transaction(sessions) as session:
                lease = acquire_worker_lease(
                    session,
                    plan_id=plan_id,
                    step_key=role.value,
                    job_id=jobs[index].job_id,
                    attempt=1,
                    workload_class="CODEX",
                    acquired_at=NOW + timedelta(minutes=3),
                    ttl=timedelta(minutes=30),
                )
                return lease.lease_id
        except ControlPlaneError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, (2, 3)))
    assert sum(value.startswith("workerlease_") for value in outcomes) == 1
    assert outcomes.count("CONTROL_CAPACITY_EXHAUSTED") == 1
    workflow_ids = tuple(workflow_id for _, workflow_id, _ in plans)
    with sessions() as session:
        held = tuple(
            session.scalars(
                select(WorkerLeaseRecord).where(
                    WorkerLeaseRecord.workflow_id.in_(workflow_ids),
                    WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING")),
                )
            )
        )
    assert len(held) == 3
    with transaction(sessions) as session:
        for lease in held:
            terminalize_worker_lease(
                session,
                lease_id=lease.lease_id,
                terminal_state="RELEASED",
                reason_code="TEST_CLEANUP",
                released_at=NOW + timedelta(minutes=4),
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


def test_knowledge_analysis_capacity_counts_held_leases_across_policy_revisions(
    db_session: Session,
) -> None:
    first_plan, first_workflow, _ = _complete_control_plane(
        db_session,
        roles=(WorkerRole.AUTHORING,),
    )
    second_plan, second_workflow, _ = _complete_control_plane(
        db_session,
        roles=(WorkerRole.REVIEW,),
    )
    first_job = _job(db_session, workflow_id=first_workflow, role="authoring")
    second_job = _job(db_session, workflow_id=second_workflow, role="review")
    acquire_worker_lease(
        db_session,
        plan_id=first_plan,
        step_key="authoring",
        job_id=first_job.job_id,
        attempt=1,
        workload_class="KNOWLEDGE_ANALYSIS",
        acquired_at=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=30),
    )

    with pytest.raises(ControlPlaneError) as captured:
        acquire_worker_lease(
            db_session,
            plan_id=second_plan,
            step_key="review",
            job_id=second_job.job_id,
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


def test_gpu_capacity_counts_held_leases_across_policy_revisions(
    db_session: Session,
) -> None:
    image_plan, image_workflow, _ = _complete_control_plane(
        db_session,
        roles=(WorkerRole.IMAGE,),
    )
    management_plan, management_workflow, _ = _complete_control_plane(
        db_session,
        roles=(WorkerRole.ITEM_MANAGEMENT,),
    )
    second_gpu_slot = db_session.get(WorkerSlotRecord, "04")
    assert second_gpu_slot is not None
    second_gpu_slot.gpu = True
    db_session.flush()
    image_job = _job(db_session, workflow_id=image_workflow, role="image")
    management_job = _job(
        db_session,
        workflow_id=management_workflow,
        role="item_management",
    )
    acquire_worker_lease(
        db_session,
        plan_id=image_plan,
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
            plan_id=management_plan,
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


def test_automatic_observation_renews_due_idle_binding_without_command(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _complete_control_plane(db_session)
    binding = db_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
    )
    assert binding is not None
    observed_at = NOW + timedelta(minutes=55)
    policy = ReviewedCapabilityPolicy.model_validate(
        {
            "version": 1,
            "expected_codex_cli_version": "0.147.0",
            "models": [
                {
                    "model": "gpt-5.6-terra",
                    "reasoning_efforts": ["high", "xhigh"],
                }
            ],
        }
    )
    observed_slots: list[str] = []

    def observe(**kwargs: Any) -> WorkerAuthObservation:
        slot = kwargs["slot"]
        observed_slots.append(slot.slot_id)
        return WorkerAuthObservation(
            binding_id=kwargs["binding_id"],
            slot_key=f"slot{slot.slot_id}",
            account_label=kwargs["account_label"],
            state="READY",
            reason_code=None,
            codex_cli_version="0.147.0",
            observed_at=kwargs["observed_at"],
            valid_until=kwargs["observed_at"] + kwargs["ttl"],
            probe_unit_name=f"eom-worker-auth-{slot.slot_id}.service",
        )

    monkeypatch.setattr("eom_orchestrator.control_command_processor.observe_worker_auth", observe)
    monkeypatch.setattr(
        "eom_orchestrator.control_command_processor.load_reviewed_capability_policy",
        lambda _path: policy,
    )
    monkeypatch.setattr(
        "eom_orchestrator.control_command_processor.observe_codex_cli_surface",
        lambda: ("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
    )
    sessions = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    processor = CodexControlCommandProcessor(
        sessions,
        capability_policy_path=Path("/reviewed/codex-capabilities.yaml"),
        runner_id="runner-automatic-observation-test",
        now=lambda: observed_at,
    )

    assert processor.maintain_once() == binding.binding_id
    assert processor.maintain_once() is None
    db_session.expire_all()
    refreshed = db_session.get(CodexAuthBindingRecord, binding.binding_id)
    assert refreshed is not None
    assert refreshed.state == "READY"
    assert refreshed.observed_at == observed_at
    assert refreshed.valid_until == observed_at + timedelta(hours=1)
    snapshot = db_session.scalar(
        select(CodexCapabilitySnapshotRecord)
        .where(CodexCapabilitySnapshotRecord.binding_id == binding.binding_id)
        .order_by(CodexCapabilitySnapshotRecord.observed_at.desc())
        .limit(1)
    )
    assert snapshot is not None
    assert snapshot.source == "LOCAL_OBSERVATION"
    assert snapshot.observed_at == observed_at
    assert {
        (entry.model, entry.reasoning_effort, entry.state)
        for entry in db_session.scalars(
            select(CodexCapabilityEntryRecord).where(
                CodexCapabilityEntryRecord.capability_snapshot_id == snapshot.capability_snapshot_id
            )
        )
    } == {
        ("gpt-5.6-terra", "high", "AVAILABLE"),
        ("gpt-5.6-terra", "xhigh", "AVAILABLE"),
    }
    assert db_session.scalar(select(func.count(CodexControlCommandRecord.command_id))) == 0
    assert observed_slots == ["01"]


def test_automatic_observation_window_covers_every_fixed_slot() -> None:
    assert timedelta(hours=1) == AUTH_OBSERVATION_TTL
    assert timedelta(hours=1) == CAPABILITY_OBSERVATION_TTL
    assert timedelta(minutes=30) == AUTOMATIC_OBSERVATION_REFRESH_LEAD
    assert FIXED_WORKER_SLOT_IDS == ("01", "02", "03", "04", "05", "06")
    assert AUTOMATIC_OBSERVATION_REFRESH_LEAD >= (AUTOMATIC_OBSERVATION_CHECK_INTERVAL * 5)


def test_automatic_observation_defers_to_pending_command(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _complete_control_plane(db_session)
    binding = db_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
    )
    assert binding is not None
    operator = OperatorRecord(
        operator_id="operator_" + uuid4().hex,
        username=f"automatic-{uuid4().hex[:12]}",
        normalized_username=f"automatic-{uuid4().hex}",
        display_name="Automatic observation test operator",
        status="ACTIVE",
        must_change_password=False,
        role_version=1,
        created_by="automatic-observation-test",
    )
    db_session.add(operator)
    command = build_codex_control_command(
        command_type="OBSERVE",
        binding_id=binding.binding_id,
        expected_resource_version=binding.resource_version,
        requested_by_operator_id=operator.operator_id,
        requested_at=NOW + timedelta(minutes=55),
        reason_code=None,
    )
    enqueue_codex_control_command(
        db_session,
        document=command,
        idempotency_key=f"automatic-observe:{uuid4().hex}",
    )
    db_session.flush()
    sessions = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    processor = CodexControlCommandProcessor(
        sessions,
        capability_policy_path=Path("/reviewed/codex-capabilities.yaml"),
        runner_id="runner-pending-command-test",
        now=lambda: NOW + timedelta(minutes=55),
    )
    monkeypatch.setattr(
        "eom_orchestrator.control_command_processor.observe_worker_auth",
        lambda **_kwargs: pytest.fail("automatic observation must defer to a pending command"),
    )

    assert processor.maintain_once() is None


def test_automatic_observation_recovers_after_local_login_becomes_ready(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _complete_control_plane(db_session)
    binding = db_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
    )
    assert binding is not None
    clock = [NOW + timedelta(minutes=55)]
    states = iter(("AUTH_REQUIRED", "READY"))
    policy = ReviewedCapabilityPolicy.model_validate(
        {
            "version": 1,
            "expected_codex_cli_version": "0.147.0",
            "models": [
                {
                    "model": "gpt-5.6-terra",
                    "reasoning_efforts": ["xhigh"],
                }
            ],
        }
    )

    def observe(**kwargs: Any) -> WorkerAuthObservation:
        state = next(states)
        slot = kwargs["slot"]
        return WorkerAuthObservation(
            binding_id=kwargs["binding_id"],
            slot_key=f"slot{slot.slot_id}",
            account_label=kwargs["account_label"],
            state=state,
            reason_code=None if state == "READY" else "CODEX_LOGIN_REQUIRED",
            codex_cli_version="0.147.0",
            observed_at=kwargs["observed_at"],
            valid_until=kwargs["observed_at"] + kwargs["ttl"],
            probe_unit_name=f"eom-worker-auth-{slot.slot_id}.service",
        )

    monkeypatch.setattr("eom_orchestrator.control_command_processor.observe_worker_auth", observe)
    monkeypatch.setattr(
        "eom_orchestrator.control_command_processor.load_reviewed_capability_policy",
        lambda _path: policy,
    )
    monkeypatch.setattr(
        "eom_orchestrator.control_command_processor.observe_codex_cli_surface",
        lambda: ("0.147.0", REQUIRED_EXEC_HELP_FLAGS),
    )
    sessions = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    processor = CodexControlCommandProcessor(
        sessions,
        capability_policy_path=Path("/reviewed/codex-capabilities.yaml"),
        runner_id="runner-auth-recovery-test",
        now=lambda: clock[0],
    )

    assert processor.maintain_once() == binding.binding_id
    db_session.expire_all()
    unavailable = db_session.get(CodexAuthBindingRecord, binding.binding_id)
    assert unavailable is not None
    assert unavailable.state == "AUTH_REQUIRED"
    assert unavailable.reason_code == "CODEX_LOGIN_REQUIRED"

    clock[0] += timedelta(minutes=5)
    assert processor.maintain_once() == binding.binding_id
    db_session.expire_all()
    recovered = db_session.get(CodexAuthBindingRecord, binding.binding_id)
    assert recovered is not None
    assert recovered.state == "READY"
    assert recovered.reason_code is None
    snapshot = db_session.scalar(
        select(CodexCapabilitySnapshotRecord)
        .where(CodexCapabilitySnapshotRecord.binding_id == binding.binding_id)
        .order_by(CodexCapabilitySnapshotRecord.observed_at.desc())
        .limit(1)
    )
    assert snapshot is not None
    assert snapshot.source == "LOCAL_OBSERVATION"
    assert snapshot.observed_at == clock[0]
    assert db_session.scalar(select(func.count(CodexControlCommandRecord.command_id))) == 0


def test_automatic_observation_does_not_interrupt_held_lease(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
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
    db_session.flush()
    sessions = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    processor = CodexControlCommandProcessor(
        sessions,
        capability_policy_path=Path("/reviewed/codex-capabilities.yaml"),
        runner_id="runner-held-lease-test",
        now=lambda: NOW + timedelta(minutes=55),
    )
    monkeypatch.setattr(
        "eom_orchestrator.control_command_processor.observe_worker_auth",
        lambda **_kwargs: pytest.fail("automatic observation must not interrupt a held lease"),
    )

    assert lease.state == "ACTIVE"
    assert processor.maintain_once() is None
    assert (
        db_session.scalar(
            select(func.count(CodexAuthHealthEventRecord.event_id)).where(
                CodexAuthHealthEventRecord.binding_id == lease.binding_id
            )
        )
        == 1
    )


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


def test_uncertain_worker_terminal_state_reconciles_before_slot_reuse(
    db_session: Session,
) -> None:
    plan_id, workflow_id, _ = _complete_control_plane(db_session)
    job = _job(db_session, workflow_id=workflow_id)
    sessions = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    controller = CodexCapacityController(
        sessions,
        activity_inspector=lambda slot, job_id: WorkerUnitActivity(
            "ABSENT", f"eom-worker-{slot.slot_id}@{job_id}.service", None
        ),
    )
    claimed = controller.claim(
        LeaseClaim(
            plan_id=plan_id,
            step_key="authoring",
            job_id=job.job_id,
            attempt=1,
            workload_class="CODEX",
            acquired_at=NOW + timedelta(minutes=1),
            ttl=timedelta(minutes=30),
        )
    )

    held = controller.defer_uncertain_process(
        lease_id=claimed.lease_id,
        observed_at=NOW + timedelta(minutes=2),
    )
    outcomes = controller.reconcile_expired(observed_at=NOW + timedelta(minutes=2))

    assert held.state == "RECONCILING"
    assert outcomes[0].lease_state == "EXPIRED"
    with sessions() as session:
        events = tuple(
            session.scalars(
                select(WorkerLeaseEventRecord)
                .where(WorkerLeaseEventRecord.lease_id == claimed.lease_id)
                .order_by(WorkerLeaseEventRecord.sequence)
            )
        )
        assert [event.reason_code for event in events] == [
            None,
            "PROCESS_TERMINAL_UNCONFIRMED",
            "PROCESS_ABSENT",
        ]


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


def test_preset_lifecycle_requires_exact_pass_evidence_and_preserves_history(
    db_session: Session,
) -> None:
    _complete_control_plane(db_session)
    template = db_session.scalar(
        select(ExecutionPresetRevisionRecord).where(
            ExecutionPresetRevisionRecord.state == "RELEASED"
        )
    )
    assert template is not None
    draft = create_execution_preset_draft(
        db_session,
        preset_key=f"phase5-draft-{uuid4().hex[:12]}",
        display_name="Phase 5 standard",
        description="Disposable immutable preset lifecycle fixture.",
        role_policies=list(template.canonical_document["role_policies"]),
        capacity_policy_revision_id=template.capacity_policy_revision_id,
        general_knowledge_policy=template.general_knowledge_policy,
        compatible_workflow_protocols=list(template.compatible_workflow_protocols),
        created_by="phase5-test",
        created_at=NOW + timedelta(minutes=20),
    )
    policy_sha256 = execution_preset_policy_sha256(draft.canonical_document)

    static_pointer = _artifact_pointer(
        db_session,
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        logical_name="static-evaluation.json",
    )
    static_report = _self_hash(
        {
            "schema_version": "execution-preset-evaluation-report/1.0",
            "evaluated_preset_revision_id": draft.preset_revision_id,
            "evaluated_policy_sha256": policy_sha256,
            "scope": "STATIC",
            "outcome": "PASS",
            "summary_code": "CONTRACT_VALIDATION",
            "cases_total": 12,
            "cases_passed": 12,
            "quality_score_permille": None,
            "completed_at": (NOW + timedelta(minutes=21)).isoformat().replace("+00:00", "Z"),
            "report_sha256": "sha256:" + "0" * 64,
        },
        "report_sha256",
    )
    static_evaluation = record_execution_preset_evaluation(
        db_session,
        document=static_report,
        report_artifact=static_pointer,
        created_by="phase5-test",
    )
    assert static_evaluation.scope == "STATIC"
    with pytest.raises(ControlPlaneError) as missing_evidence:
        release_execution_preset(
            db_session,
            draft_revision_id=draft.preset_revision_id,
            released_by="phase5-test",
            released_at=NOW + timedelta(minutes=22),
        )
    assert missing_evidence.value.code == "CONTROL_PRESET_EVALUATION_REQUIRED"

    non_live_pointer = _artifact_pointer(
        db_session,
        schema_ref="eom://schemas/workflow/execution-preset-evaluation-report/1.0",
        media_type="application/json",
        logical_name="non-live-evaluation.json",
    )
    non_live_report = _self_hash(
        {
            "schema_version": "execution-preset-evaluation-report/1.0",
            "evaluated_preset_revision_id": draft.preset_revision_id,
            "evaluated_policy_sha256": policy_sha256,
            "scope": "NON_LIVE",
            "outcome": "PASS",
            "summary_code": "FAKE_ADAPTER_ACCEPTANCE",
            "cases_total": 28,
            "cases_passed": 28,
            "quality_score_permille": 1000,
            "completed_at": (NOW + timedelta(minutes=23)).isoformat().replace("+00:00", "Z"),
            "report_sha256": "sha256:" + "0" * 64,
        },
        "report_sha256",
    )
    evidence = record_execution_preset_evaluation(
        db_session,
        document=non_live_report,
        report_artifact=non_live_pointer,
        created_by="phase5-test",
    )
    released = release_execution_preset(
        db_session,
        draft_revision_id=draft.preset_revision_id,
        released_by="phase5-test",
        released_at=NOW + timedelta(minutes=24),
    )
    logical = db_session.get(ExecutionPresetRecord, draft.preset_id)
    assert logical is not None
    assert evidence.evaluated_preset_revision_id == draft.preset_revision_id
    assert released.state == "RELEASED"
    assert released.preset_revision_id != draft.preset_revision_id
    assert execution_preset_policy_sha256(released.canonical_document) == policy_sha256
    assert logical.current_revision_id == released.preset_revision_id

    deprecated = deprecate_execution_preset(
        db_session,
        preset_id=logical.preset_id,
        deprecated_by="phase5-test",
        deprecated_at=NOW + timedelta(minutes=25),
    )
    assert deprecated.state == "DEPRECATED"
    assert logical.state == "RETIRED"
    assert logical.current_revision_id == released.preset_revision_id
    assert db_session.get(ExecutionPresetEvaluationRecord, evidence.evaluation_id) is evidence
    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        released.description = "forbidden mutation"
        db_session.flush()


def test_control_command_is_idempotent_leased_sanitized_and_terminal(
    db_session: Session,
) -> None:
    _complete_control_plane(db_session)
    binding = db_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
    )
    assert binding is not None
    operator = OperatorRecord(
        operator_id="operator_" + uuid4().hex,
        username=f"phase5-{uuid4().hex[:12]}",
        normalized_username=f"phase5-{uuid4().hex}",
        display_name="Phase 5 test operator",
        status="ACTIVE",
        must_change_password=False,
        role_version=1,
        created_by="phase5-test",
    )
    db_session.add(operator)
    db_session.flush()
    document = build_codex_control_command(
        command_type="OBSERVE",
        binding_id=binding.binding_id,
        expected_resource_version=binding.resource_version,
        requested_by_operator_id=operator.operator_id,
        requested_at=NOW + timedelta(minutes=30),
        reason_code=None,
    )
    key = f"phase5-control:{uuid4().hex}"
    command = enqueue_codex_control_command(
        db_session,
        document=document,
        idempotency_key=key,
    )
    replay = enqueue_codex_control_command(
        db_session,
        document=document,
        idempotency_key=key,
    )
    assert replay.command_id == command.command_id
    conflict_document = build_codex_control_command(
        command_type="OBSERVE",
        binding_id=binding.binding_id,
        expected_resource_version=binding.resource_version,
        requested_by_operator_id=operator.operator_id,
        requested_at=NOW + timedelta(minutes=31),
        reason_code=None,
    )
    with pytest.raises(ControlPlaneError) as conflict:
        enqueue_codex_control_command(
            db_session,
            document=conflict_document,
            idempotency_key=key,
        )
    assert conflict.value.code == "CONTROL_IDEMPOTENCY_CONFLICT"

    claimed = claim_next_codex_control_command(
        db_session,
        lease_owner="phase5-runner",
        claimed_at=NOW + timedelta(minutes=32),
        lease_ttl=timedelta(minutes=1),
    )
    assert claimed is not None
    assert claimed.command_id == command.command_id
    assert claimed.attempts == 1
    assert db_session.get(CodexControlCommandRecord, command.command_id) is claimed
    assert claimed.state == "PROCESSING"
    terminal = terminalize_codex_control_command(
        db_session,
        command_id=command.command_id,
        lease_owner="phase5-runner",
        outcome="SUCCEEDED",
        result_resource_version=binding.resource_version,
        binding_state=binding.state,
        reason_code=None,
        processed_at=NOW + timedelta(minutes=33),
    )
    assert terminal.state == "SUCCEEDED"
    assert terminal.result_document is not None
    serialized = str({"request": terminal.canonical_document, "result": terminal.result_document})
    assert all(
        forbidden not in serialized.casefold()
        for forbidden in ("token", "secret", "password", "credential", "auth.json")
    )
    assert (
        terminalize_codex_control_command(
            db_session,
            command_id=command.command_id,
            lease_owner="another-runner",
            outcome="FAILED",
            result_resource_version=None,
            binding_state=None,
            reason_code="SHOULD_NOT_REWRITE_TERMINAL",
            processed_at=NOW + timedelta(minutes=34),
        ).result_document
        == terminal.result_document
    )
    assert db_session.get(CodexControlCommandRecord, command.command_id) is terminal


def test_codex_auth_enrollment_is_idempotent_credential_free_and_assignment_immutable(
    db_session: Session,
) -> None:
    _complete_control_plane(db_session)
    binding = db_session.scalar(
        select(CodexAuthBindingRecord).where(CodexAuthBindingRecord.worker_slot_id == "01")
    )
    assert binding is not None
    operator = OperatorRecord(
        operator_id="operator_" + uuid4().hex,
        username=f"auth-{uuid4().hex[:12]}",
        normalized_username=f"auth-{uuid4().hex}",
        display_name="Device auth integration operator",
        status="ACTIVE",
        must_change_password=False,
        role_version=1,
        created_by="device-auth-test",
    )
    requested_at = NOW + timedelta(minutes=40)
    api_session = ApiSessionRecord(
        api_session_id="apisession_" + uuid4().hex,
        operator_id=operator.operator_id,
        token_family_id="tokenfamily_" + uuid4().hex,
        client_name="Device auth integration",
        authenticated_at=requested_at,
        created_at=requested_at,
        last_seen_at=requested_at,
        absolute_expires_at=requested_at + timedelta(days=1),
        idle_expires_at=requested_at + timedelta(hours=1),
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
        refresh_generation=1,
        lock_version=1,
    )
    # The two mapped types intentionally have no ORM relationship. Flush the
    # referenced operator first so unit-of-work ordering never depends on an
    # incidental identity-service import graph.
    db_session.add(operator)
    db_session.flush()
    db_session.add(api_session)
    db_session.flush()

    document = build_codex_auth_enrollment_request(
        binding_id=binding.binding_id,
        expected_binding_resource_version=binding.resource_version,
        slot_key=f"slot{binding.worker_slot_id}",
        requested_account_label="teacher-account-01",
        requested_by_operator_id=operator.operator_id,
        requested_by_api_session_id=api_session.api_session_id,
        requested_at=requested_at,
    )
    key = f"device-auth:{uuid4().hex}"
    enrollment = create_codex_auth_enrollment(db_session, document=document, idempotency_key=key)
    replay_document = build_codex_auth_enrollment_request(
        binding_id=binding.binding_id,
        expected_binding_resource_version=binding.resource_version,
        slot_key=f"slot{binding.worker_slot_id}",
        requested_account_label="teacher-account-01",
        requested_by_operator_id=operator.operator_id,
        requested_by_api_session_id=api_session.api_session_id,
        requested_at=requested_at,
    )
    replay = create_codex_auth_enrollment(
        db_session,
        document=replay_document,
        idempotency_key=key,
    )
    assert replay.enrollment_id == enrollment.enrollment_id
    status = enrollment_status_document(enrollment, challenge_available=False)
    serialized = str({"request": enrollment.canonical_document, "status": status}).casefold()
    assert all(
        forbidden not in serialized
        for forbidden in ("password", "access_token", "refresh_token", "auth.json")
    )

    conflict_document = build_codex_auth_enrollment_request(
        binding_id=binding.binding_id,
        expected_binding_resource_version=binding.resource_version,
        slot_key=f"slot{binding.worker_slot_id}",
        requested_account_label="another-account",
        requested_by_operator_id=operator.operator_id,
        requested_by_api_session_id=api_session.api_session_id,
        requested_at=requested_at,
    )
    with pytest.raises(ControlPlaneError) as conflict:
        create_codex_auth_enrollment(
            db_session,
            document=conflict_document,
            idempotency_key=key,
        )
    assert conflict.value.code == "CODEX_AUTH_IDEMPOTENCY_CONFLICT"

    second_document = build_codex_auth_enrollment_request(
        binding_id=binding.binding_id,
        expected_binding_resource_version=binding.resource_version,
        slot_key=f"slot{binding.worker_slot_id}",
        requested_account_label="teacher-account-02",
        requested_by_operator_id=operator.operator_id,
        requested_by_api_session_id=api_session.api_session_id,
        requested_at=requested_at,
    )
    with pytest.raises(ControlPlaneError) as already_active:
        create_codex_auth_enrollment(
            db_session,
            document=second_document,
            idempotency_key=f"device-auth:{uuid4().hex}",
        )
    assert already_active.value.code == "CODEX_AUTH_ENROLLMENT_ALREADY_ACTIVE"

    runner_id = "device-auth-integration-runner"
    draining_at = requested_at + timedelta(seconds=1)
    claimed = claim_due_codex_auth_enrollment(
        db_session,
        lease_owner=runner_id,
        claimed_at=draining_at,
    )
    assert claimed is enrollment
    transition_codex_auth_enrollment(
        db_session,
        enrollment_id=enrollment.enrollment_id,
        lease_owner=runner_id,
        target_state="DRAINING",
        transitioned_at=draining_at,
        next_action_at=draining_at,
    )
    claimed = claim_due_codex_auth_enrollment(
        db_session,
        lease_owner=runner_id,
        claimed_at=draining_at,
    )
    assert claimed is enrollment
    transition_codex_auth_enrollment(
        db_session,
        enrollment_id=enrollment.enrollment_id,
        lease_owner=runner_id,
        target_state="READY_FOR_LOGIN",
        transitioned_at=draining_at,
        next_action_at=draining_at,
    )
    claimed = claim_due_codex_auth_enrollment(
        db_session,
        lease_owner=runner_id,
        claimed_at=draining_at,
    )
    assert claimed is enrollment
    login_started_at = draining_at + timedelta(seconds=1)
    assert mark_codex_device_login_started(
        db_session,
        enrollment_id=enrollment.enrollment_id,
        lease_owner=runner_id,
        started_at=login_started_at,
    )
    assert not mark_codex_device_login_started(
        db_session,
        enrollment_id=enrollment.enrollment_id,
        lease_owner=runner_id,
        started_at=login_started_at + timedelta(seconds=1),
    )
    assert enrollment.login_unit_started_at == login_started_at

    waiting_at = login_started_at + timedelta(seconds=1)
    transition_codex_auth_enrollment(
        db_session,
        enrollment_id=enrollment.enrollment_id,
        lease_owner=runner_id,
        target_state="WAITING_FOR_USER",
        transitioned_at=waiting_at,
        next_action_at=waiting_at,
    )
    claimed = claim_due_codex_auth_enrollment(
        db_session,
        lease_owner=runner_id,
        claimed_at=waiting_at,
    )
    assert claimed is enrollment
    verifying_at = waiting_at + timedelta(seconds=1)
    transition_codex_auth_enrollment(
        db_session,
        enrollment_id=enrollment.enrollment_id,
        lease_owner=runner_id,
        target_state="VERIFYING",
        transitioned_at=verifying_at,
        next_action_at=verifying_at,
    )
    claimed = claim_due_codex_auth_enrollment(
        db_session,
        lease_owner=runner_id,
        claimed_at=verifying_at,
    )
    assert claimed is enrollment

    assignment = create_auth_assignment_revision(
        db_session,
        enrollment=enrollment,
        codex_cli_version="0.147.0",
        assigned_at=requested_at + timedelta(minutes=1),
    )
    binding.current_assignment_revision_id = assignment.assignment_revision_id
    with db_session.no_autoflush:
        record_auth_health(
            db_session,
            document={
                "schema_version": "codex-auth-health-view/1.0",
                "binding_id": binding.binding_id,
                "slot_key": "slot01",
                "account_label": assignment.account_label,
                "state": "READY",
                "reason_code": None,
                "codex_cli_version": "0.147.0",
                "observed_at": (requested_at + timedelta(minutes=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "valid_until": (requested_at + timedelta(minutes=16))
                .isoformat()
                .replace("+00:00", "Z"),
            },
        )
    succeeded = transition_codex_auth_enrollment(
        db_session,
        enrollment_id=enrollment.enrollment_id,
        lease_owner=runner_id,
        target_state="SUCCEEDED",
        transitioned_at=requested_at + timedelta(minutes=1),
        assignment_revision_id=assignment.assignment_revision_id,
        next_action_at=None,
    )
    assert succeeded.state == "SUCCEEDED"
    assert succeeded.assignment_revision_id == assignment.assignment_revision_id
    assert binding.current_assignment_revision_id == assignment.assignment_revision_id
    assert db_session.get(CodexAuthEnrollmentRecord, enrollment.enrollment_id) is enrollment
    assert (
        db_session.get(CodexAuthAssignmentRevisionRecord, assignment.assignment_revision_id)
        is assignment
    )
    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        assignment.account_label = "forbidden-rewrite"
        db_session.flush()


def test_workflow_command_availability_delays_capacity_retry_claim(
    db_session: Session,
) -> None:
    workflow = _workflow(db_session)
    available_at = datetime.now(UTC) + timedelta(minutes=5)
    command, created = enqueue_command(
        db_session,
        workflow_id=workflow.workflow_id,
        command_type=CommandType.ADVANCE_WORKFLOW,
        payload={"reason": "CAPACITY_AVAILABLE_RETRY", "job_id": "job_" + uuid4().hex},
        actor_type="system",
        actor_id="phase5-runner",
        source="capacity_controller",
        idempotency_key=f"phase5-capacity-retry:{uuid4().hex}",
        available_at=available_at,
    )
    assert created
    assert command.available_at == available_at
    assert not claimable_command_exists(db_session, workflow_id=workflow.workflow_id)
    assert (
        claim_next_command(
            db_session,
            runner_id="phase5-runner",
            lease_seconds=30,
            workflow_id=workflow.workflow_id,
        )
        is None
    )
    command.available_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    claimed = claim_next_command(
        db_session,
        runner_id="phase5-runner",
        lease_seconds=30,
        workflow_id=workflow.workflow_id,
    )
    assert claimed is not None
    assert claimed.command_id == command.command_id


def test_control_command_claim_index_covers_expired_lease_scan(db_session: Session) -> None:
    indexes = {
        row.name: tuple(column.name for column in row.expressions)
        for row in CodexControlCommandRecord.__table__.indexes
    }

    assert indexes["ix_codex_control_command_claim"] == (
        "state",
        "lease_expires_at",
        "requested_at",
        "command_id",
    )


def test_standard_bootstrap_is_idempotent_and_materializes_only_pinned_markdown(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "staging"
    nas_root = tmp_path / "nas"
    staging_root.mkdir()
    nas_root.mkdir()
    settings = Settings(
        worker_config=Path("config/worker-slots.example.yaml").resolve(),
        staging_root=staging_root,
        workspace_root=tmp_path / "worker-workspaces",
        worker_home_root=tmp_path / "worker-homes",
        nas_artifact_root=nas_root.resolve(),
        codex_binary=Path("/usr/local/bin/codex"),
        codex_capability_policy=Path("config/codex-capabilities.example.yaml").resolve(),
        worker_timeout_seconds=1800,
    )

    def bootstrap() -> StandardBootstrapResult:
        return bootstrap_standard_control_plane(
            integration_engine,
            config_directory=Path("config/control-plane/standard-item-v1").resolve(),
            source_commit="a" * 40,
            actor_id="phase5-integration",
            evaluation_cases_total=1,
            settings=settings,
        )

    first = bootstrap_standard_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/standard-item-v1").resolve(),
        source_commit="a" * 40,
        actor_id="phase5-integration",
        evaluation_cases_total=1,
        settings=settings,
    )
    replay = bootstrap()
    assert replay == first
    assert len(first.instruction_bundle_revision_ids) == 4
    assert len(first.auth_binding_ids) == 6

    sessions = build_session_factory(integration_engine)
    with transaction(sessions) as session:
        workflow = _workflow(session)
        plan = resolve_execution_plan(
            session,
            preset_key="standard-item",
            dependencies=ResolvedPlanDependencyEvidence(
                workflow_id=workflow.workflow_id,
                workflow_definition_key=workflow.definition_key,
                workflow_definition_version=workflow.definition_version,
                workflow_definition_sha256=workflow.definition_hash,
                workflow_role_schema_version=workflow.role_schema_version,
                content_pack_release_id="packrel_" + uuid4().hex,
                content_pack_sha256="sha256:" + uuid4().hex * 2,
            ),
            steps=(ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),),
            resolved_at=NOW + timedelta(hours=1),
        )
        allowed = authorized_execution_artifact_revisions(
            session, plan_id=plan.plan_id, step_key="authoring"
        )
        workspace = tmp_path / "materialized-workspace"
        workspace.mkdir(mode=0o2770)
        workspace.chmod(0o2770)
        materialized = materialize_execution_step(
            session,
            plan_id=plan.plan_id,
            step_key="authoring",
            workspace=workspace,
            canonical_artifact_root=nas_root.resolve(),
            worker_group_id=os.getgid(),
            authorized_artifact_revision_ids=allowed,
        )
    assert materialized.materialized_member_count == 3
    assert materialized.model == "gpt-5.6-terra"
    assert materialized.reasoning_effort == "high"
    assert (workspace / "AGENTS.md").is_file()
    assert (workspace / "instructions/platform.md").is_file()
    assert (workspace / "instructions/authoring.md").is_file()
    assert (workspace / "references/general-knowledge-provenance.md").is_file()

    successor = bootstrap_standard_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/standard-item-v2").resolve(),
        content_directory=Path("content").resolve(),
        source_commit="b" * 40,
        actor_id="phase5-integration",
        evaluation_cases_total=4,
        settings=settings,
    )
    assert successor.preset_id == first.preset_id
    assert successor.preset_revision_id != first.preset_revision_id
    assert successor.capacity_policy_revision_id == first.capacity_policy_revision_id
    assert successor.reference_bundle_revision_id is None
    assert len(successor.role_reference_bundle_revision_ids) == 4
    assert len(set(successor.role_reference_bundle_revision_ids)) == 4
    assert successor == bootstrap_standard_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/standard-item-v2").resolve(),
        content_directory=Path("content").resolve(),
        source_commit="b" * 40,
        actor_id="phase5-integration",
        evaluation_cases_total=4,
        settings=settings,
    )

    with transaction(sessions) as session:
        logical = session.get(ExecutionPresetRecord, first.preset_id)
        historical = session.get(ExecutionPresetRevisionRecord, first.preset_revision_id)
        successor_revision = session.get(
            ExecutionPresetRevisionRecord, successor.preset_revision_id
        )
        successor_evaluation = session.get(ExecutionPresetEvaluationRecord, successor.evaluation_id)
        assert logical is not None
        assert historical is not None
        assert successor_revision is not None
        assert successor_evaluation is not None
        assert logical.current_revision_id == successor.preset_revision_id
        assert historical.state == "RELEASED"
        assert successor_evaluation.cases_total == 4
        historical_reference_bundle = session.get(
            ExecutionBundleRevisionRecord, first.reference_bundle_revision_id
        )
        assert historical_reference_bundle is not None
        historical_general_pointer = historical_reference_bundle.canonical_document["entries"][0][
            "artifact"
        ]
        expected_reference_keys = {
            "authoring": {
                "general-knowledge-provenance",
                "integrated-science-single-item-authoring",
                "kice-integrated-science-illustration",
            },
            "image": {
                "general-knowledge-provenance",
                "kice-integrated-science-illustration",
            },
            "review": {
                "general-knowledge-provenance",
                "integrated-science-single-item-authoring",
                "kice-integrated-science-illustration",
            },
            "item_management": {"general-knowledge-provenance"},
        }
        for policy in successor_revision.canonical_document["role_policies"]:
            pointer = policy["reference_bundle"]
            bundle = session.get(ExecutionBundleRevisionRecord, pointer["bundle_revision_id"])
            assert bundle is not None
            assert {entry["reference_key"] for entry in bundle.canonical_document["entries"]} == (
                expected_reference_keys[policy["role"]]
            )
            general_entries = [
                entry
                for entry in bundle.canonical_document["entries"]
                if entry["reference_key"] == "general-knowledge-provenance"
            ]
            assert len(general_entries) == 1
            assert general_entries[0]["artifact"] == historical_general_pointer
        workflow = _workflow(session)
        plan = resolve_execution_plan(
            session,
            preset_key="standard-item",
            dependencies=ResolvedPlanDependencyEvidence(
                workflow_id=workflow.workflow_id,
                workflow_definition_key=workflow.definition_key,
                workflow_definition_version=workflow.definition_version,
                workflow_definition_sha256=workflow.definition_hash,
                workflow_role_schema_version=workflow.role_schema_version,
                content_pack_release_id="packrel_" + uuid4().hex,
                content_pack_sha256="sha256:" + uuid4().hex * 2,
            ),
            steps=(
                ExecutionStepRequirement("authoring", WorkerRole.AUTHORING),
                ExecutionStepRequirement("image", WorkerRole.IMAGE),
                ExecutionStepRequirement("review", WorkerRole.REVIEW),
                ExecutionStepRequirement("item_management", WorkerRole.ITEM_MANAGEMENT),
            ),
            resolved_at=NOW + timedelta(hours=2),
        )
        authoring_allowed = authorized_execution_artifact_revisions(
            session, plan_id=plan.plan_id, step_key="authoring"
        )
        item_management_allowed = authorized_execution_artifact_revisions(
            session, plan_id=plan.plan_id, step_key="item_management"
        )
        image_allowed = authorized_execution_artifact_revisions(
            session, plan_id=plan.plan_id, step_key="image"
        )
        review_allowed = authorized_execution_artifact_revisions(
            session, plan_id=plan.plan_id, step_key="review"
        )
        authoring_workspace = tmp_path / "materialized-guided-authoring"
        authoring_workspace.mkdir(mode=0o2770)
        authoring_workspace.chmod(0o2770)
        guided_authoring = materialize_execution_step(
            session,
            plan_id=plan.plan_id,
            step_key="authoring",
            workspace=authoring_workspace,
            canonical_artifact_root=nas_root.resolve(),
            worker_group_id=os.getgid(),
            authorized_artifact_revision_ids=authoring_allowed,
        )
        image_workspace = tmp_path / "materialized-guided-image"
        image_workspace.mkdir(mode=0o2770)
        image_workspace.chmod(0o2770)
        guided_image = materialize_execution_step(
            session,
            plan_id=plan.plan_id,
            step_key="image",
            workspace=image_workspace,
            canonical_artifact_root=nas_root.resolve(),
            worker_group_id=os.getgid(),
            authorized_artifact_revision_ids=image_allowed,
        )
        review_workspace = tmp_path / "materialized-guided-review"
        review_workspace.mkdir(mode=0o2770)
        review_workspace.chmod(0o2770)
        guided_review = materialize_execution_step(
            session,
            plan_id=plan.plan_id,
            step_key="review",
            workspace=review_workspace,
            canonical_artifact_root=nas_root.resolve(),
            worker_group_id=os.getgid(),
            authorized_artifact_revision_ids=review_allowed,
        )
        item_management_workspace = tmp_path / "materialized-guided-registration"
        item_management_workspace.mkdir(mode=0o2770)
        item_management_workspace.chmod(0o2770)
        guided_item_management = materialize_execution_step(
            session,
            plan_id=plan.plan_id,
            step_key="item_management",
            workspace=item_management_workspace,
            canonical_artifact_root=nas_root.resolve(),
            worker_group_id=os.getgid(),
            authorized_artifact_revision_ids=item_management_allowed,
        )
    assert guided_authoring.materialized_member_count == 5
    assert guided_image.materialized_member_count == 4
    assert guided_review.materialized_member_count == 5
    assert guided_item_management.materialized_member_count == 3
    assert (
        authoring_workspace / "references/guidance/integrated-science-single-item-authoring-v1.md"
    ).read_bytes() == Path(
        "content/authoring-rules/integrated-science-single-item-authoring-v1.md"
    ).read_bytes()
    assert (
        authoring_workspace / "references/guidance/kice-integrated-science-illustration-v1.md"
    ).read_bytes() == Path(
        "content/image-specs/kice-integrated-science-illustration-v1.md"
    ).read_bytes()
    agents = (authoring_workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "integrated-science-single-item-authoring-v1.md" in agents
    assert "kice-integrated-science-illustration-v1.md" in agents
    assert "SIA-MUST-001" not in agents
    assert "VIS-MUST-001" not in agents
    assert not (
        image_workspace / "references/guidance/integrated-science-single-item-authoring-v1.md"
    ).exists()
    assert (
        image_workspace / "references/guidance/kice-integrated-science-illustration-v1.md"
    ).is_file()
    assert (
        review_workspace / "references/guidance/integrated-science-single-item-authoring-v1.md"
    ).is_file()
    assert (
        review_workspace / "references/guidance/kice-integrated-science-illustration-v1.md"
    ).is_file()
    assert not (item_management_workspace / "references/guidance").exists()


def test_knowledge_analysis_bootstrap_is_idempotent_and_support_only(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "staging"
    nas_root = tmp_path / "nas"
    staging_root.mkdir()
    nas_root.mkdir()
    settings = Settings(
        worker_config=Path("config/worker-slots.example.yaml").resolve(),
        staging_root=staging_root,
        workspace_root=tmp_path / "worker-workspaces",
        worker_home_root=tmp_path / "worker-homes",
        nas_artifact_root=nas_root.resolve(),
        codex_binary=Path("/usr/local/bin/codex"),
        codex_capability_policy=Path("config/codex-capabilities.example.yaml").resolve(),
        worker_timeout_seconds=1800,
    )
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        capacity_exists = session.scalar(
            select(WorkerCapacityPolicyRecord).where(
                WorkerCapacityPolicyRecord.policy_key == "fixed-host"
            )
        )
    if capacity_exists is None:
        bootstrap_standard_control_plane(
            integration_engine,
            config_directory=Path("config/control-plane/standard-item-v1").resolve(),
            source_commit="a" * 40,
            actor_id="phase7-integration",
            evaluation_cases_total=1,
            settings=settings,
        )

    def bootstrap() -> KnowledgeAnalysisBootstrapResult:
        return bootstrap_knowledge_analysis_control_plane(
            integration_engine,
            config_directory=Path("config/control-plane/knowledge-analysis-v1").resolve(),
            source_commit="b" * 40,
            actor_id="phase7-integration",
            evaluation_cases_total=3,
            settings=settings,
        )

    first = bootstrap()
    assert bootstrap() == first
    with sessions() as session:
        logical = session.scalar(
            select(ExecutionPresetRecord).where(
                ExecutionPresetRecord.preset_key == "knowledge-analysis"
            )
        )
        assert logical is not None
        assert logical.current_revision_id == first.preset_revision_id
        revision = session.get(ExecutionPresetRevisionRecord, first.preset_revision_id)
        assert revision is not None
        policy = revision.canonical_document
        assert policy["compatible_workflow_protocols"] == ["workflow-role/1.4.0"]
        assert policy["capacity_policy_revision_id"] == first.capacity_policy_revision_id
        assert policy["general_knowledge_policy"] == "ALLOW_WITH_PROVENANCE"
        assert len(policy["role_policies"]) == 1
        role = policy["role_policies"][0]
        assert role["role"] == "support"
        assert role["worker_pool_key"] == "support"
        assert role["reference_bundle"] is None
        assert role["instruction_bundle"]["bundle_revision_id"] == (
            first.instruction_bundle_revision_id
        )
        protocol = session.get(ProtocolVersionRecord, "workflow-role/1.4.0")
        assert protocol is not None
        assert protocol.schema_sha256 == role_schema_bundle_hash("workflow-role/1.4.0")


def test_knowledge_analysis_v2_through_v8_bootstraps_add_immutable_revisions(
    integration_engine: Engine,
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "staging"
    nas_root = tmp_path / "nas"
    staging_root.mkdir()
    nas_root.mkdir()
    settings = Settings(
        worker_config=Path("config/worker-slots.example.yaml").resolve(),
        staging_root=staging_root,
        workspace_root=tmp_path / "worker-workspaces",
        worker_home_root=tmp_path / "worker-homes",
        nas_artifact_root=nas_root.resolve(),
        codex_binary=Path("/usr/local/bin/codex"),
        codex_capability_policy=Path("config/codex-capabilities.example.yaml").resolve(),
        worker_timeout_seconds=1800,
    )
    sessions = build_session_factory(integration_engine)
    with sessions() as session:
        capacity_exists = session.scalar(
            select(WorkerCapacityPolicyRecord).where(
                WorkerCapacityPolicyRecord.policy_key == "fixed-host"
            )
        )
    if capacity_exists is None:
        bootstrap_standard_control_plane(
            integration_engine,
            config_directory=Path("config/control-plane/standard-item-v1").resolve(),
            source_commit="a" * 40,
            actor_id="phase7-integration",
            evaluation_cases_total=1,
            settings=settings,
        )
    first = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v1").resolve(),
        source_commit="b" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    second = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v2").resolve(),
        source_commit="c" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    assert second == bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v2").resolve(),
        source_commit="c" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    third = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v3").resolve(),
        source_commit="d" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    assert third == bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v3").resolve(),
        source_commit="d" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    fourth = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v4").resolve(),
        source_commit="e" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    assert fourth == bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v4").resolve(),
        source_commit="e" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    fifth = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v5").resolve(),
        source_commit="f" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    assert fifth == bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v5").resolve(),
        source_commit="f" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    sixth = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v6").resolve(),
        source_commit="6" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    assert sixth == bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v6").resolve(),
        source_commit="6" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    seventh = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v7").resolve(),
        source_commit="7" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    assert seventh == bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v7").resolve(),
        source_commit="7" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    eighth = bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v8").resolve(),
        source_commit="8" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    assert eighth == bootstrap_knowledge_analysis_control_plane(
        integration_engine,
        config_directory=Path("config/control-plane/knowledge-analysis-v8").resolve(),
        source_commit="8" * 40,
        actor_id="phase7-integration",
        evaluation_cases_total=3,
        settings=settings,
    )
    assert (
        len(
            {
                first.instruction_bundle_revision_id,
                second.instruction_bundle_revision_id,
                third.instruction_bundle_revision_id,
                fourth.instruction_bundle_revision_id,
                fifth.instruction_bundle_revision_id,
                sixth.instruction_bundle_revision_id,
                seventh.instruction_bundle_revision_id,
                eighth.instruction_bundle_revision_id,
            }
        )
        == 8
    )
    with sessions() as session:
        logical = session.scalar(
            select(ExecutionPresetRecord).where(
                ExecutionPresetRecord.preset_key == "knowledge-analysis"
            )
        )
        assert logical is not None
        assert logical.current_revision_id == eighth.preset_revision_id
        revisions = tuple(
            session.scalars(
                select(ExecutionPresetRevisionRecord)
                .where(ExecutionPresetRevisionRecord.preset_id == logical.preset_id)
                .order_by(ExecutionPresetRevisionRecord.revision_number)
            )
        )
        assert [revision.revision_number for revision in revisions] == list(range(1, 17))
        assert [revision.state for revision in revisions] == [
            "DRAFT",
            "RELEASED",
            "DRAFT",
            "RELEASED",
            "DRAFT",
            "RELEASED",
            "DRAFT",
            "RELEASED",
            "DRAFT",
            "RELEASED",
            "DRAFT",
            "RELEASED",
            "DRAFT",
            "RELEASED",
            "DRAFT",
            "RELEASED",
        ]
        assert revisions[1].preset_revision_id == first.preset_revision_id
        assert revisions[3].preset_revision_id == second.preset_revision_id
        assert revisions[5].preset_revision_id == third.preset_revision_id
        assert revisions[7].preset_revision_id == fourth.preset_revision_id
        assert revisions[9].preset_revision_id == fifth.preset_revision_id
        assert revisions[11].preset_revision_id == sixth.preset_revision_id
        assert revisions[13].preset_revision_id == seventh.preset_revision_id
        assert revisions[15].preset_revision_id == eighth.preset_revision_id
        assert revisions[1].canonical_document["compatible_workflow_protocols"] == [
            "workflow-role/1.4.0"
        ]
        assert revisions[3].canonical_document["compatible_workflow_protocols"] == [
            "workflow-role/1.4.0",
            "workflow-role/1.5.0",
        ]
        assert revisions[7].canonical_document["role_policies"][0]["model_candidates"] == [
            {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"}
        ]
        assert revisions[9].canonical_document["role_policies"][0]["timeout_seconds"] == 7200
        assert revisions[11].canonical_document["compatible_workflow_protocols"] == [
            "workflow-role/1.4.0",
            "workflow-role/1.5.0",
            "workflow-role/1.6.0",
        ]
        assert revisions[13].canonical_document["compatible_workflow_protocols"] == [
            "workflow-role/1.4.0",
            "workflow-role/1.5.0",
            "workflow-role/1.6.0",
            "workflow-role/1.7.0",
        ]
        assert revisions[15].canonical_document["compatible_workflow_protocols"] == [
            "workflow-role/1.4.0",
            "workflow-role/1.5.0",
            "workflow-role/1.6.0",
            "workflow-role/1.7.0",
            "workflow-role/1.8.0",
        ]
        assert revisions[15].canonical_document["role_policies"][0]["model_candidates"] == [
            {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"}
        ]
        assert revisions[15].canonical_document["role_policies"][0]["timeout_seconds"] == 7200


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
