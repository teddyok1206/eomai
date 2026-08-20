from __future__ import annotations

import os
from pathlib import Path

import pytest
from eom_api.app import create_app
from eom_api.lifespan import build_services
from eom_api.settings import ApiSecrets, ApiSettings
from eom_identity_service.models import (
    ApiIdempotencyRecord,
    ApiSessionRecord,
    ApiTokenRecord,
    OperatorCredentialRecord,
    OperatorEventRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from eom_identity_service.service import OperatorService
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from eom_orchestrator.settings import database_url
from eom_workflow import compile_definition
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import import_workflow_definition
from eom_workflow_runner.state_machine import (
    WorkflowStage,
    WorkflowState,
    transition_stage,
    transition_workflow,
)
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, delete, func, select

from tests.api.helpers import TEST_FINGERPRINT_KEY, TEST_TOKEN_KEY

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
ADMIN_PASSWORD = "TEST_ONLY workflow admin password 84"
AUTHOR_TEMPORARY_PASSWORD = "TEST_ONLY workflow author temporary 73"
AUTHOR_PASSWORD = "TEST_ONLY workflow author password 95"
ROLE_SLOTS = {"authoring", "review", "image", "item_management", "support"}


class NoopAudit:
    def append(self, *args: object, **kwargs: object) -> None:
        pass


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _cleanup(engine: Engine, definition_id: str | None) -> None:
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        if definition_id is not None:
            session.execute(
                delete(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.definition_id == definition_id
                )
            )
            # Released definitions are immutable. The guarded disposable-database
            # cleanup owns their eventual removal together with the database.
        operator_ids = list(
            session.scalars(
                select(OperatorRecord.operator_id).where(
                    OperatorRecord.username.in_(("workflow-admin", "workflow-author"))
                )
            )
        )
        if operator_ids:
            session_ids = select(ApiSessionRecord.api_session_id).where(
                ApiSessionRecord.operator_id.in_(operator_ids)
            )
            session.execute(
                delete(ApiTokenRecord).where(ApiTokenRecord.api_session_id.in_(session_ids))
            )
            session.execute(
                delete(ApiIdempotencyRecord).where(
                    ApiIdempotencyRecord.operator_id.in_(operator_ids)
                )
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
            session.execute(
                delete(OperatorRecord).where(OperatorRecord.operator_id.in_(operator_ids))
            )


def test_workflow_start_separates_api_replay_from_failed_resubmission() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_API_INTEGRATION=1 with an isolated PostgreSQL database")
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        if int(session.scalar(select(func.count(OperatorRecord.operator_id))) or 0):
            pytest.skip("API workflow integration requires a database without existing Operators")
    bootstrap = OperatorService(engine).bootstrap_admin(
        username="workflow-admin", display_name="Workflow Admin"
    )
    services = build_services(
        ApiSettings(),
        ApiSecrets(
            database_url=SecretStr(database_url()),
            token_hash_key=SecretStr(TEST_TOKEN_KEY),
            fingerprint_key=SecretStr(TEST_FINGERPRINT_KEY),
        ),
    )
    services.audit = NoopAudit()  # type: ignore[assignment]
    definition_id: str | None = None
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            restricted = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "workflow-admin",
                    "password": bootstrap.temporary_password,
                    "client_name": "workflow-submission-test",
                },
            ).json()["data"]
            admin_pair = client.post(
                "/api/v1/auth/change-password",
                headers=_authorization(restricted["access_token"]),
                json={
                    "current_password": bootstrap.temporary_password,
                    "new_password": ADMIN_PASSWORD,
                },
            ).json()["data"]
            created_author = client.post(
                "/api/v1/operators",
                headers={
                    **_authorization(admin_pair["access_token"]),
                    "Idempotency-Key": "workflow-author-create-0001",
                },
                json={
                    "username": "workflow-author",
                    "display_name": "Workflow Author",
                    "temporary_password": AUTHOR_TEMPORARY_PASSWORD,
                    "initial_roles": ["AUTHOR"],
                },
            )
            assert created_author.status_code == 201
            author_restricted = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "workflow-author",
                    "password": AUTHOR_TEMPORARY_PASSWORD,
                    "client_name": "workflow-submission-test",
                },
            ).json()["data"]
            author_pair = client.post(
                "/api/v1/auth/change-password",
                headers=_authorization(author_restricted["access_token"]),
                json={
                    "current_password": AUTHOR_TEMPORARY_PASSWORD,
                    "new_password": AUTHOR_PASSWORD,
                },
            ).json()["data"]
            author_headers = _authorization(author_pair["access_token"])

            with transaction(sessions) as session:
                compiled = compile_definition(
                    Path("config/workflows/generic-item-development.v1.yaml"), ROLE_SLOTS
                )
                definition, definition_created = import_workflow_definition(session, compiled)
                assert definition_created
                definition_id = definition.definition_id

            body = {
                "definition_key": "generic-item-development",
                "definition_version": "1.0.0",
                "request_name": "PLACEHOLDER_REQUEST",
                "image_mode": "skip",
            }
            first = client.post(
                "/api/v1/workflows",
                headers={**author_headers, "Idempotency-Key": "workflow-old-key-0001"},
                json=body,
            )
            assert first.status_code == 202
            first_data = first.json()["data"]
            first_id = first_data["resource_id"]
            replay = client.post(
                "/api/v1/workflows",
                headers={**author_headers, "Idempotency-Key": "workflow-old-key-0001"},
                json=body,
            )
            assert replay.status_code == 202
            assert replay.json()["data"] == first_data
            conflict = client.post(
                "/api/v1/workflows",
                headers={**author_headers, "Idempotency-Key": "workflow-old-key-0001"},
                json={**body, "image_mode": "required"},
            )
            assert conflict.status_code == 409
            assert conflict.json()["error_code"] == "API_IDEMPOTENCY_CONFLICT"

            active_duplicate = client.post(
                "/api/v1/workflows",
                headers={**author_headers, "Idempotency-Key": "workflow-active-key-0002"},
                json=body,
            )
            assert active_duplicate.status_code == 202
            assert active_duplicate.json()["data"]["resource_id"] == first_id
            assert active_duplicate.json()["data"]["command_id"] == first_data["command_id"]

            with transaction(sessions) as session:
                workflow = session.get(WorkflowInstanceRecord, first_id)
                assert workflow is not None
                workflow.failure_code = "TEST_INFRASTRUCTURE_FAILURE"
                workflow.failure_summary = "test workflow occurrence failed"
                transition_stage(
                    session,
                    first_id,
                    WorkflowStage.FAILED,
                    workflow.current_step_key,
                    "WORKFLOW_FAILURE_STAGE_ENTERED",
                    actor_type="system",
                    actor_id="test",
                    command_id=None,
                    payload={"error_code": workflow.failure_code},
                )
                transition_workflow(
                    session,
                    first_id,
                    WorkflowState.FAILED,
                    "WORKFLOW_FAILED",
                    actor_type="system",
                    actor_id="test",
                    command_id=None,
                    step_key=workflow.current_step_key,
                    payload={"error_code": workflow.failure_code},
                )
            with sessions() as session:
                failed = session.get(WorkflowInstanceRecord, first_id)
                assert failed is not None
                failed_snapshot = (
                    failed.state,
                    failed.stage,
                    failed.failure_code,
                    failed.failure_summary,
                    failed.created_at,
                    failed.completed_at,
                    failed.request_hash,
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowEventRecord)
                        .where(WorkflowEventRecord.workflow_id == first_id)
                    ),
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowCommandRecord)
                        .where(WorkflowCommandRecord.workflow_id == first_id)
                    ),
                )

            second = client.post(
                "/api/v1/workflows",
                headers={**author_headers, "Idempotency-Key": "workflow-new-key-0003"},
                json=body,
            )
            assert second.status_code == 202
            second_data = second.json()["data"]
            second_id = second_data["resource_id"]
            assert second_id != first_id
            second_replay = client.post(
                "/api/v1/workflows",
                headers={**author_headers, "Idempotency-Key": "workflow-new-key-0003"},
                json=body,
            )
            assert second_replay.status_code == 202
            assert second_replay.json()["data"] == second_data
            no_third = client.post(
                "/api/v1/workflows",
                headers={**author_headers, "Idempotency-Key": "workflow-active-key-0004"},
                json=body,
            )
            assert no_third.status_code == 202
            assert no_third.json()["data"]["resource_id"] == second_id
            assert no_third.json()["data"]["command_id"] == second_data["command_id"]

            with sessions() as session:
                failed = session.get(WorkflowInstanceRecord, first_id)
                second_workflow = session.get(WorkflowInstanceRecord, second_id)
                second_command = session.scalar(
                    select(WorkflowCommandRecord).where(
                        WorkflowCommandRecord.workflow_id == second_id,
                        WorkflowCommandRecord.command_type == "START_WORKFLOW",
                    )
                )
                assert failed is not None and second_workflow is not None
                assert second_command is not None and second_command.attempts == 0
                assert failed_snapshot == (
                    failed.state,
                    failed.stage,
                    failed.failure_code,
                    failed.failure_summary,
                    failed.created_at,
                    failed.completed_at,
                    failed.request_hash,
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowEventRecord)
                        .where(WorkflowEventRecord.workflow_id == first_id)
                    ),
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowCommandRecord)
                        .where(WorkflowCommandRecord.workflow_id == first_id)
                    ),
                )
                assert second_workflow.request_hash == failed.request_hash
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(WorkflowInstanceRecord)
                        .where(WorkflowInstanceRecord.request_hash == failed.request_hash)
                    )
                    == 2
                )
    finally:
        services.engine.dispose()
        _cleanup(engine, definition_id)
        engine.dispose()
