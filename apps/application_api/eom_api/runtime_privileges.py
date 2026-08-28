"""Reviewed PostgreSQL table privileges required by the Application API runtime."""

from __future__ import annotations

import json
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

TablePrivilege = Literal["SELECT", "INSERT", "UPDATE"]

READ_TABLES: Final[tuple[str, ...]] = (
    "alembic_version",
    "api_audit_events",
    "api_idempotency_records",
    "api_sessions",
    "api_tokens",
    "approval_requests",
    "artifact_revisions",
    "artifacts",
    "content_intake_batches",
    "content_intake_events",
    "content_intake_source_files",
    "content_pack_activations",
    "content_pack_events",
    "content_pack_files",
    "content_pack_profiles",
    "content_pack_releases",
    "content_packs",
    "codex_auth_bindings",
    "codex_auth_assignment_revisions",
    "codex_auth_enrollments",
    "codex_auth_health_events",
    "codex_capability_entries",
    "codex_capability_snapshots",
    "codex_control_commands",
    "deliverable_events",
    "deliverable_revisions",
    "deliverables",
    "education_retrieval_access_policy_revisions",
    "education_retrieval_requests",
    "educational_document_revisions",
    "educational_documents",
    "evidence_bundle_entries",
    "evidence_bundle_revisions",
    "evidence_bundles",
    "execution_bundle_revisions",
    "execution_bundles",
    "execution_preset_evaluations",
    "execution_preset_revisions",
    "execution_preset_role_policies",
    "execution_presets",
    "hwpx_application_builds",
    "item_components",
    "item_events",
    "item_relationships",
    "item_revisions",
    "items",
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
    "knowledge_nodes",
    "knowledge_snapshot_analyses",
    "curriculum_unit_closure",
    "curriculum_units",
    "item_element_refs",
    "operator_credentials",
    "operator_events",
    "operator_role_assignments",
    "operators",
    "permissions",
    "protocol_versions",
    "resolved_execution_plan_steps",
    "resolved_execution_plans",
    "role_permissions",
    "roles",
    "usage_plans",
    "usage_records",
    "worker_capacity_policies",
    "worker_capacity_policy_revisions",
    "worker_capacity_pool_roles",
    "worker_capacity_pool_slots",
    "worker_capacity_pools",
    "worker_lease_events",
    "worker_leases",
    "worker_slots",
    "workflow_commands",
    "workflow_definitions",
    "workflow_events",
    "workflow_instances",
    "workflow_step_runs",
)

INSERT_TABLES: Final[tuple[str, ...]] = (
    "api_audit_events",
    "api_idempotency_records",
    "api_sessions",
    "api_tokens",
    "codex_auth_enrollments",
    "content_pack_activations",
    "content_pack_events",
    "deliverable_events",
    "deliverable_revisions",
    "deliverables",
    "execution_preset_revisions",
    "execution_preset_role_policies",
    "execution_presets",
    "hwpx_application_builds",
    "item_events",
    "operator_credentials",
    "operator_events",
    "operator_role_assignments",
    "operators",
    "resolved_execution_plan_steps",
    "resolved_execution_plans",
    "usage_plans",
    "usage_records",
    "workflow_commands",
    "workflow_events",
    "workflow_instances",
    "codex_control_commands",
)

UPDATE_TABLES: Final[tuple[str, ...]] = (
    "api_idempotency_records",
    "api_sessions",
    "api_tokens",
    "codex_auth_enrollments",
    "content_pack_activations",
    "content_pack_releases",
    "execution_presets",
    "hwpx_application_builds",
    "items",
    "operator_credentials",
    "operator_role_assignments",
    "operators",
    "usage_plans",
    # PostgreSQL requires UPDATE privilege for SELECT ... FOR UPDATE. Workflow
    # actions lock this row before checking the ETag and enqueueing a command.
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


def runtime_table_privileges_ready(connection: Connection) -> bool:
    """Return whether the connected role has the exact required positive grants.

    Prohibited grants remain enforced by the reconciliation script. Readiness only
    needs to detect a missing runtime capability without mutating production data.
    """

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
