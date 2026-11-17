"""Source owner authorizes only the persisted private phase linked to an exact Workflow."""

from eom_catalog_contracts.kakao_concept_authorization import (
    CONCEPT_AUTHORIZATION_MAX_BYTES,
    KakaoConceptAuthorizationReply,
    KakaoConceptAuthorizationRequest,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.kakao_concept_plan_resolution import validate_kakao_concept_execution_plan
from eom_workflow.compiler import compile_definition_data
from eom_workflow.kakao_concept_request import (
    CONCEPT_RESULT_SCHEMA,
    CONCEPT_ROLE_PROTOCOL,
    KakaoConceptWorkflowRequest,
)
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import load_persisted_workflow_request

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_models import KakaoConceptPhaseRecord
from .kakao_concept_task_service import KakaoConceptTaskService


class CatalogKakaoConceptAuthorizationService:
    def __init__(self, tasks: KakaoConceptTaskService) -> None:
        self.tasks = tasks

    def authorize(
        self, request: KakaoConceptAuthorizationRequest
    ) -> KakaoConceptAuthorizationReply:
        # End the metadata transaction before reading the private immutable Artifact.
        with self.tasks.sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, request.workflow_id)
            step = session.get(WorkflowStepRunRecord, request.step_run_id)
            if (
                workflow is None
                or step is None
                or workflow.state == "CANCELLED"
                or (
                    workflow.definition_key,
                    workflow.definition_version,
                    workflow.created_actor_type,
                )
                != ("kakao-concepts", "1.0.0", "human")
                or (step.workflow_id, step.step_key, step.worker_role, step.step_type, step.attempt)
                != (workflow.workflow_id, "assist", "support", "agent", 1)
                or workflow.role_schema_version != CONCEPT_ROLE_PROTOCOL
                or step.result_schema != CONCEPT_RESULT_SCHEMA
            ):
                raise ValueError("KAKAO_CONCEPT_STORED_ROLE_INVALID")
            definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
            if definition is None:
                raise ValueError("KAKAO_CONCEPT_DEFINITION_MISSING")
            compiled = compile_definition_data(
                definition.canonical_definition, definition.source_path, {"support"}
            )
            if (
                definition.definition_key,
                definition.definition_version,
                definition.definition_hash,
                compiled.sha256,
            ) != (
                workflow.definition_key,
                workflow.definition_version,
                workflow.definition_hash,
                workflow.definition_hash,
            ):
                raise ValueError("KAKAO_CONCEPT_DEFINITION_CHANGED")
            original = load_persisted_workflow_request(workflow.initial_request)
            if not isinstance(original, KakaoConceptWorkflowRequest) or original != (
                load_persisted_workflow_request(workflow.request_payload)
            ):
                raise ValueError("KAKAO_CONCEPT_STORED_INPUT_CHANGED")
            work, owner = original.work_input, workflow.created_actor_id
            plan = validate_kakao_concept_execution_plan(
                session.get(ResolvedExecutionPlanRecord, request.plan_id),
                workflow_id=workflow.workflow_id,
                step_key=step.step_key,
                work=work,
            )
            if (
                plan.plan_sha256 != request.plan_sha256
                or content_sha256(work) != request.work_sha256
                or plan.workflow_definition_sha256 != workflow.definition_hash
            ):
                raise ValueError("KAKAO_CONCEPT_AUTHORIZATION_PLAN_MISMATCH")
        authority = self.tasks.accepted_source_authority(task_id=work.task_id, operator_id=owner)
        with self.tasks.sessions() as session:
            current = session.get(
                WorkflowInstanceRecord, request.workflow_id, populate_existing=True
            )
            if current is None or current.state == "CANCELLED":
                raise ValueError("KAKAO_CONCEPT_WORKFLOW_CANCELLED")
            authority.reauthorize(session, operator_id=owner, work=work)
            phase = session.get(
                KakaoConceptPhaseRecord, (work.task_id, work.phase), populate_existing=True
            )
            if phase is None or phase.workflow_id != request.workflow_id:
                raise ValueError("KAKAO_CONCEPT_WORKFLOW_NOT_ACCEPTED")
        return KakaoConceptAuthorizationReply(
            status="SUCCESS",
            request_sha256=content_sha256(request),
            work_sha256=request.work_sha256,
            error_code=None,
        )


def dispatch_kakao_concept_authorization(
    value: object, service: CatalogKakaoConceptAuthorizationService | None
) -> bytes:
    # Invalid framing is rejected by the existing server; no unvalidated identity is echoed.
    if len(canonical_json_bytes(value)) > CONCEPT_AUTHORIZATION_MAX_BYTES:
        raise ValueError("KAKAO_CONCEPT_AUTHORIZATION_TOO_LARGE")
    request = KakaoConceptAuthorizationRequest.model_validate(value)
    try:
        if service is None:
            raise RuntimeError("concept authorization not configured")
        reply = service.authorize(request)
    except Exception as error:
        reply = KakaoConceptAuthorizationReply(
            status="FAILED",
            request_sha256=content_sha256(request),
            work_sha256=None,
            error_code="KAKAO_CONCEPT_AUTHORIZATION_FAILED"
            if isinstance(error, (ValueError, KakaoArchiveError))
            else "KAKAO_CONCEPT_AUTHORIZATION_UNAVAILABLE",
        )
    return canonical_json_bytes(reply) + b"\n"
