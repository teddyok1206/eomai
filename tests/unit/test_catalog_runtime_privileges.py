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
    content_intake_tables = {
        "content_intake_batches",
        "content_intake_events",
        "content_intake_source_files",
    }
    assert content_intake_tables <= set(READ_TABLES)
    assert content_intake_tables <= set(INSERT_TABLES)
    assert "content_intake_batches" in UPDATE_TABLES
    assert {"content_intake_events", "content_intake_source_files"}.isdisjoint(UPDATE_TABLES)
    batch_tables = {
        "knowledge_analysis_batches",
        "knowledge_analysis_batch_ranges",
        "knowledge_analysis_batch_events",
    }
    assert batch_tables <= set(READ_TABLES)
    assert batch_tables <= set(INSERT_TABLES)
    assert {"knowledge_analysis_batches", "knowledge_analysis_batch_ranges"} <= set(UPDATE_TABLES)
    assert "knowledge_analysis_batch_events" not in UPDATE_TABLES
    for table in (
        "knowledge_corpora",
        "knowledge_corpus_revisions",
        "knowledge_graph_snapshots",
        "knowledge_graph_publications",
        "knowledge_nodes",
        "knowledge_node_terms",
        "knowledge_edges",
        "knowledge_node_source_pointers",
        "knowledge_edge_source_pointers",
        "knowledge_snapshot_analyses",
        "curriculum_units",
        "curriculum_unit_closure",
        "item_element_refs",
    ):
        assert table in READ_TABLES
        assert table in INSERT_TABLES
    assert "knowledge_corpora" in UPDATE_TABLES
    for table in (
        "education_retrieval_requests",
        "evidence_bundles",
        "evidence_bundle_revisions",
        "evidence_bundle_entries",
    ):
        assert table in READ_TABLES
        assert table in INSERT_TABLES
    assert "education_retrieval_access_policy_revisions" in READ_TABLES
    assert "education_retrieval_access_policy_revisions" not in INSERT_TABLES
    assert "evidence_bundles" in UPDATE_TABLES
    assert "evidence_bundle_revisions" not in UPDATE_TABLES
    assert "knowledge_graph_snapshots" not in UPDATE_TABLES
    immutable_legacy_tables = {
        "assessment_assembly_revisions",
        "assessment_form_revisions",
        "assessment_item_placements",
        "legacy_usage_mapping_contract_revisions",
        "legacy_usage_row_proposals",
        "legacy_usage_row_reviews",
        "product_usage_projections",
        "publication_revisions",
        "usage_records_v1",
    }
    mutable_legacy_headers = {
        "assessment_assemblies",
        "assessment_forms",
        "legacy_usage_imports",
        "legacy_usage_mapping_contracts",
        "publications",
    }
    assert immutable_legacy_tables | mutable_legacy_headers <= set(READ_TABLES)
    assert immutable_legacy_tables | mutable_legacy_headers <= set(INSERT_TABLES)
    assert immutable_legacy_tables.isdisjoint(UPDATE_TABLES)
    assert mutable_legacy_headers <= set(UPDATE_TABLES)
    immutable_item_origin_tables = {
        "organization_revisions",
        "organization_aliases",
        "organization_source_evidence",
        "assessment_occurrence_revisions",
        "assessment_occurrence_source_evidence",
        "item_origin_profiles",
        "item_origin_occurrences",
        "item_origin_derivations",
        "item_origin_provenance",
    }
    mutable_item_origin_headers = {"organizations", "assessment_occurrences"}
    assert immutable_item_origin_tables | mutable_item_origin_headers <= set(READ_TABLES)
    assert immutable_item_origin_tables | mutable_item_origin_headers <= set(INSERT_TABLES)
    assert immutable_item_origin_tables.isdisjoint(UPDATE_TABLES)
    assert mutable_item_origin_headers <= set(UPDATE_TABLES)
    immutable_legacy_assessment_tables = {
        "assessment_source_bundle_revisions",
        "assessment_source_bundle_members",
        "assessment_layout_observations",
        "legacy_item_extraction_acceptances",
        "legacy_item_extraction_decisions",
        "legacy_item_corpus_coverages",
        "legacy_item_corpus_bundle_coverages",
    }
    assert immutable_legacy_assessment_tables | {"assessment_source_bundles"} <= set(READ_TABLES)
    assert immutable_legacy_assessment_tables | {"assessment_source_bundles"} <= set(INSERT_TABLES)
    assert immutable_legacy_assessment_tables.isdisjoint(UPDATE_TABLES)
    assert "assessment_source_bundles" in UPDATE_TABLES
    assert {"deliverables", "deliverable_revisions"} <= set(READ_TABLES)
    assert {"deliverables", "deliverable_revisions"}.isdisjoint(INSERT_TABLES)
    assert {"deliverables", "deliverable_revisions"}.isdisjoint(UPDATE_TABLES)
    assert "api_sessions" not in READ_TABLES
    assert "api_tokens" not in READ_TABLES
    assert "operator_credentials" not in READ_TABLES
    assert "content_pack_activations" not in UPDATE_TABLES
    educational_document_tables = {
        "educational_documents",
        "educational_document_revisions",
        "educational_document_registrations",
    }
    assert educational_document_tables <= set(READ_TABLES)
    assert educational_document_tables <= set(INSERT_TABLES)
    assert "educational_documents" in UPDATE_TABLES
    assert "educational_document_registrations" in UPDATE_TABLES
    assert "educational_document_revisions" not in UPDATE_TABLES
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
