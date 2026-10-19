"""Common native terminal persistence, preserving immutable private source context."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_workflow.local_embedding_workflow_receipt_v2 import SupportedLocalEmbeddingStepOutput
from eom_workflow.private_chat_query_execution import parse_private_chat_query_workflow_request
from eom_workflow.private_chat_query_submission_context import (
    parse_private_chat_query_submission_context,
    validate_private_chat_query_submission_context,
)
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from eom_workflow.reference_query_execution import ReferenceQueryStepOutput
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import CommandLeaseIdentity, create_step_run
from eom_workflow_runner.state_machine import (
    StepState,
    WorkflowStage,
    WorkflowState,
    transition_stage,
    transition_step,
    transition_workflow,
)

type NativeStepKey = Literal["encode_batch", "encode_reference_query", "encode_private_chat_query"]
type NativeStepOutput = (
    SupportedLocalEmbeddingStepOutput | ReferenceQueryStepOutput | PrivateChatQueryStepOutput
)
type ValidateNativeCompletion = Callable[
    [Session, WorkflowInstanceRecord, WorkflowStepRunRecord], NativeStepOutput
]

_TERMINAL_KEYS = MappingProxyType(
    {
        "encode_batch": ("embedding_receipt", "LOCAL_EMBEDDING_COMPLETION_STAGE_ENTERED"),
        "encode_reference_query": (
            "reference_query_receipt",
            "REFERENCE_QUERY_COMPLETION_STAGE_ENTERED",
        ),
        "encode_private_chat_query": (None, "PRIVATE_CHAT_QUERY_COMPLETION_STAGE_ENTERED"),
    }
)


def native_application_step(
    session: Session,
    workflow_id: str,
    step_key: NativeStepKey,
) -> WorkflowStepRunRecord | None:
    return session.scalar(
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id == workflow_id,
            WorkflowStepRunRecord.step_key == step_key,
        )
        .order_by(WorkflowStepRunRecord.attempt.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


def _require_terminal_shape(terminal: WorkflowStepRunRecord | None) -> None:
    if terminal is None or (
        terminal.attempt != 1
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


def _require_private_terminal_context(
    workflow: WorkflowInstanceRecord, output: NativeStepOutput
) -> None:
    """Original metadata closure only; the callback owns current permission/receipt checks."""
    try:
        if not isinstance(output, PrivateChatQueryStepOutput):
            raise ValueError()
        PrivateChatQueryStepOutput.model_validate(raw_similarity_contract_value(output))
        request = parse_private_chat_query_workflow_request(workflow.initial_request)
        context = validate_private_chat_query_submission_context(
            request, parse_private_chat_query_submission_context(workflow.runtime_context)
        )
        if (
            workflow.created_actor_type != "human"
            or workflow.created_actor_id != context.origin.actor_id
            or workflow.definition_key != request.workflow_definition_key
            or workflow.definition_version != request.workflow_definition_version
            or workflow.definition_hash != request.workflow_definition_sha256
        ):
            raise ValueError()
    except (ValueError, TypeError, SchemaError):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
            "private native terminal original context differs",
        ) from None


def validate_completed_native_workflow(
    session: Session,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    output: NativeStepOutput,
) -> None:
    """Read-only terminal closure; actual current source/IAM remains the owner's duty."""
    manifest_key, _event = _TERMINAL_KEYS[output.step_key]
    if (
        workflow.state != WorkflowState.COMPLETED.value
        or workflow.stage != WorkflowStage.COMPLETED.value
        or workflow.current_step_key != "complete"
        or output.workflow_id != workflow.workflow_id
        or step.workflow_id != workflow.workflow_id
        or step.step_key != output.step_key
        or step.step_run_id != output.step_run_id
        or step.state != StepState.SUCCEEDED.value
        or step.attempt != output.attempt
        or step.platform_job_id != output.receipt_owner_job_id
        or step.output_pointer_manifest != output.model_dump(mode="json")
        or (
            manifest_key is not None
            and workflow.runtime_context.get("final_pointer_manifest")
            != {manifest_key: output.model_dump(mode="json")}
        )
    ):
        raise WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
            "native terminal replay pointer differs",
        )
    if manifest_key is None:
        _require_private_terminal_context(workflow, output)
    terminal = session.scalar(
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
            WorkflowStepRunRecord.step_key == "complete",
        )
        .order_by(WorkflowStepRunRecord.attempt.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    _require_terminal_shape(terminal)


def complete_native_terminal(
    *,
    workflow_id: str,
    step_key: NativeStepKey,
    lease: CommandLeaseIdentity,
    validate_completion: ValidateNativeCompletion,
    fenced_transaction: NativeFencedRunnerTransaction,
    actor_type: str,
    actor_id: str,
) -> None:
    """Only the purpose owner may supply a freshly canonical-validated output.

    This function owns common terminal transitions, not source/native admission.
    The callback is mandatory and is called again for every completed replay.
    """
    manifest_key, event = _TERMINAL_KEYS[step_key]
    with fenced_transaction() as session:
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        step = native_application_step(session, workflow_id, step_key)
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
        try:
            output = validate_completion(session, workflow, step)
        except ValueError as exc:
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                "native terminal receipt could not be validated",
            ) from exc
        if (
            output.workflow_id != workflow_id
            or output.step_run_id != step.step_run_id
            or output.step_key != step_key
            or output.attempt != step.attempt
            or output.receipt_owner_job_id != step.platform_job_id
        ):
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
                "native terminal receipt has a different step/producer identity",
            )
        if manifest_key is None:
            _require_private_terminal_context(workflow, output)
        if workflow.state == WorkflowState.COMPLETED.value:
            validate_completed_native_workflow(session, workflow, step, output)
            return
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
        if terminal is None:
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
        _require_terminal_shape(terminal)
        if manifest_key is not None:
            workflow.runtime_context = workflow.runtime_context | {
                "final_pointer_manifest": {manifest_key: output.model_dump(mode="json")}
            }
        transition_stage(
            session,
            workflow_id,
            WorkflowStage.COMPLETED,
            "complete",
            event,
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
