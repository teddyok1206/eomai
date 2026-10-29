"""Start an exact prepared creative role through the existing command queue."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.external_item_learning_execution import (
    validate_external_item_learning_execution_plan,
)
from eom_orchestrator.external_item_learning_page_publication import (
    read_external_item_learning_page_artifact,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_workflow.creative_learning_profile import creative_learning_profile
from eom_workflow.models import ExternalItemLearningWorkerRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.external_item_learning_admission import (
    ExternalItemLearningSourceAuthorizer,
    reauthorize_external_item_learning_submission,
    validate_external_item_learning_submission,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    enqueue_command,
    load_persisted_workflow_request,
)


@dataclass(frozen=True, slots=True)
class StartedExternalItemLearning:
    selection: ExternalItemLearningRoleSelection
    command_id: str
    command_state: str
    command_created: bool


def start_prepared_external_item_learning(
    session: Session,
    *,
    selection: ExternalItemLearningRoleSelection,
    operator_id: str,
    source_authorizer: ExternalItemLearningSourceAuthorizer,
    page_publisher: ControlFileSetPublisher,
) -> StartedExternalItemLearning:
    """Caller authenticates the operator and owns commit/rollback, including late denial."""
    if not session.in_transaction():
        raise ValueError("creative start requires a caller-owned root transaction")
    selection = ExternalItemLearningRoleSelection.model_validate(selection.model_dump(mode="json"))
    workflow = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == selection.workflow_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        workflow is None
        or workflow.created_actor_type != "human"
        or workflow.created_actor_id != operator_id
        or workflow.state not in {"REQUESTED", "RUNNING", "COMPLETED"}
        or workflow.definition_key != "external-item-learning"
    ):
        raise ValueError("creative start owner or lifecycle differs")
    profile = creative_learning_profile(workflow.definition_version)
    if workflow.role_schema_version != profile.role_protocol:
        raise ValueError("creative start protocol differs")
    definition = session.get(
        WorkflowDefinitionRecord, workflow.definition_id, populate_existing=True
    )
    if definition is None or definition.definition_hash != workflow.definition_hash:
        raise ValueError("creative start definition differs")
    request = validate_external_item_learning_submission(
        definition=definition,
        request=load_persisted_workflow_request(workflow.initial_request),
        actor_type=workflow.created_actor_type,
        actor_id=operator_id,
    )
    worker = request.worker_request()
    if (
        request != load_persisted_workflow_request(workflow.request_payload)
        or not isinstance(worker, ExternalItemLearningWorkerRequest)
        or worker.work_input.request_sha256 != selection.work_input_sha256
    ):
        raise ValueError("creative start original input differs")
    step = session.get(WorkflowStepRunRecord, selection.step_run_id, populate_existing=True)
    if (
        step is None
        or step.workflow_id != workflow.workflow_id
        or step.step_key != "extract"
        or step.step_type != "agent"
        or step.worker_role != "support"
        or step.result_schema != profile.result_schema
        or step.attempt != 1
    ):
        raise ValueError("creative start role differs")
    plan = validate_external_item_learning_execution_plan(
        session.get(ResolvedExecutionPlanRecord, selection.plan_id, populate_existing=True),
        workflow_id=workflow.workflow_id,
        step_key=step.step_key,
        request=worker,
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
        raise ValueError("creative start pinned plan differs")
    reauthorize_external_item_learning_submission(
        session, request=request, operator_id=operator_id, source_authorizer=source_authorizer
    )
    read_external_item_learning_page_artifact(page_publisher, worker.work_input.page_artifact)
    key = "creative-start:" + content_sha256(
        {"owner": operator_id, "selection": selection.model_dump(mode="json")}
    ).removeprefix("sha256:")
    commands = tuple(
        session.scalars(
            select(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.workflow_id == workflow.workflow_id)
            .limit(2)
        )
    )
    if commands:
        if len(commands) != 1 or (
            commands[0].idempotency_key != key
            or commands[0].command_type != CommandType.START_WORKFLOW.value
            or commands[0].actor_type != "human"
            or commands[0].actor_id != operator_id
            or commands[0].source != "creative_item_learning"
            or commands[0].payload != {}
        ):
            raise ValueError("creative start cannot adopt unrelated command history")
    elif (
        workflow.state != "REQUESTED"
        or workflow.stage != "KNOWLEDGE_ANALYSIS"
        or workflow.current_step_key != "extract"
        or step.state != "READY"
        or step.platform_job_id is not None
        or step.input_pointer_manifest != {"upstream_artifacts": []}
        or step.output_pointer_manifest is not None
        or step.started_at is not None
        or step.finished_at is not None
        or step.error_code is not None
        or step.superseded_by_step_run_id is not None
    ):
        raise ValueError("creative start requires an untouched prepared role")
    command, created = enqueue_command(
        session,
        workflow_id=workflow.workflow_id,
        command_type=CommandType.START_WORKFLOW,
        payload={},
        actor_type="human",
        actor_id=operator_id,
        source="creative_item_learning",
        idempotency_key=key,
    )
    reauthorize_external_item_learning_submission(
        session, request=request, operator_id=operator_id, source_authorizer=source_authorizer
    )
    return StartedExternalItemLearning(selection, command.command_id, command.state, created)
