"""Exact PostgreSQL privileges required by the HWPX application manager."""

from __future__ import annotations

import json
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

TablePrivilege = Literal["SELECT", "INSERT", "UPDATE"]

READ_TABLES: Final[tuple[str, ...]] = (
    "alembic_version",
    "artifact_revisions",
    "artifacts",
    "hwpx_application_builds",
    "hwpx_assessment_assembly_builds",
    "hwpx_curated_builds",
    "curated_document_assemblies",
    "curated_document_assembly_revisions",
    "curated_document_assembly_placements",
    "content_intake_source_files",
    "external_item_sources",
    "external_item_source_revisions",
    "external_item_imports",
    "external_item_edition_documents",
    # Current-actor/source authorization is read-only; no credential table is granted.
    "operators",
    "permissions",
    "roles",
    "role_permissions",
    "operator_role_assignments",
    "knowledge_corpora",
    "knowledge_graph_snapshots",
    "knowledge_nodes",
    "knowledge_node_source_pointers",
    "knowledge_snapshot_analyses",
    "assessment_item_occurrence_references",
    "assessment_assemblies",
    "assessment_assembly_revisions",
    "item_components",
    "item_revisions",
    "items",
    "job_events",
    "jobs",
    "protocol_versions",
)

INSERT_TABLES: Final[tuple[str, ...]] = (
    "artifact_revisions",
    "artifacts",
    "job_events",
    "jobs",
    "protocol_versions",
)

UPDATE_TABLES: Final[tuple[str, ...]] = (
    "hwpx_application_builds",
    "hwpx_assessment_assembly_builds",
    "hwpx_curated_builds",
    "jobs",
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


def manager_runtime_privileges_ready(connection: Connection) -> bool:
    """Check the closed positive privilege matrix without mutating the database."""

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
