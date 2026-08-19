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
from eom_identity_service.models import (
    ApiAuditEventRecord,
    ApiIdempotencyRecord,
    ApiSessionRecord,
    ApiTokenRecord,
    OperatorCredentialRecord,
    OperatorEventRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from eom_identity_service.service import CreateOperatorCommand, OperatorService
from eom_operator_identity import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from eom_workflow import WorkflowRequest, compile_definition_data
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    create_approval_request,
    create_step_run,
    create_workflow_instance,
    enqueue_command,
    import_workflow_definition,
)
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
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]

REVIEWER_TEMPORARY_PASSWORD = "TEST_ONLY approval reviewer temporary 61"
REVIEWER_PASSWORD = "TEST_ONLY approval reviewer password 83"
ROLE_SLOTS = {"authoring", "review", "image", "item_management", "support"}


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
        create_approval_request(
            session,
            workflow_id=workflow.workflow_id,
            step_run_id=gate.step_run_id,
            allowed_roles=("reviewer", "admin"),
            allowed_rework_targets=("authoring", "image", "review"),
        )
        return workflow.workflow_id, definition.definition_id


def _cleanup(engine: Engine, definition_id: str, usernames: tuple[str, ...]) -> None:
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        session.execute(
            delete(WorkflowInstanceRecord).where(
                WorkflowInstanceRecord.definition_id == definition_id
            )
        )
        session.execute(
            delete(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_id == definition_id
            )
        )
        operator_ids = list(
            session.scalars(
                select(OperatorRecord.operator_id).where(OperatorRecord.username.in_(usernames))
            )
        )
        if not operator_ids:
            return
        session_ids = select(ApiSessionRecord.api_session_id).where(
            ApiSessionRecord.operator_id.in_(operator_ids)
        )
        session.execute(
            delete(ApiAuditEventRecord).where(ApiAuditEventRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(ApiTokenRecord).where(ApiTokenRecord.api_session_id.in_(session_ids))
        )
        session.execute(
            delete(ApiIdempotencyRecord).where(ApiIdempotencyRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(ApiSessionRecord).where(ApiSessionRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(OperatorEventRecord).where(OperatorEventRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(OperatorRoleAssignmentRecord).where(
                OperatorRoleAssignmentRecord.operator_id.in_(operator_ids)
            )
        )
        session.execute(
            delete(OperatorCredentialRecord).where(
                OperatorCredentialRecord.operator_id.in_(operator_ids)
            )
        )
        session.execute(delete(OperatorRecord).where(OperatorRecord.operator_id.in_(operator_ids)))


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
    workflow_id, definition_id = _create_waiting_workflow(
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
                    == 0
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
                assert len(commands) == 1
                assert commands[0].command_id == approved.json()["data"]["command_id"]
                assert commands[0].state == CommandState.PENDING.value
                assert events_after == events_before
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
        _cleanup(owner_engine, definition_id, (admin_username, reviewer_username))
        owner_engine.dispose()
