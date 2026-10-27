"""Persist exact creative inputs and a READY role without scheduling execution.

The submitting application owns authentication and the root transaction. Current
source permission is checked by the Catalog port; file-set resolution remains
owned by Orchestrator. This module never enqueues commands or launches workers.
"""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningWorkInput
from eom_orchestrator.execution_resolver import resolve_external_item_learning_plan
from eom_orchestrator.external_item_learning_page_publication import (
    read_external_item_learning_page_artifact,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.models import WorkflowRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
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
from eom_workflow_runner.repository import create_step_run, create_workflow_instance
from eom_workflow_runner.state_machine import record_workflow_event


@dataclass(frozen=True, slots=True)
class PreparedExternalItemLearning:
    selection: ExternalItemLearningRoleSelection
    workflow_created: bool
    step_created: bool


def prepare_external_item_learning_workflow(
    session: Session,
    *,
    definition: WorkflowDefinitionRecord,
    work: ExternalItemLearningWorkInput,
    operator_id: str,
    idempotency_key: str,
    source_authorizer: ExternalItemLearningSourceAuthorizer,
    page_publisher: ControlFileSetPublisher,
    expected_preset: ExecutionPresetRevision | None = None,
) -> PreparedExternalItemLearning:
    """Prepare in the caller root; any rejection leaves no partial preparation.

    No command is created. A READY role is data, not a worker claim; the ordinary
    runner still requires its separately authorized START_WORKFLOW command.
    """

    if not session.in_transaction():
        raise ValueError("creative preparation requires a caller-owned root transaction")
    try:
        request = WorkflowRequest(
            request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
            image_mode="skip",
            execution_preset_key="external-item-learning",
            external_item_learning_work=work,
        )
        request = validate_external_item_learning_submission(
            definition=definition, request=request, actor_type="human", actor_id=operator_id
        )
        checked_work = request.external_item_learning_work
        if checked_work is None:  # the typed submission validator above requires this branch
            raise ValueError("creative work input is missing")
        work = checked_work
        reauthorize_external_item_learning_submission(
            session, request=request, operator_id=operator_id, source_authorizer=source_authorizer
        )
        read_external_item_learning_page_artifact(page_publisher, work.page_artifact)
        workflow, created = create_workflow_instance(
            session,
            definition=definition,
            request=request,
            idempotency_key=idempotency_key,
            actor_type="human",
            actor_id=operator_id,
            external_item_learning_authorizer=source_authorizer,
        )
        # Serialize same-key and different-key equivalent preparations before
        # checking or creating the one READY step. Do not manufacture attempts.
        locked = session.scalar(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == workflow.workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            locked is None
            or locked.state != "REQUESTED"
            or locked.stage != "KNOWLEDGE_ANALYSIS"
            or locked.current_step_key != "extract"
            or session.scalar(
                select(WorkflowCommandRecord.command_id)
                .where(WorkflowCommandRecord.workflow_id == workflow.workflow_id)
                .limit(1)
            )
            is not None
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                "creative preparation cannot reinterpret scheduled or terminal history",
            )
        plan = resolve_external_item_learning_plan(
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
        existing_pointer = workflow.runtime_context.get("execution_plan")
        if existing_pointer is not None and existing_pointer != pointer:
            raise ValueError("creative preparation plan pointer differs")
        workflow.runtime_context = {**workflow.runtime_context, "execution_plan": pointer}
        steps = tuple(
            session.scalars(
                select(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == workflow.workflow_id)
                .order_by(WorkflowStepRunRecord.step_key, WorkflowStepRunRecord.attempt)
                .limit(2)
            )
        )
        if len(steps) > 1:
            raise ValueError("creative preparation has additional step history")
        step = steps[0] if steps else None
        step_created = step is None
        if step is None:
            step = create_step_run(
                session,
                workflow_id=workflow.workflow_id,
                step_key="extract",
                step_type="agent",
                worker_role="support",
                result_schema="external-item-learning-result@1.0",
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
                step_key="extract",
                payload={"step_run_id": step.step_run_id, "attempt": 1},
            )
        if (
            step.state != "READY"
            or step.step_key != "extract"
            or step.attempt != 1
            or step.step_type != "agent"
            or step.worker_role != "support"
            or step.result_schema != "external-item-learning-result@1.0"
            or step.platform_job_id is not None
            or step.input_pointer_manifest != {"upstream_artifacts": []}
            or step.output_pointer_manifest is not None
            or step.started_at is not None
            or step.finished_at is not None
            or step.error_code is not None
            or step.superseded_by_step_run_id is not None
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                "creative preparation requires its untouched READY role",
            )
        reauthorize_external_item_learning_submission(
            session, request=request, operator_id=operator_id, source_authorizer=source_authorizer
        )
        session.flush()
        return PreparedExternalItemLearning(
            selection=ExternalItemLearningRoleSelection(
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                work_input_sha256=work.request_sha256,
            ),
            workflow_created=created,
            step_created=step_created,
        )
    except Exception:
        # A caller must not catch a late source/preset failure and commit an
        # orphan Workflow, plan, READY event or stale preparation pointer.
        session.rollback()
        raise
