"""Fixed native two-step Runner use case; actual computation/publication stays with its owner."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from eom_orchestrator.database import transaction
from eom_workflow.compiler import CompiledWorkflowDefinition
from eom_workflow.local_embedding_request import LocalEmbeddingWorkflowRequestV11
from eom_workflow.local_embedding_workflow import LocalEmbeddingWorkflowDefinition
from eom_workflow.local_embedding_workflow_receipt import (
    LocalEmbeddingStepOutput,
    parse_local_embedding_step_output,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

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
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandLeaseIdentity,
    CommandType,
    create_step_run,
    enqueue_command,
    load_persisted_local_embedding_workflow_request,
    require_command_lease,
)
from eom_workflow_runner.state_machine import (
    CommandState,
    StepState,
    WorkflowStage,
    WorkflowState,
    record_workflow_event,
    transition_stage,
    transition_step,
    transition_workflow,
)


@contextmanager
def native_fenced_runner_transaction(
    factory: sessionmaker[Session],
    *,
    owner: LocalEmbeddingOwnerAdmission,
    workflow_id: str,
    request: LocalEmbeddingWorkflowRequestV11,
    lease: CommandLeaseIdentity,
) -> Iterator[Session]:
    """Fresh root authority and Workflow→command lock order, never an inference scope."""
    with transaction(factory) as session:
        workflow = session.scalar(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == workflow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if workflow is None:
            raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "native workflow disappeared")
        command = require_command_lease(session, lease, for_update=True)
        initial_command_state = command.state
        if (
            command.workflow_id != workflow_id
            or workflow.definition_key != request.workflow_definition_key
            or workflow.definition_version != request.workflow_definition_version
            or workflow.definition_hash != request.workflow_definition_sha256
            or workflow.role_schema_version != "local-embedding/1.0"
            or workflow.protocol_version != "1.0.1"
            or load_persisted_local_embedding_workflow_request(workflow.initial_request) != request
            or workflow.request_payload != workflow.initial_request
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "native mutation request or command differs",
            )
        owner.fence_mutation(session, request, lease)
        yield session
        session.flush()
        final_command_state = command.state
        owner.fence_mutation(session, request, lease)
        # Authority checks can themselves consume time: expiry is checked LAST.
        if final_command_state in {CommandState.SUCCEEDED.value, CommandState.FAILED.value}:
            # Only this root's PROCESSING→terminal transition is allowed. Keep
            # the acquired row lock, actual owner and unexpired exact identity.
            current = session.scalar(
                select(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.command_id == lease.command_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                initial_command_state != CommandState.PROCESSING.value
                or current is None
                or current.state != final_command_state
                or current.lease_owner != lease.runner_id
                or current.lease_token != lease.lease_token
                or current.lease_generation != lease.lease_generation
                or current.lease_expires_at is None
                or current.lease_expires_at <= datetime.now(UTC)
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                    "native terminal command lost its acquired lease",
                )
        else:
            require_command_lease(session, lease, for_update=True)


def _native_step(session: Session, workflow_id: str) -> WorkflowStepRunRecord | None:
    return session.scalar(
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id == workflow_id,
            WorkflowStepRunRecord.step_key == "encode_batch",
        )
        .order_by(WorkflowStepRunRecord.attempt.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


def _checked_step(step: WorkflowStepRunRecord, request: LocalEmbeddingWorkflowRequestV11) -> None:
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
    request: LocalEmbeddingWorkflowRequestV11,
    lease: CommandLeaseIdentity,
    output: LocalEmbeddingStepOutput,
) -> LocalEmbeddingStepOutput:
    output = parse_local_embedding_step_output(output)
    if (
        output.workflow_id != workflow.workflow_id
        or output.step_run_id != step.step_run_id
        or output.attempt != step.attempt
        or (
            step.platform_job_id is not None and step.platform_job_id != output.receipt_owner_job_id
        )
    ):
        raise ValueError("LOCAL_EMBEDDING_COMPLETION_IDENTITY_INVALID")
    checked = parse_local_embedding_step_output(
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
    request: LocalEmbeddingWorkflowRequestV11,
    lease: CommandLeaseIdentity,
    owner: LocalEmbeddingOwnerAdmission,
    executor: LocalEmbeddingNativeExecutor,
    fenced_transaction: NativeFencedRunnerTransaction,
    poll_interval_seconds: int,
    actor_type: str,
    actor_id: str,
) -> bool:
    """Execute only between closed SQL roots; return False for exact pending owner reads."""
    if not isinstance(compiled.definition, LocalEmbeddingWorkflowDefinition):
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
                    output=parse_local_embedding_step_output(step.output_pointer_manifest),
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
        if not isinstance(outcome, LocalEmbeddingStepOutput):
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                "native executor returned an unsupported outcome",
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
    request: LocalEmbeddingWorkflowRequestV11,
    lease: CommandLeaseIdentity,
    executor: LocalEmbeddingNativeExecutor,
    fenced_transaction: NativeFencedRunnerTransaction,
    actor_type: str,
    actor_id: str,
) -> None:
    with fenced_transaction() as session:
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        step = _native_step(session, workflow_id)
        if (
            workflow is None
            or workflow.current_step_key != "complete"
            or workflow.state not in {WorkflowState.RUNNING.value, WorkflowState.COMPLETED.value}
            or step is None
            or step.state != StepState.SUCCEEDED.value
        ):
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                "native terminal has no exact successful receipt",
            )
        _checked_step(step, request)
        try:
            output = _checked_completion(
                session,
                executor=executor,
                workflow=workflow,
                step=step,
                request=request,
                lease=lease,
                output=parse_local_embedding_step_output(step.output_pointer_manifest),
            )
        except ValueError as exc:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                "native terminal receipt could not be validated",
            ) from exc
        expected = {"embedding_receipt": output.model_dump(mode="json")}
        terminal = session.scalar(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == workflow_id,
                WorkflowStepRunRecord.step_key == "complete",
            )
            .order_by(WorkflowStepRunRecord.attempt.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        if workflow.state == WorkflowState.COMPLETED.value:
            if (
                workflow.runtime_context.get("final_pointer_manifest") != expected
                or terminal is None
            ):
                raise WorkflowError(
                    WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                    "native terminal replay pointer differs",
                )
        elif terminal is None:
            terminal = create_step_run(
                session,
                workflow_id=workflow_id,
                step_key="complete",
                step_type="terminal",
                worker_role=None,
                result_schema=None,
                input_pointer_manifest={},
                max_attempts=1,
            )
            terminal.started_at = datetime.now(UTC)
            transition_step(terminal, StepState.RUNNING)
            transition_step(terminal, StepState.SUCCEEDED)
            terminal.finished_at = datetime.now(UTC)
        if (
            terminal is None
            or terminal.attempt != 1
            or terminal.step_type != "terminal"
            or terminal.worker_role is not None
            or terminal.result_schema is not None
            or terminal.input_pointer_manifest != {}
            or terminal.output_pointer_manifest is not None
            or terminal.platform_job_id is not None
            or terminal.state != StepState.SUCCEEDED.value
        ):
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                "native terminal step history differs",
            )
        if workflow.state == WorkflowState.COMPLETED.value:
            return
        workflow.runtime_context = workflow.runtime_context | {"final_pointer_manifest": expected}
        transition_stage(
            session,
            workflow_id,
            WorkflowStage.COMPLETED,
            "complete",
            "LOCAL_EMBEDDING_COMPLETION_STAGE_ENTERED",
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=lease.command_id,
        )
        transition_workflow(
            session,
            workflow_id,
            WorkflowState.COMPLETED,
            "WORKFLOW_COMPLETED",
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=lease.command_id,
            step_key="complete",
        )
