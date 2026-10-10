"""Actual stage CHECK in a marker-guarded disposable owner DB only.

Rows below are explicitly synthetic migration fixtures, not application-created
or approved Workflows. An outer transaction removes every row and DDL change.
No worker, corpus, model or NAS operation is performed.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_orchestrator.database import build_engine
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from psycopg.errors import CheckViolation
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from scripts.api.testdb_guard import (
    TestDatabaseManifest as DisposableManifest,
)
from scripts.api.testdb_guard import (
    validate_application_schema_metadata,
    validate_state_directory,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def stage_owner_connection() -> Iterator[Connection]:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh chat-knowledge-tests; never production")
    state_value = os.environ.get("EOM_CHAT_KNOWLEDGE_TEST_STATE")
    explicit_url = os.environ.get("EOM_DATABASE_URL")
    if not state_value or not explicit_url:
        pytest.fail("explicit guarded disposable state and owner DB are required")
    state = validate_state_directory(Path(state_value))
    manifest = DisposableManifest.load(state / "manifest.json")
    parsed = urlsplit(explicit_url)
    assert parsed.username == manifest.owner_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    engine = build_engine(explicit_url)
    try:
        with engine.connect() as connection, connection.begin() as outer:
            assert connection.scalar(text("SELECT current_database()")) == manifest.database
            assert connection.scalar(text("SELECT current_user")) == manifest.owner_role
            owner, marker = connection.execute(
                text(
                    "SELECT owner.rolname,obj_description(namespace.oid,'pg_namespace') "
                    "FROM pg_namespace namespace JOIN pg_roles owner "
                    "ON owner.oid=namespace.nspowner WHERE namespace.nspname='app'"
                )
            ).one()
            path, usage, create = connection.execute(
                text(
                    "SELECT current_schemas(false),"
                    "has_schema_privilege(current_user,'app','USAGE'),"
                    "has_schema_privilege(current_user,'app','CREATE')"
                )
            ).one()
            validate_application_schema_metadata(
                manifest,
                schema_owner=owner,
                schema_comment=marker,
                effective_search_path=tuple(path),
                has_usage=usage,
                has_create=create,
            )
            assert (
                connection.scalar(text("SELECT version_num FROM app.alembic_version"))
                == CURRENT_MIGRATION_REVISION
                == "20261010_0051"
            )
            yield connection
            outer.rollback()
    finally:
        engine.dispose()


def _insert_synthetic_stage_fixture(connection: Connection) -> str:
    identity = uuid4().hex
    workflow_id = "workflow_" + identity
    connection.execute(
        text(
            "INSERT INTO app.workflow_definitions "
            "(definition_id,definition_key,definition_version,schema_version,"
            "canonical_definition,definition_hash,active,source_path) "
            "VALUES (:definition_id,:definition_key,'1.0.0','1.0','{}'::jsonb,"
            ":hash,false,'synthetic/inference-transfer-stage-check-only.yaml')"
        ),
        {
            "definition_id": "wfdef_" + identity,
            "definition_key": "synthetic-transfer-stage-" + identity,
            "hash": "sha256:" + "a" * 64,
        },
    )
    connection.execute(
        text(
            "INSERT INTO app.workflow_instances "
            "(workflow_id,definition_id,definition_key,definition_version,definition_hash,"
            "protocol_version,role_schema_version,state,stage,current_step_key,request_payload,"
            "initial_request,runtime_context,idempotency_key,request_hash,lock_version,"
            "rework_cycle_count,created_actor_type,created_actor_id) "
            "VALUES (:workflow_id,:definition_id,:definition_key,'1.0.0',:hash,'1.0.1',"
            "'workflow-role/1.29.0','RUNNING','INFERENCE_TRANSFER','synthetic_stage_check',"
            '\'{"fixture_kind":"STAGE_CHECK_ONLY"}\'::jsonb,'
            "'{\"fixture_kind\":\"STAGE_CHECK_ONLY\"}'::jsonb,'{}'::jsonb,"
            ":idempotency_key,:request_hash,1,0,'human','synthetic-stage-constraint-test')"
        ),
        {
            "workflow_id": workflow_id,
            "definition_id": "wfdef_" + identity,
            "definition_key": "synthetic-transfer-stage-" + identity,
            "hash": "sha256:" + "a" * 64,
            "idempotency_key": "synthetic-stage-check-" + identity,
            "request_hash": "sha256:" + identity * 2,
        },
    )
    return workflow_id


def test_actual_check_accepts_dedicated_stage_but_rejects_unknown_stage(
    stage_owner_connection: Connection,
) -> None:
    workflow_id = _insert_synthetic_stage_fixture(stage_owner_connection)
    with pytest.raises(IntegrityError) as error, stage_owner_connection.begin_nested():
        stage_owner_connection.execute(
            text("UPDATE app.workflow_instances SET stage='UNKNOWN_STAGE' WHERE workflow_id=:id"),
            {"id": workflow_id},
        )
    cause = error.value.orig
    assert isinstance(cause, CheckViolation)
    assert cause.sqlstate == "23514"
    assert cause.diag.constraint_name == "ck_workflow_instances_stage"
    assert (
        stage_owner_connection.scalar(
            text("SELECT stage FROM app.workflow_instances WHERE workflow_id=:id"),
            {"id": workflow_id},
        )
        == "INFERENCE_TRANSFER"
    )


def test_downgrade_refuses_current_comparison_and_rollback_preserves_row_and_head(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_id = _insert_synthetic_stage_fixture(stage_owner_connection)
    path = Path("migrations/versions/20261010_0051_inference_transfer_stage.py")
    spec = importlib.util.spec_from_file_location("guarded_stage_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    context = MigrationContext.configure(
        stage_owner_connection,
        opts={"version_table": "alembic_version", "version_table_schema": "app"},
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    with pytest.raises(IntegrityError) as error, stage_owner_connection.begin_nested():
        migration.downgrade()
    cause = error.value.orig
    assert isinstance(cause, CheckViolation)
    assert cause.sqlstate == "23514"
    assert cause.diag.constraint_name == "ck_workflow_instances_stage"
    assert (
        stage_owner_connection.scalar(
            text("SELECT stage FROM app.workflow_instances WHERE workflow_id=:id"),
            {"id": workflow_id},
        )
        == "INFERENCE_TRANSFER"
    )
    assert stage_owner_connection.scalar(text("SELECT version_num FROM app.alembic_version")) == (
        "20261010_0051"
    )
    definition = stage_owner_connection.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='app.workflow_instances'::regclass "
            "AND conname='ck_workflow_instances_stage'"
        )
    )
    assert isinstance(definition, str) and "INFERENCE_TRANSFER" in definition
