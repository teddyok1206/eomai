"""Private-purpose Runner state progression over existing commands/steps/terminal owner.

Not an admission grant: the installed composition must supply the actual fenced
owner/executor and separately admit the fixed definition and private SQL step.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_query_job_allocation import read_native_query_launch
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    NativePrivateQueryCompleted,
    NativePrivateQueryCompletedV2,
)
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryWorkflowRequestV2,
    SupportedPrivateChatQueryWorkflowRequest,
    parse_supported_private_chat_query_workflow_request,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_submission_context import (
    PrivateChatQuerySubmissionContext,
    parse_private_chat_query_submission_context,
    validate_private_chat_query_submission_context,
)
from eom_workflow.private_chat_query_workflow_v2 import (
    PrivateChatQueryStepOutputV2,
    SupportedPrivateChatQueryStepOutput,
    SupportedPrivateChatQueryWorkflowDefinition,
    parse_supported_private_chat_query_step_output,
    private_chat_query_result_schema,
    validate_supported_private_chat_query_definition,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.native_step_completion import (
    complete_native_terminal,
    native_application_step,
)
from eom_workflow_runner.private_chat_query_admission import PrivateChatQueryOwnerAdmission
from eom_workflow_runner.private_chat_query_command_lineage import (
    PRIVATE_CHAT_QUERY_CONTINUATION_SOURCE,
    private_chat_query_continuation_key,
)
from eom_workflow_runner.private_chat_query_execution_port import (
    PrivateChatQueryNativeExecutor,
    PrivateChatQueryStepPending,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    validate_private_chat_query_execution_step,
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


def _output(
    value: object, request: SupportedPrivateChatQueryWorkflowRequest
) -> SupportedPrivateChatQueryStepOutput:
    try:
        output = parse_supported_private_chat_query_step_output(
            raw_similarity_contract_value(value)
        )
        if isinstance(request, PrivateChatQueryWorkflowRequestV2) != isinstance(
            output, PrivateChatQueryStepOutputV2
        ):
            raise ValueError()
        return output
    except (ValueError, TypeError, SchemaError):
        raise ValueError("PRIVATE_CHAT_QUERY_STEP_OUTPUT_INVALID") from None


def _completion(
    session: Session,
    *,
    executor: PrivateChatQueryNativeExecutor,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: SupportedPrivateChatQueryWorkflowRequest,
    lease: CommandLeaseIdentity,
    output: object,
) -> SupportedPrivateChatQueryStepOutput:
    validate_private_chat_query_execution_step(step, workflow, request)
    result = _output(output, request)
    if (
        result.workflow_id != workflow.workflow_id
        or result.step_run_id != step.step_run_id
        or result.attempt != step.attempt
        or (
            step.platform_job_id is not None and step.platform_job_id != result.receipt_owner_job_id
        )
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_IDENTITY_INVALID")
    checked: SupportedPrivateChatQueryStepOutput
    if isinstance(request, PrivateChatQueryWorkflowRequestV2):
        if not isinstance(result, PrivateChatQueryStepOutputV2):
            raise ValueError("PRIVATE_CHAT_QUERY_STEP_OUTPUT_INVALID")
        checked = executor.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=request,
            command_lease=lease,
            output=result,
        )
    else:
        if isinstance(result, PrivateChatQueryStepOutputV2):
            raise ValueError("PRIVATE_CHAT_QUERY_STEP_OUTPUT_INVALID")
        checked = executor.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=request,
            command_lease=lease,
            output=result,
        )
    checked = _output(checked, request)
    if checked != result:
        raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_REPLACEMENT_DENIED")
    return checked


def _pending(
    session: Session,
    request: SupportedPrivateChatQueryWorkflowRequest,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    outcome: PrivateChatQueryStepPending,
    context: PrivateChatQuerySubmissionContext,
) -> SupportedPrivateChatQueryStepOutput | None:
    pending = PrivateChatQueryStepPending(
        outcome.native_launch_job_id, outcome.association_sha256, outcome.reason
    )
    launch = read_native_query_launch(
        session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
    )
    if not isinstance(launch, PrivateChatQueryLaunchAssociation) or (
        launch.native_launch_job_id != pending.native_launch_job_id
        or launch.association_sha256 != pending.association_sha256
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_PENDING_ORIGINAL_INVALID")
    history = NativePrivateChatQueryCoordinator(request, launch).read(session)
    if (
        not history.records
        or history.state in {"FAILED", "CANCELLED"}
        or not isinstance(history.records[0].payload, NativePrivateQueryAllocation)
        or history.records[0].payload.origin != context.origin
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_PENDING_HISTORY_INVALID")
    if len(history.records) == 4:
        completed = history.records[3].payload
        if not isinstance(completed, (NativePrivateQueryCompleted, NativePrivateQueryCompletedV2)):
            raise ValueError("PRIVATE_CHAT_QUERY_PENDING_HISTORY_INVALID")
        return _output(completed.output, request)
    return None


def advance_private_chat_query_step(
    *,
    workflow: WorkflowInstanceRecord,
    definition: SupportedPrivateChatQueryWorkflowDefinition,
    request: SupportedPrivateChatQueryWorkflowRequest,
    lease: CommandLeaseIdentity,
    owner: PrivateChatQueryOwnerAdmission,
    executor: PrivateChatQueryNativeExecutor,
    fenced_transaction: NativeFencedRunnerTransaction,
    actor_type: str,
    actor_id: str,
    poll_interval_seconds: int = 30,
) -> bool:
    request = parse_supported_private_chat_query_workflow_request(request)
    validate_supported_private_chat_query_definition(definition, request)
    workflow_id = workflow.workflow_id
    with fenced_transaction() as session:
        current = session.get(WorkflowInstanceRecord, workflow_id)
        if (
            current is None
            or current.current_step_key != "encode_private_chat_query"
            or current.state not in {WorkflowState.REQUESTED.value, WorkflowState.RUNNING.value}
            or actor_type != "human"
            or current.created_actor_type != actor_type
            or current.created_actor_id != actor_id
        ):
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                "private QUERY current step/actor differs",
            )
        context = validate_private_chat_query_submission_context(
            request, parse_private_chat_query_submission_context(current.runtime_context)
        )
        # Current-source reads precede any state write; the private source owner
        # deliberately refuses caller writes rather than autoflushing them.
        scope = owner.resolve_submission(session, request, context)
        scope.__post_init__()
        if scope.request != request or scope.projection.origin != context.origin:
            raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_CONTEXT_INVALID")
        step = native_application_step(session, workflow_id, "encode_private_chat_query")
        if current.state == WorkflowState.REQUESTED.value:
            if step is not None:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "private QUERY original start has an existing step",
                )
            transition_workflow(
                session,
                workflow_id,
                WorkflowState.RUNNING,
                "WORKFLOW_STARTED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=lease.command_id,
                step_key="encode_private_chat_query",
            )
        if step is None:
            step = create_step_run(
                session,
                workflow_id=workflow_id,
                step_key="encode_private_chat_query",
                step_type="application",
                worker_role=None,
                result_schema=private_chat_query_result_schema(request),
                input_pointer_manifest={"workflow_request_sha256": request.request_sha256},
                max_attempts=1,
            )
        if step.state == StepState.SUCCEEDED.value:
            _completion(
                session,
                executor=executor,
                workflow=current,
                step=step,
                request=request,
                lease=lease,
                output=step.output_pointer_manifest,
            )
            current.current_step_key = "complete"
            return True
        if step.state == StepState.READY.value:
            transition_step(step, StepState.RUNNING)
            step.started_at = datetime.now(UTC)
            record_workflow_event(
                session,
                workflow_id,
                "PRIVATE_CHAT_QUERY_STEP_STARTED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=lease.command_id,
                step_key="encode_private_chat_query",
            )
        validate_private_chat_query_execution_step(step, current, request)
        # Initial RUNNING state and original allocation share one commit. No SQL
        # root survives either physical computation or unit observation.
        session.flush()
        executor.allocate_execution(
            session=session, workflow=current, step=step, request=request, command_lease=lease
        )
        step_run_id = step.step_run_id
        session.expunge(current)
        session.expunge(step)
    try:
        outcome = executor.execute(
            workflow=current,
            step=step,
            request=request,
            command_lease=lease,
            idempotency_key=f"private-chat-query-step:{workflow_id}:encode_private_chat_query:1:{request.workflow_definition_sha256}",
            fenced_transaction=fenced_transaction,
        )
        with fenced_transaction() as session:
            current = session.get(WorkflowInstanceRecord, workflow_id)
            step = session.get(WorkflowStepRunRecord, step_run_id)
            if (
                current is None
                or step is None
                or current.workflow_id != workflow_id
                or current.state != WorkflowState.RUNNING.value
                or current.current_step_key != "encode_private_chat_query"
                or step.step_run_id != step_run_id
                or step.state != StepState.RUNNING.value
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                    "private QUERY completion lost original step",
                )
            validate_private_chat_query_execution_step(step, current, request)
            current_context = validate_private_chat_query_submission_context(
                request, parse_private_chat_query_submission_context(current.runtime_context)
            )
            if current_context != context:
                raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_CONTEXT_INVALID")
            if isinstance(outcome, PrivateChatQueryStepPending):
                completed = _pending(session, request, current, step, outcome, current_context)
                if completed is None:
                    enqueue_command(
                        session,
                        workflow_id=workflow_id,
                        command_type=CommandType.ADVANCE_WORKFLOW,
                        payload={"step_run_id": step_run_id},
                        actor_type=actor_type,
                        actor_id=actor_id,
                        source=PRIVATE_CHAT_QUERY_CONTINUATION_SOURCE,
                        idempotency_key=private_chat_query_continuation_key(
                            step_run_id, lease.command_id
                        ),
                        available_at=datetime.now(UTC)
                        + timedelta(seconds=min(60, max(5, poll_interval_seconds))),
                    )
                    return False
                outcome = completed
            output = _completion(
                session,
                executor=executor,
                workflow=current,
                step=step,
                request=request,
                lease=lease,
                output=outcome,
            )
            step.platform_job_id = output.receipt_owner_job_id
            step.output_pointer_manifest = output.model_dump(mode="json")
            step.finished_at = datetime.now(UTC)
            transition_step(step, StepState.SUCCEEDED)
            current.current_step_key = "complete"
            record_workflow_event(
                session,
                workflow_id,
                "PRIVATE_CHAT_QUERY_STEP_SUCCEEDED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=lease.command_id,
                step_key="encode_private_chat_query",
            )
            return True
    except (ValueError, TypeError, SchemaError):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
            "private QUERY execution/completion could not be validated",
        ) from None


def complete_private_chat_query_terminal(
    *,
    workflow_id: str,
    request: SupportedPrivateChatQueryWorkflowRequest,
    lease: CommandLeaseIdentity,
    executor: PrivateChatQueryNativeExecutor,
    fenced_transaction: NativeFencedRunnerTransaction,
    actor_type: str,
    actor_id: str,
) -> None:
    request = parse_supported_private_chat_query_workflow_request(request)

    def validate(
        session: Session, workflow: WorkflowInstanceRecord, step: WorkflowStepRunRecord
    ) -> SupportedPrivateChatQueryStepOutput:
        if actor_type != workflow.created_actor_type or actor_id != workflow.created_actor_id:
            raise ValueError("PRIVATE_CHAT_QUERY_TERMINAL_ACTOR_INVALID")
        return _completion(
            session,
            executor=executor,
            workflow=workflow,
            step=step,
            request=request,
            lease=lease,
            output=step.output_pointer_manifest,
        )

    complete_native_terminal(
        workflow_id=workflow_id,
        step_key="encode_private_chat_query",
        lease=lease,
        validate_completion=validate,
        fenced_transaction=fenced_transaction,
        actor_type=actor_type,
        actor_id=actor_id,
    )
