from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

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
        assert revision == "20260817_0006"
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
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("UPDATE app.alembic_version SET version_num = version_num")
        connection.rollback()
    connection.close()
