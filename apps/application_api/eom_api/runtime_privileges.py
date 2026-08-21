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
    "content_intake_batches",
    "content_intake_events",
    "content_intake_source_files",
    "content_pack_activations",
    "content_pack_events",
    "content_pack_files",
    "content_pack_profiles",
    "content_pack_releases",
    "content_packs",
    "deliverable_events",
    "deliverable_revisions",
    "deliverables",
    "hwpx_application_builds",
    "item_components",
    "item_events",
    "item_relationships",
    "item_revisions",
    "items",
    "operator_credentials",
    "operator_events",
    "operator_role_assignments",
    "operators",
    "permissions",
    "role_permissions",
    "roles",
    "usage_plans",
    "usage_records",
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
    "content_pack_activations",
    "content_pack_events",
    "deliverable_events",
    "deliverable_revisions",
    "deliverables",
    "hwpx_application_builds",
    "item_events",
    "operator_credentials",
    "operator_events",
    "operator_role_assignments",
    "operators",
    "usage_plans",
    "usage_records",
    "workflow_commands",
    "workflow_events",
    "workflow_instances",
)

UPDATE_TABLES: Final[tuple[str, ...]] = (
    "api_idempotency_records",
    "api_sessions",
    "api_tokens",
    "content_pack_activations",
    "content_pack_releases",
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
