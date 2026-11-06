"""Resolve one completed material child through the existing Workflow/Artifact owners."""

from dataclasses import dataclass

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialDiscoveryResult,
    MaterialDiscoveryWork,
    MaterialExtractionResult,
    MaterialExtractionWork,
    MaterialLearningRoleReceipt,
    MaterialLearningWork,
    validate_material_discovery,
    validate_material_extraction,
)
from eom_catalog_contracts.material_learning_authorization import (
    MaterialLearningAuthorizationRequest,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.material_learning_execution import validate_material_learning_execution_plan
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.material_learning_request import MaterialLearningWorkerRequest
from eom_workflow.models import ArtifactPointer, MaterialLearningRoleResult
from eom_workflow.schemas import validate_role_input, validate_role_result
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_authorization import (
    CatalogMaterialLearningAuthorizationService,
)
from eom_catalog_service.material_learning_models import (
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_source import authorize_material_learning
from eom_catalog_service.material_task_history import read_material_task_histories


@dataclass(frozen=True, slots=True)
class ResolvedMaterialTask:
    task_id: str
    unit_key: str
    operator_id: str
    selection: MaterialLearningAuthorizationRequest
    work: MaterialLearningWork
    work_pointer: MaterialArtifactMember
    role: MaterialLearningRoleResult
    result_pointer: ArtifactMemberPointer
    result_bytes: int


def resolve_completed_material_task(
    session: Session,
    artifacts: CatalogArtifactService,
    *,
    task_id: str,
    operator_id: str,
) -> ResolvedMaterialTask:
    """No implicit latest, raw result cache, fake succeeded Job, or whole-book read."""
    authorize_material_learning(session, operator_id)
    task = session.get(MaterialLearningTaskRecord, task_id, populate_existing=True)
    parent = (
        session.get(MaterialLearningRunRecord, task.run_id, populate_existing=True)
        if task
        else None
    )
    if (
        task is None
        or parent is None
        or parent.created_by != operator_id
        or parent.state == "CANCELLED"
        or task.state == "CANCELLED"
        or (task.workflow_id is None and task.predecessor_task_id is None)
    ):
        raise ValueError("MATERIAL_LEARNING_TASK_SOURCE_INELIGIBLE")
    if task.workflow_id is None:
        history = read_material_task_histories(session, (task,))[task.task_id]
        task = history.result_task()
        if task.workflow_id is None:
            raise ValueError("MATERIAL_LEARNING_TASK_SOURCE_INELIGIBLE")
    workflow = session.get(WorkflowInstanceRecord, task.workflow_id, populate_existing=True)
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == task.workflow_id,
                WorkflowStepRunRecord.step_key == "learn",
                WorkflowStepRunRecord.step_type == "agent",
            )
            .limit(2)
        )
    )
    if (
        workflow is None
        or len(steps) != 1
        or workflow.state != "COMPLETED"
        or (workflow.definition_key, workflow.definition_version, workflow.role_schema_version)
        != ("material-learning", "1.0.0", "workflow-role/1.37.0")
        or workflow.created_actor_type != "human"
        or workflow.created_actor_id != operator_id
    ):
        raise ValueError("MATERIAL_LEARNING_CHILD_NOT_COMPLETED")
    step = steps[0]
    if (
        step.step_key,
        step.step_type,
        step.worker_role,
        step.attempt,
        step.state,
        step.result_schema,
    ) != (
        "learn",
        "agent",
        "support",
        1,
        "SUCCEEDED",
        "material-learning-result@1.0",
    ) or step.platform_job_id is None:
        raise ValueError("MATERIAL_LEARNING_CHILD_ROLE_INVALID")
    input_revision = (
        session.get(ArtifactRevisionRecord, task.input_artifact_revision_id)
        if task.input_artifact_revision_id
        else None
    )
    if (
        input_revision is None
        or task.input_artifact_id is None
        or task.input_sha256 is None
        or task.input_artifact_revision_id is None
    ):
        raise ValueError("MATERIAL_LEARNING_INPUT_MISSING")
    work_schema = "eom://schemas/material-learning/" + (
        "discovery-work/1.0" if task.task_kind == "DISCOVER" else "extraction-work/1.0"
    )
    work_pointer = MaterialArtifactMember(
        artifact_id=task.input_artifact_id,
        artifact_revision_id=task.input_artifact_revision_id,
        member_path="material/work.json",
        schema_ref=work_schema,
        media_type="application/json",
        sha256=task.input_sha256,
        bytes=input_revision.content_bytes,
    )
    work: MaterialLearningWork
    if task.task_kind == "DISCOVER":
        work = read_material_metadata(
            artifacts,
            work_pointer,
            MaterialDiscoveryWork,
            schema_ref=work_schema,
            member_path="material/work.json",
        )
    elif task.task_kind == "QUESTION":
        work = read_material_metadata(
            artifacts,
            work_pointer,
            MaterialExtractionWork,
            schema_ref=work_schema,
            member_path="material/work.json",
        )
    else:
        raise ValueError("MATERIAL_LEARNING_TASK_KIND_INVALID")
    row = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
        )
    )
    plan = validate_material_learning_execution_plan(
        row,
        workflow_id=workflow.workflow_id,
        step_key=step.step_key,
        request=MaterialLearningWorkerRequest(work_input=work),
    )
    selection = MaterialLearningAuthorizationRequest(
        workflow_id=workflow.workflow_id,
        step_run_id=step.step_run_id,
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        input_sha256=work.input_sha256,
    )
    reply = CatalogMaterialLearningAuthorizationService(
        artifacts.engine, artifacts.settings
    ).authorize(selection)
    reply.validate_for(selection)
    if reply.status != "SUCCESS":
        raise ValueError("MATERIAL_LEARNING_SOURCE_AUTHORIZATION_FAILED")
    job = session.get(JobRecord, step.platform_job_id)
    revision = session.get(ArtifactRevisionRecord, job.revision_id) if job else None
    logical = session.get(ArtifactRecord, job.logical_artifact_id) if job else None
    if (
        job is None
        or revision is None
        or logical is None
        or job.status != "SUCCEEDED"
        or job.error_code is not None
        or not logical.approved
        or not revision.approved
        or revision.logical_artifact_id != logical.logical_artifact_id
        or logical.job_id != job.job_id
        or revision.job_id != job.job_id
        or job.task_type != "workflow_support"
        or logical.artifact_type != "workflow_support"
    ):
        raise ValueError("MATERIAL_LEARNING_RESULT_POINTER_INVALID")
    final = workflow.runtime_context.get("final_pointer_manifest")
    pointers = final.get("artifact_pointers") if isinstance(final, dict) else None
    if not isinstance(pointers, list) or len(pointers) != 1:
        raise ValueError("MATERIAL_LEARNING_FINAL_POINTER_INVALID")
    pointer = ArtifactPointer.model_validate(pointers[0])
    if (
        pointer.job_id,
        pointer.logical_artifact_id,
        pointer.revision_id,
        pointer.content_hash,
        pointer.result_schema,
        pointer.step_key,
        pointer.attempt,
    ) != (
        job.job_id,
        logical.logical_artifact_id,
        revision.revision_id,
        revision.content_hash,
        "material-learning-result@1.0",
        "learn",
        1,
    ):
        raise ValueError("MATERIAL_LEARNING_FINAL_POINTER_INVALID")
    result_pointer = ArtifactMemberPointer(
        artifact_id=logical.logical_artifact_id,
        artifact_revision_id=revision.revision_id,
        member_path="result.json",
        schema_ref="material-learning-result@1.0",
        media_type="application/json",
        sha256=revision.content_hash,
    )
    if task.output_artifact_revision_id is not None and (
        task.output_artifact_id,
        task.output_artifact_revision_id,
        task.output_sha256,
    ) != (result_pointer.artifact_id, result_pointer.artifact_revision_id, result_pointer.sha256):
        raise ValueError("MATERIAL_LEARNING_STORED_RESULT_DIFFERS")
    # Role jobs publish the Orchestrator's single-primary ArtifactManifest, not
    # a Catalog file-set member. Reuse its existing verified JSON primary read;
    # the exact Workflow/Job closure above and typed role below own the schema.
    payload = artifacts.load_json_revision(
        artifact_id=result_pointer.artifact_id,
        revision_id=result_pointer.artifact_revision_id,
        content_hash=result_pointer.sha256,
        max_bytes=4 * 1024 * 1024,
    )
    raw = canonical_json_bytes(payload)
    if len(raw) != revision.content_bytes or sha256_bytes(raw) != result_pointer.sha256:
        raise ValueError("MATERIAL_LEARNING_RESULT_SIZE_DIFFERS")
    role = validate_role_result(payload, "support", "material-learning-result@1.0")
    if not isinstance(role, MaterialLearningRoleResult) or (
        role.workflow_id,
        role.step_run_id,
        role.job_id,
    ) != (workflow.workflow_id, step.step_run_id, job.job_id):
        raise ValueError("MATERIAL_LEARNING_RESULT_ROLE_DIFFERS")
    original = validate_role_input(job.request, "support", "workflow-role/1.37.0")
    if (
        not isinstance(original.request, MaterialLearningWorkerRequest)
        or original.request.work_input != work
        or original.job_id != role.job_id
        or original.workflow_id != role.workflow_id
        or original.step_run_id != role.step_run_id
        or role.artifact != original.artifact
        or (role.artifact.logical_artifact_id, role.artifact.revision_id)
        != (logical.logical_artifact_id, revision.revision_id)
    ):
        raise ValueError("MATERIAL_LEARNING_RESULT_INPUT_DIFFERS")
    receipt = MaterialLearningRoleReceipt.model_validate(revision.result)
    if (
        receipt.input_sha256 != work.input_sha256
        or receipt.result_sha256 != content_sha256(role.model_dump(mode="json"))
        or receipt.task_kind != work.task_kind
    ):
        raise ValueError("MATERIAL_LEARNING_RESULT_RECEIPT_DIFFERS")
    if isinstance(work, MaterialDiscoveryWork):
        if not isinstance(role.output.learning_result, MaterialDiscoveryResult):
            raise ValueError("MATERIAL_LEARNING_RESULT_KIND_DIFFERS")
        validate_material_discovery(role.output.learning_result, work)
    else:
        if not isinstance(role.output.learning_result, MaterialExtractionResult):
            raise ValueError("MATERIAL_LEARNING_RESULT_KIND_DIFFERS")
        validate_material_extraction(role.output.learning_result, work)
    return ResolvedMaterialTask(
        task.task_id,
        task.unit_key,
        operator_id,
        selection,
        work,
        work_pointer,
        role,
        result_pointer,
        len(raw),
    )
