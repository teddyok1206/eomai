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
    # The private Catalog application process reuses the DB-only API runtime role
    # and must resolve the logical Artifact row for pinned media pointers.  This
    # remains metadata read-only; artifact registration stays outside the API.
    assert "artifacts" in READ_TABLES
    assert "artifacts" not in INSERT_TABLES
    assert "artifacts" not in UPDATE_TABLES
    assert "codex_control_commands" in READ_TABLES
    assert "codex_control_commands" in INSERT_TABLES
    assert "codex_control_commands" not in UPDATE_TABLES
    assert "codex_auth_bindings" in READ_TABLES
    assert "codex_auth_bindings" not in INSERT_TABLES
    assert "codex_auth_bindings" in UPDATE_TABLES
    assert "execution_presets" in READ_TABLES
    assert "execution_presets" in INSERT_TABLES
    assert "execution_presets" in UPDATE_TABLES
    assert "execution_preset_revisions" in INSERT_TABLES
    assert "execution_preset_role_policies" in INSERT_TABLES
    assert "resolved_execution_plans" in READ_TABLES
    assert "resolved_execution_plans" in INSERT_TABLES
    assert "resolved_execution_plans" not in UPDATE_TABLES
    for table in (
        "knowledge_analysis_events",
        "knowledge_analysis_reviews",
        "knowledge_analysis_risk_policy_revisions",
        "knowledge_analysis_runs",
    ):
        assert table in READ_TABLES
        assert table not in INSERT_TABLES
        assert table not in UPDATE_TABLES
    batch_tables = {
        "knowledge_analysis_batches",
        "knowledge_analysis_batch_ranges",
        "knowledge_analysis_batch_events",
    }
    assert batch_tables <= set(READ_TABLES)
    assert batch_tables.isdisjoint(INSERT_TABLES)
    assert batch_tables.isdisjoint(UPDATE_TABLES)
    educational_document_tables = {
        "educational_documents",
        "educational_document_revisions",
    }
    assert educational_document_tables <= set(READ_TABLES)
    assert educational_document_tables.isdisjoint(INSERT_TABLES)
    assert educational_document_tables.isdisjoint(UPDATE_TABLES)
    for table in (
        "knowledge_corpora",
        "knowledge_corpus_revisions",
        "knowledge_graph_snapshots",
        "knowledge_graph_publications",
        "knowledge_nodes",
        "knowledge_edges",
        "knowledge_node_source_pointers",
        "knowledge_edge_source_pointers",
        "knowledge_snapshot_analyses",
        "curriculum_units",
        "curriculum_unit_closure",
        "item_element_refs",
        "education_retrieval_access_policy_revisions",
        "education_retrieval_requests",
        "evidence_bundles",
        "evidence_bundle_revisions",
        "evidence_bundle_entries",
    ):
        assert table in READ_TABLES
        assert table not in INSERT_TABLES
        assert table not in UPDATE_TABLES
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
