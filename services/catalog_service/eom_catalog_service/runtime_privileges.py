"""Least-privilege PostgreSQL contract for the private Catalog application runtime."""

from __future__ import annotations

import json
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

TablePrivilege = Literal["SELECT", "INSERT", "UPDATE"]

READ_TABLES: Final[tuple[str, ...]] = (
    "alembic_version",
    "assessment_assemblies",
    "assessment_assembly_revisions",
    "assessment_form_revisions",
    "assessment_forms",
    "assessment_item_placements",
    "artifact_revisions",
    "artifacts",
    "content_intake_batches",
    "content_intake_source_files",
    "content_pack_files",
    "content_pack_profiles",
    "content_pack_releases",
    "content_packs",
    "curriculum_unit_closure",
    "curriculum_units",
    "deliverable_revisions",
    "deliverables",
    "education_retrieval_access_policy_revisions",
    "education_retrieval_requests",
    "educational_document_revisions",
    "educational_document_registrations",
    "educational_documents",
    "evidence_bundle_entries",
    "evidence_bundle_revisions",
    "evidence_bundles",
    "execution_bundle_revisions",
    "execution_bundles",
    "execution_preset_revisions",
    "execution_preset_role_policies",
    "execution_presets",
    "item_components",
    "item_events",
    "item_metadata_snapshots",
    "item_provenance",
    "item_relationships",
    "item_revisions",
    "items",
    "job_events",
    "jobs",
    "knowledge_analysis_events",
    "knowledge_analysis_batch_events",
    "knowledge_analysis_batch_ranges",
    "knowledge_analysis_batches",
    "knowledge_analysis_reviews",
    "knowledge_analysis_risk_policy_revisions",
    "knowledge_analysis_runs",
    "knowledge_corpora",
    "knowledge_corpus_revisions",
    "knowledge_edge_source_pointers",
    "knowledge_edges",
    "knowledge_graph_publications",
    "knowledge_graph_snapshots",
    "knowledge_node_source_pointers",
    "knowledge_node_terms",
    "knowledge_nodes",
    "knowledge_snapshot_analyses",
    "legacy_usage_imports",
    "legacy_usage_mapping_contract_revisions",
    "legacy_usage_mapping_contracts",
    "legacy_usage_row_proposals",
    "legacy_usage_row_reviews",
    "item_element_refs",
    "operators",
    "protocol_versions",
    "publication_revisions",
    "publications",
    "product_usage_projections",
    "resolved_execution_plan_steps",
    "resolved_execution_plans",
    "worker_capacity_policies",
    "worker_capacity_policy_revisions",
    "worker_capacity_pool_roles",
    "worker_capacity_pool_slots",
    "worker_capacity_pools",
    "workflow_commands",
    "workflow_definitions",
    "workflow_events",
    "workflow_instances",
    "workflow_step_runs",
    "usage_records_v1",
)

INSERT_TABLES: Final[tuple[str, ...]] = (
    "assessment_assemblies",
    "assessment_assembly_revisions",
    "assessment_form_revisions",
    "assessment_forms",
    "assessment_item_placements",
    "artifact_revisions",
    "artifacts",
    "curriculum_unit_closure",
    "curriculum_units",
    "education_retrieval_requests",
    "educational_document_revisions",
    "educational_document_registrations",
    "educational_documents",
    "evidence_bundle_entries",
    "evidence_bundle_revisions",
    "evidence_bundles",
    "item_components",
    "item_events",
    "item_metadata_snapshots",
    "item_provenance",
    "item_relationships",
    "item_revisions",
    "items",
    "job_events",
    "jobs",
    "knowledge_analysis_events",
    "knowledge_analysis_batch_events",
    "knowledge_analysis_batch_ranges",
    "knowledge_analysis_batches",
    "knowledge_analysis_reviews",
    "knowledge_analysis_runs",
    "knowledge_corpora",
    "knowledge_corpus_revisions",
    "knowledge_edge_source_pointers",
    "knowledge_edges",
    "knowledge_graph_publications",
    "knowledge_graph_snapshots",
    "knowledge_node_source_pointers",
    "knowledge_node_terms",
    "knowledge_nodes",
    "knowledge_snapshot_analyses",
    "legacy_usage_imports",
    "legacy_usage_mapping_contract_revisions",
    "legacy_usage_mapping_contracts",
    "legacy_usage_row_proposals",
    "legacy_usage_row_reviews",
    "item_element_refs",
    "protocol_versions",
    "publication_revisions",
    "publications",
    "product_usage_projections",
    "resolved_execution_plan_steps",
    "resolved_execution_plans",
    "workflow_commands",
    "workflow_events",
    "workflow_instances",
    "usage_records_v1",
)

UPDATE_TABLES: Final[tuple[str, ...]] = (
    "assessment_assemblies",
    "assessment_forms",
    "educational_document_registrations",
    "educational_documents",
    "evidence_bundles",
    "item_revisions",
    "items",
    "jobs",
    "knowledge_analysis_batch_ranges",
    "knowledge_analysis_batches",
    "knowledge_analysis_runs",
    "knowledge_corpora",
    "legacy_usage_imports",
    "legacy_usage_mapping_contracts",
    "publications",
    "workflow_instances",
)

TABLE_PRIVILEGES: Final[tuple[tuple[TablePrivilege, tuple[str, ...]], ...]] = (
    ("SELECT", READ_TABLES),
    ("INSERT", INSERT_TABLES),
    ("UPDATE", UPDATE_TABLES),
)

_REQUIRED_PRIVILEGES_JSON: Final[str] = json.dumps(
    [
        {"table_name": table_name, "privilege": privilege}
        for privilege, table_names in TABLE_PRIVILEGES
        for table_name in table_names
    ],
    separators=(",", ":"),
    sort_keys=True,
)


def catalog_runtime_privileges_ready(connection: Connection) -> bool:
    """Check every positive grant with one read-only query."""

    value = connection.scalar(
        text(
            "SELECT COALESCE(bool_and(has_table_privilege("
            "current_user, format('app.%I', required.table_name), required.privilege"
            ")), false) "
            "FROM jsonb_to_recordset(CAST(:requirements AS jsonb)) "
            "AS required(table_name text, privilege text)"
        ),
        {"requirements": _REQUIRED_PRIVILEGES_JSON},
    )
    return value is True
