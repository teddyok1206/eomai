"""Resolve one completed creative proposal through its actual Workflow and Job."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.assessment_item import ImageBlock
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_contracts.external_item_learning_result import (
    validate_external_item_learning_result_for_source,
)
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningWorkInput
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.external_item_learning_execution import (
    validate_external_item_learning_execution_plan,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import ArtifactManifest
from eom_workflow.creative_learning_profile import (
    creative_learning_profile,
    creative_learning_profile_for_preset,
)
from eom_workflow.models import (
    ExternalItemLearningRoleResult,
    ExternalItemLearningRoleResultV2,
    ExternalItemLearningWorkerRequest,
)
from eom_workflow.schemas import validate_role_result
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import load_persisted_workflow_request
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogJsonRevisionReader
from eom_catalog_service.creative_proposal_read_set import CreativeProposalReadSet


class CreativeLearningProposalError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ResolvedCreativeLearningProposal:
    """An exact data binding, not a source permission or scientific approval."""

    selection: ExternalItemLearningRoleSelection
    operator_id: str
    work: ExternalItemLearningWorkInput
    role: ExternalItemLearningRoleResult | ExternalItemLearningRoleResultV2
    pointer: ArtifactMemberPointer


def resolve_completed_creative_learning_proposal(
    session: Session,
    artifacts: CatalogJsonRevisionReader,
    selection: ExternalItemLearningRoleSelection,
    *,
    read_set: CreativeProposalReadSet | None = None,
) -> ResolvedCreativeLearningProposal:
    selection = ExternalItemLearningRoleSelection.model_validate(selection.model_dump(mode="json"))
    rows = None if read_set is None else read_set.for_selection(session, selection)
    workflow = (
        session.get(WorkflowInstanceRecord, selection.workflow_id, populate_existing=True)
        if rows is None
        else rows.workflow
    )
    step = (
        session.get(WorkflowStepRunRecord, selection.step_run_id, populate_existing=True)
        if rows is None
        else rows.step
    )
    if (
        workflow is None
        or step is None
        or workflow.state != "COMPLETED"
        or workflow.definition_key != "external-item-learning"
        or workflow.created_actor_type != "human"
        or step.workflow_id != workflow.workflow_id
        or step.step_key != "extract"
        or step.worker_role != "support"
        or step.state != "SUCCEEDED"
        or step.attempt != 1
        or step.platform_job_id is None
    ):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_PROPOSAL_NOT_COMPLETED")
    try:
        profile = creative_learning_profile(workflow.definition_version)
    except ValueError as exc:
        raise CreativeLearningProposalError("CREATIVE_LEARNING_PROPOSAL_NOT_COMPLETED") from exc
    if (
        workflow.role_schema_version != profile.role_protocol
        or step.result_schema != profile.result_schema
    ):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_PROPOSAL_NOT_COMPLETED")
    initial = load_persisted_workflow_request(workflow.initial_request)
    try:
        profile = creative_learning_profile_for_preset(
            workflow.definition_version, initial.execution_preset_key or ""
        )
    except ValueError as exc:
        raise CreativeLearningProposalError("CREATIVE_LEARNING_INPUT_MISMATCH") from exc
    request = initial.worker_request()
    if (
        initial != load_persisted_workflow_request(workflow.request_payload)
        or initial.execution_preset_key != profile.preset_key
        or not isinstance(request, ExternalItemLearningWorkerRequest)
        or request.work_input.request_sha256 != selection.work_input_sha256
    ):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_INPUT_MISMATCH")
    plan = validate_external_item_learning_execution_plan(
        session.get(ResolvedExecutionPlanRecord, selection.plan_id, populate_existing=True)
        if rows is None
        else rows.plan,
        workflow_id=workflow.workflow_id,
        step_key=step.step_key,
        request=request,
    )
    if (
        plan.plan_sha256 != selection.plan_sha256
        or plan.workflow_definition_version != profile.definition_version
        or plan.workflow_definition_sha256 != workflow.definition_hash
        or workflow.runtime_context.get("execution_plan")
        != {
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "preset_id": plan.preset_id,
            "preset_revision_id": plan.preset_revision_id,
        }
    ):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_PLAN_MISMATCH")
    job = (
        session.get(JobRecord, step.platform_job_id, populate_existing=True)
        if rows is None
        else rows.job
    )
    revision = (
        (
            session.get(ArtifactRevisionRecord, job.revision_id, populate_existing=True)
            if rows is None
            else rows.result_revision
        )
        if job is not None
        else None
    )
    if (
        job is None
        or job.status != "SUCCEEDED"
        or revision is None
        or not revision.approved
        or revision.logical_artifact_id != job.logical_artifact_id
    ):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_RESULT_POINTER_INVALID")
    # The current Codex result uses the existing single-file ArtifactManifest.
    # Its result schema is supplied by the pinned Workflow step, not by a path
    # guess or a model-selected schema. The Catalog reader verifies both formats.
    if "files" not in revision.manifest:
        manifest = ArtifactManifest.model_validate(revision.manifest)
        if manifest.file_name != "result.json" or manifest.media_type != "application/json":
            raise CreativeLearningProposalError("CREATIVE_LEARNING_RESULT_MANIFEST_INVALID")
    else:
        files = revision.manifest.get("files")
        if not isinstance(files, list) or any(not isinstance(entry, dict) for entry in files):
            raise CreativeLearningProposalError("CREATIVE_LEARNING_RESULT_MANIFEST_INVALID")
        members = [entry for entry in files if entry.get("file_name") == "result.json"]
        if (
            revision.manifest.get("primary_file") != "result.json"
            or len(members) != 1
            or members[0].get("sha256") != revision.content_hash
            or members[0].get("media_type") != "application/json"
            or members[0].get("schema_ref") != step.result_schema
        ):
            raise CreativeLearningProposalError("CREATIVE_LEARNING_RESULT_MANIFEST_INVALID")
    pointer = ArtifactMemberPointer(
        artifact_id=job.logical_artifact_id,
        artifact_revision_id=job.revision_id,
        member_path="result.json",
        schema_ref=step.result_schema,
        media_type="application/json",
        sha256=revision.content_hash,
    )
    raw = artifacts.load_json_revision(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        content_hash=pointer.sha256,
        max_bytes=4 * 1024 * 1024,
    )
    role = validate_role_result(raw, "support", step.result_schema)
    if not isinstance(role, (ExternalItemLearningRoleResult, ExternalItemLearningRoleResultV2)):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_RESULT_POINTER_INVALID")
    if (
        (role.job_id, role.workflow_id, role.step_run_id)
        != (job.job_id, workflow.workflow_id, step.step_run_id)
        or role.artifact.logical_artifact_id != job.logical_artifact_id
        or role.artifact.revision_id != job.revision_id
    ):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_RESULT_JOB_MISMATCH")
    work, result = request.work_input, role.output.learning_result
    source = work.source
    validate_external_item_learning_result_for_source(
        result,
        source.input_sha256,
        source.source_id,
        source.source_revision_id,
        source.external_number,
    )
    if any(region.physical_page > len(work.page_set.pages) for region in result.regions):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_REGION_PAGE_INVALID")
    # A worker may reference only delivered image members, never an arbitrary
    # Artifact it happens to know. Cropped visuals need an explicit derivation.
    allowed = {
        (
            work.page_artifact.artifact_id,
            work.page_artifact.artifact_revision_id,
            page.member_path,
            page.sha256,
        )
        for page in work.page_set.pages
    }
    if (
        isinstance(role, ExternalItemLearningRoleResult)
        and role.output.learning_result.proposal is not None
        and any(
            (
                block.artifact.artifact_id,
                block.artifact.artifact_revision_id,
                block.artifact.artifact_member,
                block.artifact.sha256,
            )
            not in allowed
            for block in role.output.learning_result.proposal.content.body
            if isinstance(block, ImageBlock)
        )
    ):
        raise CreativeLearningProposalError("CREATIVE_LEARNING_IMAGE_POINTER_UNBOUND")
    return ResolvedCreativeLearningProposal(
        selection, workflow.created_actor_id, work, role, pointer
    )
