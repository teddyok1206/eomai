"""Owner-only explicit failure of an exact never-allocated indexing execution.

No source grant, Workflow rewrite, lease renewal, Job, unit or Artifact is created.
The caller commits/rolls back one short root. A successor still needs its own
ordinary release, current authorization and missing-binding submission.
"""

from __future__ import annotations

from eom_identifiers import content_sha256
from eom_identity_service import lock_current_local_indexing_service_metadata
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_embedding_launch_identity import native_embedding_launch_key
from eom_workflow.local_embedding_request import (
    local_embedding_request_service,
    parse_local_embedding_service_workflow_request,
)
from eom_workflow.local_indexing_preallocation_retirement import (
    LocalIndexingPreallocationRetirementCommand,
    LocalIndexingPreallocationRetirementReceipt,
    parse_local_indexing_retirement_command,
    parse_local_indexing_retirement_receipt,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_start_command import (
    LOCAL_EMBEDDING_SUBMISSION_SOURCE,
    resolve_native_start_command,
)
from eom_workflow_runner.repository import validate_local_embedding_workflow_submission
from eom_workflow_runner.state_machine import (
    CommandState,
    StepState,
    WorkflowStage,
    WorkflowState,
    transition_command,
    transition_stage,
    transition_step,
    transition_workflow,
)

RETIREMENT_EVENT = "LOCAL_INDEXING_PREALLOCATION_RETIRED"


class LocalIndexingRetirementError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _owner(session: Session) -> str:
    root = session.get_transaction()
    if (
        root is None
        or not root.is_active
        or session.in_nested_transaction()
        or session.new
        or session.dirty
        or session.deleted
        or session.get_bind().dialect.name != "postgresql"
    ):
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_CONTEXT_INVALID")
    principal, current, writable, isolation = session.execute(
        text(
            "SELECT SESSION_USER,CURRENT_USER,"
            "pg_catalog.current_setting('transaction_read_only')='off',"
            "pg_catalog.current_setting('transaction_isolation')"
        )
    ).one()
    owners = session.execute(
        text(
            "SELECT c.relname,pg_catalog.pg_get_userbyid(c.relowner) "
            "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='app' AND c.relkind='r' AND c.relname IN "
            "('workflow_instances','workflow_commands','workflow_step_runs','workflow_events')"
        )
    ).all()
    if (
        not isinstance(principal, str)
        or current != principal
        or len(owners) != 4
        or any(owner != principal for _table, owner in owners)
    ):
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_OWNER_REQUIRED")
    if writable is not True or isolation != "read committed":
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_CONTEXT_INVALID")
    return principal


def retire_unallocated_indexing_workflow(
    session: Session, command: LocalIndexingPreallocationRetirementCommand
) -> LocalIndexingPreallocationRetirementReceipt:
    """Verify exact preallocation evidence, then append FAILED history atomically.

    This operation is explicit owner maintenance, not a runtime automatic retry.
    A DB timeout/race requires rollback and exact replay, never a force flag.
    """
    command = parse_local_indexing_retirement_command(command)
    principal = _owner(session)
    try:
        return _retire(session, command, principal)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in {"55P03", "57014", "40P01"}:
            raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_BUSY") from error
        raise


def _retire(
    session: Session, command: LocalIndexingPreallocationRetirementCommand, principal: str
) -> LocalIndexingPreallocationRetirementReceipt:
    workflow = session.scalar(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == command.workflow_id)
        .with_for_update(nowait=True)
        .execution_options(populate_existing=True)
    )
    if workflow is None:
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_SCOPE_INVALID")
    request = parse_local_embedding_service_workflow_request(workflow.initial_request)
    if (
        request.request_sha256 != command.workflow_request_sha256
        or local_embedding_request_service(request) != command.service
        or workflow.created_actor_type != "local_indexing_service"
        or workflow.created_actor_id != command.service.service_id
    ):
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_SCOPE_INVALID")
    definition = session.get(
        WorkflowDefinitionRecord, workflow.definition_id, populate_existing=True
    )
    if definition is None:
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_SCOPE_INVALID")
    validate_local_embedding_workflow_submission(
        session,
        workflow,
        definition=definition,
        request=request,
        actor_type="local_indexing_service",
        actor_id=command.service.service_id,
    )
    rows = tuple(
        session.scalars(
            select(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.workflow_id == workflow.workflow_id)
            .order_by(WorkflowCommandRecord.command_id)
            .limit(2)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
    )
    steps = tuple(
        session.scalars(
            select(WorkflowStepRunRecord)
            .where(WorkflowStepRunRecord.workflow_id == workflow.workflow_id)
            .order_by(WorkflowStepRunRecord.step_run_id)
            .limit(2)
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
    )
    if len(rows) != 1 or len(steps) != 1:
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_PREALLOCATION_UNPROVEN")
    original, step = rows[0], steps[0]
    start, _created = resolve_native_start_command(
        session,
        workflow=workflow,
        workflow_created=False,
        actor_type="local_indexing_service",
        actor_id=command.service.service_id,
        source=LOCAL_EMBEDDING_SUBMISSION_SOURCE,
    )
    if (
        start is not original
        or original.command_id != command.command_id
        or original.lease_generation != command.lease_generation
        or original.attempts != command.lease_generation
        or step.step_key != "encode_batch"
        or step.attempt != 1
        or step.step_type != "application"
        or step.worker_role is not None
        or step.result_schema != "incremental-embedding-result@1.0"
        or step.platform_job_id is not None
        or step.output_pointer_manifest is not None
        or step.input_pointer_manifest
        != {
            "source_plan": request.source_plan.model_dump(mode="json"),
            "source_plan_sha256": request.source_plan_sha256,
        }
        or session.scalar(
            select(JobRecord.job_id).where(
                JobRecord.idempotency_key
                == native_embedding_launch_key(
                    workflow.workflow_id, step.step_run_id, request.request_sha256
                )
            )
        )
        is not None
    ):
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_PREALLOCATION_UNPROVEN")
    events = tuple(
        session.scalars(
            select(WorkflowEventRecord)
            .where(
                WorkflowEventRecord.workflow_id == workflow.workflow_id,
                WorkflowEventRecord.event_type == RETIREMENT_EVENT,
            )
            .order_by(WorkflowEventRecord.sequence)
            .limit(2)
        )
    )
    if events:
        if len(events) != 1:
            raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_HISTORY_INVALID")
        event = events[0]
        receipt = parse_local_indexing_retirement_receipt(event.payload)
        if receipt.command != command:
            raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_REPLAY_CONFLICT")
        if (
            receipt.step_run_id != step.step_run_id
            or event.actor_type != "database_owner"
            or event.actor_id != receipt.performed_by
            or event.command_id != command.command_id
            or (workflow.state, workflow.stage, original.state, step.state)
            != ("FAILED", "FAILED", "FAILED", "FAILED")
            or (workflow.failure_code, original.error_code, step.error_code)
            != (command.reason,) * 3
        ):
            raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_HISTORY_INVALID")
        return receipt
    # A first retirement is a control-plane mutation: exact current metadata and
    # actual Identity owner are checked, never an impersonated runtime principal.
    identity = lock_current_local_indexing_service_metadata(session, command.service)
    if identity.runtime_source_commit == command.successor_source_commit:
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_SCOPE_INVALID")
    now = session.scalar(select(func.clock_timestamp()))
    if now is None or (
        workflow.state != "RUNNING"
        or workflow.stage != "LOCAL_EMBEDDING"
        or workflow.current_step_key != "encode_batch"
        or original.state != "PROCESSING"
        or step.state != "RUNNING"
        or original.lease_expires_at is None
        or original.lease_expires_at >= now
        or original.lease_owner is None
        or original.lease_token is None
        or workflow.failure_code is not None
        or original.error_code is not None
        or step.error_code is not None
        or step.finished_at is not None
        or workflow.completed_at is not None
        or original.processed_at is not None
    ):
        raise LocalIndexingRetirementError("LOCAL_INDEXING_RETIREMENT_PREALLOCATION_UNPROVEN")
    body = {
        "schema_version": "local-indexing-preallocation-retirement/1.0",
        "record_type": "RECEIPT",
        "command": command.model_dump(mode="json"),
        "step_run_id": step.step_run_id,
        "performed_by": principal,
        "performed_at": now.isoformat().replace("+00:00", "Z"),
        "prior_command_state": "PROCESSING",
        "new_workflow_state": "FAILED",
        "new_stage": "FAILED",
        "new_command_state": "FAILED",
        "new_step_state": "FAILED",
    }
    receipt = parse_local_indexing_retirement_receipt(
        body | {"receipt_sha256": content_sha256(body)}
    )
    transition_command(original, CommandState.FAILED)
    original.error_code = command.reason
    transition_step(step, StepState.FAILED)
    step.error_code = command.reason
    workflow.failure_code = command.reason
    transition_stage(
        session,
        workflow.workflow_id,
        WorkflowStage.FAILED,
        "encode_batch",
        "LOCAL_INDEXING_PREALLOCATION_STAGE_FAILED",
        actor_type="database_owner",
        actor_id=principal,
        command_id=command.command_id,
    )
    transition_workflow(
        session,
        workflow.workflow_id,
        WorkflowState.FAILED,
        RETIREMENT_EVENT,
        actor_type="database_owner",
        actor_id=principal,
        command_id=command.command_id,
        step_key="encode_batch",
        payload=receipt.model_dump(mode="json"),
    )
    session.flush()
    return receipt
