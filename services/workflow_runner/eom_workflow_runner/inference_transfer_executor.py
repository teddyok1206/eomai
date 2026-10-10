"""Purpose leaf: actual stored context → authorized prompt → existing platform job."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

from eom_catalog_service.inference_transfer_service import InferenceTransferSearchCommand
from eom_catalog_service.inference_transfer_worker_preparation import (
    prepare_inference_transfer_worker_comparison,
)
from eom_operator_identity import PermissionKey
from eom_orchestrator.inference_transfer_resolution import resolve_inference_transfer_execution_plan
from eom_orchestrator.orchestrator import Orchestrator
from eom_workflow import AgentStep, compile_definition_data
from eom_workflow.inference_transfer import (
    TRANSFER_PAIR_PROTOCOL,
    TRANSFER_PAIR_RESULT_SCHEMA,
    TRANSFER_PAIR_WORKFLOW_KEY,
    TRANSFER_PAIR_WORKFLOW_VERSION,
    InferenceTransferPairWorkerRequest,
)
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow.schemas import validate_inference_transfer_workflow_request
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.actor_authorization import (
    OPERATOR_ACTOR_PATTERN,
    WorkflowActorAuthorizer,
    WorkflowActorNamespace,
)
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.inference_transfer_execution_port import (
    FencedRunnerTransaction,
    InferenceTransferPairSourcePort,
)
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import load_persisted_inference_transfer_workflow_request
from eom_workflow_runner.role_execution_binding import (
    bind_platform_role_job,
    read_platform_role_result,
)
from eom_workflow_runner.role_execution_port import RoleExecutionResult
from eom_workflow_runner.state_machine import StepState, WorkflowStage, WorkflowState


class PlatformInferenceTransferExecutor:
    def __init__(
        self,
        *,
        orchestrator: Orchestrator,
        source: InferenceTransferPairSourcePort,
        actor_authorizer: WorkflowActorAuthorizer,
    ) -> None:
        self.orchestrator = orchestrator
        self.source = source
        self.actor_authorizer = actor_authorizer

    def _authorize_actor(self, actor_id: str) -> None:
        if OPERATOR_ACTOR_PATTERN.fullmatch(actor_id) is None:
            raise WorkflowError(
                WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
                "comparison requires its actual Operator principal",
            )
        authorization = self.actor_authorizer.authorize(actor_id, PermissionKey.ITEM_READ)
        if (
            not authorization.authorized
            or authorization.namespace is not WorkflowActorNamespace.OPERATOR_IDENTITY
            or authorization.canonical_actor_id != actor_id
        ):
            raise WorkflowError(
                WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
                "comparison Operator is not currently authorized",
            )

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: InferenceTransferWorkflowRequest,
        idempotency_key: str,
        fenced_transaction: FencedRunnerTransaction,
    ) -> RoleExecutionResult:
        with fenced_transaction() as session:
            actual, actual_step, checked = _stored_execution_context(
                session, workflow=workflow, step=step, request=request
            )
            # This is the immutable Workflow creator, never the system command
            # processor actor. The initial permission SHA remains an audit pin.
            actor_id = actual.created_actor_id
            self._authorize_actor(actor_id)
            command = InferenceTransferSearchCommand(
                actor_id=actor_id,
                graph_snapshot=checked.left_profile.source_basis.graph_snapshot,
                access_policy_revision_id=checked.access_policy_revision_id,
                access_policy_sha256=checked.access_policy_sha256,
                query_item_revision_id=checked.left_profile.source_basis.source.item_revision_id,
                source_classes=cast(
                    tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...],
                    tuple(
                        sorted(
                            {
                                checked.left_profile.source_basis.source.source_class,
                                checked.right_profile.source_basis.source.source_class,
                            }
                        )
                    ),
                ),
                maximum_candidates=2,
                top_k=2,
            )
            self.source.authorize_pair(command, checked.left_profile, checked.right_profile)
            prepared = prepare_inference_transfer_worker_comparison(
                checked.comparison, left=checked.left_profile, right=checked.right_profile
            )
            plan = resolve_inference_transfer_execution_plan(
                session,
                workflow_id=actual.workflow_id,
                workflow_definition_version=actual.definition_version,
                workflow_definition_sha256=actual.definition_hash,
                workflow_role_schema_version=actual.role_schema_version,
                workflow_request=checked,
                core_prompt_sha256=prepared.core_prompt_sha256,
                prompt_sha256=prepared.prompt_sha256,
                resolved_at=datetime.now(UTC),
            )
            plan_pin = {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "preset_id": plan.preset_id,
                "preset_revision_id": plan.preset_revision_id,
            }
            prompt_pin = {
                "prompt_version": prepared.prompt_version,
                "core_prompt_sha256": prepared.core_prompt_sha256,
                "prompt_sha256": prepared.prompt_sha256,
                "workflow_request_sha256": checked.request_sha256,
            }
            runtime = dict(actual.runtime_context)
            if runtime.get("execution_plan", plan_pin) != plan_pin:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                    "stored comparison execution pin differs",
                )
            inputs = dict(actual_step.input_pointer_manifest)
            if inputs.get("transfer_prompt", prompt_pin) != prompt_pin:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                    "stored comparison prompt pins differ",
                )
            runtime["execution_plan"] = plan_pin
            inputs["transfer_prompt"] = prompt_pin
            actual.runtime_context = runtime
            actual_step.input_pointer_manifest = inputs

        def reauthorize_sources(worker_request: InferenceTransferPairWorkerRequest) -> None:
            candidate = InferenceTransferPairWorkerRequest.model_validate(
                worker_request.model_dump(mode="json")
            )
            if candidate != prepared.request:
                raise ValueError("comparison reauthorization request differs")
            try:
                self._authorize_actor(actor_id)
            except WorkflowError as exc:
                # The platform owner callback normalizes ValueError into its
                # existing failed-job boundary; do not strand a running job.
                raise ValueError("comparison Operator authorization failed") from exc
            self.source.authorize_pair(command, checked.left_profile, checked.right_profile)

        def bind(job_id: str) -> None:
            with fenced_transaction() as session:
                bind_platform_role_job(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                    step_key=step.step_key,
                    attempt=step.attempt,
                    worker_role=step.worker_role,
                    job_id=job_id,
                )

        job = self.orchestrator.submit_workflow_role(
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            step_key=step.step_key,
            attempt=step.attempt,
            role="support",
            request=prepared.request,
            upstream_artifacts=(),
            result_schema=TRANSFER_PAIR_RESULT_SCHEMA,
            idempotency_key=idempotency_key,
            prompt_text=prepared.prompt_text,
            before_execute=bind,
            reauthorize_transfer_sources=reauthorize_sources,
            transfer_core_prompt_sha256=prepared.core_prompt_sha256,
            transfer_workflow_request=checked,
        )
        with fenced_transaction() as session:
            return read_platform_role_result(session, job)


def _stored_execution_context(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: InferenceTransferWorkflowRequest,
) -> tuple[WorkflowInstanceRecord, WorkflowStepRunRecord, InferenceTransferWorkflowRequest]:
    actual = session.execute(
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id == workflow.workflow_id)
        .with_for_update()
    ).scalar_one_or_none()
    actual_step = session.execute(
        select(WorkflowStepRunRecord)
        .where(WorkflowStepRunRecord.step_run_id == step.step_run_id)
        .with_for_update()
    ).scalar_one_or_none()
    if actual is None or actual_step is None:
        raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "comparison context is missing")
    checked = load_persisted_inference_transfer_workflow_request(actual.initial_request)
    supplied = validate_inference_transfer_workflow_request(request.model_dump(mode="json"))
    definition = session.get(WorkflowDefinitionRecord, actual.definition_id)
    if definition is None:
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID, "comparison definition is missing"
        )
    compiled = compile_definition_data(
        definition.canonical_definition, definition.source_path, {"support"}
    )
    comparison_step = compiled.steps_by_key.get("compare_pair")
    if (
        actual.definition_key != TRANSFER_PAIR_WORKFLOW_KEY
        or actual.definition_version != TRANSFER_PAIR_WORKFLOW_VERSION
        or actual.role_schema_version != TRANSFER_PAIR_PROTOCOL
        or actual.definition_hash != definition.definition_hash
        or actual.definition_hash != compiled.sha256
        or compiled.definition.definition_key != actual.definition_key
        or compiled.definition.definition_version != actual.definition_version
        or definition.definition_key != actual.definition_key
        or definition.definition_version != actual.definition_version
        or actual.created_actor_type != "human"
        or actual.state != WorkflowState.RUNNING.value
        or actual.stage != WorkflowStage.INFERENCE_TRANSFER.value
        or actual.current_step_key != "compare_pair"
        or not isinstance(comparison_step, AgentStep)
        or comparison_step.worker_role != "support"
        or comparison_step.result_schema != TRANSFER_PAIR_RESULT_SCHEMA
        or checked != supplied
        or actual.request_payload != checked.model_dump(mode="json")
        or actual_step.workflow_id != actual.workflow_id
        or actual_step.step_type != "agent"
        or actual_step.step_key != "compare_pair"
        or actual_step.step_key != step.step_key
        or actual_step.attempt != step.attempt
        or actual_step.worker_role != "support"
        or actual_step.worker_role != step.worker_role
        or actual_step.result_schema != TRANSFER_PAIR_RESULT_SCHEMA
        or actual_step.result_schema != step.result_schema
        or actual_step.state != StepState.RUNNING.value
        or actual_step.input_pointer_manifest.get("upstream_artifacts") != []
    ):
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
            "comparison stored purpose, request or step differs",
        )
    return actual, actual_step, checked
