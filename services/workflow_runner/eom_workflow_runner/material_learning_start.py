"""Submit one prepared material task through the existing Workflow/command owner."""

from dataclasses import dataclass

from eom_catalog_contracts.material_learning import MaterialLearningWork
from eom_orchestrator.material_learning_plan_resolution import resolve_material_learning_plan
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.material_learning_request import MaterialLearningWorkflowRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.material_learning_admission import (
    MaterialLearningSourceAuthorizer,
    reauthorize_material_learning_submission,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    create_step_run,
    create_workflow_instance,
    enqueue_command,
)
from eom_workflow_runner.state_machine import record_workflow_event


@dataclass(frozen=True, slots=True)
class SubmittedMaterialLearning:
    workflow_id: str
    step_run_id: str
    command_id: str
    command_state: str
    workflow_created: bool


def submit_material_learning_workflow(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    work: MaterialLearningWork,
    operator_id: str,
    idempotency_key: str,
    source_authorizer: MaterialLearningSourceAuthorizer,
    expected_preset: ExecutionPresetRevision,
) -> SubmittedMaterialLearning:
    if not session.in_transaction():
        raise ValueError("material submission requires a caller-owned root transaction")
    request = MaterialLearningWorkflowRequest(work_input=work)
    # A caller catching a late plan/source failure must not commit an orphan child.
    with session.begin_nested():
        workflow, created = create_workflow_instance(
            session,
            definition=definition,
            request=request,
            idempotency_key=idempotency_key,
            actor_type="human",
            actor_id=operator_id,
            material_learning_authorizer=source_authorizer,
        )
        workflow = session.scalars(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == workflow.workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        plan = resolve_material_learning_plan(
            session,
            workflow_id=workflow.workflow_id,
            workflow_definition_sha256=definition.definition_hash,
            workflow_role_schema_version=workflow.role_schema_version,
            work=work,
            expected_preset=expected_preset,
        )
        pointer = {
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "preset_id": plan.preset_id,
            "preset_revision_id": plan.preset_revision_id,
        }
        prior = workflow.runtime_context.get("execution_plan")
        if prior is not None and prior != pointer:
            raise ValueError("material execution pointer differs")
        workflow.runtime_context = {**workflow.runtime_context, "execution_plan": pointer}
        steps = tuple(
            session.scalars(
                select(WorkflowStepRunRecord)
                .where(
                    WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
                    WorkflowStepRunRecord.step_key == "learn",
                    WorkflowStepRunRecord.step_type == "agent",
                )
                .limit(2)
            )
        )
        if len(steps) > 1:
            raise ValueError("material purpose has unexpected step history")
        if not steps:
            if workflow.state != "REQUESTED":
                raise ValueError("material role cannot be created after start")
            step = create_step_run(
                session,
                workflow_id=workflow.workflow_id,
                step_key="learn",
                step_type="agent",
                worker_role="support",
                result_schema="material-learning-result@1.0",
                input_pointer_manifest={"upstream_artifacts": []},
                max_attempts=1,
            )
            record_workflow_event(
                session,
                workflow.workflow_id,
                "STEP_READY",
                actor_type="human",
                actor_id=operator_id,
                command_id=None,
                step_key="learn",
                payload={"step_run_id": step.step_run_id, "attempt": 1},
            )
        else:
            step = steps[0]
        if (
            step.step_key != "learn"
            or step.step_type != "agent"
            or step.worker_role != "support"
            or step.result_schema != "material-learning-result@1.0"
            or step.attempt != 1
        ):
            raise ValueError("material stored role differs")
        commands = tuple(
            session.scalars(
                select(WorkflowCommandRecord)
                .where(
                    WorkflowCommandRecord.workflow_id == workflow.workflow_id,
                    WorkflowCommandRecord.command_type == CommandType.START_WORKFLOW.value,
                )
                .limit(2)
            )
        )
        key = "material-start:" + workflow.workflow_id
        if commands:
            if len(commands) != 1 or (
                commands[0].idempotency_key != key
                or commands[0].command_type != CommandType.START_WORKFLOW.value
                or commands[0].actor_type != "human"
                or commands[0].actor_id != operator_id
                or commands[0].source != "material_learning"
                or commands[0].payload != {}
            ):
                raise ValueError("material cannot adopt unrelated command history")
        elif (
            workflow.state != "REQUESTED"
            or step.state != "READY"
            or step.platform_job_id is not None
        ):
            raise ValueError("material start requires an untouched prepared role")
        reauthorize_material_learning_submission(
            session,
            request=request,
            operator_id=operator_id,
            source_authorizer=source_authorizer,
        )
        command, _ = enqueue_command(
            session,
            workflow_id=workflow.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type="human",
            actor_id=operator_id,
            source="material_learning",
            idempotency_key=key,
        )
        reauthorize_material_learning_submission(
            session,
            request=request,
            operator_id=operator_id,
            source_authorizer=source_authorizer,
        )
        return SubmittedMaterialLearning(
            workflow.workflow_id, step.step_run_id, command.command_id, command.state, created
        )
