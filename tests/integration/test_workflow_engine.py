from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
)
from eom_orchestrator.database import transaction
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
    upsert_worker_slot,
)
from eom_orchestrator.state_machine import JobState, transition_job
from eom_workflow import ArtifactPointer, WorkerRequest, WorkflowRequest, compile_definition
from eom_workflow.compiler import compile_definition_data
from eom_workflow.identifiers import new_approval_request_id, new_step_run_id
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.catalog_port import PreparedPrompt, RegistrationOutcome
from eom_workflow_runner.engine import RoleExecutionResult, WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
    WorkflowRuntimeNotReady,
)
from eom_workflow_runner.repository import (
    CommandType,
    active_approval,
    claim_next_command,
    create_approval_request,
    create_step_run,
    create_workflow_instance,
    enqueue_command,
    import_workflow_definition,
    list_step_runs,
    list_workflow_events,
)
from eom_workflow_runner.settings import WorkflowSettings
from eom_workflow_runner.state_machine import (
    CommandState,
    StepState,
    WorkflowState,
    transition_command,
    transition_step,
    transition_workflow,
)
from sqlalchemy import Engine, delete, select
from sqlalchemy.engine import Connection, RootTransaction
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration

ROLE_SLOTS = {
    "authoring": ("01", "eom-cdx-01"),
    "review": ("02", "eom-cdx-02"),
    "image": ("03", "eom-cdx-03"),
    "item_management": ("04", "eom-cdx-04"),
}


class ReadyWorkflowRuntime:
    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(())


class UnreadyWorkflowRuntime:
    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    name="catalog_staging",
                    status=ReadinessStatus.FAIL,
                    code="CATALOG_STAGING_UNWRITABLE",
                    detail="permission denied",
                ),
            )
        )


class FakeRoleExecutor:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions
        self.calls: list[tuple[str, int, str]] = []
        self.worker_requests: list[dict[str, object]] = []
        self.prompts: list[str | None] = []

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkerRequest,
        upstream: tuple[ArtifactPointer, ...],
        idempotency_key: str,
        prompt_text: str | None,
    ) -> RoleExecutionResult:
        del upstream
        assert step.worker_role is not None
        self.calls.append((step.step_key, step.attempt, step.worker_role))
        self.worker_requests.append(request.model_dump(mode="json"))
        self.prompts.append(prompt_text)
        with transaction(self.sessions) as session:
            existing = session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == idempotency_key)
            )
            if existing is not None:
                revision = session.get(ArtifactRevisionRecord, existing.revision_id)
                assert revision is not None
                return _execution(existing, revision.content_hash)

            job_id = new_job_id()
            logical_artifact_id = new_logical_artifact_id()
            revision_id = new_revision_id()
            slot_id, linux_user = ROLE_SLOTS[step.worker_role]
            ensure_protocol_version(session, "workflow-role/1.0.1", role_schema_bundle_hash())
            upsert_worker_slot(
                session,
                slot_id=slot_id,
                linux_user=linux_user,
                role=step.worker_role,
                enabled=True,
                gpu=step.worker_role == "image",
            )
            request_document = {
                "workflow_id": workflow.workflow_id,
                "step_run_id": step.step_run_id,
                "attempt": step.attempt,
                "role": step.worker_role,
            }
            job, created = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version="workflow-role/1.0.1",
                idempotency_key=idempotency_key,
                task_type=f"workflow_{step.worker_role}",
                request=request_document,
                logical_artifact_id=logical_artifact_id,
                revision_id=revision_id,
            )
            assert created
            for target, event in (
                (JobState.VALIDATED, "REQUEST_VALIDATED"),
                (JobState.QUEUED, "JOB_QUEUED"),
            ):
                transition_job(session, job.job_id, target, event)
            job.worker_slot_id = slot_id
            transition_job(session, job.job_id, JobState.CLAIMED, "WORKER_CLAIMED")
            transition_job(session, job.job_id, JobState.RUNNING, "WORKER_STARTED")
            transition_job(
                session, job.job_id, JobState.VALIDATING_RESULT, "WORKER_RESULT_RECEIVED"
            )
            transition_job(session, job.job_id, JobState.COMMITTING, "ARTIFACT_COMMIT_STARTED")
            result = {
                "status": "ok",
                "role": step.worker_role,
                "placeholder": "PLACEHOLDER_CONTENT",
            }
            content_hash = content_sha256(result)
            create_artifact_records(
                session,
                job=job,
                content_hash=content_hash,
                manifest_hash=content_sha256({"content_hash": content_hash}),
                content_bytes=1,
                nas_path=f"/tmp/{logical_artifact_id}/{revision_id}",
                manifest={"content_hash": content_hash},
                result=result,
            )
            transition_job(session, job.job_id, JobState.SUCCEEDED, "ARTIFACT_COMMITTED")
            return _execution(job, content_hash)


class FakeWorkflowCatalog:
    def __init__(self) -> None:
        self.prepared: list[tuple[str, int]] = []
        self.registrations: list[tuple[str, int]] = []

    def prepare_prompt(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        upstream: tuple[ArtifactPointer, ...],
    ) -> PreparedPrompt:
        del workflow, request, upstream
        self.prepared.append((step.step_key, step.attempt))
        suffix = {
            "authoring": "1",
            "review": "2",
            "registration": "3",
        }[step.step_key]
        return PreparedPrompt(
            text=f"PLACEHOLDER PROMPT {step.step_key}",
            pointer={
                "artifact_id": f"artifact_{suffix * 32}",
                "artifact_revision_id": f"rev_{suffix * 32}",
                "sha256": "sha256:" + suffix * 64,
                "manifest_sha256": "sha256:" + suffix * 64,
                "schema_ref": "eom://schemas/content-pack/prompt-envelope-v1",
            },
            envelope={
                "schema_version": "1.0",
                "step_run_id": step.step_run_id,
            },
        )

    def register_workflow(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> RegistrationOutcome:
        del workflow, request, artifacts
        self.registrations.append((step.step_key, step.attempt))
        return RegistrationOutcome(
            item_id="item_" + "4" * 32,
            item_revision_id="itemrev_" + "5" * 32,
            revision_number=1,
            manifest_artifact_id="artifact_" + "6" * 32,
            manifest_artifact_revision_id="rev_" + "7" * 32,
            manifest_sha256="sha256:" + "8" * 64,
        )


class FailedRoleExecutor:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkerRequest,
        upstream: tuple[ArtifactPointer, ...],
        idempotency_key: str,
        prompt_text: str | None,
    ) -> RoleExecutionResult:
        del request, upstream, prompt_text
        job_id = new_job_id()
        logical_artifact_id = new_logical_artifact_id()
        revision_id = new_revision_id()
        with transaction(self.sessions) as session:
            ensure_protocol_version(session, "workflow-role/1.0.1", role_schema_bundle_hash())
            job, created = submit_structured_job(
                session,
                job_id=job_id,
                protocol_version="workflow-role/1.0.1",
                idempotency_key=idempotency_key,
                task_type=f"workflow_{step.worker_role}",
                request={
                    "workflow_id": workflow.workflow_id,
                    "step_run_id": step.step_run_id,
                    "role": step.worker_role,
                    "attempt": step.attempt,
                },
                logical_artifact_id=logical_artifact_id,
                revision_id=revision_id,
            )
            assert created
            job.error_code = "WORKER_EXEC_FAILED"
            transition_job(session, job.job_id, JobState.FAILED, "JOB_FAILED")
        return RoleExecutionResult(
            job_id=job_id,
            status="FAILED",
            worker_slot="01",
            logical_artifact_id=logical_artifact_id,
            revision_id=revision_id,
            content_hash=None,
            error_code="WORKER_EXEC_FAILED",
        )


class RaisingRoleExecutor:
    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkerRequest,
        upstream: tuple[ArtifactPointer, ...],
        idempotency_key: str,
        prompt_text: str | None,
    ) -> RoleExecutionResult:
        del workflow, step, request, upstream, idempotency_key, prompt_text
        raise OSError("untrusted adapter detail")


def _execution(job: JobRecord, content_hash: str) -> RoleExecutionResult:
    return RoleExecutionResult(
        job_id=job.job_id,
        status=job.status,
        worker_slot=job.worker_slot_id,
        logical_artifact_id=job.logical_artifact_id,
        revision_id=job.revision_id,
        content_hash=content_hash,
        error_code=job.error_code,
    )


def _environment(
    engine: Engine, image_mode: str, idempotency_key: str
) -> tuple[
    WorkflowRunner,
    FakeRoleExecutor,
    sessionmaker[Session],
    str,
    tuple[Connection, RootTransaction],
]:
    connection = engine.connect()
    outer = connection.begin()
    sessions = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    compiled = compile_definition(
        Path("config/workflows/generic-item-development.v1.yaml"), set(ROLE_SLOTS) | {"support"}
    )
    with transaction(sessions) as session:
        definition, _ = import_workflow_definition(session, compiled)
        workflow, created = create_workflow_instance(
            session,
            definition=definition,
            request=WorkflowRequest(
                request_name="PLACEHOLDER_REQUEST",
                image_mode=image_mode,  # type: ignore[arg-type]
            ),
            idempotency_key=idempotency_key,
            actor_type="human",
            actor_id="requester_01",
        )
        assert created
        enqueue_command(
            session,
            workflow_id=workflow.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type="human",
            actor_id="requester_01",
            source="test",
            idempotency_key=f"start:{workflow.workflow_id}",
        )
        workflow_id = workflow.workflow_id
    fake = FakeRoleExecutor(sessions)
    runner = WorkflowRunner(
        engine,
        WorkflowSettings(),
        fake,
        catalog=FakeWorkflowCatalog(),
        readiness=ReadyWorkflowRuntime(),
        available_roles=frozenset(ROLE_SLOTS) | {"support"},
        runner_id="test-runner",
    )
    runner.sessions = sessions
    return runner, fake, sessions, workflow_id, (connection, outer)


def _close(resources: tuple[Connection, RootTransaction]) -> None:
    connection, outer = resources
    outer.rollback()
    connection.close()


def _enqueue_approval(
    sessions: sessionmaker[Session],
    workflow_id: str,
    command_type: CommandType,
    idempotency_key: str,
    payload: dict[str, object] | None = None,
) -> str:
    with transaction(sessions) as session:
        approval = active_approval(session, workflow_id)
        assert approval is not None
        normalized = {
            "approval_request_id": approval.approval_request_id,
            "approval_lock_version": approval.lock_version,
            **(payload or {}),
        }
        command, _ = enqueue_command(
            session,
            workflow_id=workflow_id,
            command_type=command_type,
            payload=normalized,
            actor_type="human",
            actor_id="reviewer_01",
            source="test",
            idempotency_key=idempotency_key,
        )
        return command.command_id


def test_image_skip_approval_and_registration_flow(integration_engine: Engine) -> None:
    runner, executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-skip"
    )
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            assert workflow.state == WorkflowState.AWAITING_HUMAN_APPROVAL.value
            steps = list_step_runs(session, workflow_id)
            image = next(step for step in steps if step.step_key == "image")
            assert image.state == StepState.SKIPPED.value
            assert [role for _, _, role in executor.calls] == ["authoring", "review"]
        command_id = _enqueue_approval(
            sessions,
            workflow_id,
            CommandType.APPROVE_WORKFLOW,
            "approve-workflow-integration-skip",
        )
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            command = session.get(WorkflowCommandRecord, command_id)
            assert workflow is not None and command is not None
            assert workflow.state == WorkflowState.COMPLETED.value
            assert command.state == CommandState.SUCCEEDED.value
            assert [role for _, _, role in executor.calls] == [
                "authoring",
                "review",
                "item_management",
            ]
            final = workflow.runtime_context["final_pointer_manifest"]
            assert final["registration"]["step_key"] == "registration"
            sequences = [event.sequence for event in list_workflow_events(session, workflow_id)]
            assert sequences == list(range(1, len(sequences) + 1))
    finally:
        _close(resources)


def test_runtime_preflight_failure_does_not_claim_or_fail_workflow(
    integration_engine: Engine,
) -> None:
    runner, _, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-preflight-unready"
    )
    runner.readiness = UnreadyWorkflowRuntime()
    try:
        with pytest.raises(WorkflowRuntimeNotReady) as captured:
            runner.run_once(workflow_id)
        assert captured.value.report.failed_codes == ("CATALOG_STAGING_UNWRITABLE",)

        with sessions() as session:
            command = session.scalar(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == workflow_id
                )
            )
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert command is not None and workflow is not None
            assert command.state == CommandState.PENDING.value
            assert command.attempts == 0
            assert command.lease_owner is None
            assert command.lease_expires_at is None
            assert workflow.state == WorkflowState.REQUESTED.value
            assert len(list_workflow_events(session, workflow_id)) == 1
    finally:
        _close(resources)


def test_catalog_workflow_pins_prompts_and_registration_without_leaking_request(
    integration_engine: Engine,
) -> None:
    connection = integration_engine.connect()
    outer = connection.begin()
    sessions = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    compiled = compile_definition(
        Path("config/workflows/generic-item-development.v1.1.yaml"),
        set(ROLE_SLOTS) | {"support"},
    )
    request = WorkflowRequest.model_validate(
        {
            "request_name": "PLACEHOLDER_REQUEST",
            "image_mode": "skip",
            "content_pack": {
                "pack_key": "generic-placeholder",
                "environment": "development",
            },
            "profiles": {
                "authoring": "authoring-default",
                "review": "review-default",
                "image": "image-placeholder",
                "registration": "registration-default",
            },
            "source_intake": {"batch_ids": ["intake_" + "a" * 32]},
            "registry_intent": {"mode": "CREATE_ITEM"},
        }
    )
    runtime_context = {
        "content_pack": {
            "release_id": "packrel_" + "b" * 32,
            "pack_key": "generic-placeholder",
            "version": "0.1.0",
            "release_sha256": "sha256:" + "c" * 64,
            "manifest_sha256": "sha256:" + "d" * 64,
        },
        "profiles": request.profiles.model_dump(mode="json") if request.profiles else {},
        "source_intake": request.source_intake.model_dump(mode="json")
        if request.source_intake
        else {},
        "registry_intent": request.registry_intent.model_dump(mode="json")
        if request.registry_intent
        else {},
        "prompt_artifacts": [],
    }
    try:
        with transaction(sessions) as session:
            definition, _ = import_workflow_definition(session, compiled)
            workflow, created = create_workflow_instance(
                session,
                definition=definition,
                request=request,
                idempotency_key="workflow-catalog-pinning",
                actor_type="human",
                actor_id="requester_01",
                runtime_context=runtime_context,
            )
            assert created
            enqueue_command(
                session,
                workflow_id=workflow.workflow_id,
                command_type=CommandType.START_WORKFLOW,
                payload={},
                actor_type="human",
                actor_id="requester_01",
                source="test",
                idempotency_key=f"start:{workflow.workflow_id}",
            )
            workflow_id = workflow.workflow_id

        executor = FakeRoleExecutor(sessions)
        catalog = FakeWorkflowCatalog()
        runner = WorkflowRunner(
            integration_engine,
            WorkflowSettings(),
            executor,
            catalog=catalog,
            readiness=ReadyWorkflowRuntime(),
            available_roles=frozenset(ROLE_SLOTS) | {"support"},
            runner_id="catalog-test-runner",
        )
        runner.sessions = sessions
        runner.run_until_idle(workflow_id)
        _enqueue_approval(
            sessions,
            workflow_id,
            CommandType.APPROVE_WORKFLOW,
            "approve-workflow-catalog",
        )
        runner.run_until_idle(workflow_id)

        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            assert workflow.state == WorkflowState.COMPLETED.value
            assert workflow.runtime_context["content_pack"] == runtime_context["content_pack"]
            prompt_step_keys = [
                entry["step_key"] for entry in workflow.runtime_context["prompt_artifacts"]
            ]
            assert prompt_step_keys == [
                "authoring",
                "review",
                "registration",
            ]
            assert workflow.runtime_context["item_registration"] == {
                "item_id": "item_" + "4" * 32,
                "item_revision_id": "itemrev_" + "5" * 32,
                "revision_number": 1,
                "manifest_artifact_id": "artifact_" + "6" * 32,
                "manifest_artifact_revision_id": "rev_" + "7" * 32,
                "manifest_sha256": "sha256:" + "8" * 64,
            }
        assert catalog.prepared == [("authoring", 1), ("review", 1), ("registration", 1)]
        assert catalog.registrations == [("registration", 1)]
        assert all(prompt is not None for prompt in executor.prompts)
        assert (
            executor.worker_requests
            == [{"request_name": "PLACEHOLDER_REQUEST", "image_mode": "skip"}] * 3
        )

        runner.reconcile(workflow_id)
        assert catalog.registrations == [("registration", 1)]
    finally:
        outer.rollback()
        connection.close()


def test_image_required_rework_preserves_attempt_history(integration_engine: Engine) -> None:
    runner, executor, sessions, workflow_id, resources = _environment(
        integration_engine, "required", "workflow-integration-rework"
    )
    try:
        runner.run_until_idle(workflow_id)
        _enqueue_approval(
            sessions,
            workflow_id,
            CommandType.REQUEST_REWORK,
            "rework-workflow-integration",
            {"target": "authoring", "reason": "PLACEHOLDER_REWORK_REASON"},
        )
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            assert workflow.state == WorkflowState.AWAITING_HUMAN_APPROVAL.value
            counts = Counter(role for _, _, role in executor.calls)
            assert counts == {"authoring": 2, "image": 2, "review": 2}
            authoring = [
                step
                for step in list_step_runs(session, workflow_id)
                if step.step_key == "authoring"
            ]
            assert [step.attempt for step in authoring] == [1, 2]
            assert authoring[0].state == StepState.SUPERSEDED.value
            assert authoring[0].output_pointer_manifest is not None
            assert authoring[0].superseded_by_step_run_id == authoring[1].step_run_id
            assert authoring[1].state == StepState.SUCCEEDED.value
        _enqueue_approval(
            sessions,
            workflow_id,
            CommandType.APPROVE_WORKFLOW,
            "approve-workflow-integration-rework",
        )
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            assert workflow.state == WorkflowState.COMPLETED.value
            assert workflow.rework_cycle_count == 1
            assert executor.calls[-1][2] == "item_management"
            for key in ("authoring", "image", "review"):
                runs = [
                    step for step in list_step_runs(session, workflow_id) if step.step_key == key
                ]
                assert runs[0].superseded_by_step_run_id == runs[1].step_run_id
            final = workflow.runtime_context["final_pointer_manifest"]
            assert [pointer["attempt"] for pointer in final["artifact_pointers"]] == [
                2,
                2,
                2,
                1,
            ]
            assert [pointer["step_key"] for pointer in final["artifact_pointers"]] == [
                "authoring",
                "image",
                "review",
                "registration",
            ]
    finally:
        _close(resources)


def test_failed_platform_job_is_persisted_as_terminal_workflow_failure(
    integration_engine: Engine,
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-failure"
    )
    runner.executor = FailedRoleExecutor(sessions)
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            command = session.scalar(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == workflow_id
                )
            )
            authoring = session.scalar(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == workflow_id,
                    WorkflowStepRunRecord.step_key == "authoring",
                )
            )
            assert workflow is not None and command is not None and authoring is not None
            assert workflow.state == WorkflowState.FAILED.value
            assert workflow.failure_code == "WORKER_EXEC_FAILED"
            assert authoring.state == StepState.FAILED.value
            assert authoring.error_code == "WORKER_EXEC_FAILED"
            assert command.state == CommandState.FAILED.value
            assert command.error_code == WorkflowErrorCode.WORKFLOW_STEP_FAILED.value
    finally:
        _close(resources)


def test_platform_adapter_exception_is_sanitized_as_terminal_failure(
    integration_engine: Engine,
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-adapter-exception"
    )
    runner.executor = RaisingRoleExecutor()
    try:
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            authoring = session.scalar(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == workflow_id,
                    WorkflowStepRunRecord.step_key == "authoring",
                )
            )
            assert workflow is not None and authoring is not None
            assert workflow.state == WorkflowState.FAILED.value
            assert workflow.failure_code == WorkflowErrorCode.WORKFLOW_STEP_FAILED.value
            assert authoring.state == StepState.FAILED.value
            assert authoring.error_summary == "platform role execution raised an exception"
            assert "untrusted" not in authoring.error_summary
    finally:
        _close(resources)


def test_approval_race_only_resolves_once(integration_engine: Engine) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-race"
    )
    try:
        runner.run_until_idle(workflow_id)
        approve_id = _enqueue_approval(
            sessions, workflow_id, CommandType.APPROVE_WORKFLOW, "race-approve"
        )
        rework_id = _enqueue_approval(
            sessions,
            workflow_id,
            CommandType.REQUEST_REWORK,
            "race-rework",
            {"target": "authoring", "reason": "PLACEHOLDER_REWORK_REASON"},
        )
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            states = {
                command_id: session.get(WorkflowCommandRecord, command_id).state  # type: ignore[union-attr]
                for command_id in (approve_id, rework_id)
            }
            assert Counter(states.values()) == {"SUCCEEDED": 1, "FAILED": 1}
            failed = next(
                session.get(WorkflowCommandRecord, command_id)
                for command_id, state in states.items()
                if state == "FAILED"
            )
            assert failed is not None
            assert failed.error_code == WorkflowErrorCode.APPROVAL_ALREADY_RESOLVED.value
    finally:
        _close(resources)


def test_command_idempotency_lease_recovery_and_optimistic_lock(
    integration_engine: Engine,
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-command"
    )
    try:
        runner.run_until_idle(workflow_id)
        with transaction(sessions) as session:
            first, created = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.RECONCILE_WORKFLOW,
                payload={},
                actor_type="system",
                actor_id="test",
                source="test",
                idempotency_key="workflow-command-idempotency",
            )
            duplicate, duplicate_created = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.RECONCILE_WORKFLOW,
                payload={},
                actor_type="system",
                actor_id="test",
                source="test",
                idempotency_key="workflow-command-idempotency",
            )
            assert created and not duplicate_created
            assert first.command_id == duplicate.command_id
            first.state = CommandState.LEASED.value
            first.lease_owner = "dead-runner"
            first.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        with transaction(sessions) as session:
            recovered = claim_next_command(
                session,
                runner_id="recovery-runner",
                lease_seconds=60,
                workflow_id=workflow_id,
            )
            assert recovered is not None
            assert recovered.command_id == first.command_id
            assert recovered.lease_owner == "recovery-runner"
            assert recovered.attempts == 1
        with transaction(sessions) as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            with pytest.raises(WorkflowError) as error:
                transition_workflow(
                    session,
                    workflow_id,
                    WorkflowState.RUNNING,
                    "INVALID_OPTIMISTIC_TRANSITION",
                    actor_type="system",
                    actor_id="test",
                    command_id=None,
                    expected_lock_version=workflow.lock_version + 1,
                )
            assert error.value.code == WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT
    finally:
        _close(resources)


def test_runner_refuses_a_command_lease_owned_by_another_runner(
    integration_engine: Engine,
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-lease-owner"
    )
    try:
        with transaction(sessions) as session:
            command = session.scalar(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == workflow_id
                )
            )
            assert command is not None
            transition_command(command, CommandState.LEASED)
            transition_command(command, CommandState.PROCESSING)
            command.lease_owner = "another-runner"
            command_id = command.command_id
        with pytest.raises(WorkflowError) as error:
            runner._renew_command_lease(command_id)
        assert error.value.code == WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT
        with sessions() as session:
            command = session.get(WorkflowCommandRecord, command_id)
            assert command is not None
            assert command.state == CommandState.PROCESSING.value
            assert command.lease_owner == "another-runner"
    finally:
        _close(resources)


def test_rework_limit_leaves_workflow_at_admin_decision_gate(integration_engine: Engine) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-rework-limit"
    )
    try:
        runner.run_until_idle(workflow_id)
        with transaction(sessions) as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            workflow.rework_cycle_count = 3
        command_id = _enqueue_approval(
            sessions,
            workflow_id,
            CommandType.REQUEST_REWORK,
            "workflow-rework-limit-command",
            {"target": "authoring", "reason": "PLACEHOLDER_REWORK_REASON"},
        )
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            command = session.get(WorkflowCommandRecord, command_id)
            assert workflow is not None and command is not None
            assert workflow.state == WorkflowState.AWAITING_HUMAN_APPROVAL.value
            assert active_approval(session, workflow_id) is not None
            assert command.state == CommandState.FAILED.value
            assert command.error_code == WorkflowErrorCode.WORKFLOW_REWORK_LIMIT_EXCEEDED.value
    finally:
        _close(resources)


def test_database_uniqueness_definition_conflict_and_two_session_claim(
    integration_engine: Engine,
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-constraints"
    )
    try:
        runner.run_until_idle(workflow_id)
        with transaction(sessions) as session:
            authoring = session.scalar(
                select(WorkflowStepRunRecord).where(
                    WorkflowStepRunRecord.workflow_id == workflow_id,
                    WorkflowStepRunRecord.step_key == "authoring",
                )
            )
            assert authoring is not None
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(
                    WorkflowStepRunRecord(
                        step_run_id=new_step_run_id(),
                        workflow_id=workflow_id,
                        step_key="authoring",
                        attempt=authoring.attempt,
                        step_type="agent",
                        worker_role="authoring",
                        result_schema="authoring-result@1.0",
                        state=StepState.READY.value,
                        input_pointer_manifest={},
                    )
                )
                session.flush()

            extra_gate = WorkflowStepRunRecord(
                step_run_id=new_step_run_id(),
                workflow_id=workflow_id,
                step_key="human_approval",
                attempt=2,
                step_type="human_gate",
                worker_role=None,
                result_schema=None,
                state=StepState.WAITING_FOR_HUMAN.value,
                input_pointer_manifest={},
            )
            session.add(extra_gate)
            session.flush()
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(
                    ApprovalRequestRecord(
                        approval_request_id=new_approval_request_id(),
                        workflow_id=workflow_id,
                        step_run_id=extra_gate.step_run_id,
                        status="PENDING",
                        lock_version=1,
                        allowed_roles=["reviewer"],
                        allowed_rework_targets=["authoring"],
                    )
                )
                session.flush()

            definition = session.scalar(select(WorkflowDefinitionRecord))
            assert definition is not None
            with pytest.raises(DBAPIError, match="immutable"), session.begin_nested():
                definition.source_path = "/tmp/changed-definition.yaml"
                session.flush()
            session.refresh(definition)
            duplicate, created = create_workflow_instance(
                session,
                definition=definition,
                request=WorkflowRequest(
                    request_name="PLACEHOLDER_REQUEST",
                    image_mode="skip",
                ),
                idempotency_key="workflow-integration-constraints",
                actor_type="human",
                actor_id="requester_01",
            )
            assert not created
            assert duplicate.workflow_id == workflow_id
            changed = dict(definition.canonical_definition)
            changed["limits"] = {"max_rework_cycles": 2, "max_step_attempts": 4}
            conflicting = compile_definition_data(
                changed, definition.source_path, set(ROLE_SLOTS) | {"support"}
            )
            with pytest.raises(WorkflowError) as conflict:
                import_workflow_definition(session, conflicting)
            assert conflict.value.code == WorkflowErrorCode.WORKFLOW_DEFINITION_CONFLICT

            for number in range(2):
                enqueue_command(
                    session,
                    workflow_id=workflow_id,
                    command_type=CommandType.RECONCILE_WORKFLOW,
                    payload={"number": number},
                    actor_type="system",
                    actor_id="test",
                    source="test",
                    idempotency_key=f"two-session-claim-{number}",
                )
        first_session = sessions()
        second_session = sessions()
        try:
            with first_session.begin():
                first = claim_next_command(
                    first_session,
                    runner_id="runner-one",
                    lease_seconds=60,
                    workflow_id=workflow_id,
                )
                assert first is not None
                first_id = first.command_id
            with second_session.begin():
                second = claim_next_command(
                    second_session,
                    runner_id="runner-two",
                    lease_seconds=60,
                    workflow_id=workflow_id,
                )
                assert second is not None
                assert second.command_id != first_id
        finally:
            first_session.close()
            second_session.close()
    finally:
        _close(resources)


def test_invalid_target_stale_snapshot_and_unauthorized_actor_are_rejected(
    integration_engine: Engine,
) -> None:
    runner, _executor, sessions, workflow_id, resources = _environment(
        integration_engine, "skip", "workflow-integration-approval-errors"
    )
    try:
        runner.run_until_idle(workflow_id)
        with transaction(sessions) as session:
            approval = active_approval(session, workflow_id)
            assert approval is not None
            base_payload = {
                "approval_request_id": approval.approval_request_id,
                "approval_lock_version": approval.lock_version,
            }
            invalid, _ = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.REQUEST_REWORK,
                payload={
                    **base_payload,
                    "target": "registration",
                    "reason": "PLACEHOLDER_REWORK_REASON",
                },
                actor_type="human",
                actor_id="reviewer_01",
                source="test",
                idempotency_key="approval-invalid-target",
            )
            unauthorized, _ = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.APPROVE_WORKFLOW,
                payload=base_payload,
                actor_type="human",
                actor_id="requester_01",
                source="test",
                idempotency_key="approval-unauthorized",
            )
            stale, _ = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.APPROVE_WORKFLOW,
                payload={**base_payload, "approval_lock_version": approval.lock_version + 1},
                actor_type="human",
                actor_id="reviewer_01",
                source="test",
                idempotency_key="approval-stale",
            )
            command_ids = (invalid.command_id, unauthorized.command_id, stale.command_id)
        runner.run_until_idle(workflow_id)
        with sessions() as session:
            errors = {
                session.get(WorkflowCommandRecord, command_id).error_code  # type: ignore[union-attr]
                for command_id in command_ids
            }
            assert errors == {
                WorkflowErrorCode.APPROVAL_INVALID_REWORK_TARGET.value,
                WorkflowErrorCode.APPROVAL_UNAUTHORIZED.value,
                WorkflowErrorCode.APPROVAL_STALE.value,
            }
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None
            assert workflow.state == WorkflowState.AWAITING_HUMAN_APPROVAL.value
            assert active_approval(session, workflow_id) is not None
    finally:
        _close(resources)


def test_postgresql_skip_locked_claim_uses_two_connections(integration_engine: Engine) -> None:
    sessions = sessionmaker(bind=integration_engine, expire_on_commit=False)
    key = f"workflow-two-connection-{uuid4().hex}"
    workflow_id = ""
    try:
        compiled = compile_definition(
            Path("config/workflows/generic-item-development.v1.yaml"),
            set(ROLE_SLOTS) | {"support"},
        )
        with transaction(sessions) as session:
            definition, _ = import_workflow_definition(session, compiled)
            workflow, _ = create_workflow_instance(
                session,
                definition=definition,
                request=WorkflowRequest(
                    request_name="PLACEHOLDER_REQUEST",
                    image_mode="skip",
                ),
                idempotency_key=key,
                actor_type="human",
                actor_id="requester_01",
            )
            workflow_id = workflow.workflow_id
            for number in range(2):
                enqueue_command(
                    session,
                    workflow_id=workflow_id,
                    command_type=CommandType.RECONCILE_WORKFLOW,
                    payload={"number": number},
                    actor_type="system",
                    actor_id="test",
                    source="test",
                    idempotency_key=f"{key}-command-{number}",
                )

        first_session = sessions()
        second_session = sessions()
        first_transaction = first_session.begin()
        second_transaction = second_session.begin()
        try:
            first = claim_next_command(
                first_session,
                runner_id="runner-one",
                lease_seconds=60,
                workflow_id=workflow_id,
            )
            second = claim_next_command(
                second_session,
                runner_id="runner-two",
                lease_seconds=60,
                workflow_id=workflow_id,
            )
            assert first is not None and second is not None
            assert first.command_id != second.command_id
        finally:
            second_transaction.rollback()
            first_transaction.rollback()
            second_session.close()
            first_session.close()
    finally:
        if workflow_id:
            with integration_engine.begin() as connection:
                connection.execute(
                    delete(WorkflowInstanceRecord).where(
                        WorkflowInstanceRecord.workflow_id == workflow_id
                    )
                )


def test_simultaneous_approve_and_rework_resolves_one_decision(
    integration_engine: Engine,
) -> None:
    sessions = sessionmaker(bind=integration_engine, expire_on_commit=False)
    key = f"workflow-approval-race-{uuid4().hex}"
    workflow_id = ""
    try:
        compiled = compile_definition(
            Path("config/workflows/generic-item-development.v1.yaml"),
            set(ROLE_SLOTS) | {"support"},
        )
        with transaction(sessions) as session:
            definition, _ = import_workflow_definition(session, compiled)
            workflow, _ = create_workflow_instance(
                session,
                definition=definition,
                request=WorkflowRequest(
                    request_name="PLACEHOLDER_REQUEST",
                    image_mode="skip",
                ),
                idempotency_key=key,
                actor_type="human",
                actor_id="requester_01",
            )
            workflow_id = workflow.workflow_id
            workflow.state = WorkflowState.AWAITING_HUMAN_APPROVAL.value
            workflow.stage = "AWAITING_HUMAN_APPROVAL"
            workflow.current_step_key = "human_approval"
            gate = create_step_run(
                session,
                workflow_id=workflow_id,
                step_key="human_approval",
                step_type="human_gate",
                worker_role=None,
                result_schema=None,
                input_pointer_manifest={},
                max_attempts=4,
            )
            transition_step(gate, StepState.WAITING_FOR_HUMAN)
            approval = create_approval_request(
                session,
                workflow_id=workflow_id,
                step_run_id=gate.step_run_id,
                allowed_roles=("reviewer", "admin"),
                allowed_rework_targets=("authoring", "image", "review"),
            )
            base_payload = {
                "approval_request_id": approval.approval_request_id,
                "approval_lock_version": approval.lock_version,
            }
            approve, _ = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.APPROVE_WORKFLOW,
                payload=base_payload,
                actor_type="human",
                actor_id="reviewer_01",
                source="test",
                idempotency_key=f"{key}-approve",
            )
            rework, _ = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=CommandType.REQUEST_REWORK,
                payload={
                    **base_payload,
                    "target": "authoring",
                    "reason": "PLACEHOLDER_REWORK_REASON",
                },
                actor_type="human",
                actor_id="reviewer_01",
                source="test",
                idempotency_key=f"{key}-rework",
            )
            command_ids = (approve.command_id, rework.command_id)

        barrier = Barrier(2)

        def resolve(command_id: str, command_type: CommandType) -> str:
            runner = WorkflowRunner(
                integration_engine,
                WorkflowSettings(),
                FakeRoleExecutor(sessions),
                catalog=FakeWorkflowCatalog(),
                readiness=ReadyWorkflowRuntime(),
                available_roles=frozenset(ROLE_SLOTS) | {"support"},
                runner_id=f"race-{command_type.value}",
            )
            with sessions() as session:
                command = session.get(WorkflowCommandRecord, command_id)
                assert command is not None
                session.expunge(command)
            barrier.wait()
            try:
                if command_type == CommandType.APPROVE_WORKFLOW:
                    runner._approve(command)
                else:
                    runner._request_rework(command)
            except WorkflowError as exc:
                return exc.code.value
            return "RESOLVED"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    lambda args: resolve(*args),
                    zip(
                        command_ids,
                        (CommandType.APPROVE_WORKFLOW, CommandType.REQUEST_REWORK),
                        strict=True,
                    ),
                )
            )
        assert Counter(outcomes) == {
            "RESOLVED": 1,
            WorkflowErrorCode.APPROVAL_ALREADY_RESOLVED.value: 1,
        }
    finally:
        if workflow_id:
            with integration_engine.begin() as connection:
                connection.execute(
                    delete(WorkflowInstanceRecord).where(
                        WorkflowInstanceRecord.workflow_id == workflow_id
                    )
                )
