"""Fixed native two-step Runner use case; actual computation/publication stays with its owner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from eom_workflow.compiler import CompiledWorkflowDefinition
from eom_workflow.local_embedding_request_v2 import (
    LocalEmbeddingWorkflowRequestV2,
    SupportedLocalEmbeddingRequest,
)
from eom_workflow.local_embedding_request_v3 import LocalEmbeddingWorkflowRequestV3
from eom_workflow.local_embedding_workflow import LocalEmbeddingWorkflowDefinition
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    LocalEmbeddingStepOutputV2,
    SupportedLocalEmbeddingStepOutput,
    parse_supported_local_embedding_step_output,
)
from eom_workflow.local_embedding_workflow_receipt_v3 import LocalEmbeddingStepOutputV3
from eom_workflow.local_embedding_workflow_v2 import LocalEmbeddingWorkflowDefinitionV2
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import (
    LocalEmbeddingOwnerAdmission,
    validate_local_embedding_runner_admission,
)
from eom_workflow_runner.local_embedding_execution_port import (
    LocalEmbeddingNativeExecutor,
    LocalEmbeddingStepPending,
    NativeFencedRunnerTransaction,
)
from eom_workflow_runner.models import (
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_step_completion import (
    complete_native_terminal,
    native_application_step,
)
from eom_workflow_runner.native_workflow_transaction import (
    native_fenced_runner_transaction as native_fenced_runner_transaction,
)
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    CommandType,
    create_step_run,
    enqueue_command,
)
from eom_workflow_runner.state_machine import (
    StepState,
    WorkflowState,
    record_workflow_event,
    transition_step,
    transition_workflow,
)


def _native_step(session: Session, workflow_id: str) -> WorkflowStepRunRecord | None:
    return native_application_step(session, workflow_id, "encode_batch")


def _checked_step(step: WorkflowStepRunRecord, request: SupportedLocalEmbeddingRequest) -> None:
    if (
        step.step_key != "encode_batch"
        or step.attempt != 1
        or step.step_type != "application"
        or step.worker_role is not None
        or step.result_schema != "incremental-embedding-result@1.0"
        or step.input_pointer_manifest
        != {
            "source_plan": request.source_plan.model_dump(mode="json"),
            "source_plan_sha256": request.source_plan_sha256,
        }
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
            "native step identity or original input pointer differs",
        )


def _checked_completion(
    session: Session,
    *,
    executor: LocalEmbeddingNativeExecutor,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: SupportedLocalEmbeddingRequest,
    lease: CommandLeaseIdentity,
    output: SupportedLocalEmbeddingStepOutput,
) -> SupportedLocalEmbeddingStepOutput:
    output = parse_supported_local_embedding_step_output(output)
    if isinstance(request, LocalEmbeddingWorkflowRequestV2) != isinstance(
        output, LocalEmbeddingStepOutputV2
    ) or (
        isinstance(request, LocalEmbeddingWorkflowRequestV3)
        != isinstance(output, LocalEmbeddingStepOutputV3)
    ):
        raise ValueError("LOCAL_EMBEDDING_COMPLETION_FAMILY_MISMATCH")
    if (
        output.workflow_id != workflow.workflow_id
        or output.step_run_id != step.step_run_id
        or output.attempt != step.attempt
        or (
            step.platform_job_id is not None and step.platform_job_id != output.receipt_owner_job_id
        )
    ):
        raise ValueError("LOCAL_EMBEDDING_COMPLETION_IDENTITY_INVALID")
    checked = parse_supported_local_embedding_step_output(
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
        raise ValueError("LOCAL_EMBEDDING_COMPLETION_REPLACEMENT_DENIED")
    return checked


def advance_local_embedding_step(
    *,
    workflow: WorkflowInstanceRecord,
    compiled: CompiledWorkflowDefinition,
    request: SupportedLocalEmbeddingRequest,
    lease: CommandLeaseIdentity,
    owner: LocalEmbeddingOwnerAdmission,
    executor: LocalEmbeddingNativeExecutor,
    fenced_transaction: NativeFencedRunnerTransaction,
    poll_interval_seconds: int,
    actor_type: str,
    actor_id: str,
) -> bool:
    """Execute only between closed SQL roots; return False for exact pending owner reads."""
    if not isinstance(
        compiled.definition, LocalEmbeddingWorkflowDefinition | LocalEmbeddingWorkflowDefinitionV2
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID, "native fixed definition differs"
        )
    workflow_id = workflow.workflow_id
    with fenced_transaction() as session:
        current = session.get(WorkflowInstanceRecord, workflow_id)
        if current is None or current.current_step_key != "encode_batch":
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT, "native step is no longer current"
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
                step_key="encode_batch",
            )
        if current.state != WorkflowState.RUNNING.value:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION, "native workflow is not executable"
            )
        scope = validate_local_embedding_runner_admission(
            owner.resolve_submission(session, request),
            compiled,
            actor_type=current.created_actor_type,
            actor_id=current.created_actor_id,
        )
        if scope.request != request:
            raise ValueError("LOCAL_EMBEDDING_EXECUTION_CONTEXT_INVALID")
        step = _native_step(session, workflow_id)
        if step is None:
            step = create_step_run(
                session,
                workflow_id=workflow_id,
                step_key="encode_batch",
                step_type="application",
                worker_role=None,
                result_schema="incremental-embedding-result@1.0",
                input_pointer_manifest={
                    "source_plan": request.source_plan.model_dump(mode="json"),
                    "source_plan_sha256": request.source_plan_sha256,
                },
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
                    output=parse_supported_local_embedding_step_output(
                        step.output_pointer_manifest
                    ),
                )
            except ValueError as exc:
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                    "native step replay receipt could not be validated",
                ) from exc
            current.current_step_key = "complete"
            return True
        if step.state == StepState.READY.value:
            transition_step(step, StepState.RUNNING)
            step.started_at = datetime.now(UTC)
            record_workflow_event(
                session,
                workflow_id,
                "LOCAL_EMBEDDING_STEP_STARTED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=lease.command_id,
                step_key="encode_batch",
            )
        if step.state != StepState.RUNNING.value:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                "native step cannot restart a failed or cancelled attempt",
            )
        step_run_id = step.step_run_id
        session.expunge(current)
        session.expunge(step)
    # The executor may use the callback for SHORT independent owner mutations;
    # no Session, root transaction or source lock survives around computation.
    outcome = executor.execute(
        workflow=current,
        step=step,
        request=request,
        command_lease=lease,
        idempotency_key=f"local-embedding-step:{workflow_id}:encode_batch:1:{compiled.sha256}",
        fenced_transaction=fenced_transaction,
    )
    with fenced_transaction() as session:
        current = session.get(WorkflowInstanceRecord, workflow_id)
        step = session.get(WorkflowStepRunRecord, step_run_id)
        if (
            current is None
            or step is None
            or current.state != WorkflowState.RUNNING.value
            or current.current_step_key != "encode_batch"
            or step.workflow_id != workflow_id
            or step.state != StepState.RUNNING.value
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "native completion lost its original current step",
            )
        _checked_step(step, request)
        if isinstance(outcome, LocalEmbeddingStepPending):
            try:
                pending = LocalEmbeddingStepPending(outcome.readings)
            except ValueError as exc:
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                    "native pending owner reads could not be validated",
                ) from exc
            expected = {
                demand.encoding.encoding_sha256: demand.encoding for demand in scope.plan.demands
            }
            actual = {row.owned_job.request.encoding.encoding_sha256 for row in pending.readings}
            if actual != set(expected) or any(
                row.owned_job.request.space != scope.plan.space
                or row.owned_job.request.encoding
                != expected[row.owned_job.request.encoding.encoding_sha256]
                or (
                    row.status == "OWNED"
                    and (
                        row.owner_intent.workflow_id != workflow_id
                        or row.owner_intent.step_run_id != step_run_id
                        or row.owner_intent.workflow_request_sha256 != request.request_sha256
                        or row.owner_intent.source_plan != request.source_plan
                    )
                )
                for row in pending.readings
            ):
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                    "native pending keys, space or owned intent differ from the original plan",
                )
            enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.ADVANCE_WORKFLOW,
                payload={"step_run_id": step_run_id},
                actor_type=actor_type,
                actor_id=actor_id,
                source="local-embedding-owner",
                idempotency_key=f"local-embedding-pending:{step_run_id}:{lease.command_id}",
                available_at=datetime.now(UTC)
                + timedelta(seconds=min(60, max(1, poll_interval_seconds))),
            )
            return False
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
                "native completion receipt could not be validated",
            ) from exc
        step.platform_job_id = output.receipt_owner_job_id
        step.output_pointer_manifest = output.model_dump(mode="json")
        step.finished_at = datetime.now(UTC)
        transition_step(step, StepState.SUCCEEDED)
        current.current_step_key = "complete"
        record_workflow_event(
            session,
            workflow_id,
            "LOCAL_EMBEDDING_STEP_SUCCEEDED",
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=lease.command_id,
            step_key="encode_batch",
        )
    return True


def complete_local_embedding_terminal(
    *,
    workflow_id: str,
    request: SupportedLocalEmbeddingRequest,
    lease: CommandLeaseIdentity,
    executor: LocalEmbeddingNativeExecutor,
    fenced_transaction: NativeFencedRunnerTransaction,
    actor_type: str,
    actor_id: str,
) -> None:
    def validate(
        session: Session, workflow: WorkflowInstanceRecord, step: WorkflowStepRunRecord
    ) -> SupportedLocalEmbeddingStepOutput:
        _checked_step(step, request)
        return _checked_completion(
            session,
            executor=executor,
            workflow=workflow,
            step=step,
            request=request,
            lease=lease,
            output=parse_supported_local_embedding_step_output(step.output_pointer_manifest),
        )

    complete_native_terminal(
        workflow_id=workflow_id,
        step_key="encode_batch",
        lease=lease,
        validate_completion=validate,
        fenced_transaction=fenced_transaction,
        actor_type=actor_type,
        actor_id=actor_id,
    )
