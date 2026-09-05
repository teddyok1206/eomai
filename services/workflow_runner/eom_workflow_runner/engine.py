"""Deterministic command processor and workflow advancement engine."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_models import WorkerLeaseRecord
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.orchestrator import Orchestrator
from eom_workflow import (
    AgentStep,
    ArtifactPointer,
    CompiledWorkflowDefinition,
    DecisionStep,
    HumanGateStep,
    KnowledgeAnalysisWorkerRequest,
    LegacyItemEditorialCompatibilityWorkerRequest,
    LegacyItemExtractionWorkerRequest,
    TerminalStep,
    WorkerRequest,
    compile_definition_data,
    evaluate_decision,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_workflow_runner.actor_authorization import (
    WorkflowActorAuthorization,
    WorkflowActorAuthorizer,
    WorkflowActorDenialReason,
)
from eom_workflow_runner.catalog_port import (
    ContentTeamStimulusPointer,
    GeneratedStimulusPointer,
    RegistrationOutcome,
    WorkflowCatalogPort,
)
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.logging import log_workflow_event
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.readiness import (
    WorkflowExecutionReadiness,
    WorkflowRuntimeNotReady,
)
from eom_workflow_runner.repository import (
    CommandType,
    active_approval,
    claim_next_command,
    claimable_command_exists,
    create_approval_request,
    create_step_run,
    enqueue_command,
    link_superseded_attempts,
    list_step_runs,
    load_persisted_workflow_request,
)
from eom_workflow_runner.settings import WorkflowSettings
from eom_workflow_runner.state_machine import (
    SUCCESSFUL_TERMINAL_WORKFLOW_STATES,
    UNSUCCESSFUL_TERMINAL_WORKFLOW_STATES,
    ApprovalState,
    CommandState,
    StepState,
    WorkflowStage,
    WorkflowState,
    direct_agent_entry_stage,
    record_workflow_event,
    resume_capacity_queued_failure,
    transition_command,
    transition_stage,
    transition_step,
    transition_workflow,
)

LOGGER = logging.getLogger("eom.workflow.runner")
TERMINAL_WORKFLOW_STATES = {
    state.value
    for state in SUCCESSFUL_TERMINAL_WORKFLOW_STATES | UNSUCCESSFUL_TERMINAL_WORKFLOW_STATES
}


def _prompt_name_for_request(
    *,
    worker_role: str,
    request: (
        WorkerRequest
        | KnowledgeAnalysisWorkerRequest
        | LegacyItemExtractionWorkerRequest
        | LegacyItemEditorialCompatibilityWorkerRequest
    ),
) -> str:
    """Select the fixed prompt without conflating support workloads."""

    if worker_role == "support" and isinstance(request, LegacyItemExtractionWorkerRequest):
        return "legacy-item-extraction"
    if worker_role == "support" and isinstance(
        request, LegacyItemEditorialCompatibilityWorkerRequest
    ):
        return "legacy-item-editorial-compatibility"
    if worker_role == "item_management":
        return "registration"
    return worker_role


@dataclass(frozen=True)
class RoleExecutionResult:
    job_id: str
    status: str
    worker_slot: str | None
    logical_artifact_id: str
    revision_id: str
    content_hash: str | None
    error_code: str | None


class RoleJobExecutor(Protocol):
    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: (
            WorkerRequest
            | KnowledgeAnalysisWorkerRequest
            | LegacyItemExtractionWorkerRequest
            | LegacyItemEditorialCompatibilityWorkerRequest
        ),
        upstream: tuple[ArtifactPointer, ...],
        idempotency_key: str,
        prompt_text: str | None,
    ) -> RoleExecutionResult: ...


class ControlCommandProcessor(Protocol):
    def maintain_once(self) -> str | None: ...

    def process_once(self) -> str | None: ...


class CapacityReconciler(Protocol):
    def reconcile_expired(self, *, observed_at: datetime) -> tuple[object, ...]: ...


class PlatformRoleJobExecutor:
    def __init__(
        self,
        engine: Engine,
        workflow_settings: WorkflowSettings,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.orchestrator = orchestrator or Orchestrator(engine)
        self.workflow_settings = workflow_settings

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: (
            WorkerRequest
            | KnowledgeAnalysisWorkerRequest
            | LegacyItemExtractionWorkerRequest
            | LegacyItemEditorialCompatibilityWorkerRequest
        ),
        upstream: tuple[ArtifactPointer, ...],
        idempotency_key: str,
        prompt_text: str | None,
    ) -> RoleExecutionResult:
        if step.worker_role is None or step.result_schema is None:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_STEP_FAILED,
                "agent step is missing role contract",
            )
        prompt_name = _prompt_name_for_request(worker_role=step.worker_role, request=request)
        prompt_path = (
            None
            if prompt_text is not None
            else self.workflow_settings.prompt_root / f"{prompt_name}.txt"
        )

        def bind_platform_job(job_id: str) -> None:
            with transaction(self.sessions) as session:
                current = session.execute(
                    select(WorkflowStepRunRecord)
                    .where(WorkflowStepRunRecord.step_run_id == step.step_run_id)
                    .with_for_update()
                ).scalar_one()
                if (
                    current.workflow_id != workflow.workflow_id
                    or current.step_key != step.step_key
                    or current.attempt != step.attempt
                    or current.worker_role != step.worker_role
                    or current.state != StepState.RUNNING.value
                    or current.platform_job_id not in {None, job_id}
                ):
                    raise WorkflowError(
                        WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                        "platform job does not match the running workflow step",
                    )
                current.platform_job_id = job_id

        job = self.orchestrator.submit_workflow_role(
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            step_key=step.step_key,
            attempt=step.attempt,
            role=step.worker_role,
            request=request,
            upstream_artifacts=upstream,
            result_schema=step.result_schema,
            idempotency_key=idempotency_key,
            prompt_path=prompt_path,
            prompt_text=prompt_text,
            before_execute=bind_platform_job,
        )
        content_hash: str | None = None
        if job.status == "SUCCEEDED":
            with self.sessions() as session:
                revision = session.get(ArtifactRevisionRecord, job.revision_id)
                if revision is None:
                    raise WorkflowError(
                        WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                        "platform job succeeded without artifact revision",
                    )
                content_hash = revision.content_hash
        return RoleExecutionResult(
            job_id=job.job_id,
            status=job.status,
            worker_slot=job.worker_slot_id,
            logical_artifact_id=job.logical_artifact_id,
            revision_id=job.revision_id,
            content_hash=content_hash,
            error_code=job.error_code,
        )


class WorkflowRunner:
    def __init__(
        self,
        engine: Engine,
        settings: WorkflowSettings | None = None,
        executor: RoleJobExecutor | None = None,
        *,
        catalog: WorkflowCatalogPort,
        actor_authorizer: WorkflowActorAuthorizer,
        readiness: WorkflowExecutionReadiness,
        available_roles: frozenset[str],
        control_processor: ControlCommandProcessor | None = None,
        capacity_reconciler: CapacityReconciler | None = None,
        runner_id: str | None = None,
    ) -> None:
        if catalog is None:
            raise ValueError("workflow catalog adapter is required")
        if actor_authorizer is None:
            raise ValueError("workflow actor authorizer is required")
        if not available_roles:
            raise ValueError("workflow worker roles are required")
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.settings = settings or WorkflowSettings.from_environment()
        self.runner_config = self.settings.load_runner()
        self.actor_authorizer = actor_authorizer
        self.available_roles = available_roles
        self.executor = executor or PlatformRoleJobExecutor(engine, self.settings)
        self.catalog = catalog
        self.readiness = readiness
        self.runner_id = runner_id or f"runner-{uuid4().hex}"
        self.control_processor = control_processor
        self.capacity_reconciler = capacity_reconciler

    def run_once(self, workflow_id: str | None = None) -> WorkflowCommandRecord | None:
        with self.sessions() as session:
            has_work = claimable_command_exists(session, workflow_id=workflow_id)
        if not has_work:
            return None
        self._require_runtime_ready()
        with transaction(self.sessions) as session:
            command = claim_next_command(
                session,
                runner_id=self.runner_id,
                lease_seconds=self.runner_config.command_lease_seconds,
                workflow_id=workflow_id,
            )
            if command is None:
                return None
            command_id = command.command_id
        with transaction(self.sessions) as session:
            processing = session.execute(
                select(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.command_id == command_id)
                .with_for_update()
            ).scalar_one()
            transition_command(processing, CommandState.PROCESSING)

        try:
            self._process_command(command_id)
        except WorkflowError as exc:
            with transaction(self.sessions) as session:
                failed = session.execute(
                    select(WorkflowCommandRecord)
                    .where(WorkflowCommandRecord.command_id == command_id)
                    .with_for_update()
                ).scalar_one()
                if (
                    failed.state == CommandState.PROCESSING.value
                    and failed.lease_owner == self.runner_id
                ):
                    failed.error_code = exc.code.value
                    transition_command(failed, CommandState.FAILED)
            log_workflow_event(
                LOGGER,
                logging.ERROR,
                str(exc),
                event="WORKFLOW_COMMAND_FAILED",
                command_id=command_id,
                error_code=exc.code.value,
            )
        else:
            with transaction(self.sessions) as session:
                succeeded = session.execute(
                    select(WorkflowCommandRecord)
                    .where(WorkflowCommandRecord.command_id == command_id)
                    .with_for_update()
                ).scalar_one()
                if (
                    succeeded.state == CommandState.PROCESSING.value
                    and succeeded.lease_owner == self.runner_id
                ):
                    transition_command(succeeded, CommandState.SUCCEEDED)
        with self.sessions() as session:
            result = session.get(WorkflowCommandRecord, command_id)
            if result is None:
                raise RuntimeError("processed command disappeared")
            session.expunge(result)
            return result

    def _require_runtime_ready(self) -> None:
        readiness = self.readiness.evaluate()
        if not readiness.ready:
            log_workflow_event(
                LOGGER,
                logging.ERROR,
                "workflow runtime is not ready",
                event="WORKFLOW_RUNTIME_NOT_READY",
                error_code=",".join(readiness.failed_codes),
            )
            raise WorkflowRuntimeNotReady(readiness)

    def run_until_idle(self, workflow_id: str, limit: int | None = None) -> int:
        processed = 0
        maximum = limit or self.runner_config.max_commands_per_run
        while processed < maximum and self.run_once(workflow_id) is not None:
            processed += 1
        return processed

    def serve(self) -> None:
        while True:
            if self.capacity_reconciler is not None:
                self.capacity_reconciler.reconcile_expired(observed_at=datetime.now(UTC))
            maintenance_result = (
                self.control_processor.maintain_once()
                if self.control_processor is not None
                else None
            )
            control_result = (
                self.control_processor.process_once()
                if self.control_processor is not None
                else None
            )
            try:
                result = self.run_once()
            except WorkflowRuntimeNotReady:
                result = None
            if result is None and maintenance_result is None and control_result is None:
                time.sleep(self.runner_config.poll_interval_seconds)

    def reconcile(self, workflow_id: str) -> None:
        self._require_runtime_ready()
        self._advance(workflow_id, None, "system", self.runner_id)

    def _process_command(self, command_id: str) -> None:
        with self.sessions() as session:
            command = session.get(WorkflowCommandRecord, command_id)
            if command is None:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                    "claimed command disappeared",
                )
            session.expunge(command)
        command_type = CommandType(command.command_type)
        if command_type in {
            CommandType.START_WORKFLOW,
            CommandType.ADVANCE_WORKFLOW,
        }:
            self._advance(
                command.workflow_id,
                command.command_id,
                command.actor_type,
                command.actor_id,
            )
        elif command_type == CommandType.RECONCILE_WORKFLOW:
            if command.actor_type == "human":
                authorization = self._authorize_actor(
                    command.actor_id, PermissionKey.WORKFLOW_RECONCILE
                )
                if "admin" not in authorization.workflow_roles:
                    raise WorkflowError(
                        WorkflowErrorCode.APPROVAL_UNAUTHORIZED,
                        "only an admin can reconcile a workflow",
                    )
            self._resume_capacity_queued_failure(command)
            self._advance(
                command.workflow_id,
                command.command_id,
                command.actor_type,
                command.actor_id,
            )
        elif command_type == CommandType.APPROVE_WORKFLOW:
            self._approve(command)
            self._advance(
                command.workflow_id,
                command.command_id,
                command.actor_type,
                command.actor_id,
            )
        elif command_type == CommandType.REQUEST_REWORK:
            self._request_rework(command)
            self._advance(
                command.workflow_id,
                command.command_id,
                command.actor_type,
                command.actor_id,
            )
        elif command_type == CommandType.CANCEL_WORKFLOW:
            self._cancel(command)
        else:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                "command type is not implemented in workflow v0",
            )

    def _advance(
        self, workflow_id: str, command_id: str | None, actor_type: str, actor_id: str
    ) -> None:
        for _ in range(128):
            workflow, compiled = self._load_workflow(workflow_id)
            if workflow.state in TERMINAL_WORKFLOW_STATES:
                if workflow.state == WorkflowState.COMPLETED.value:
                    with transaction(self.sessions) as session:
                        link_superseded_attempts(session, workflow.workflow_id)
                return
            if workflow.state == WorkflowState.AWAITING_HUMAN_APPROVAL.value:
                return
            if workflow.state == WorkflowState.REQUESTED.value:
                with transaction(self.sessions) as session:
                    transition_workflow(
                        session,
                        workflow_id,
                        WorkflowState.RUNNING,
                        "WORKFLOW_STARTED",
                        actor_type=actor_type,
                        actor_id=actor_id,
                        command_id=command_id,
                        step_key=workflow.current_step_key,
                    )
                continue

            step_definition = compiled.steps_by_key[workflow.current_step_key]
            if isinstance(step_definition, AgentStep):
                if step_definition.worker_role == "item_management" and workflow.state == (
                    WorkflowState.APPROVED.value
                ):
                    with transaction(self.sessions) as session:
                        transition_workflow(
                            session,
                            workflow_id,
                            WorkflowState.REGISTERING,
                            "REGISTRATION_STARTED",
                            actor_type=actor_type,
                            actor_id=actor_id,
                            command_id=command_id,
                            step_key=step_definition.key,
                        )
                    continue
                should_continue = self._execute_agent(
                    workflow,
                    compiled,
                    step_definition,
                    command_id,
                    actor_type,
                    actor_id,
                )
                if not should_continue:
                    return
            elif isinstance(step_definition, DecisionStep):
                self._execute_decision(
                    workflow,
                    compiled,
                    step_definition,
                    command_id,
                    actor_type,
                    actor_id,
                )
            elif isinstance(step_definition, HumanGateStep):
                self._open_human_gate(
                    workflow,
                    compiled,
                    step_definition,
                    command_id,
                    actor_type,
                    actor_id,
                )
                return
            elif isinstance(step_definition, TerminalStep):
                self._complete_terminal(
                    workflow,
                    compiled,
                    step_definition,
                    command_id,
                    actor_type,
                    actor_id,
                )
                return
        raise WorkflowError(
            WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
            "workflow advancement exceeded deterministic step limit",
        )

    def _execute_agent(
        self,
        workflow: WorkflowInstanceRecord,
        compiled: CompiledWorkflowDefinition,
        definition: AgentStep,
        command_id: str | None,
        actor_type: str,
        actor_id: str,
    ) -> bool:
        with transaction(self.sessions) as session:
            current = session.get(WorkflowInstanceRecord, workflow.workflow_id)
            if current is None:
                raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow disappeared")
            direct_review_predecessor = any(
                isinstance(step, AgentStep)
                and step.worker_role == "authoring"
                and step.on_success == definition.key
                for step in compiled.definition.steps
            )
            if (
                definition.worker_role == "review"
                and WorkflowStage(current.stage) is WorkflowStage.AUTHORING
                and direct_review_predecessor
            ):
                current = transition_stage(
                    session,
                    workflow.workflow_id,
                    WorkflowStage.IMAGE_SKIPPED,
                    definition.key,
                    "IMAGE_DECISION_COMPLETED",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    command_id=command_id,
                    payload={"branch": definition.key, "entry": "direct_agent"},
                )
                current = transition_stage(
                    session,
                    workflow.workflow_id,
                    WorkflowStage.REVIEWING,
                    definition.key,
                    "REVIEW_STAGE_ENTERED",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    command_id=command_id,
                    payload={"entry": "direct_agent"},
                )
            entry_stage = direct_agent_entry_stage(
                WorkflowStage(current.stage),
                definition.worker_role,
            )
            if entry_stage is not None:
                current = transition_stage(
                    session,
                    workflow.workflow_id,
                    entry_stage,
                    definition.key,
                    "IMAGE_STAGE_ENTERED",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    command_id=command_id,
                    payload={"entry": "direct_agent"},
                )
            step = self._latest_active_step(session, workflow.workflow_id, definition.key)
            if step is None:
                step = create_step_run(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_key=definition.key,
                    step_type=definition.type,
                    worker_role=definition.worker_role,
                    result_schema=definition.result_schema,
                    input_pointer_manifest={
                        "upstream_artifacts": [
                            pointer.model_dump(mode="json")
                            for pointer in self._upstream_pointers(
                                session, workflow.workflow_id, compiled, definition.key
                            )
                        ]
                    },
                    max_attempts=compiled.definition.limits.max_step_attempts,
                )
                record_workflow_event(
                    session,
                    workflow.workflow_id,
                    "STEP_READY",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    command_id=command_id,
                    step_key=definition.key,
                    payload={"step_run_id": step.step_run_id, "attempt": step.attempt},
                )
            if step.state == StepState.SUCCEEDED.value:
                self._move_after_agent(
                    session,
                    current,
                    definition,
                    command_id,
                    actor_type,
                    actor_id,
                )
                return True
            if step.state == StepState.READY.value:
                transition_step(step, StepState.RUNNING)
                record_workflow_event(
                    session,
                    workflow.workflow_id,
                    "STEP_STARTED",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    command_id=command_id,
                    step_key=definition.key,
                    payload={"step_run_id": step.step_run_id, "attempt": step.attempt},
                )
            elif step.state != StepState.RUNNING.value:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "agent step is not executable",
                )
            step_run_id = step.step_run_id
            attempt = step.attempt
            upstream = self._upstream_pointers(
                session, workflow.workflow_id, compiled, definition.key
            )

        idempotency_key = _step_job_idempotency_key(
            workflow.workflow_id, definition.key, attempt, workflow.definition_hash
        )
        self._renew_command_lease(command_id)
        full_request = load_persisted_workflow_request(workflow.initial_request)
        registration: RegistrationOutcome | None = None
        generated_stimulus: GeneratedStimulusPointer | None = None
        content_team_stimuli: tuple[ContentTeamStimulusPointer, ...] | None = None
        result_pointer: ArtifactPointer | None = None
        try:
            prompt_text: str | None = None
            if full_request.content_pack is not None:
                prepared = self.catalog.prepare_prompt(
                    workflow=workflow,
                    step=self._detached_step(step_run_id),
                    request=full_request,
                    upstream=upstream,
                )
                prompt_text = prepared.text
                with transaction(self.sessions) as session:
                    prepared_step = session.execute(
                        select(WorkflowStepRunRecord)
                        .where(WorkflowStepRunRecord.step_run_id == step_run_id)
                        .with_for_update()
                    ).scalar_one()
                    input_manifest = dict(prepared_step.input_pointer_manifest)
                    input_manifest["prompt"] = prepared.pointer
                    input_manifest["prompt_envelope"] = prepared.envelope
                    prepared_step.input_pointer_manifest = input_manifest
                    current = session.get(WorkflowInstanceRecord, workflow.workflow_id)
                    assert current is not None
                    context = dict(current.runtime_context)
                    prompt_artifacts = list(context.get("prompt_artifacts", []))
                    if not any(
                        item.get("step_key") == definition.key and item.get("attempt") == attempt
                        for item in prompt_artifacts
                        if isinstance(item, dict)
                    ):
                        prompt_artifacts.append(
                            {
                                "step_key": definition.key,
                                "attempt": attempt,
                                **prepared.pointer,
                            }
                        )
                    context["prompt_artifacts"] = prompt_artifacts
                    current.runtime_context = context
            execution = self.executor.execute(
                workflow=workflow,
                step=self._detached_step(step_run_id),
                request=full_request.worker_request(),
                upstream=upstream,
                idempotency_key=idempotency_key,
                prompt_text=prompt_text,
            )
            if execution.status == "SUCCEEDED" and execution.content_hash is not None:
                result_pointer = ArtifactPointer(
                    step_key=definition.key,
                    attempt=attempt,
                    job_id=execution.job_id,
                    logical_artifact_id=execution.logical_artifact_id,
                    revision_id=execution.revision_id,
                    content_hash=execution.content_hash,
                    result_schema=definition.result_schema,
                )
                if definition.worker_role == "item_management":
                    registration = self.catalog.register_workflow(
                        workflow=workflow,
                        step=self._detached_step(step_run_id),
                        request=full_request,
                        artifacts=(*upstream, result_pointer),
                    )
                elif (
                    definition.worker_role == "image"
                    and full_request.request_name == "GENERATED_KNOWLEDGE_ITEM_REQUEST"
                ):
                    if definition.result_schema == "image-result@8.0":
                        content_team_stimuli = self.catalog.materialize_content_team_stimuli(
                            workflow=workflow,
                            artifacts=(*upstream, result_pointer),
                        )
                    else:
                        generated_stimulus = self.catalog.materialize_generated_stimulus(
                            workflow=workflow,
                            artifacts=(*upstream, result_pointer),
                        )
        except Exception as exc:
            with transaction(self.sessions) as session:
                failed_step = session.execute(
                    select(WorkflowStepRunRecord)
                    .where(WorkflowStepRunRecord.step_run_id == step_run_id)
                    .with_for_update()
                ).scalar_one()
                failed_step.error_code = WorkflowErrorCode.WORKFLOW_STEP_FAILED.value
                failed_step.error_summary = "platform role execution raised an exception"
                if failed_step.state == StepState.RUNNING.value:
                    transition_step(failed_step, StepState.FAILED)
                self._fail_workflow(
                    session,
                    workflow.workflow_id,
                    command_id,
                    actor_type,
                    actor_id,
                    failed_step.error_code,
                )
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_STEP_FAILED,
                "platform role execution failed",
            ) from exc
        if execution.status == "QUEUED":
            with transaction(self.sessions) as session:
                queued_step = session.execute(
                    select(WorkflowStepRunRecord)
                    .where(WorkflowStepRunRecord.step_run_id == step_run_id)
                    .with_for_update()
                ).scalar_one()
                if (
                    queued_step.state != StepState.RUNNING.value
                    or queued_step.platform_job_id != execution.job_id
                ):
                    raise WorkflowError(
                        WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                        "queued platform job does not match the running workflow step",
                    )
                retry_source = command_id or f"direct-v{workflow.lock_version}"
                retry, _ = enqueue_command(
                    session,
                    workflow_id=workflow.workflow_id,
                    command_type=CommandType.ADVANCE_WORKFLOW,
                    payload={"reason": "CAPACITY_AVAILABLE_RETRY", "job_id": execution.job_id},
                    actor_type="system",
                    actor_id=self.runner_id,
                    source="capacity_controller",
                    idempotency_key=(f"capacity-retry:{retry_source}:{execution.job_id}"),
                    available_at=datetime.now(UTC)
                    + timedelta(seconds=max(1, self.runner_config.poll_interval_seconds)),
                )
                record_workflow_event(
                    session,
                    workflow.workflow_id,
                    "STEP_CAPACITY_QUEUED",
                    actor_type="system",
                    actor_id=self.runner_id,
                    command_id=command_id,
                    step_key=definition.key,
                    payload={
                        "step_run_id": step_run_id,
                        "attempt": attempt,
                        "job_id": execution.job_id,
                        "retry_command_id": retry.command_id,
                    },
                )
            return False

        execution_failed = execution.status != "SUCCEEDED" or execution.content_hash is None
        with transaction(self.sessions) as session:
            step = session.execute(
                select(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.step_run_id == step_run_id)
                .with_for_update()
            ).scalar_one()
            step.platform_job_id = execution.job_id
            if execution_failed:
                step.error_code = (
                    execution.error_code or WorkflowErrorCode.WORKFLOW_STEP_FAILED.value
                )
                step.error_summary = "platform role job failed"
                if step.state == StepState.RUNNING.value:
                    transition_step(step, StepState.FAILED)
                self._fail_workflow(
                    session,
                    workflow.workflow_id,
                    command_id,
                    actor_type,
                    actor_id,
                    step.error_code,
                )
            else:
                assert result_pointer is not None
                step.output_pointer_manifest = result_pointer.model_dump(mode="json")
                transition_step(step, StepState.SUCCEEDED)
                current = session.get(WorkflowInstanceRecord, workflow.workflow_id)
                if current is None:
                    raise WorkflowError(
                        WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow disappeared"
                    )
                context = dict(current.runtime_context)
                pointers = list(context.get("artifact_pointers", []))
                pointers.append(result_pointer.model_dump(mode="json"))
                context["artifact_pointers"] = pointers
                if generated_stimulus is not None:
                    context["generated_stimulus"] = generated_stimulus.as_dict()
                if content_team_stimuli is not None:
                    context["content_team_stimuli"] = [
                        pointer.as_dict() for pointer in content_team_stimuli
                    ]
                if registration is not None:
                    context["item_registration"] = {
                        "item_id": registration.item_id,
                        "item_revision_id": registration.item_revision_id,
                        "revision_number": registration.revision_number,
                        "manifest_artifact_id": registration.manifest_artifact_id,
                        "manifest_artifact_revision_id": (
                            registration.manifest_artifact_revision_id
                        ),
                        "manifest_sha256": registration.manifest_sha256,
                    }
                current.runtime_context = context
                record_workflow_event(
                    session,
                    workflow.workflow_id,
                    "STEP_SUCCEEDED",
                    actor_type="worker",
                    actor_id=definition.worker_role,
                    command_id=command_id,
                    step_key=definition.key,
                    payload={
                        "step_run_id": step.step_run_id,
                        "attempt": attempt,
                        "job_id": execution.job_id,
                        "logical_artifact_id": execution.logical_artifact_id,
                        "revision_id": execution.revision_id,
                    },
                )
                self._move_after_agent(
                    session,
                    current,
                    definition,
                    command_id,
                    actor_type,
                    actor_id,
                )
        if execution_failed:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_STEP_FAILED,
                "platform role job failed",
            )
        return True

    def _move_after_agent(
        self,
        session: Session,
        workflow: WorkflowInstanceRecord,
        definition: AgentStep,
        command_id: str | None,
        actor_type: str,
        actor_id: str,
    ) -> None:
        workflow.current_step_key = definition.on_success
        record_workflow_event(
            session,
            workflow.workflow_id,
            "STEP_ADVANCED",
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=command_id,
            step_key=definition.on_success,
            payload={"from_step": definition.key},
        )
        if definition.worker_role == "image":
            transition_stage(
                session,
                workflow.workflow_id,
                WorkflowStage.REVIEWING,
                definition.on_success,
                "REVIEW_STAGE_ENTERED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=command_id,
            )
        elif definition.worker_role == "review":
            transition_stage(
                session,
                workflow.workflow_id,
                WorkflowStage.AWAITING_HUMAN_APPROVAL,
                definition.on_success,
                "HUMAN_APPROVAL_STAGE_ENTERED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=command_id,
            )

    def _execute_decision(
        self,
        workflow: WorkflowInstanceRecord,
        compiled: CompiledWorkflowDefinition,
        definition: DecisionStep,
        command_id: str | None,
        actor_type: str,
        actor_id: str,
    ) -> None:
        if definition.operator == "step_result_image_count":
            with self.sessions() as session:
                upstream = self._upstream_pointers(
                    session, workflow.workflow_id, compiled, definition.key
                )
            matches = tuple(
                pointer for pointer in upstream if pointer.step_key == definition.source_step
            )
            if len(matches) != 1:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                    "image decision source result is missing or ambiguous",
                )
            count = self.catalog.content_team_image_slot_count(
                workflow=workflow,
                authoring=matches[0],
            )
            try:
                target = definition.branches[str(count)]
            except KeyError as exc:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                    "image-count decision has no exact branch",
                ) from exc
        else:
            target = evaluate_decision(definition, workflow.initial_request)
        with transaction(self.sessions) as session:
            step = self._latest_active_step(session, workflow.workflow_id, definition.key)
            if step is None:
                step = create_step_run(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_key=definition.key,
                    step_type=definition.type,
                    worker_role=None,
                    result_schema=None,
                    input_pointer_manifest={"field": definition.field},
                    max_attempts=compiled.definition.limits.max_step_attempts,
                )
                transition_step(step, StepState.RUNNING)
                transition_step(step, StepState.SUCCEEDED)
            workflow_record = session.get(WorkflowInstanceRecord, workflow.workflow_id)
            if workflow_record is None:
                raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow disappeared")
            workflow_record.current_step_key = target
            skipped_image: WorkflowStepRunRecord | None = None
            if target == "review":
                if definition.operator == "step_result_image_count":
                    context = dict(workflow_record.runtime_context)
                    context["content_team_stimuli"] = []
                    workflow_record.runtime_context = context
                image_definition = compiled.steps_by_key.get("image")
                if not isinstance(image_definition, AgentStep):
                    raise WorkflowError(
                        WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                        "image decision has no image agent step",
                    )
                skipped_image = create_step_run(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_key=image_definition.key,
                    step_type=image_definition.type,
                    worker_role=image_definition.worker_role,
                    result_schema=image_definition.result_schema,
                    input_pointer_manifest={"decision": "skip"},
                    max_attempts=compiled.definition.limits.max_step_attempts,
                )
                transition_step(skipped_image, StepState.SKIPPED)
            stage = (
                WorkflowStage.IMAGE_REQUIRED if target == "image" else WorkflowStage.IMAGE_SKIPPED
            )
            transition_stage(
                session,
                workflow.workflow_id,
                stage,
                target,
                "IMAGE_DECISION_COMPLETED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=command_id,
                payload={
                    "step_run_id": step.step_run_id,
                    "branch": target,
                    "skipped_step_run_id": (
                        skipped_image.step_run_id if skipped_image is not None else None
                    ),
                },
            )
            if target == "review":
                transition_stage(
                    session,
                    workflow.workflow_id,
                    WorkflowStage.REVIEWING,
                    target,
                    "REVIEW_STAGE_ENTERED",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    command_id=command_id,
                )

    def _open_human_gate(
        self,
        workflow: WorkflowInstanceRecord,
        compiled: CompiledWorkflowDefinition,
        definition: HumanGateStep,
        command_id: str | None,
        actor_type: str,
        actor_id: str,
    ) -> None:
        with transaction(self.sessions) as session:
            approval = active_approval(session, workflow.workflow_id, for_update=True)
            if approval is not None:
                return
            step = self._latest_active_step(session, workflow.workflow_id, definition.key)
            if step is None:
                step = create_step_run(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_key=definition.key,
                    step_type=definition.type,
                    worker_role=None,
                    result_schema=None,
                    input_pointer_manifest={
                        "upstream_artifacts": [
                            pointer.model_dump(mode="json")
                            for pointer in self._upstream_pointers(
                                session, workflow.workflow_id, compiled, definition.key
                            )
                        ]
                    },
                    max_attempts=compiled.definition.limits.max_step_attempts,
                )
                transition_step(step, StepState.WAITING_FOR_HUMAN)
            approval = create_approval_request(
                session,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                allowed_roles=definition.allowed_actor_roles,
                allowed_rework_targets=definition.allowed_rework_targets,
            )
            transition_workflow(
                session,
                workflow.workflow_id,
                WorkflowState.AWAITING_HUMAN_APPROVAL,
                "HUMAN_APPROVAL_REQUESTED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=command_id,
                step_key=definition.key,
                payload={
                    "approval_request_id": approval.approval_request_id,
                    "step_run_id": step.step_run_id,
                },
            )

    def _approve(self, command: WorkflowCommandRecord) -> None:
        authorization = self._authorize_actor(command.actor_id, PermissionKey.WORKFLOW_APPROVE)
        with transaction(self.sessions) as session:
            approval = self._validate_pending_approval(
                session, command, authorization.workflow_roles
            )
            step = session.execute(
                select(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.step_run_id == approval.step_run_id)
                .with_for_update()
            ).scalar_one()
            transition_step(step, StepState.SUCCEEDED)
            approval.status = ApprovalState.APPROVED.value
            approval.lock_version += 1
            approval.resolved_at = datetime.now(UTC)
            approval.resolved_actor_type = command.actor_type
            approval.resolved_actor_id = command.actor_id
            approval.decision = "APPROVED"
            workflow = transition_workflow(
                session,
                command.workflow_id,
                WorkflowState.APPROVED,
                "WORKFLOW_APPROVED",
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                command_id=command.command_id,
                step_key=step.step_key,
                payload={
                    "approval_request_id": approval.approval_request_id,
                    "authorization_source": authorization.namespace.value,
                },
            )
            compiled = self._compiled_for_record(session, workflow)
            gate = compiled.steps_by_key[step.step_key]
            if not isinstance(gate, HumanGateStep):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                    "approval step is not a human gate",
                )
            transition_stage(
                session,
                command.workflow_id,
                WorkflowStage.REGISTERING,
                gate.on_approve,
                "REGISTRATION_STAGE_ENTERED",
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                command_id=command.command_id,
            )

    def _resume_capacity_queued_failure(self, command: WorkflowCommandRecord) -> bool:
        """Reconcile a failed workflow only when its worker job never started."""

        with transaction(self.sessions) as session:
            workflow = session.execute(
                select(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.workflow_id == command.workflow_id)
                .with_for_update()
            ).scalar_one_or_none()
            if workflow is None:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_NOT_FOUND,
                    "workflow not found",
                )
            if workflow.state != WorkflowState.FAILED.value:
                return False
            if (
                workflow.stage != WorkflowStage.FAILED.value
                or workflow.failure_code != WorkflowErrorCode.WORKFLOW_STEP_FAILED.value
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "failed workflow is not a recoverable capacity-queued failure",
                )
            compiled = self._compiled_for_record(session, workflow)
            definition = compiled.steps_by_key.get(workflow.current_step_key)
            if not isinstance(definition, AgentStep):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "failed workflow is not positioned on an agent step",
                )
            step = self._latest_active_step(
                session,
                workflow.workflow_id,
                definition.key,
            )
            if (
                step is None
                or step.state != StepState.FAILED.value
                or step.error_code != WorkflowErrorCode.WORKFLOW_STEP_FAILED.value
                or step.platform_job_id is None
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "failed step is not a recoverable capacity-queued attempt",
                )
            job = session.execute(
                select(JobRecord).where(JobRecord.job_id == step.platform_job_id).with_for_update()
            ).scalar_one_or_none()
            if job is None:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                    "failed step platform job is missing",
                )
            request = job.request
            if (
                job.status != "QUEUED"
                or job.worker_slot_id is not None
                or job.worker_exit_code is not None
                or job.worker_stdout_path is not None
                or job.worker_stderr_path is not None
                or job.error_code is not None
                or job.error_message is not None
                or job.completed_at is not None
                or request.get("workflow_id") != workflow.workflow_id
                or request.get("step_run_id") != step.step_run_id
                or request.get("attempt") != step.attempt
                or request.get("role") != definition.worker_role
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "platform job has crossed the worker execution boundary",
                )
            events = tuple(
                session.scalars(
                    select(JobEventRecord)
                    .where(JobEventRecord.job_id == job.job_id)
                    .order_by(JobEventRecord.sequence)
                )
            )
            event_contract = tuple(
                (event.sequence, event.event, event.from_state, event.to_state) for event in events
            )
            if event_contract != (
                (1, "JOB_CREATED", None, "CREATED"),
                (2, "REQUEST_VALIDATED", "CREATED", "VALIDATED"),
                (3, "JOB_QUEUED", "VALIDATED", "QUEUED"),
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "platform job event history is not an untouched queue",
                )
            if (
                session.scalar(
                    select(ArtifactRecord.logical_artifact_id).where(
                        ArtifactRecord.job_id == job.job_id
                    )
                )
                is not None
                or session.scalar(
                    select(WorkerLeaseRecord.lease_id).where(WorkerLeaseRecord.job_id == job.job_id)
                )
                is not None
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "queued platform job already has execution or artifact evidence",
                )
            competing_command = session.scalar(
                select(WorkflowCommandRecord.command_id)
                .where(
                    WorkflowCommandRecord.workflow_id == workflow.workflow_id,
                    WorkflowCommandRecord.command_id != command.command_id,
                    WorkflowCommandRecord.state.in_(
                        (
                            CommandState.PENDING.value,
                            CommandState.LEASED.value,
                            CommandState.PROCESSING.value,
                        )
                    ),
                )
                .limit(1)
            )
            if competing_command is not None:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                    "workflow has another active command",
                )
            target_state, target_stage = _capacity_resume_target(
                definition.worker_role,
                workflow.definition_key,
            )
            resume_capacity_queued_failure(
                session,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                job_id=job.job_id,
                target_state=target_state,
                target_stage=target_stage,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                command_id=command.command_id,
            )
            return True

    def _request_rework(self, command: WorkflowCommandRecord) -> None:
        authorization = self._authorize_actor(
            command.actor_id, PermissionKey.WORKFLOW_REQUEST_REWORK
        )
        target = command.payload.get("target")
        reason = command.payload.get("reason")
        if not isinstance(target, str) or not isinstance(reason, str):
            raise WorkflowError(
                WorkflowErrorCode.APPROVAL_INVALID_REWORK_TARGET,
                "rework command payload is invalid",
            )
        with transaction(self.sessions) as session:
            approval = self._validate_pending_approval(
                session, command, authorization.workflow_roles
            )
            if target not in approval.allowed_rework_targets:
                raise WorkflowError(
                    WorkflowErrorCode.APPROVAL_INVALID_REWORK_TARGET,
                    "rework target is not allowed",
                )
            workflow = session.execute(
                select(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.workflow_id == command.workflow_id)
                .with_for_update()
            ).scalar_one()
            compiled = self._compiled_for_record(session, workflow)
            if workflow.rework_cycle_count >= compiled.definition.limits.max_rework_cycles:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_REWORK_LIMIT_EXCEEDED,
                    "workflow rework limit exceeded; admin decision required",
                )
            target_definition = compiled.steps_by_key[target]
            if not isinstance(target_definition, AgentStep):
                raise WorkflowError(
                    WorkflowErrorCode.APPROVAL_INVALID_REWORK_TARGET,
                    "rework target must be an agent step",
                )
            approval_step = session.get(WorkflowStepRunRecord, approval.step_run_id)
            if approval_step is None:
                raise WorkflowError(WorkflowErrorCode.APPROVAL_STALE, "approval step disappeared")
            transition_step(approval_step, StepState.SUPERSEDED)
            approval.status = ApprovalState.REWORK_REQUESTED.value
            approval.lock_version += 1
            approval.resolved_at = datetime.now(UTC)
            approval.resolved_actor_type = command.actor_type
            approval.resolved_actor_id = command.actor_id
            approval.decision = "REWORK_REQUESTED"
            approval.reason = reason[:1000]
            approval.rework_target_step = target

            order = [step.key for step in compiled.definition.steps]
            target_index = order.index(target)
            old_target_runs: list[WorkflowStepRunRecord] = []
            for step_run in list_step_runs(session, command.workflow_id):
                if order.index(step_run.step_key) < target_index:
                    continue
                if step_run.state in {
                    StepState.SUCCEEDED.value,
                    StepState.SKIPPED.value,
                    StepState.WAITING_FOR_HUMAN.value,
                }:
                    transition_step(step_run, StepState.SUPERSEDED)
                    if step_run.step_key == target:
                        old_target_runs.append(step_run)

            new_target = create_step_run(
                session,
                workflow_id=command.workflow_id,
                step_key=target_definition.key,
                step_type=target_definition.type,
                worker_role=target_definition.worker_role,
                result_schema=target_definition.result_schema,
                input_pointer_manifest={
                    "upstream_artifacts": [
                        pointer.model_dump(mode="json")
                        for pointer in self._upstream_pointers(
                            session, command.workflow_id, compiled, target
                        )
                    ]
                },
                max_attempts=compiled.definition.limits.max_step_attempts,
            )
            for old in old_target_runs:
                old.superseded_by_step_run_id = new_target.step_run_id
            workflow.rework_cycle_count += 1
            transition_workflow(
                session,
                command.workflow_id,
                WorkflowState.REWORK_REQUESTED,
                "WORKFLOW_REWORK_REQUESTED",
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                command_id=command.command_id,
                step_key=target,
                payload={
                    "approval_request_id": approval.approval_request_id,
                    "target": target,
                    "reason": reason[:200],
                    "new_step_run_id": new_target.step_run_id,
                    "authorization_source": authorization.namespace.value,
                },
            )
            transition_stage(
                session,
                command.workflow_id,
                _stage_for_rework_target(target),
                target,
                "REWORK_STAGE_ENTERED",
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                command_id=command.command_id,
            )
            transition_workflow(
                session,
                command.workflow_id,
                WorkflowState.RUNNING,
                "WORKFLOW_REWORK_STARTED",
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                command_id=command.command_id,
                step_key=target,
            )

    def _cancel(self, command: WorkflowCommandRecord) -> None:
        authorization = self._authorize_actor(command.actor_id, PermissionKey.WORKFLOW_CANCEL)
        if "admin" not in authorization.workflow_roles:
            raise WorkflowError(
                WorkflowErrorCode.APPROVAL_UNAUTHORIZED,
                "only an admin can cancel a workflow",
            )
        with transaction(self.sessions) as session:
            workflow = session.get(WorkflowInstanceRecord, command.workflow_id)
            if workflow is None:
                raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow not found")
            if workflow.state in TERMINAL_WORKFLOW_STATES:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
                    "terminal workflow cannot be cancelled",
                )
            approval = active_approval(session, command.workflow_id, for_update=True)
            if approval is not None:
                approval.status = ApprovalState.CANCELLED.value
                approval.resolved_at = datetime.now(UTC)
                approval.resolved_actor_type = command.actor_type
                approval.resolved_actor_id = command.actor_id
                approval.decision = "CANCELLED"
            for step in list_step_runs(session, command.workflow_id):
                if step.state in {
                    StepState.PENDING.value,
                    StepState.READY.value,
                    StepState.RUNNING.value,
                    StepState.WAITING_FOR_HUMAN.value,
                }:
                    transition_step(step, StepState.CANCELLED)
            transition_stage(
                session,
                command.workflow_id,
                WorkflowStage.CANCELLED,
                workflow.current_step_key,
                "WORKFLOW_CANCEL_STAGE_ENTERED",
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                command_id=command.command_id,
            )
            transition_workflow(
                session,
                command.workflow_id,
                WorkflowState.CANCELLED,
                "WORKFLOW_CANCELLED",
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                command_id=command.command_id,
                step_key=workflow.current_step_key,
                payload={
                    "reason": str(command.payload.get("reason", ""))[:200],
                    "authorization_source": authorization.namespace.value,
                },
            )

    def _complete_terminal(
        self,
        workflow: WorkflowInstanceRecord,
        compiled: CompiledWorkflowDefinition,
        definition: TerminalStep,
        command_id: str | None,
        actor_type: str,
        actor_id: str,
    ) -> None:
        with transaction(self.sessions) as session:
            step = self._latest_active_step(session, workflow.workflow_id, definition.key)
            if step is None:
                step = create_step_run(
                    session,
                    workflow_id=workflow.workflow_id,
                    step_key=definition.key,
                    step_type=definition.type,
                    worker_role=None,
                    result_schema=None,
                    input_pointer_manifest={},
                    max_attempts=compiled.definition.limits.max_step_attempts,
                )
                transition_step(step, StepState.RUNNING)
                transition_step(step, StepState.SUCCEEDED)
            link_superseded_attempts(session, workflow.workflow_id)
            workflow_record = session.get(WorkflowInstanceRecord, workflow.workflow_id)
            if workflow_record is None:
                raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow disappeared")
            context = dict(workflow_record.runtime_context)
            pointers = [
                pointer.model_dump(mode="json")
                for pointer in self._upstream_pointers(
                    session, workflow.workflow_id, compiled, definition.key
                )
            ]
            context["final_pointer_manifest"] = {
                "workflow_id": workflow.workflow_id,
                "definition_hash": workflow.definition_hash,
                "artifact_pointers": pointers,
                "registration": (
                    pointers[-1]
                    if pointers and workflow.definition_key != "knowledge-analysis"
                    else None
                ),
                "analysis_proposal": (
                    pointers[-1]
                    if pointers and workflow.definition_key == "knowledge-analysis"
                    else None
                ),
                "item_registration": context.get("item_registration"),
                "content_pack": context.get("content_pack"),
            }
            workflow_record.runtime_context = context
            transition_stage(
                session,
                workflow.workflow_id,
                WorkflowStage.COMPLETED,
                definition.key,
                "TERMINAL_STAGE_ENTERED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=command_id,
            )
            transition_workflow(
                session,
                workflow.workflow_id,
                WorkflowState.COMPLETED,
                "WORKFLOW_COMPLETED",
                actor_type=actor_type,
                actor_id=actor_id,
                command_id=command_id,
                step_key=definition.key,
                payload={"pointer_count": len(pointers)},
            )

    def _validate_pending_approval(
        self,
        session: Session,
        command: WorkflowCommandRecord,
        actor_roles: frozenset[str],
    ) -> ApprovalRequestRecord:
        approval_id = command.payload.get("approval_request_id")
        expected_lock = command.payload.get("approval_lock_version")
        if not isinstance(approval_id, str) or not isinstance(expected_lock, int):
            raise WorkflowError(WorkflowErrorCode.APPROVAL_STALE, "approval snapshot is missing")
        approval = session.execute(
            select(ApprovalRequestRecord)
            .where(ApprovalRequestRecord.approval_request_id == approval_id)
            .with_for_update()
        ).scalar_one_or_none()
        if approval is None or approval.workflow_id != command.workflow_id:
            raise WorkflowError(WorkflowErrorCode.APPROVAL_NOT_FOUND, "approval does not exist")
        if approval.status != ApprovalState.PENDING.value:
            raise WorkflowError(
                WorkflowErrorCode.APPROVAL_ALREADY_RESOLVED,
                "approval was already resolved",
            )
        if approval.lock_version != expected_lock:
            raise WorkflowError(WorkflowErrorCode.APPROVAL_STALE, "approval snapshot is stale")
        if not actor_roles.intersection(approval.allowed_roles):
            raise WorkflowError(
                WorkflowErrorCode.APPROVAL_UNAUTHORIZED,
                "actor role cannot resolve this approval",
            )
        return approval

    def _authorize_actor(
        self, actor_id: str, required_permission: PermissionKey
    ) -> WorkflowActorAuthorization:
        decision = self.actor_authorizer.authorize(actor_id, required_permission)
        if decision.canonical_actor_id != actor_id:
            raise WorkflowError(
                WorkflowErrorCode.APPROVAL_UNAUTHORIZED,
                "actor authorization changed canonical identity",
            )
        if decision.authorized:
            return decision
        if decision.denial_reason is WorkflowActorDenialReason.IDENTITY_BACKEND_UNAVAILABLE:
            raise WorkflowError(
                WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE,
                "workflow actor authorization backend is unavailable",
            )
        reason = decision.denial_reason or WorkflowActorDenialReason.ACTOR_UNKNOWN
        raise WorkflowError(
            WorkflowErrorCode.APPROVAL_UNAUTHORIZED,
            f"workflow actor authorization denied: {reason.value}",
        )

    def _load_workflow(
        self, workflow_id: str
    ) -> tuple[WorkflowInstanceRecord, CompiledWorkflowDefinition]:
        with self.sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            if workflow is None:
                raise WorkflowError(WorkflowErrorCode.WORKFLOW_NOT_FOUND, "workflow not found")
            compiled = self._compiled_for_record(session, workflow)
            session.expunge(workflow)
            return workflow, compiled

    def _compiled_for_record(
        self, session: Session, workflow: WorkflowInstanceRecord
    ) -> CompiledWorkflowDefinition:
        definition = session.get(WorkflowDefinitionRecord, workflow.definition_id)
        if definition is None or definition.definition_hash != workflow.definition_hash:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                "workflow definition snapshot is unavailable",
            )
        try:
            return compile_definition_data(
                definition.canonical_definition,
                definition.source_path,
                set(self.available_roles),
            )
        except ValueError as exc:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID,
                "stored workflow definition is invalid",
            ) from exc

    def _upstream_pointers(
        self,
        session: Session,
        workflow_id: str,
        compiled: CompiledWorkflowDefinition,
        current_step_key: str,
    ) -> tuple[ArtifactPointer, ...]:
        order = [definition.key for definition in compiled.definition.steps]
        current_index = order.index(current_step_key)
        pointers: list[ArtifactPointer] = []
        for key in order[:current_index]:
            latest = self._latest_active_step(session, workflow_id, key)
            if latest is None or latest.state != StepState.SUCCEEDED.value:
                continue
            if latest.output_pointer_manifest:
                pointers.append(ArtifactPointer.model_validate(latest.output_pointer_manifest))
        return tuple(pointers)

    @staticmethod
    def _latest_active_step(
        session: Session, workflow_id: str, step_key: str
    ) -> WorkflowStepRunRecord | None:
        return session.scalar(
            select(WorkflowStepRunRecord)
            .where(
                WorkflowStepRunRecord.workflow_id == workflow_id,
                WorkflowStepRunRecord.step_key == step_key,
                WorkflowStepRunRecord.state != StepState.SUPERSEDED.value,
            )
            .order_by(WorkflowStepRunRecord.attempt.desc())
            .limit(1)
        )

    def _detached_step(self, step_run_id: str) -> WorkflowStepRunRecord:
        with self.sessions() as session:
            step = session.get(WorkflowStepRunRecord, step_run_id)
            if step is None:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_RECONCILIATION_FAILED,
                    "step run disappeared before execution",
                )
            session.expunge(step)
            return step

    def _renew_command_lease(self, command_id: str | None) -> None:
        if command_id is None:
            return
        with transaction(self.sessions) as session:
            command = session.execute(
                select(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.command_id == command_id)
                .with_for_update()
            ).scalar_one()
            if (
                command.state != CommandState.PROCESSING.value
                or command.lease_owner != self.runner_id
            ):
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                    "workflow command lease ownership was lost",
                )
            command.lease_expires_at = datetime.now(UTC) + timedelta(
                seconds=self.runner_config.command_lease_seconds
            )

    @staticmethod
    def _fail_workflow(
        session: Session,
        workflow_id: str,
        command_id: str | None,
        actor_type: str,
        actor_id: str,
        error_code: str,
    ) -> None:
        workflow = session.get(WorkflowInstanceRecord, workflow_id)
        if workflow is None or workflow.state in TERMINAL_WORKFLOW_STATES:
            return
        workflow.failure_code = error_code
        workflow.failure_summary = "workflow step failed"
        transition_stage(
            session,
            workflow_id,
            WorkflowStage.FAILED,
            workflow.current_step_key,
            "WORKFLOW_FAILURE_STAGE_ENTERED",
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=command_id,
            payload={"error_code": error_code},
        )
        transition_workflow(
            session,
            workflow_id,
            WorkflowState.FAILED,
            "WORKFLOW_FAILED",
            actor_type=actor_type,
            actor_id=actor_id,
            command_id=command_id,
            step_key=workflow.current_step_key,
            payload={"error_code": error_code},
        )


def _step_job_idempotency_key(
    workflow_id: str, step_key: str, attempt: int, definition_hash: str
) -> str:
    digest = content_sha256(
        {
            "workflow_id": workflow_id,
            "step_key": step_key,
            "attempt": attempt,
            "definition_hash": definition_hash,
        }
    ).removeprefix("sha256:")
    return f"wfstep-{digest}"


def _stage_for_rework_target(target: str) -> WorkflowStage:
    return {
        "authoring": WorkflowStage.AUTHORING,
        "image": WorkflowStage.IMAGE_REQUIRED,
        "review": WorkflowStage.REVIEWING,
    }[target]


def _capacity_resume_target(
    worker_role: str,
    definition_key: str,
) -> tuple[WorkflowState, WorkflowStage]:
    if worker_role == "authoring":
        return WorkflowState.RUNNING, WorkflowStage.AUTHORING
    if worker_role == "image":
        return WorkflowState.RUNNING, WorkflowStage.IMAGE_REQUIRED
    if worker_role == "review":
        return WorkflowState.RUNNING, WorkflowStage.REVIEWING
    if worker_role == "item_management":
        return WorkflowState.REGISTERING, WorkflowStage.REGISTERING
    if worker_role == "support" and definition_key in {
        "knowledge-analysis",
        "legacy-item-extraction",
        "legacy-item-editorial-compatibility",
    }:
        return WorkflowState.RUNNING, WorkflowStage.KNOWLEDGE_ANALYSIS
    raise WorkflowError(
        WorkflowErrorCode.WORKFLOW_INVALID_TRANSITION,
        "failed workflow role has no capacity reconciliation target",
    )
