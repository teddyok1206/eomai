from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import Mock

from eom_api.runtime_privileges import INSERT_TABLES as API_INSERT_TABLES
from eom_api.runtime_privileges import UPDATE_TABLES as API_UPDATE_TABLES
from eom_hwpx_manager.runtime_privileges import (
    INSERT_TABLES,
    READ_TABLES,
    TABLE_PRIVILEGES,
    UPDATE_TABLES,
    manager_runtime_privileges_ready,
)
from sqlalchemy.engine import Connection


def test_manager_privilege_matrix_matches_owned_access_patterns() -> None:
    assert set(READ_TABLES) == {
        "alembic_version",
        "artifact_revisions",
        "artifacts",
        "hwpx_application_builds",
        "item_components",
        "item_revisions",
        "items",
        "job_events",
        "jobs",
        "protocol_versions",
    }
    assert set(INSERT_TABLES) == {
        "artifact_revisions",
        "artifacts",
        "job_events",
        "jobs",
        "protocol_versions",
    }
    assert set(UPDATE_TABLES) == {"hwpx_application_builds", "jobs"}
    assert "hwpx_application_builds" not in INSERT_TABLES
    assert not set(INSERT_TABLES) & set(API_INSERT_TABLES)
    assert "jobs" not in API_UPDATE_TABLES
    assert {privilege for privilege, _tables in TABLE_PRIVILEGES} == {
        "SELECT",
        "INSERT",
        "UPDATE",
    }


def test_manager_privilege_readiness_is_one_read_only_matrix_query() -> None:
    connection = Mock(spec=Connection)
    connection.scalar.return_value = True
    assert manager_runtime_privileges_ready(cast(Connection, connection))
    connection.scalar.assert_called_once()
    statement, parameters = connection.scalar.call_args.args
    assert "has_table_privilege" in str(statement)
    assert "protocol_versions" in parameters["requirements"]
    assert "hwpx_application_builds" in parameters["requirements"]


def test_manager_bootstrap_is_fixed_and_revokes_before_granting() -> None:
    source = Path("scripts/hwpx/bootstrap_manager_runtime_role.py").read_text(encoding="utf-8")
    assert 'ROLE = "eom_hwpx_manager_runtime"' in source
    assert 'TARGET = Path("/etc/eom/secrets/hwpx-manager.env")' in source
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES" in source
    assert "REVOKE ALL PRIVILEGES ON ALL SEQUENCES" in source
    assert "for checked_privilege in (" in source
    assert '"DELETE"' in source and '"TRUNCATE"' in source
    assert "GRANT USAGE ON ALL SEQUENCES" not in source
    assert "HWPX_MANAGER_ROLE_MEMBERSHIP_MISMATCH" in source
    assert "HWPX_MANAGER_SEQUENCE_PRIVILEGE_MISMATCH" in source
    assert "has_function_privilege" in source
    assert "HWPX_MANAGER_FUNCTION_PRIVILEGE_MISMATCH" in source
    assert "EOM_API_TOKEN_HASH_KEY" not in source.split("def main()", 1)[0]
