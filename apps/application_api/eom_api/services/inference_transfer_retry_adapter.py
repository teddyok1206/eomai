"""One parent-locked successor through the existing atomic comparison START boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator.control_models import WorkerLeaseRecord
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.inference_transfer_resolution import (
    resolve_inference_transfer_retry_execution_plan_v11,
)
from eom_orchestrator.models import ArtifactRecord, JobRecord
from eom_workflow.inference_transfer_control import (
    ResolvedExecutionPlanV21,
    ResolvedExecutionPlanV22,
)
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequestV11
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import load_persisted_inference_transfer_workflow_request
from eom_workflow_runner.state_machine import record_workflow_event
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from eom_api.errors import ApiError
from eom_api.services.inference_transfer_retry import AuthorizedInferenceTransferRetry
from eom_api.services.inference_transfer_start_adapter import (
    inference_transfer_start_identity,
    start_inference_transfer_in_session,
    validate_inference_transfer_start_replay,
)

RETRY_EVENT = "INFERENCE_TRANSFER_RETRY_CREATED"
RETRY_CONTEXT = "inference_transfer_retry"
_FAILED_JOB_CODES = frozenset({"WORKER_RESULT_INVALID", "WORKER_EXEC_FAILED"})
_ACTIVE_COMMANDS = ("PENDING", "LEASED", "PROCESSING")
_HELD_LEASES = ("ACTIVE", "RECONCILING")
_PLAN_EXECUTION_FIELDS = {
    "plan_id",
    "workflow_id",
    "resolved_at",
    "plan_sha256",
    "requester_permissions_sha256",
}


def _conflict(detail: str) -> ApiError:
    return ApiError(409, "INFERENCE_TRANSFER_RETRY_CONFLICT", "Comparison retry conflict", detail)


def _ineligible(detail: str) -> ApiError:
    return ApiError(
        409, "INFERENCE_TRANSFER_RETRY_INELIGIBLE", "Comparison cannot be retried", detail
    )


class InferenceTransferRetryAdapter:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def retry(
        self,
        authorized: AuthorizedInferenceTransferRetry,
        actor: ActorContext,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[str, str, int]:
        submission = authorized.submission
        if (
            actor.actor_id != submission.operator_id
            or authorized.request.selection != submission.selection
        ):
            raise ApiError(
                403, "PERMISSION_DENIED", "Permission denied", "Actual retry principal differs."
            )
        with transaction(self.sessions) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "inference-transfer-start:" + idempotency_key},
            )
            parent = session.scalar(
                select(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.workflow_id == authorized.parent_workflow_id)
                .with_for_update()
            )
            if parent is None:
                raise ApiError(
                    404,
                    "INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND",
                    "Comparison missing",
                    "Original Workflow is missing.",
                )
            parent_plan = validate_inference_transfer_start_replay(session, parent, submission)
            if not isinstance(parent_plan, ResolvedExecutionPlanV22):
                raise _ineligible("Only the exact three-axis comparison can be retried.")
            if RETRY_CONTEXT in parent.runtime_context:
                raise _ineligible("A retry successor cannot itself be retried.")
            step, job = _failed_comparison(session, parent, authorized)
            lineage = {
                "parent_workflow_id": parent.workflow_id,
                "failed_step_run_id": step.step_run_id,
                "failed_attempt": step.attempt,
                "failed_job_id": job.job_id,
                "parent_plan_id": parent_plan.plan_id,
                "parent_plan_sha256": parent_plan.plan_sha256,
                "selection_sha256": submission.selection.submission_sha256,
                "retry_sha256": authorized.request.retry_sha256,
                "operation_key_sha256": content_sha256(idempotency_key),
            }
            events = tuple(
                session.scalars(
                    select(WorkflowEventRecord)
                    .where(
                        WorkflowEventRecord.workflow_id == parent.workflow_id,
                        WorkflowEventRecord.event_type == RETRY_EVENT,
                    )
                    .order_by(WorkflowEventRecord.sequence)
                    .limit(2)
                )
            )
            if events:
                if len(events) != 1:
                    raise _conflict("Original comparison has ambiguous retry lineage.")
                event = events[0]
                payload = event.payload
                if any(payload.get(key) != value for key, value in lineage.items()):
                    raise _conflict("Original comparison already has another explicit successor.")
                child_id = payload.get("child_workflow_id")
                if not isinstance(child_id, str):
                    raise _conflict("Existing retry successor identity is missing.")
                child = session.get(WorkflowInstanceRecord, child_id)
                if child is None or child.idempotency_key != idempotency_key:
                    raise _conflict(
                        "Existing retry successor is missing or has a different operation key."
                    )
                child_plan = validate_inference_transfer_start_replay(session, child, submission)
                _validate_child(parent_plan, child, child_plan, lineage)
                if (
                    payload.get("child_plan_id") != child_plan.plan_id
                    or payload.get("child_plan_sha256") != child_plan.plan_sha256
                ):
                    raise _conflict("Existing retry event and child execution plan differ.")
                return inference_transfer_start_identity(session, child)
            if parent.lock_version != expected_version:
                raise ApiError(
                    412,
                    "API_PRECONDITION_FAILED",
                    "Precondition failed",
                    "The original comparison changed since it was observed.",
                )
            definition = session.get(WorkflowDefinitionRecord, parent.definition_id)
            if definition is None or not definition.active:
                raise _ineligible("The original comparison definition is no longer admitted.")
            original = load_persisted_inference_transfer_workflow_request(parent.initial_request)
            wrapper = submission.workflow_request
            if not isinstance(original, InferenceTransferWorkflowRequestV11) or not isinstance(
                wrapper, InferenceTransferWorkflowRequestV11
            ):
                raise _ineligible("Retry requires the original typed three-axis inputs.")

            def resolve_plan(
                actual: Session,
                workflow: WorkflowInstanceRecord,
                core_prompt_sha256: str,
                prompt_sha256: str,
            ) -> ResolvedExecutionPlanV21:
                return resolve_inference_transfer_retry_execution_plan_v11(
                    actual,
                    parent_plan_id=parent_plan.plan_id,
                    parent_workflow_id=parent.workflow_id,
                    parent_workflow_request=original,
                    workflow_id=workflow.workflow_id,
                    workflow_definition_sha256=parent.definition_hash,
                    workflow_request=wrapper,
                    core_prompt_sha256=core_prompt_sha256,
                    prompt_sha256=prompt_sha256,
                    resolved_at=datetime.now(UTC),
                )

            identity = start_inference_transfer_in_session(
                session,
                definition=definition,
                submission=submission,
                actor=actor,
                idempotency_key=idempotency_key,
                resolve_plan=resolve_plan,
                runtime_context={RETRY_CONTEXT: lineage},
            )
            child = session.get(WorkflowInstanceRecord, identity[1])
            if child is None or child.idempotency_key != idempotency_key:
                raise _conflict("Retry cannot adopt another comparison execution.")
            child_plan = validate_inference_transfer_start_replay(session, child, submission)
            _validate_child(parent_plan, child, child_plan, lineage)
            record_workflow_event(
                session,
                parent.workflow_id,
                RETRY_EVENT,
                actor_type="human",
                actor_id=actor.actor_id,
                command_id=None,
                step_key="compare_pair",
                payload=lineage
                | {
                    "child_workflow_id": child.workflow_id,
                    "child_start_command_id": identity[0],
                    "child_plan_id": child_plan.plan_id,
                    "child_plan_sha256": child_plan.plan_sha256,
                    "observed_parent_resource_version": expected_version,
                    "reason": authorized.request.reason,
                },
            )
            return identity


def _failed_comparison(
    session: Session,
    parent: WorkflowInstanceRecord,
    authorized: AuthorizedInferenceTransferRetry,
) -> tuple[WorkflowStepRunRecord, JobRecord]:
    if (
        parent.state != "FAILED"
        or parent.stage != "FAILED"
        or parent.current_step_key != "compare_pair"
    ):
        raise _ineligible("Original comparison is not positioned at its failed comparison step.")
    step = session.scalar(
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id == parent.workflow_id,
            WorkflowStepRunRecord.step_key == "compare_pair",
        )
        .order_by(WorkflowStepRunRecord.attempt.desc(), WorkflowStepRunRecord.step_run_id.desc())
        .limit(1)
        .with_for_update()
    )
    if (
        step is None
        or step.step_run_id != authorized.request.failed_step_run_id
        or step.attempt != authorized.request.failed_attempt
        or step.attempt != 1
        or step.state != "FAILED"
        or step.step_type != "agent"
        or step.worker_role != "support"
        or step.result_schema != "item-inference-transfer-pair-result@1.1"
        or step.platform_job_id is None
        or step.output_pointer_manifest is not None
        or step.superseded_by_step_run_id is not None
    ):
        raise _ineligible("The exact original failed attempt is unavailable or already has output.")
    job = session.get(JobRecord, step.platform_job_id, with_for_update=True)
    if (
        job is None
        or job.status != "FAILED"
        or job.error_code not in _FAILED_JOB_CODES
        or job.request.get("workflow_id") != parent.workflow_id
        or job.request.get("step_run_id") != step.step_run_id
        or job.request.get("attempt") != step.attempt
        or job.request.get("role") != "support"
    ):
        raise _ineligible(
            "The original worker failure is not a retryable comparison result failure."
        )
    if (
        session.scalar(
            select(ArtifactRecord.logical_artifact_id)
            .where(ArtifactRecord.job_id == job.job_id)
            .limit(1)
        )
        is not None
    ):
        raise _ineligible("The original failed job already has a committed Artifact.")
    if (
        session.scalar(
            select(WorkflowCommandRecord.command_id)
            .where(
                WorkflowCommandRecord.workflow_id == parent.workflow_id,
                WorkflowCommandRecord.state.in_(_ACTIVE_COMMANDS),
            )
            .limit(1)
        )
        is not None
    ):
        raise _ineligible("The original comparison still has an active command.")
    if (
        session.scalar(
            select(WorkerLeaseRecord.lease_id)
            .where(
                WorkerLeaseRecord.workflow_id == parent.workflow_id,
                WorkerLeaseRecord.state.in_(_HELD_LEASES),
            )
            .limit(1)
        )
        is not None
    ):
        raise _ineligible("The original comparison still holds a worker lease.")
    return step, job


def _validate_child(
    parent_plan: ResolvedExecutionPlanV22,
    child: WorkflowInstanceRecord,
    child_plan: ResolvedExecutionPlanV21,
    lineage: dict[str, Any],
) -> None:
    if (
        child.runtime_context.get(RETRY_CONTEXT) != lineage
        or not isinstance(child_plan, ResolvedExecutionPlanV22)
        or child_plan.model_dump(mode="json", exclude=_PLAN_EXECUTION_FIELDS)
        != parent_plan.model_dump(mode="json", exclude=_PLAN_EXECUTION_FIELDS)
    ):
        raise _conflict("Retry successor changed the original lineage or immutable controls.")
