"""Opt-in QUERY CHECK/downgrade tests in the guarded disposable owner DB only.

Synthetic rows/DDL are rolled back by the existing outer owner fixture.
No live DB, IAM grant, physical QUERY, model, NAS or deployment is exercised.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.errors import CheckViolation
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.integration.test_local_embedding_stage_migration import _seed, _step

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def _migration(connection: Connection, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "guarded_query_step_migration",
        Path("migrations/versions/20261013_0054_reference_query_step.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
    return module


@pytest.mark.parametrize(
    "kind,role,schema,key",
    [
        ("application", None, None, "encode_reference_query"),
        (
            "application",
            "reviewer",
            "embedding-reference-query-result@1.0",
            "encode_reference_query",
        ),
        ("application", None, "embedding-reference-query-result@1.0", "encode_batch"),
        ("application", None, "incremental-embedding-result@1.0", "encode_reference_query"),
        ("agent", None, "embedding-reference-query-result@1.0", "encode_reference_query"),
    ],
)
def test_actual_query_check_rejects_wrong_purpose_shape(
    stage_owner_connection: Connection,
    kind: str,
    role: str | None,
    schema: str | None,
    key: str,
) -> None:
    _, workflow = _seed(stage_owner_connection)
    with pytest.raises(IntegrityError) as error, stage_owner_connection.begin_nested():
        _step(stage_owner_connection, workflow, step_type=kind, role=role, schema=schema, key=key)
    assert isinstance(error.value.orig, CheckViolation)
    assert error.value.orig.diag.constraint_name == "ck_workflow_step_runs_local_embedding"


def test_actual_query_only_attempt_one_preserves_index_and_terminal(
    stage_owner_connection: Connection,
) -> None:
    _, workflow = _seed(stage_owner_connection)
    step = _step(
        stage_owner_connection,
        workflow,
        step_type="application",
        role=None,
        schema="embedding-reference-query-result@1.0",
        key="encode_reference_query",
    )
    with pytest.raises(IntegrityError), stage_owner_connection.begin_nested():
        stage_owner_connection.execute(
            text("UPDATE workflow_step_runs SET attempt=2 WHERE step_run_id=:id"), {"id": step}
        )
    _step(
        stage_owner_connection,
        workflow,
        step_type="application",
        role=None,
        schema="incremental-embedding-result@1.0",
        key="encode_batch",
    )
    _step(
        stage_owner_connection,
        workflow,
        step_type="terminal",
        role=None,
        schema=None,
        key="complete",
    )


@pytest.mark.parametrize(
    "marker", ["definition", "protocol", "initial", "payload", "step", "carrier"]
)
def test_actual_downgrade_refuses_query_history_before_ddl(
    stage_owner_connection: Connection,
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
) -> None:
    definition, workflow = _seed(stage_owner_connection)
    if marker == "definition":
        statement = (
            "UPDATE workflow_definitions SET definition_key='local-embedding-reference-query' "
            "WHERE definition_id=:id"
        )
        stage_owner_connection.execute(text(statement), {"id": definition})
    elif marker in {"protocol", "initial", "payload"}:
        # Closed synthetic fixture statements, not a user-controlled SQL adapter.
        assignment = {
            "protocol": "role_schema_version='reference-query/1.0'",
            "initial": 'initial_request=\'{"purpose":"REFERENCE_QUERY"}\'::jsonb',
            "payload": (
                'request_payload=\'{"schema_version":'
                '"reference-query-workflow-request/1.0"}\'::jsonb'
            ),
        }[marker]
        stage_owner_connection.execute(
            text(f"UPDATE workflow_instances SET {assignment} WHERE workflow_id=:id"),
            {"id": workflow},
        )
    elif marker == "step":
        _step(
            stage_owner_connection,
            workflow,
            step_type="application",
            role=None,
            schema="embedding-reference-query-result@1.0",
            key="encode_reference_query",
        )
    else:
        step = _step(
            stage_owner_connection,
            workflow,
            step_type="terminal",
            role=None,
            schema=None,
            key="complete",
        )
        stage_owner_connection.execute(
            text(
                'UPDATE workflow_step_runs SET output_pointer_manifest=\'{"schema_version":'
                '"reference-query-step-output/1.0"}\'::jsonb WHERE step_run_id=:id'
            ),
            {"id": step},
        )
    check = text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname='ck_workflow_step_runs_local_embedding' "
        "AND conrelid='workflow_step_runs'::regclass"
    )
    before = stage_owner_connection.scalar(check)
    module = _migration(stage_owner_connection, monkeypatch)
    with pytest.raises(DBAPIError, match="absent QUERY"), stage_owner_connection.begin_nested():
        module.downgrade()
    assert stage_owner_connection.scalar(check) == before


def test_empty_query_downgrade_keeps_index_and_round_trips_only_check(
    stage_owner_connection: Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, workflow = _seed(stage_owner_connection)
    _step(
        stage_owner_connection,
        workflow,
        step_type="application",
        role=None,
        schema="incremental-embedding-result@1.0",
        key="encode_batch",
    )
    module = _migration(stage_owner_connection, monkeypatch)
    module.downgrade()
    with pytest.raises(IntegrityError), stage_owner_connection.begin_nested():
        _step(
            stage_owner_connection,
            workflow,
            step_type="application",
            role=None,
            schema="embedding-reference-query-result@1.0",
            key="encode_reference_query",
        )
    module.upgrade()
    _step(
        stage_owner_connection,
        workflow,
        step_type="application",
        role=None,
        schema="embedding-reference-query-result@1.0",
        key="encode_reference_query",
    )
