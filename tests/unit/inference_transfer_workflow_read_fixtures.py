"""Synthetic exact comparison lineage; no real Identity, DB or Artifact reads."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from eom_catalog_contracts.inference_transfer_invocation import InferenceTransferWorkflowReadRequest
from eom_catalog_service.inference_transfer_worker_preparation import (
    prepare_inference_transfer_worker_comparison,
)
from eom_catalog_service.inference_transfer_workflow_read import (
    CatalogInferenceTransferWorkflowReadService,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_models import (
    ResolvedExecutionPlanRecord,
    ResolvedExecutionPlanStepRecord,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.models import ArtifactManifest
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV21
from eom_workflow.models import ArtifactPointer, InferenceTransferPairRoleResult, RoleWorkerInput
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)

from tests.unit.inference_transfer_execution_fixtures import transfer_plan
from tests.unit.inference_transfer_fixtures import NOW, result
from tests.unit.inference_transfer_workflow_fixtures import (
    OPERATOR_ID,
    definition,
    workflow_request,
)


def read_request(mode="CANONICAL_RESULT", workflow_id="workflow_" + "1" * 32):
    body = {
        "schema_version": "inference-transfer-workflow-read-request/1.0",
        "workflow_id": workflow_id,
        "mode": mode,
    }
    return InferenceTransferWorkflowReadRequest.model_validate(
        body | {"read_sha256": content_sha256(body)}
    )


def owner_fixture(monkeypatch, state="COMPLETED"):
    request, stored_definition = workflow_request(), definition()
    workflow_id, step_id, job_id = (
        "workflow_" + "1" * 32,
        "steprun_" + "1" * 32,
        "job_" + "1" * 32,
    )
    worker = RoleWorkerInput(
        protocol_version="workflow-role/1.29.0",
        job_id=job_id,
        workflow_id=workflow_id,
        step_run_id=step_id,
        attempt=1,
        role="support",
        request=request.worker_request(),
        upstream_artifacts=(),
        artifact={"logical_artifact_id": "artifact_" + "8" * 32, "revision_id": "rev_" + "8" * 32},
    )
    role_result = InferenceTransferPairRoleResult(
        job_id=job_id,
        workflow_id=workflow_id,
        step_run_id=step_id,
        artifact=worker.artifact,
        completed_at=NOW,
        output=result(request.comparison),
    )
    document = role_result.model_dump(mode="json")
    manifest = ArtifactManifest(
        job_id=job_id,
        logical_artifact_id=worker.artifact.logical_artifact_id,
        revision_id=worker.artifact.revision_id,
        content_hash=content_sha256(document),
        content_bytes=len(canonical_json_bytes(document)),
        worker_slot="06",
        created_at=NOW,
    )
    pointer = ArtifactPointer(
        step_key="compare_pair",
        attempt=1,
        job_id=job_id,
        logical_artifact_id=worker.artifact.logical_artifact_id,
        revision_id=worker.artifact.revision_id,
        content_hash=manifest.content_hash,
        result_schema="item-inference-transfer-pair-result@1.0",
    )
    prepared = prepare_inference_transfer_worker_comparison(
        request.comparison, left=request.left_profile, right=request.right_profile
    )
    plan_body = transfer_plan(request.comparison).model_dump(mode="json", exclude={"plan_sha256"})
    plan_body.update(
        workflow_definition_sha256=stored_definition.definition_hash,
        access_policy_revision_id=request.access_policy_revision_id,
        access_policy_sha256=request.access_policy_sha256,
        requester_permissions_sha256=request.requester_permissions_sha256,
        core_prompt_sha256=prepared.core_prompt_sha256,
        prompt_sha256=prepared.prompt_sha256,
    )
    plan = ResolvedExecutionPlanV21.model_validate(
        plan_body | {"plan_sha256": content_sha256(plan_body)}
    )
    plan_record = ResolvedExecutionPlanRecord(
        plan_id=plan.plan_id,
        workflow_id=workflow_id,
        preset_id=plan.preset_id,
        preset_revision_id=plan.preset_revision_id,
        capacity_policy_revision_id=plan.capacity_policy_revision_id,
        graph_snapshot_revision_id=plan.graph_snapshot.graph_snapshot_revision_id,
        evidence_bundle_revision_id=None,
        plan_sha256=plan.plan_sha256,
        resolver_version=plan.resolver_version,
        canonical_document=plan.model_dump(mode="json"),
        resolved_at=NOW,
    )
    plan_step = plan.steps[0]
    plan_step_record = ResolvedExecutionPlanStepRecord(
        plan_id=plan.plan_id,
        step_key="compare_pair",
        role="support",
        model=plan_step.model,
        reasoning_effort=str(plan_step.reasoning_effort),
        instruction_bundle_revision_id=plan_step.instruction_bundle.bundle_revision_id,
        reference_bundle_revision_id=None,
        worker_pool_key=plan_step.worker_pool_key,
        timeout_seconds=plan_step.timeout_seconds,
        sandbox=plan_step.sandbox,
        network=plan_step.network,
        general_knowledge_mode=str(plan_step.general_knowledge_mode),
    )
    pointer_body = pointer.model_dump(mode="json")
    workflow = WorkflowInstanceRecord(
        workflow_id=workflow_id,
        definition_id=stored_definition.definition_id,
        definition_key=stored_definition.definition_key,
        definition_version=stored_definition.definition_version,
        definition_hash=stored_definition.definition_hash,
        protocol_version="1.0.1",
        role_schema_version="workflow-role/1.29.0",
        state=state,
        stage="COMPLETED" if state == "COMPLETED" else "INFERENCE_TRANSFER",
        current_step_key="complete" if state == "COMPLETED" else "compare_pair",
        initial_request=request.model_dump(mode="json"),
        request_payload=request.model_dump(mode="json"),
        request_hash=content_sha256(
            {
                "definition_key": stored_definition.definition_key,
                "definition_version": stored_definition.definition_version,
                "definition_hash": stored_definition.definition_hash,
                "request": request.model_dump(mode="json"),
                "actor": {"actor_type": "human", "actor_id": OPERATOR_ID},
            }
        ),
        runtime_context={
            "execution_plan": {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "preset_id": plan.preset_id,
                "preset_revision_id": plan.preset_revision_id,
            },
            "artifact_pointers": [pointer_body],
            "final_pointer_manifest": {
                "workflow_id": workflow_id,
                "definition_hash": stored_definition.definition_hash,
                "artifact_pointers": [pointer_body],
                "comparison_result": pointer_body,
                "registration": None,
                "analysis_proposal": None,
            },
        },
        idempotency_key="synthetic-owner-read",
        lock_version=3,
        rework_cycle_count=0,
        created_actor_type="human",
        created_actor_id=OPERATOR_ID,
        failure_code="UNTRUSTED_SECRET_VALUE",
        failure_summary="must never return arbitrary historical details",
    )
    step = WorkflowStepRunRecord(
        step_run_id=step_id,
        workflow_id=workflow_id,
        step_key="compare_pair",
        attempt=1,
        step_type="agent",
        worker_role="support",
        result_schema="item-inference-transfer-pair-result@1.0",
        state="SUCCEEDED",
        platform_job_id=job_id,
        input_pointer_manifest={
            "upstream_artifacts": [],
            "transfer_prompt": {
                "prompt_version": prepared.prompt_version,
                "core_prompt_sha256": prepared.core_prompt_sha256,
                "prompt_sha256": prepared.prompt_sha256,
                "workflow_request_sha256": request.request_sha256,
            },
        },
        output_pointer_manifest=pointer_body,
        superseded_by_step_run_id=None,
    )
    job_document = worker.model_dump(mode="json")
    job = JobRecord(
        job_id=job_id,
        protocol_version="workflow-role/1.29.0",
        task_type="workflow_support",
        request=job_document,
        request_hash=content_sha256(
            {
                "protocol_version": worker.protocol_version,
                "task_type": "workflow_support",
                "request": job_document,
            }
        ),
        status="SUCCEEDED",
        logical_artifact_id=worker.artifact.logical_artifact_id,
        revision_id=worker.artifact.revision_id,
        worker_slot_id="06",
        completed_at=NOW,
    )
    artifact = ArtifactRecord(
        logical_artifact_id=worker.artifact.logical_artifact_id,
        job_id=job_id,
        artifact_type="workflow_support",
        approved=True,
    )
    revision = ArtifactRevisionRecord(
        revision_id=worker.artifact.revision_id,
        logical_artifact_id=worker.artifact.logical_artifact_id,
        job_id=job_id,
        content_hash=manifest.content_hash,
        manifest_hash=content_sha256(manifest.model_dump(mode="json")),
        content_bytes=manifest.content_bytes,
        manifest=manifest.model_dump(mode="json"),
        result={"not": "the canonical payload"},
        approved=True,
    )
    rows = {
        WorkflowInstanceRecord: workflow,
        WorkflowDefinitionRecord: stored_definition,
        JobRecord: job,
        ArtifactRecord: artifact,
        ArtifactRevisionRecord: revision,
        ResolvedExecutionPlanRecord: plan_record,
    }
    row_lists = {WorkflowStepRunRecord: [step], ResolvedExecutionPlanStepRecord: [plan_step_record]}
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.side_effect = lambda entity, key: (
        row if (row := rows.get(entity)) is not None and key == _row_key(entity, row) else None
    )
    session.scalars.side_effect = lambda statement: row_lists[
        statement.column_descriptions[0]["entity"]
    ]
    owner = object.__new__(CatalogInferenceTransferWorkflowReadService)
    owner.sessions = Mock(return_value=session)
    owner.source = Mock()
    owner.artifacts = Mock()
    owner.artifacts.load_json_revision.return_value = document
    monkeypatch.setattr(
        "eom_catalog_service.inference_transfer_workflow_read.effective_permissions",
        lambda *_: {PermissionKey.WORKFLOW_READ},
    )
    return SimpleNamespace(
        owner=owner,
        workflow=workflow,
        definition=stored_definition,
        step=step,
        job=job,
        artifact=artifact,
        revision=revision,
        plan=plan_record,
        plan_step=plan_step_record,
        document=document,
        role_result=role_result,
        request=request,
        session=session,
        rows=rows,
        row_lists=row_lists,
    )


def _row_key(entity, row):
    keys = {
        WorkflowInstanceRecord: "workflow_id",
        WorkflowDefinitionRecord: "definition_id",
        JobRecord: "job_id",
        ArtifactRecord: "logical_artifact_id",
        ArtifactRevisionRecord: "revision_id",
        ResolvedExecutionPlanRecord: "plan_id",
    }
    return getattr(row, keys[entity])
