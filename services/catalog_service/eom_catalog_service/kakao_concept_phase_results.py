"""Read the exact completed child result through Workflow/Job and Artifact owners."""

from dataclasses import dataclass, field
from typing import Literal

from eom_catalog_contracts.kakao_concept_knowledge import KakaoConceptResultPin
from eom_identifiers import sha256_bytes
from eom_kakao_archive_contracts import canonical_bytes
from eom_kakao_archive_contracts.concepts import (
    ConceptComposeRequest,
    ConceptPlanRequest,
    validate_concept_result,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.kakao_concept_request import (
    KakaoConceptWork,
    KakaoConceptWorkerRequest,
    KakaoConceptWorkflowRequest,
    validate_kakao_concept_request_bytes,
)
from eom_workflow.kakao_concept_result import KakaoConceptRoleResult
from eom_workflow.models import RoleWorkerInput
from eom_workflow.schemas import validate_role_result_for_request
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import load_persisted_workflow_request
from sqlalchemy import select

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_models import KakaoConceptPhaseRecord
from .kakao_concept_task_service import KakaoConceptSourceAuthority


@dataclass(frozen=True, slots=True)
class CompletedKakaoConceptPhase:
    work: KakaoConceptWork
    pin: KakaoConceptResultPin
    request: ConceptPlanRequest | ConceptComposeRequest = field(repr=False)
    result: KakaoConceptRoleResult = field(repr=False)


def read_kakao_concept_phase_result(
    authority: KakaoConceptSourceAuthority, phase: Literal["PLAN", "COMPOSE"]
) -> CompletedKakaoConceptPhase:
    service = authority.service
    with service.sessions() as session:
        task = service.accepted_intent_row(
            session, authority.intent, operator_id=authority.owner_operator_id
        )
        stored = session.get(KakaoConceptPhaseRecord, (task.task_id, phase))
        if stored is None or stored.workflow_id is None:
            raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_NOT_READY")
        work = KakaoConceptWork.model_validate(stored.work_input)
        authority.reauthorize(session, operator_id=task.owner_operator_id, work=work)
        workflow = session.get(WorkflowInstanceRecord, stored.workflow_id)
        steps = tuple(
            session.scalars(
                select(WorkflowStepRunRecord)
                .where(
                    WorkflowStepRunRecord.workflow_id == stored.workflow_id,
                    WorkflowStepRunRecord.step_key == "assist",
                )
                .limit(2)
            )
        )
        if workflow is None or workflow.state != "COMPLETED" or len(steps) != 1:
            raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_NOT_READY")
        original = load_persisted_workflow_request(workflow.initial_request)
        if (
            (
                workflow.definition_key,
                workflow.definition_version,
                workflow.role_schema_version,
                workflow.created_actor_type,
            )
            != ("kakao-concepts", "1.0.0", "workflow-role/1.41.0", "human")
            or not isinstance(original, KakaoConceptWorkflowRequest)
            or original.work_input != work
            or original != load_persisted_workflow_request(workflow.request_payload)
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
        step = steps[0]
        job = session.get(JobRecord, step.platform_job_id) if step.platform_job_id else None
        if (
            (step.worker_role, step.result_schema, step.state, step.attempt)
            != ("support", "kakao-concepts-result@1.0", "SUCCEEDED", 1)
            or job is None
            or job.status != "SUCCEEDED"
            or job.task_type != "workflow_support"
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_NOT_READY")
        revision = session.get(ArtifactRevisionRecord, job.revision_id)
        if (
            revision is None
            or not revision.approved
            or (revision.logical_artifact_id, revision.job_id)
            != (job.logical_artifact_id, job.job_id)
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
        worker_input = RoleWorkerInput.model_validate(job.request)
        if (
            worker_input.job_id,
            worker_input.workflow_id,
            worker_input.step_run_id,
            worker_input.role,
            worker_input.protocol_version,
            worker_input.request,
        ) != (
            job.job_id,
            workflow.workflow_id,
            step.step_run_id,
            "support",
            "workflow-role/1.41.0",
            KakaoConceptWorkerRequest(work_input=work),
        ) or workflow.created_actor_id != task.owner_operator_id:
            raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
        if (
            worker_input.artifact.logical_artifact_id,
            worker_input.artifact.revision_id,
            worker_input.attempt,
            job.protocol_version,
        ) != (
            job.logical_artifact_id,
            job.revision_id,
            step.attempt,
            worker_input.protocol_version,
        ):
            raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
        pin = KakaoConceptResultPin(
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            job_id=job.job_id,
            artifact_id=revision.logical_artifact_id,
            artifact_revision_id=revision.revision_id,
            sha256=revision.content_hash,
        )
    payload = service.artifacts.read_member(
        artifact_id=work.request_member.artifact_id,
        revision_id=work.request_member.artifact_revision_id,
        member_path=work.request_member.member_path,
        schema_ref=work.request_member.schema_ref,
        media_type=work.request_member.media_type,
        sha256=work.request_member.sha256,
        max_bytes=work.request_bytes,
    )
    request = validate_kakao_concept_request_bytes(work, payload)
    raw = service.artifacts.load_json_revision(
        artifact_id=pin.artifact_id,
        revision_id=pin.artifact_revision_id,
        content_hash=pin.sha256,
        max_bytes=512 * 1024,
    )
    if sha256_bytes(canonical_bytes(raw)) != pin.sha256:
        raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
    result = validate_role_result_for_request(
        raw, "support", "kakao-concepts-result@1.0", worker_input
    )
    if not isinstance(result, KakaoConceptRoleResult) or (
        result.job_id,
        result.workflow_id,
        result.step_run_id,
        result.artifact,
    ) != (
        worker_input.job_id,
        worker_input.workflow_id,
        worker_input.step_run_id,
        worker_input.artifact,
    ):
        raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_POINTER_INVALID")
    validate_concept_result(request, result.output.model_dump(mode="json"))
    with service.sessions() as session:
        authority.reauthorize(session, operator_id=authority.owner_operator_id, work=work)
    return CompletedKakaoConceptPhase(work, pin, request, result)
