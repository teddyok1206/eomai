"""Submit a pinned concept phase to the existing Workflow command queue."""

from dataclasses import dataclass

from eom_orchestrator.kakao_concept_plan_resolution import resolve_kakao_concept_plan
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.kakao_concept_request import KakaoConceptWork, KakaoConceptWorkflowRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from .kakao_concept_admission import (
    KakaoConceptSourceAuthorizer,
    reauthorize_kakao_concept_submission,
)
from .models import WorkflowCommandRecord, WorkflowDefinitionRecord, WorkflowInstanceRecord
from .repository import CommandType, create_workflow_instance, enqueue_command


@dataclass(frozen=True, slots=True)
class SubmittedKakaoConcept:
    workflow_id: str
    command_id: str
    command_state: str
    workflow_created: bool


def submit_kakao_concept_workflow(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    work: KakaoConceptWork,
    operator_id: str,
    idempotency_key: str,
    source_authorizer: KakaoConceptSourceAuthorizer,
    expected_preset: ExecutionPresetRevision,
) -> SubmittedKakaoConcept:
    if not session.in_transaction():
        raise ValueError("concept submission requires a caller-owned root transaction")
    request = KakaoConceptWorkflowRequest(work_input=work)
    with session.begin_nested():
        workflow, created = create_workflow_instance(
            session,
            definition=definition,
            request=request,
            idempotency_key=idempotency_key,
            actor_type="human",
            actor_id=operator_id,
            kakao_concept_authorizer=source_authorizer,
        )
        workflow = session.scalars(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == workflow.workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        plan = resolve_kakao_concept_plan(
            session,
            workflow_id=workflow.workflow_id,
            workflow_definition_sha256=definition.definition_hash,
            workflow_role_schema_version=workflow.role_schema_version,
            work=work,
            expected_preset=expected_preset,
        )
        pointer = dict(
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            preset_id=plan.preset_id,
            preset_revision_id=plan.preset_revision_id,
        )
        prior = workflow.runtime_context.get("execution_plan")
        if prior is not None and prior != pointer:
            raise ValueError("concept execution pointer differs")
        workflow.runtime_context = workflow.runtime_context | dict(execution_plan=pointer)
        reauthorize_kakao_concept_submission(
            session, request=request, operator_id=operator_id, source_authorizer=source_authorizer
        )
        key = "kakao-concept-start:" + workflow.workflow_id
        starts = tuple(
            session.scalars(
                select(WorkflowCommandRecord)
                .where(
                    WorkflowCommandRecord.workflow_id == workflow.workflow_id,
                    WorkflowCommandRecord.command_type == CommandType.START_WORKFLOW.value,
                )
                .limit(2)
            )
        )
        if starts and (
            len(starts) != 1
            or any(
                (
                    starts[0].idempotency_key != key,
                    starts[0].actor_type != "human",
                    starts[0].actor_id != operator_id,
                    starts[0].source != "kakao_concepts",
                    starts[0].payload != {},
                )
            )
        ):
            raise ValueError("concept cannot adopt unrelated command history")
        command, command_created = enqueue_command(
            session,
            workflow_id=workflow.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type="human",
            actor_id=operator_id,
            source="kakao_concepts",
            idempotency_key=key,
        )
        if command_created and workflow.state != "REQUESTED":
            raise ValueError("concept start requires its untouched prepared Workflow")
        reauthorize_kakao_concept_submission(
            session, request=request, operator_id=operator_id, source_authorizer=source_authorizer
        )
        # Normal Runner start creates its one role; do not maintain a second step factory.
        return SubmittedKakaoConcept(
            workflow.workflow_id, command.command_id, command.state, created
        )
