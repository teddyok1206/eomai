from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from eom_api.runtime_privileges import TABLE_PRIVILEGES
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from psycopg import sql

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_disposable_runtime_role_allows_dml_and_denies_schema_changes() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("run through scripts/api/testdb_run.sh with a disposable database")
    environment = Path(os.environ["EOM_API_TEST_RUNTIME_ENV"])
    values: dict[str, str] = {}
    for line in environment.read_text(encoding="ascii").splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    assert set(values) == {
        "EOM_API_DATABASE_URL",
        "EOM_API_FINGERPRINT_KEY",
        "EOM_API_TOKEN_HASH_KEY",
    }

    connection = psycopg.connect(values["EOM_API_DATABASE_URL"].replace("+psycopg", ""))
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, version_num FROM app.alembic_version")
        current_user, revision = cursor.fetchone() or (None, None)
        assert str(current_user).startswith("eom_api_test_runtime_")
        assert revision == CURRENT_MIGRATION_REVISION
        for privilege, tables in TABLE_PRIVILEGES:
            for table_name in tables:
                cursor.execute(
                    "SELECT has_table_privilege(current_user, %s, %s)",
                    (f"app.{table_name}", privilege),
                )
                assert cursor.fetchone() == (True,)
        cursor.execute("SELECT workflow_id FROM app.workflow_instances WHERE false FOR UPDATE")
        cursor.execute(
            "INSERT INTO app.api_audit_events "
            "(api_audit_event_id, request_id, event_type, operation_id, http_method, "
            "route_template, outcome, http_status, created_at) "
            "VALUES ('apiaudit_test_runtime_role_00000001', 'req_runtime_role_live', "
            "'PRIVILEGE_PROBE', 'runtime_role_live', 'POST', '/internal/test', "
            "'ROLLED_BACK', 204, CURRENT_TIMESTAMP)"
        )
        connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("CREATE TABLE app.eom_api_runtime_live_probe (id integer)")
        connection.rollback()
        for statement in (
            "ALTER TABLE app.operators ADD COLUMN eom_api_runtime_live_probe integer",
            "DROP TABLE app.operators",
            "TRUNCATE TABLE app.api_audit_events",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(statement)
            connection.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("UPDATE app.alembic_version SET version_num = version_num")
        connection.rollback()
    connection.close()


def test_workflow_approval_lock_reproduces_the_pre_fix_privilege_boundary() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("run through scripts/api/testdb_run.sh with a disposable database")
    environment = Path(os.environ["EOM_API_TEST_RUNTIME_ENV"])
    values = dict(
        line.split("=", 1) for line in environment.read_text(encoding="ascii").splitlines()
    )
    runtime = psycopg.connect(values["EOM_API_DATABASE_URL"].replace("+psycopg", ""))
    owner = psycopg.connect(os.environ["EOM_DATABASE_URL"].replace("+psycopg", ""))
    with runtime.cursor() as runtime_cursor:
        runtime_cursor.execute("SELECT current_user")
        runtime_role = str((runtime_cursor.fetchone() or ("",))[0])
    runtime.commit()
    owner.autocommit = True
    try:
        with owner.cursor() as owner_cursor:
            owner_cursor.execute(
                sql.SQL("REVOKE UPDATE ON TABLE app.workflow_instances FROM {}").format(
                    sql.Identifier(runtime_role)
                )
            )
        with (
            runtime.cursor() as runtime_cursor,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            runtime_cursor.execute(
                "SELECT workflow_id FROM app.workflow_instances WHERE false FOR UPDATE"
            )
        runtime.rollback()
    finally:
        with owner.cursor() as owner_cursor:
            owner_cursor.execute(
                sql.SQL("GRANT UPDATE ON TABLE app.workflow_instances TO {}").format(
                    sql.Identifier(runtime_role)
                )
            )
    with runtime.cursor() as runtime_cursor:
        runtime_cursor.execute(
            "SELECT workflow_id FROM app.workflow_instances WHERE false FOR UPDATE"
        )
    runtime.rollback()
    runtime.close()
    owner.close()
