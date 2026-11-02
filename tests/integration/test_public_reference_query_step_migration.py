"""Guarded disposable PG real repository INSERT/DDL; source/IAM/numerics not exercised."""

from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_workflow.compiler import compile_definition_data
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import create_step_run, import_workflow_definition
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.integration.test_local_embedding_stage_migration import (
    empty_workflow_tables as empty_workflow_tables,
)
from tests.unit.test_public_reference_query_step_migration import public_step_migration
from tests.unit.test_public_solution_reference_query_execution import (
    public_definition_body,
    public_workflow_case,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def public_workflow(session):
    compiled = compile_definition_data(public_definition_body(), "synthetic/step68", set())
    definition, _ = import_workflow_definition(session, compiled)
    request = public_workflow_case(identity=uuid4().hex).request
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + uuid4().hex,
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version="2.0.0",
        definition_hash=compiled.sha256,
        protocol_version="1.0.1",
        role_schema_version="reference-query/2.0",
        state="RUNNING",
        stage="LOCAL_EMBEDDING",
        current_step_key="encode_reference_query",
        request_payload=request.model_dump(mode="json"),
        initial_request=request.model_dump(mode="json"),
        runtime_context={},
        idempotency_key="synthetic-step68-" + uuid4().hex,
        request_hash=request.request_sha256,
        created_actor_type="human",
        created_actor_id=request.operator_audit.operator_id,
    )
    session.add(workflow)
    session.flush()
    return workflow


def application_step(session, workflow):
    return create_step_run(
        session,
        workflow_id=workflow.workflow_id,
        step_key="encode_reference_query",
        step_type="application",
        worker_role=None,
        result_schema="embedding-reference-query-result@2.0",
        input_pointer_manifest={"workflow_request_sha256": workflow.request_hash},
        max_attempts=1,
    )


def test_actual_repository_public2_insert_and_duplicate_guard(stage_owner_connection):
    with (
        Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session,
        session.begin(),
    ):
        workflow = public_workflow(session)
        created = application_step(session, workflow)
        assert created.result_schema == "embedding-reference-query-result@2.0"
        with pytest.raises(WorkflowError) as error, session.begin_nested():
            application_step(session, workflow)
        assert error.value.code == WorkflowErrorCode.WORKFLOW_REWORK_LIMIT_EXCEEDED


def test_public2_cannot_use_private_step_key(stage_owner_connection):
    with (
        Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session,
        session.begin(),
    ):
        workflow = public_workflow(session)
        with pytest.raises(IntegrityError) as error, session.begin_nested():
            create_step_run(
                session,
                workflow_id=workflow.workflow_id,
                step_key="encode_private_chat_query",
                step_type="application",
                worker_role=None,
                result_schema="embedding-reference-query-result@2.0",
                input_pointer_manifest={},
                max_attempts=1,
            )
        assert error.value.orig.sqlstate == "23514"
        assert error.value.orig.diag.constraint_name == "ck_workflow_step_runs_local_embedding"


def test_67_rejects_public2_then_68_accepts_and_refuses_destructive_downgrade(
    empty_workflow_tables, monkeypatch
):
    connection = empty_workflow_tables
    migration = public_step_migration()
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
    # LIKE copies CHECKs but not triggers; install the matching temporary guards.
    migration.upgrade()
    migration.downgrade()
    with (
        Session(bind=connection, join_transaction_mode="create_savepoint") as session,
        session.begin(),
    ):
        workflow = public_workflow(session)
        with pytest.raises(IntegrityError) as error, session.begin_nested():
            application_step(session, workflow)
        assert error.value.orig.sqlstate == "23514"
        migration.upgrade()
        application_step(session, workflow)
        before = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname='ck_workflow_step_runs_local_embedding' "
                "AND conrelid='workflow_step_runs'::regclass"
            )
        )
        with pytest.raises(DBAPIError, match="absent public successor"), connection.begin_nested():
            migration.downgrade()
        assert (
            connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname='ck_workflow_step_runs_local_embedding' "
                    "AND conrelid='workflow_step_runs'::regclass"
                )
            )
            == before
        )
