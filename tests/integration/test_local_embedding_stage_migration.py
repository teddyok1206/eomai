"""Opt-in guarded disposable migration checks; no application/native execution grant.

Synthetic fixtures are rolled back with the official outer owner transaction.
Direct Operations calls change constraints only inside it, never stamp/history-delete.
Only the root's guarded disposable test harness may execute this file.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from psycopg.errors import CheckViolation, RaiseException
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def empty_workflow_tables(stage_owner_connection: Connection) -> Connection:
    """Real PostgreSQL CHECKs on empty temporary schema copies, never history deletion.

    Claim tests deliberately retain committed synthetic history in app. A positive
    absent-history case must not assume a fresh DB or erase that evidence on replay.
    All negative/history/immutability cases continue to use the actual app tables.
    """
    for name in ("workflow_definitions", "workflow_instances", "workflow_step_runs"):
        stage_owner_connection.exec_driver_sql(
            f"CREATE TEMP TABLE {name} (LIKE app.{name} INCLUDING ALL) ON COMMIT DROP"
        )
    stage_owner_connection.exec_driver_sql("SET LOCAL search_path TO pg_temp,app,public")
    return stage_owner_connection


def _migration(connection: Connection, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = Path("migrations/versions/20261012_0053_local_embedding_stage.py")
    spec = importlib.util.spec_from_file_location("guarded_native_stage_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = MigrationContext.configure(
        connection, opts={"version_table": "alembic_version", "version_table_schema": "app"}
    )
    monkeypatch.setattr(module, "op", Operations(context))
    return module


def _seed(
    connection: Connection, *, definition_native: bool = False, marker: str = "none"
) -> tuple[str, str]:
    identity = uuid4().hex
    definition_id, workflow_id = "wfdef_" + identity, "workflow_" + identity
    definition_key = (
        "local-embedding-reference-query"
        if marker == "query_definition"
        else "local-embedding-index"
        if definition_native
        else "synthetic-native-guard-" + identity
    )
    canonical = (
        '{"definition_key":"local-embedding-index"}' if marker == "definition_snapshot" else "{}"
    )
    connection.execute(
        text(
            "INSERT INTO workflow_definitions (definition_id,definition_key,definition_version,"
            "schema_version,canonical_definition,definition_hash,active,source_path) VALUES "
            "(:id,:key,:version,'1.1',CAST(:canonical AS jsonb),:hash,false,'synthetic/guard-only')"
        ),
        {
            "id": definition_id,
            "key": definition_key,
            "version": "synthetic-" + identity[:8],
            "canonical": canonical,
            "hash": "sha256:" + "a" * 64,
        },
    )
    native_v1 = (
        '{"schema_version":"local-embedding-workflow-request/1.0",'
        '"request_name":"LOCAL_EMBEDDING_WORKFLOW_REQUEST"}'
    )
    native_v11 = (
        '{"schema_version":"local-embedding-workflow-request/1.1",'
        '"request_name":"LOCAL_EMBEDDING_WORKFLOW_REQUEST","purpose":"LOCAL_EMBEDDING"}'
    )
    unrelated = '{"purpose":"NOT_LOCAL_EMBEDDING","note":"LOCAL_EMBEDDING"}'
    initial = (
        '{"purpose":"REFERENCE_QUERY"}'
        if marker == "query_initial"
        else native_v1
        if marker == "initial_v1"
        else native_v11
        if marker == "initial_v11"
        else unrelated
    )
    payload = (
        '{"schema_version":"reference-query-workflow-request/1.0"}'
        if marker == "query_payload"
        else native_v1
        if marker == "payload_v1"
        else native_v11
        if marker == "payload_v11"
        else unrelated
    )
    connection.execute(
        text(
            "INSERT INTO workflow_instances (workflow_id,definition_id,definition_key,"
            "definition_version,definition_hash,protocol_version,role_schema_version,state,stage,"
            "current_step_key,request_payload,initial_request,runtime_context,idempotency_key,"
            "request_hash,lock_version,rework_cycle_count,created_actor_type,created_actor_id) "
            "VALUES "
            "(:id,:definition,:key,'1.0.0',:hash,'1.0.1',:protocol,'COMPLETED',:stage,'complete',"
            "CAST(:payload AS jsonb),CAST(:initial AS jsonb),'{}'::jsonb,:idem,:request,1,0,"
            "'human','synthetic-native-guard-only')"
        ),
        {
            "id": workflow_id,
            "definition": definition_id,
            "key": "local-embedding-index" if marker == "instance_definition" else definition_key,
            "hash": "sha256:" + "a" * 64,
            "protocol": (
                "reference-query/1.0"
                if marker == "query_protocol"
                else "local-embedding/1.0"
                if marker == "protocol"
                else "workflow-role/1.29.0"
            ),
            "stage": "LOCAL_EMBEDDING" if marker == "stage" else "COMPLETED",
            "payload": payload,
            "initial": initial,
            "idem": "synthetic-native-guard-" + identity,
            "request": "sha256:" + identity * 2,
        },
    )
    return definition_id, workflow_id


def _step(
    connection: Connection,
    workflow_id: str,
    *,
    step_type: str,
    role: str | None,
    schema: str | None,
    key: str = "encode_batch",
    carrier: bool = False,
) -> str:
    identity = "steprun_" + uuid4().hex
    output = '{"schema_version":"local-embedding-step-output/1.0"}' if carrier else "null"
    connection.execute(
        text(
            "INSERT INTO workflow_step_runs "
            "(step_run_id,workflow_id,step_key,attempt,step_type,"
            "worker_role,result_schema,state,input_pointer_manifest,output_pointer_manifest) "
            "VALUES (:id,:workflow,:key,1,:type,:role,:schema,'SUCCEEDED','{}'::jsonb,"
            "CAST(:output AS jsonb))"
        ),
        {
            "id": identity,
            "workflow": workflow_id,
            "key": key,
            "type": step_type,
            "role": role,
            "schema": schema,
            "output": output,
        },
    )
    return identity


@pytest.mark.parametrize(
    "step_type,role,schema,key",
    [
        ("application", None, None, "encode_batch"),
        ("application", None, "authoring-result@1.0", "encode_batch"),
        ("application", "support", "incremental-embedding-result@1.0", "encode_batch"),
        ("application", None, "incremental-embedding-result@1.0", "other_step"),
        ("agent", None, "incremental-embedding-result@1.0", "encode_batch"),
    ],
)
def test_actual_total_boolean_native_check_rejects_null_and_wrong_shape(
    stage_owner_connection: Connection,
    step_type: str,
    role: str | None,
    schema: str | None,
    key: str,
) -> None:
    _, workflow_id = _seed(stage_owner_connection)
    with pytest.raises(IntegrityError) as error, stage_owner_connection.begin_nested():
        _step(
            stage_owner_connection,
            workflow_id,
            step_type=step_type,
            role=role,
            schema=schema,
            key=key,
        )
    cause = error.value.orig
    assert isinstance(cause, CheckViolation) and cause.sqlstate == "23514"
    assert cause.diag.constraint_name == "ck_workflow_step_runs_local_embedding"


def test_actual_native_stage_and_valid_step_do_not_change_legacy_null_shape(
    stage_owner_connection: Connection,
) -> None:
    _, native_workflow = _seed(stage_owner_connection, marker="stage")
    _step(
        stage_owner_connection,
        native_workflow,
        step_type="application",
        role=None,
        schema="incremental-embedding-result@1.0",
    )
    _, legacy_workflow = _seed(stage_owner_connection)
    _step(
        stage_owner_connection,
        legacy_workflow,
        step_type="terminal",
        role=None,
        schema=None,
        key="complete",
    )
    with pytest.raises(IntegrityError), stage_owner_connection.begin_nested():
        stage_owner_connection.execute(
            text("UPDATE app.workflow_instances SET stage='UNKNOWN_STAGE' WHERE workflow_id=:id"),
            {"id": native_workflow},
        )


@pytest.mark.parametrize(
    "marker",
    [
        "definition",
        "definition_snapshot",
        "instance_definition",
        "stage",
        "protocol",
        "initial_v1",
        "initial_v11",
        "payload_v1",
        "payload_v11",
        "step",
        "carrier",
    ],
)
def test_actual_downgrade_refuses_all_native_history_before_ddl_without_row_rewrite(
    stage_owner_connection: Connection,
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
) -> None:
    _, workflow_id = _seed(
        stage_owner_connection, definition_native=marker == "definition", marker=marker
    )
    if marker == "step":
        _step(
            stage_owner_connection,
            workflow_id,
            step_type="application",
            role=None,
            schema="incremental-embedding-result@1.0",
        )
    elif marker == "carrier":
        _step(
            stage_owner_connection,
            workflow_id,
            step_type="terminal",
            role=None,
            schema=None,
            key="complete",
            carrier=True,
        )
    before = stage_owner_connection.execute(
        text(
            "SELECT state,stage,definition_key,initial_request,request_payload "
            "FROM app.workflow_instances WHERE workflow_id=:id"
        ),
        {"id": workflow_id},
    ).one()
    module = _migration(stage_owner_connection, monkeypatch)
    with pytest.raises(DBAPIError) as error, stage_owner_connection.begin_nested():
        module.downgrade()
    cause = error.value.orig
    assert isinstance(cause, CheckViolation) and not isinstance(cause, RaiseException)
    assert cause.sqlstate == "23514"
    assert (
        cause.diag.message_primary
        == "local embedding downgrade requires absent native Workflow history"
    )
    after = stage_owner_connection.execute(
        text(
            "SELECT state,stage,definition_key,initial_request,request_payload "
            "FROM app.workflow_instances WHERE workflow_id=:id"
        ),
        {"id": workflow_id},
    ).one()
    assert after == before
    assert (
        stage_owner_connection.scalar(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid='app.workflow_step_runs'::regclass "
                "AND conname='ck_workflow_step_runs_local_embedding'"
            )
        )
        == 1
    )
    assert (
        stage_owner_connection.scalar(text("SELECT version_num FROM app.alembic_version"))
        == CURRENT_MIGRATION_REVISION
    )


def test_actual_down_up_with_only_legacy_rows_and_unrelated_native_words(
    empty_workflow_tables: Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_owner_connection = empty_workflow_tables
    actual_check = text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='app.workflow_step_runs'::regclass "
        "AND conname='ck_workflow_step_runs_local_embedding'"
    )
    preserved_actual_check = stage_owner_connection.scalar(actual_check)
    _, workflow_id = _seed(stage_owner_connection)
    _step(
        stage_owner_connection,
        workflow_id,
        step_type="terminal",
        role=None,
        schema=None,
        key="complete",
    )
    module = _migration(stage_owner_connection, monkeypatch)
    module.downgrade()
    assert (
        stage_owner_connection.scalar(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid='pg_temp.workflow_step_runs'::regclass "
                "AND conname='ck_workflow_step_runs_local_embedding'"
            )
        )
        == 0
    )
    module.upgrade()
    assert (
        stage_owner_connection.scalar(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid='pg_temp.workflow_step_runs'::regclass "
                "AND conname='ck_workflow_step_runs_local_embedding'"
            )
        )
        == 1
    )
    assert (
        stage_owner_connection.scalar(
            text("SELECT state FROM pg_temp.workflow_instances WHERE workflow_id=:id"),
            {"id": workflow_id},
        )
        == "COMPLETED"
    )
    assert stage_owner_connection.scalar(actual_check) == preserved_actual_check
