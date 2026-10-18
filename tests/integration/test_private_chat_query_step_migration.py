"""Opt-in guarded private-step CHECK/downgrade DDL, not runtime admission."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.errors import CheckViolation
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.integration.test_local_embedding_stage_migration import (
    _seed,
    _step,
)
from tests.integration.test_local_embedding_stage_migration import (
    empty_workflow_tables as empty_workflow_tables,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]

PRIVATE_SCHEMA = "embedding-private-chat-query-result@1.0"
PRIVATE_KEY = "encode_private_chat_query"


def migration(connection, monkeypatch):
    path = Path("migrations/versions/20261017_0057_private_chat_query_step.py")
    spec = importlib.util.spec_from_file_location("guarded_private_step_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    return module


@pytest.mark.parametrize(
    "kind,role,schema,key",
    [
        ("application", None, None, PRIVATE_KEY),
        ("application", "reviewer", PRIVATE_SCHEMA, PRIVATE_KEY),
        ("application", None, PRIVATE_SCHEMA, "encode_reference_query"),
        ("application", None, "embedding-reference-query-result@1.0", PRIVATE_KEY),
        ("agent", None, PRIVATE_SCHEMA, PRIVATE_KEY),
        ("terminal", None, PRIVATE_SCHEMA, PRIVATE_KEY),
    ],
)
def test_postgres_private_check_rejects_wrong_or_cross_purpose_tuples(
    stage_owner_connection, kind, role, schema, key
):
    _, workflow = _seed(stage_owner_connection)
    with pytest.raises(IntegrityError) as error, stage_owner_connection.begin_nested():
        _step(stage_owner_connection, workflow, step_type=kind, role=role, schema=schema, key=key)
    assert isinstance(error.value.orig, CheckViolation)
    assert error.value.orig.diag.constraint_name == "ck_workflow_step_runs_local_embedding"


def test_postgres_private_step_only_allows_attempt_one(stage_owner_connection):
    _, workflow = _seed(stage_owner_connection)
    step = _step(
        stage_owner_connection,
        workflow,
        step_type="application",
        role=None,
        schema=PRIVATE_SCHEMA,
        key=PRIVATE_KEY,
    )
    with pytest.raises(IntegrityError), stage_owner_connection.begin_nested():
        stage_owner_connection.execute(
            text("UPDATE workflow_step_runs SET attempt=2 WHERE step_run_id=:id"), {"id": step}
        )


@pytest.mark.parametrize("marker", ["key", "schema", "carrier"])
def test_postgres_private_step_downgrade_refuses_history_before_ddl(
    stage_owner_connection, monkeypatch, marker
):
    _, workflow = _seed(stage_owner_connection)
    step = _step(
        stage_owner_connection,
        workflow,
        step_type="application" if marker == "schema" else "terminal",
        role=None,
        schema=PRIVATE_SCHEMA if marker == "schema" else None,
        key="complete" if marker == "carrier" else PRIVATE_KEY,
    )
    if marker == "carrier":
        stage_owner_connection.execute(
            text(
                'UPDATE workflow_step_runs SET output_pointer_manifest=\'{"schema_version":'
                '"private-chat-query-step-output/1.0"}\'::jsonb WHERE step_run_id=:id'
            ),
            {"id": step},
        )
    query = text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname='ck_workflow_step_runs_local_embedding' "
        "AND conrelid='workflow_step_runs'::regclass"
    )
    before = stage_owner_connection.scalar(query)
    module = migration(stage_owner_connection, monkeypatch)
    with (
        pytest.raises(DBAPIError, match="absent private step"),
        stage_owner_connection.begin_nested(),
    ):
        module.downgrade()
    assert stage_owner_connection.scalar(query) == before


def test_postgres_absent_private_step_downgrade_preserves_older_tuples_and_roundtrips(
    empty_workflow_tables, monkeypatch
):
    connection = empty_workflow_tables
    _, workflow = _seed(connection)
    _step(
        connection,
        workflow,
        step_type="application",
        role=None,
        schema="incremental-embedding-result@1.0",
        key="encode_batch",
    )
    _step(
        connection,
        workflow,
        step_type="application",
        role=None,
        schema="embedding-reference-query-result@1.0",
        key="encode_reference_query",
    )
    module = migration(connection, monkeypatch)
    module.downgrade()
    with pytest.raises(IntegrityError), connection.begin_nested():
        _step(
            connection,
            workflow,
            step_type="application",
            role=None,
            schema=PRIVATE_SCHEMA,
            key=PRIVATE_KEY,
        )
    module.upgrade()
    _step(
        connection,
        workflow,
        step_type="application",
        role=None,
        schema=PRIVATE_SCHEMA,
        key=PRIVATE_KEY,
    )
