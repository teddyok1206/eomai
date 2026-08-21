from __future__ import annotations

from typing import cast
from unittest.mock import Mock

from eom_api.runtime_privileges import (
    INSERT_TABLES,
    READ_TABLES,
    TABLE_PRIVILEGES,
    UPDATE_TABLES,
    runtime_table_privileges_ready,
)
from sqlalchemy.engine import Connection


def test_runtime_privilege_matrix_covers_workflow_approval_lock() -> None:
    assert "workflow_instances" in READ_TABLES
    assert "workflow_instances" in UPDATE_TABLES
    assert "workflow_commands" in READ_TABLES
    assert "workflow_commands" in INSERT_TABLES
    assert "approval_requests" in READ_TABLES
    assert "approval_requests" not in UPDATE_TABLES
    assert "workflow_events" in READ_TABLES
    assert "workflow_events" in INSERT_TABLES
    assert "workflow_events" not in UPDATE_TABLES
    assert "hwpx_application_builds" in READ_TABLES
    assert "hwpx_application_builds" in INSERT_TABLES
    assert "hwpx_application_builds" in UPDATE_TABLES
    assert {privilege for privilege, _tables in TABLE_PRIVILEGES} == {
        "SELECT",
        "INSERT",
        "UPDATE",
    }


def test_runtime_privilege_readiness_uses_one_read_only_matrix_query() -> None:
    connection = Mock(spec=Connection)
    connection.scalar.return_value = True

    assert runtime_table_privileges_ready(cast(Connection, connection))

    connection.scalar.assert_called_once()
    statement, parameters = connection.scalar.call_args.args
    sql = str(statement)
    assert "has_table_privilege" in sql
    assert "current_user" in sql
    assert "workflow_instances" in parameters["requirements"]
    assert "UPDATE" in parameters["requirements"]


def test_runtime_privilege_readiness_rejects_a_missing_grant() -> None:
    connection = Mock(spec=Connection)
    connection.scalar.return_value = False

    assert not runtime_table_privileges_ready(cast(Connection, connection))
