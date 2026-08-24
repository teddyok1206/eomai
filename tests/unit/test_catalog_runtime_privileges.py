from __future__ import annotations

from typing import cast
from unittest.mock import Mock

from eom_catalog_service.runtime_privileges import (
    INSERT_TABLES,
    READ_TABLES,
    TABLE_PRIVILEGES,
    UPDATE_TABLES,
    catalog_runtime_privileges_ready,
)
from sqlalchemy.engine import Connection


def test_catalog_runtime_grants_only_its_application_boundary() -> None:
    for table in (
        "artifacts",
        "artifact_revisions",
        "jobs",
        "job_events",
        "knowledge_analysis_runs",
        "knowledge_analysis_events",
        "knowledge_analysis_reviews",
    ):
        assert table in READ_TABLES
        assert table in INSERT_TABLES
    assert "knowledge_analysis_risk_policy_revisions" in READ_TABLES
    assert "knowledge_analysis_risk_policy_revisions" not in INSERT_TABLES
    assert "knowledge_analysis_runs" in UPDATE_TABLES
    assert "jobs" in UPDATE_TABLES
    assert "api_sessions" not in READ_TABLES
    assert "api_tokens" not in READ_TABLES
    assert "operator_credentials" not in READ_TABLES
    assert "content_pack_activations" not in UPDATE_TABLES
    assert {privilege for privilege, _tables in TABLE_PRIVILEGES} == {
        "SELECT",
        "INSERT",
        "UPDATE",
    }


def test_catalog_runtime_readiness_is_one_read_only_matrix_query() -> None:
    connection = Mock(spec=Connection)
    connection.scalar.return_value = True
    assert catalog_runtime_privileges_ready(cast(Connection, connection))
    statement, parameters = connection.scalar.call_args.args
    assert "has_table_privilege" in str(statement)
    assert "knowledge_analysis_runs" in parameters["requirements"]


def test_catalog_runtime_readiness_fails_on_a_missing_grant() -> None:
    connection = Mock(spec=Connection)
    connection.scalar.return_value = False
    assert not catalog_runtime_privileges_ready(cast(Connection, connection))
