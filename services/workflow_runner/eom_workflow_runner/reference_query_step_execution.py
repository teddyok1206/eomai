"""Fixed QUERY Runner lifecycle; actual computation and canonical receipts stay with owners."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_workflow.compiler import CompiledWorkflowDefinition
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    ReferenceQueryWorkflowRequest,
    parse_reference_query_step_output,
)
from eom_workflow.reference_query_workflow import (
    REFERENCE_QUERY_RESULT_SCHEMA,
    ReferenceQueryWorkflowDefinition,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.native_step_completion import (
    complete_native_terminal,
    native_application_step,
)
from eom_workflow_runner.reference_query_admission import (
    ReferenceQueryOwnerAdmission,
    validate_reference_query_runner_admission,
)
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.repository import CommandLeaseIdentity, create_step_run
from eom_workflow_runner.state_machine import (
    StepState,
    WorkflowState,
    record_workflow_event,
    transition_step,
    transition_workflow,
)


def _checked_step(step: WorkflowStepRunRecord, request: ReferenceQueryWorkflowRequest) -> None:
    if (
        step.step_key != "encode_reference_query"
        or step.attempt != 1
        or step.step_type != "application"
        or step.worker_role is not None
        or step.result_schema != REFERENCE_QUERY_RESULT_SCHEMA
        or step.input_pointer_manifest != {"workflow_request_sha256": request.request_sha256}
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
            "QUERY step or immutable input hash differs",
        )


def _checked_completion(
    session: Session,
    *,
    executor: ReferenceQueryNativeExecutor,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: ReferenceQueryWorkflowRequest,
    lease: CommandLeaseIdentity,
    output: ReferenceQueryStepOutput,
) -> ReferenceQueryStepOutput:
    output = parse_reference_query_step_output(output)
    if (
        output.workflow_id != workflow.workflow_id
        or output.step_run_id != step.step_run_id
        or output.attempt != step.attempt
        or (
            step.platform_job_id is not None and step.platform_job_id != output.receipt_owner_job_id
        )
    ):
        raise ValueError("REFERENCE_QUERY_COMPLETION_IDENTITY_INVALID")
    checked = parse_reference_query_step_output(
        executor.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=request,
            command_lease=lease,
            output=output,
        )
    )
    if checked != output:
        raise ValueError("REFERENCE_QUERY_COMPLETION_REPLACEMENT_DENIED")
    return checked


def advance_reference_query_step(
    *,
    workflow: WorkflowInstanceRecord,
    compiled: CompiledWorkflowDefinition,
    request: ReferenceQueryWorkflowRequest,
    lease: CommandLeaseIdentity,
    owner: ReferenceQueryOwnerAdmission,
    executor: ReferenceQueryNativeExecutor,
    fenced_transaction: NativeFencedRunnerTransaction,
    actor_type: str,
    actor_id: str,
) -> None:
    if not isinstance(compiled.definition, ReferenceQueryWorkflowDefinition):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID, "QUERY fixed definition differs"
        )
    workflow_id = workflow.workflow_id
    with fenced_transaction() as session:
        current = session.get(WorkflowInstanceRecord, workflow_id)
        if current is None or current.current_step_key != "encode_reference_query":
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT, "QUERY step is no longer current"
            )
        if current.state == WorkflowState.REQUESTED.value:
            transition_workflow(
                session,
                workflow_id,
                WorkflowState.RUNNING,
                "WORKFLOW_STARTED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=lease.command_id,
                step_key="encode_reference_query",
            )
        if current.state != WorkflowState.RUNNING.value:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION, "QUERY Workflow is not running"
            )
        scope = validate_reference_query_runner_admission(
            owner.resolve_submission(session, request),
            compiled,
            actor_type=current.created_actor_type,
            actor_id=current.created_actor_id,
        )
        if scope.request != request:
            raise ValueError("REFERENCE_QUERY_EXECUTION_CONTEXT_INVALID")
        step = native_application_step(session, workflow_id, "encode_reference_query")
        if step is None:
            step = create_step_run(
                session,
                workflow_id=workflow_id,
                step_key="encode_reference_query",
                step_type="application",
                worker_role=None,
                result_schema=REFERENCE_QUERY_RESULT_SCHEMA,
                input_pointer_manifest={"workflow_request_sha256": request.request_sha256},
                max_attempts=1,
            )
        _checked_step(step, request)
        if step.state == StepState.SUCCEEDED.value:
            try:
                _checked_completion(
                    session,
                    executor=executor,
                    workflow=current,
                    step=step,
                    request=request,
                    lease=lease,
                    output=parse_reference_query_step_output(step.output_pointer_manifest),
                )
            except ValueError as exc:
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                    "QUERY step replay receipt could not be validated",
                ) from exc
            current.current_step_key = "complete"
            return
        if step.state == StepState.READY.value:
            transition_step(step, StepState.RUNNING)
            step.started_at = datetime.now(UTC)
            record_workflow_event(
                session,
                workflow_id,
                "REFERENCE_QUERY_STEP_STARTED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=lease.command_id,
                step_key="encode_reference_query",
            )
        if step.state != StepState.RUNNING.value:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                "QUERY cannot restart a failed or cancelled attempt",
            )
        step_run_id = step.step_run_id
        session.expunge(current)
        session.expunge(step)
    # No source lock, Session or SQL root survives into actual numerical work.
    outcome = executor.execute(
        workflow=current,
        step=step,
        request=request,
        command_lease=lease,
        idempotency_key=f"reference-query-step:{workflow_id}:encode_reference_query:1:{compiled.sha256}",
        fenced_transaction=fenced_transaction,
    )
    with fenced_transaction() as session:
        current = session.get(WorkflowInstanceRecord, workflow_id)
        step = session.get(WorkflowStepRunRecord, step_run_id)
        if (
            current is None
            or step is None
            or current.state != WorkflowState.RUNNING.value
            or current.current_step_key != "encode_reference_query"
            or step.workflow_id != workflow_id
            or step.state != StepState.RUNNING.value
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "QUERY completion lost its original current step",
            )
        _checked_step(step, request)
        if not isinstance(outcome, ReferenceQueryStepOutput):
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                "QUERY executor returned another purpose's outcome",
            )
        try:
            output = _checked_completion(
                session,
                executor=executor,
                workflow=current,
                step=step,
                request=request,
                lease=lease,
                output=outcome,
            )
        except ValueError as exc:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                "QUERY canonical completion could not be validated",
            ) from exc
        step.platform_job_id = output.receipt_owner_job_id
        step.output_pointer_manifest = output.model_dump(mode="json")
        step.finished_at = datetime.now(UTC)
        transition_step(step, StepState.SUCCEEDED)
        current.current_step_key = "complete"
        record_workflow_event(
            session,
            workflow_id,
            "REFERENCE_QUERY_STEP_SUCCEEDED",
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=lease.command_id,
            step_key="encode_reference_query",
        )


def complete_reference_query_terminal(
    *,
    workflow_id: str,
    request: ReferenceQueryWorkflowRequest,
    lease: CommandLeaseIdentity,
    executor: ReferenceQueryNativeExecutor,
    fenced_transaction: NativeFencedRunnerTransaction,
    actor_type: str,
    actor_id: str,
) -> None:
    def validate(
        session: Session, workflow: WorkflowInstanceRecord, step: WorkflowStepRunRecord
    ) -> ReferenceQueryStepOutput:
        _checked_step(step, request)
        return _checked_completion(
            session,
            executor=executor,
            workflow=workflow,
            step=step,
            request=request,
            lease=lease,
            output=parse_reference_query_step_output(step.output_pointer_manifest),
        )

    complete_native_terminal(
        workflow_id=workflow_id,
        step_key="encode_reference_query",
        lease=lease,
        validate_completion=validate,
        fenced_transaction=fenced_transaction,
        actor_type=actor_type,
        actor_id=actor_id,
    )
