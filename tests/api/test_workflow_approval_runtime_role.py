from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import yaml
from eom_api.app import create_app
from eom_api.lifespan import build_services
from eom_api.settings import ApiSecrets, ApiSettings
from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
)
from eom_identity_service.models import OperatorRecord
from eom_identity_service.service import CreateOperatorCommand, OperatorService
from eom_operator_identity import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from eom_orchestrator.repository import (
    ensure_protocol_version,
    submit_structured_job,
    upsert_worker_slot,
)
from eom_orchestrator.state_machine import JobState, transition_job
from eom_workflow import ArtifactPointer, WorkerRequest, WorkflowRequest, compile_definition_data
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.actor_authorization import (
    CompositeWorkflowActorAuthorizer,
)
from eom_workflow_runner.actor_authorization_adapters import (
    OperatorIdentityWorkflowActorAuthorizer,
    SqlAlchemyOperatorActorSource,
    StaticWorkflowActorAuthorizer,
)
from eom_workflow_runner.catalog_port import PreparedPrompt, RegistrationOutcome
from eom_workflow_runner.engine import RoleExecutionResult, WorkflowRunner
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.readiness import RuntimeReadinessReport
from eom_workflow_runner.repository import (
    CommandType,
    create_approval_request,
    create_step_run,
    create_workflow_instance,
    enqueue_command,
    import_workflow_definition,
)
from eom_workflow_runner.settings import WorkflowSettings
from eom_workflow_runner.state_machine import (
    ApprovalState,
    CommandState,
    StepState,
    WorkflowStage,
    WorkflowState,
    transition_command,
    transition_stage,
    transition_step,
    transition_workflow,
)
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]

REVIEWER_TEMPORARY_PASSWORD = "TEST_ONLY approval reviewer temporary 61"
REVIEWER_PASSWORD = "TEST_ONLY approval reviewer password 83"
ROLE_SLOTS = {"authoring", "review", "image", "item_management", "support"}
ROOT = Path(__file__).resolve().parents[2]


def _workflow_settings() -> WorkflowSettings:
    return WorkflowSettings(
        definition_path=ROOT / "config/workflows/generic-item-development.v1.2.yaml",
        actor_config_path=ROOT / "config/human-actors.example.yaml",
        runner_config_path=ROOT / "config/workflow-runner.example.yaml",
        prompt_root=ROOT / "content/prompt-templates/placeholders",
    )


class ReadyWorkflowRuntime:
    def evaluate(self) -> RuntimeReadinessReport:
        return RuntimeReadinessReport(())


class PlaceholderRoleExecutor:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

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
        assert step.worker_role is not None
        with transaction(self.sessions) as session:
            job_id = new_job_id()
            logical_artifact_id = new_logical_artifact_id()
            revision_id = new_revision_id()
            ensure_protocol_version(session, "workflow-role/1.0.1", role_schema_bundle_hash())
            upsert_worker_slot(
                session,
                slot_id="04",
                linux_user="eom-cdx-04",
                role=step.worker_role,
                enabled=True,
                gpu=False,
            )
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
            for target, event in (
                (JobState.VALIDATED, "REQUEST_VALIDATED"),
                (JobState.QUEUED, "JOB_QUEUED"),
            ):
                transition_job(session, job.job_id, target, event)
            job.worker_slot_id = "04"
            for target, event in (
                (JobState.CLAIMED, "WORKER_CLAIMED"),
                (JobState.RUNNING, "WORKER_STARTED"),
                (JobState.VALIDATING_RESULT, "WORKER_RESULT_RECEIVED"),
                (JobState.COMMITTING, "ARTIFACT_COMMIT_STARTED"),
                (JobState.SUCCEEDED, "ARTIFACT_COMMITTED"),
            ):
                transition_job(session, job.job_id, target, event)
            result_hash = content_sha256(
                {
                    "status": "ok",
                    "role": step.worker_role,
                    "workflow_id": workflow.workflow_id,
                }
            )
        return RoleExecutionResult(
            job_id=job_id,
            status="SUCCEEDED",
            worker_slot="04",
            logical_artifact_id=logical_artifact_id,
            revision_id=revision_id,
            content_hash=result_hash,
            error_code=None,
        )


class PlaceholderWorkflowCatalog:
    def prepare_prompt(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        upstream: tuple[ArtifactPointer, ...],
    ) -> PreparedPrompt:
        del workflow, step, request, upstream
        raise AssertionError("legacy fixture has no Content Pack prompt")

    def register_workflow(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: WorkflowRequest,
        artifacts: tuple[ArtifactPointer, ...],
    ) -> RegistrationOutcome:
        del workflow, step, request, artifacts
        return RegistrationOutcome(
            item_id="item_" + "d" * 32,
            item_revision_id="itemrev_" + "e" * 32,
            revision_number=1,
            manifest_artifact_id="artifact_" + "f" * 32,
            manifest_artifact_revision_id="rev_" + "1" * 32,
            manifest_sha256="sha256:" + "2" * 64,
        )


def _enabled() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("run through scripts/api/testdb_run.sh with a disposable database")


def _runtime_environment() -> dict[str, str]:
    path = Path(os.environ["EOM_API_TEST_RUNTIME_ENV"])
    return dict(line.split("=", 1) for line in path.read_text(encoding="ascii").splitlines())


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_waiting_workflow(engine: Engine, actor_id: str, suffix: str) -> tuple[str, str]:
    sessions = build_session_factory(engine)
    raw = yaml.safe_load(
        Path("config/workflows/generic-item-development.v1.yaml").read_text(encoding="utf-8")
    )
    raw["definition_key"] = f"approval-grant-{suffix[:16]}"
    compiled = compile_definition_data(raw, "test-runtime-approval", ROLE_SLOTS)
    with transaction(sessions) as session:
        definition, created = import_workflow_definition(session, compiled)
        assert created
        workflow, workflow_created = create_workflow_instance(
            session,
            definition=definition,
            request=WorkflowRequest(
                request_name="PLACEHOLDER_REQUEST",
                image_mode="skip",
            ),
            idempotency_key=f"approval-workflow-{suffix}",
            actor_type="human",
            actor_id=actor_id,
        )
        assert workflow_created
        start, start_created = enqueue_command(
            session,
            workflow_id=workflow.workflow_id,
            command_type=CommandType.START_WORKFLOW,
            payload={},
            actor_type="human",
            actor_id=actor_id,
            source="test",
            idempotency_key=f"start:{workflow.workflow_id}",
        )
        assert start_created
        for command_state in (
            CommandState.LEASED,
            CommandState.PROCESSING,
            CommandState.SUCCEEDED,
        ):
            transition_command(start, command_state)
        transition_workflow(
            session,
            workflow.workflow_id,
            WorkflowState.RUNNING,
            "TEST_WORKFLOW_RUNNING",
            actor_type="system",
            actor_id="runtime-approval-fixture",
            command_id=start.command_id,
        )
        for stage, step_key in (
            (WorkflowStage.IMAGE_SKIPPED, "review"),
            (WorkflowStage.REVIEWING, "review"),
            (WorkflowStage.AWAITING_HUMAN_APPROVAL, "human_approval"),
        ):
            transition_stage(
                session,
                workflow.workflow_id,
                stage,
                step_key,
                f"TEST_{stage.value}",
                actor_type="system",
                actor_id="runtime-approval-fixture",
                command_id=start.command_id,
            )
        transition_workflow(
            session,
            workflow.workflow_id,
            WorkflowState.AWAITING_HUMAN_APPROVAL,
            "TEST_WORKFLOW_AWAITING_APPROVAL",
            actor_type="system",
            actor_id="runtime-approval-fixture",
            command_id=start.command_id,
            step_key="human_approval",
        )
        gate = create_step_run(
            session,
            workflow_id=workflow.workflow_id,
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
            workflow_id=workflow.workflow_id,
            step_run_id=gate.step_run_id,
            allowed_roles=("reviewer", "admin"),
            allowed_rework_targets=("authoring", "image", "review"),
        )
        approval_payload = {
            "approval_request_id": approval.approval_request_id,
            "approval_lock_version": approval.lock_version,
        }
        old_content_key = content_sha256(
            {
                "workflow_id": workflow.workflow_id,
                "action": CommandType.APPROVE_WORKFLOW.value,
                "lock_version": workflow.lock_version,
                "actor_id": actor_id,
                "payload": approval_payload,
            }
        )
        failed, failed_created = enqueue_command(
            session,
            workflow_id=workflow.workflow_id,
            command_type=CommandType.APPROVE_WORKFLOW,
            payload=approval_payload,
            actor_type="human",
            actor_id=actor_id,
            source="application_api",
            idempotency_key=f"api-{old_content_key.removeprefix('sha256:')}",
        )
        assert failed_created
        for command_state in (
            CommandState.LEASED,
            CommandState.PROCESSING,
            CommandState.FAILED,
        ):
            transition_command(failed, command_state)
        failed.error_code = "APPROVAL_UNAUTHORIZED"
        return workflow.workflow_id, failed.command_id


def test_api_approval_requires_only_the_reconciled_runtime_grant_matrix() -> None:
    _enabled()
    suffix = uuid4().hex
    admin_username = f"grant-admin-{suffix[:12]}"
    reviewer_username = f"grant-reviewer-{suffix[:12]}"
    owner_engine = build_engine()
    operator_service = OperatorService(owner_engine)
    with build_session_factory(owner_engine)() as session:
        if int(session.scalar(select(func.count(OperatorRecord.operator_id))) or 0):
            pytest.skip("runtime approval integration requires a database without Operators")
    bootstrap = operator_service.bootstrap_admin(
        username=admin_username,
        display_name="Runtime Grant Admin",
    )
    admin_actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=bootstrap.operator.operator_id,
        session_id=None,
        request_id=f"runtime-grant-{suffix}",
        authentication_time=datetime.now(UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.CLI,
    )
    reviewer = operator_service.create_operator(
        CreateOperatorCommand(
            username=reviewer_username,
            display_name="Runtime Grant Reviewer",
            temporary_password=REVIEWER_TEMPORARY_PASSWORD,
            initial_roles=(RoleKey.REVIEWER,),
        ),
        admin_actor,
    )
    workflow_id, failed_command_id = _create_waiting_workflow(
        owner_engine, reviewer.operator_id, suffix
    )
    runtime_values = _runtime_environment()
    runtime_url = runtime_values["EOM_API_DATABASE_URL"]
    services = build_services(
        ApiSettings(),
        ApiSecrets(
            database_url=SecretStr(runtime_url),
            token_hash_key=SecretStr(runtime_values["EOM_API_TOKEN_HASH_KEY"]),
            fingerprint_key=SecretStr(runtime_values["EOM_API_FINGERPRINT_KEY"]),
        ),
    )
    runtime_role = runtime_url.split("//", 1)[1].split(":", 1)[0]
    owner = psycopg.connect(os.environ["EOM_DATABASE_URL"].replace("+psycopg", ""))
    owner.autocommit = True
    grant_restored = True
    try:
        with TestClient(
            create_app(services),
            base_url="http://localhost",
            raise_server_exceptions=False,
        ) as client:
            restricted = client.post(
                "/api/v1/auth/login",
                json={
                    "username": reviewer_username,
                    "password": REVIEWER_TEMPORARY_PASSWORD,
                    "client_name": "runtime-grant-integration",
                },
            )
            assert restricted.status_code == 200
            changed = client.post(
                "/api/v1/auth/change-password",
                headers=_authorization(restricted.json()["data"]["access_token"]),
                json={
                    "current_password": REVIEWER_TEMPORARY_PASSWORD,
                    "new_password": REVIEWER_PASSWORD,
                },
            )
            assert changed.status_code == 200
            headers = _authorization(changed.json()["data"]["access_token"])
            before = client.get(f"/api/v1/workflows/{workflow_id}", headers=headers)
            assert before.status_code == 200
            assert before.json()["data"]["state"] == WorkflowState.AWAITING_HUMAN_APPROVAL
            etag = before.headers["ETag"]
            version = before.json()["data"]["resource_version"]

            with build_session_factory(owner_engine)() as session:
                events_before = int(
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowEventRecord)
                        .where(WorkflowEventRecord.workflow_id == workflow_id)
                    )
                    or 0
                )

            with owner.cursor() as cursor:
                cursor.execute(
                    sql.SQL("REVOKE UPDATE ON TABLE app.workflow_instances FROM {}").format(
                        sql.Identifier(runtime_role)
                    )
                )
            grant_restored = False
            failed = client.post(
                f"/api/v1/workflows/{workflow_id}/approvals",
                headers={
                    **headers,
                    "Idempotency-Key": f"approval-prefixed-failure-{suffix}",
                    "If-Match": etag,
                },
                json={},
            )
            assert failed.status_code == 500
            assert failed.json()["error_code"] == "API_INTERNAL_ERROR"
            with build_session_factory(owner_engine)() as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowCommandRecord)
                        .where(
                            WorkflowCommandRecord.workflow_id == workflow_id,
                            WorkflowCommandRecord.command_type
                            == CommandType.APPROVE_WORKFLOW.value,
                        )
                    )
                    == 1
                )

            with owner.cursor() as cursor:
                cursor.execute(
                    sql.SQL("GRANT UPDATE ON TABLE app.workflow_instances TO {}").format(
                        sql.Identifier(runtime_role)
                    )
                )
            grant_restored = True
            approval_key = f"approval-fixed-runtime-{suffix}"
            approval_headers = {
                **headers,
                "Idempotency-Key": approval_key,
                "If-Match": etag,
            }
            approved = client.post(
                f"/api/v1/workflows/{workflow_id}/approvals",
                headers=approval_headers,
                json={},
            )
            assert approved.status_code == 202
            replay = client.post(
                f"/api/v1/workflows/{workflow_id}/approvals",
                headers=approval_headers,
                json={},
            )
            assert replay.status_code == 202
            assert replay.json()["data"]["command_id"] == approved.json()["data"]["command_id"]
            approval_command_id = approved.json()["data"]["command_id"]
            assert approval_command_id != failed_command_id
            assert approved.json()["data"]["resource_version"] == version
            after = client.get(f"/api/v1/workflows/{workflow_id}", headers=headers)
            assert after.status_code == 200
            assert after.headers["ETag"] == etag
            assert client.get("/api/v1/health/ready").status_code == 200

            with build_session_factory(owner_engine)() as session:
                approval = session.scalar(
                    select(ApprovalRequestRecord).where(
                        ApprovalRequestRecord.workflow_id == workflow_id
                    )
                )
                commands = list(
                    session.scalars(
                        select(WorkflowCommandRecord).where(
                            WorkflowCommandRecord.workflow_id == workflow_id,
                            WorkflowCommandRecord.command_type
                            == CommandType.APPROVE_WORKFLOW.value,
                        )
                    )
                )
                events_after = int(
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowEventRecord)
                        .where(WorkflowEventRecord.workflow_id == workflow_id)
                    )
                    or 0
                )
                assert approval is not None and approval.status == ApprovalState.PENDING.value
                assert len(commands) == 2
                by_id = {command.command_id: command for command in commands}
                assert by_id[failed_command_id].state == CommandState.FAILED.value
                assert by_id[failed_command_id].error_code == "APPROVAL_UNAUTHORIZED"
                assert by_id[approval_command_id].state == CommandState.PENDING.value
                assert by_id[approval_command_id].actor_id == reviewer.operator_id
                assert events_after == events_before

            workflow_settings = _workflow_settings()
            actor_authorizer = CompositeWorkflowActorAuthorizer(
                operator=OperatorIdentityWorkflowActorAuthorizer(
                    SqlAlchemyOperatorActorSource(owner_engine)
                ),
                static=StaticWorkflowActorAuthorizer(workflow_settings.load_actors()),
            )
            runner = WorkflowRunner(
                owner_engine,
                workflow_settings,
                PlaceholderRoleExecutor(owner_engine),
                catalog=PlaceholderWorkflowCatalog(),
                actor_authorizer=actor_authorizer,
                readiness=ReadyWorkflowRuntime(),
                available_roles=frozenset(ROLE_SLOTS),
                runner_id=f"runtime-approval-{suffix}",
            )
            result = runner.run_once(workflow_id)
            assert result is not None
            assert result.command_id == approval_command_id
            assert result.state == CommandState.SUCCEEDED.value

            with build_session_factory(owner_engine)() as session:
                approval = session.scalar(
                    select(ApprovalRequestRecord).where(
                        ApprovalRequestRecord.workflow_id == workflow_id
                    )
                )
                command = session.get(WorkflowCommandRecord, approval_command_id)
                failed_command = session.get(WorkflowCommandRecord, failed_command_id)
                workflow = session.get(WorkflowInstanceRecord, workflow_id)
                approved_event = session.scalar(
                    select(WorkflowEventRecord).where(
                        WorkflowEventRecord.workflow_id == workflow_id,
                        WorkflowEventRecord.event_type == "WORKFLOW_APPROVED",
                    )
                )
                assert approval is not None and approval.status == ApprovalState.APPROVED.value
                assert workflow is not None and workflow.state == WorkflowState.COMPLETED.value
                assert command is not None and command.actor_id == reviewer.operator_id
                assert command.state == CommandState.SUCCEEDED.value
                assert failed_command is not None
                assert failed_command.state == CommandState.FAILED.value
                assert failed_command.error_code == "APPROVAL_UNAUTHORIZED"
                assert approved_event is not None
                assert approved_event.actor_id == reviewer.operator_id
                assert approved_event.payload["authorization_source"] == "OPERATOR_IDENTITY"

            revoked_suffix = uuid4().hex
            revoked_workflow_id, _ = _create_waiting_workflow(
                owner_engine, reviewer.operator_id, revoked_suffix
            )
            revoked_view = client.get(f"/api/v1/workflows/{revoked_workflow_id}", headers=headers)
            assert revoked_view.status_code == 200
            revoked_submission = client.post(
                f"/api/v1/workflows/{revoked_workflow_id}/approvals",
                headers={
                    **headers,
                    "Idempotency-Key": f"approval-before-revoke-{revoked_suffix}",
                    "If-Match": revoked_view.headers["ETag"],
                },
                json={},
            )
            assert revoked_submission.status_code == 202
            revoked_command_id = revoked_submission.json()["data"]["command_id"]
            operator_service.revoke_role(
                reviewer.operator_id,
                RoleKey.REVIEWER,
                admin_actor,
                reason="TEST_ONLY revoke before workflow command processing",
            )
            revoked_result = runner.run_once(revoked_workflow_id)
            assert revoked_result is not None
            assert revoked_result.command_id == revoked_command_id
            assert revoked_result.state == CommandState.FAILED.value
            assert revoked_result.error_code == "APPROVAL_UNAUTHORIZED"
            with build_session_factory(owner_engine)() as session:
                revoked_workflow = session.get(WorkflowInstanceRecord, revoked_workflow_id)
                assert revoked_workflow is not None
                assert revoked_workflow.state == WorkflowState.AWAITING_HUMAN_APPROVAL.value

            operator_service.assign_role(reviewer.operator_id, RoleKey.REVIEWER, admin_actor)
            disabled_suffix = uuid4().hex
            disabled_workflow_id, _ = _create_waiting_workflow(
                owner_engine, reviewer.operator_id, disabled_suffix
            )
            disabled_view = client.get(f"/api/v1/workflows/{disabled_workflow_id}", headers=headers)
            assert disabled_view.status_code == 200
            disabled_submission = client.post(
                f"/api/v1/workflows/{disabled_workflow_id}/approvals",
                headers={
                    **headers,
                    "Idempotency-Key": f"approval-before-disable-{disabled_suffix}",
                    "If-Match": disabled_view.headers["ETag"],
                },
                json={},
            )
            assert disabled_submission.status_code == 202
            disabled_command_id = disabled_submission.json()["data"]["command_id"]
            operator_service.disable(
                reviewer.operator_id,
                admin_actor,
                reason="TEST_ONLY disable before workflow command processing",
            )
            disabled_result = runner.run_once(disabled_workflow_id)
            assert disabled_result is not None
            assert disabled_result.command_id == disabled_command_id
            assert disabled_result.state == CommandState.FAILED.value
            assert disabled_result.error_code == "APPROVAL_UNAUTHORIZED"
            with build_session_factory(owner_engine)() as session:
                disabled_workflow = session.get(WorkflowInstanceRecord, disabled_workflow_id)
                assert disabled_workflow is not None
                assert disabled_workflow.state == WorkflowState.AWAITING_HUMAN_APPROVAL.value
    finally:
        if not grant_restored:
            with owner.cursor() as cursor:
                cursor.execute(
                    sql.SQL("GRANT UPDATE ON TABLE app.workflow_instances TO {}").format(
                        sql.Identifier(runtime_role)
                    )
                )
        owner.close()
        services.engine.dispose()
        # The approval path writes append-only audit and immutable workflow
        # history. The guarded disposable-database cleanup removes them as one
        # unit after this final integration test.
        owner_engine.dispose()
