"""Actual schema-owner transaction admission for the two fixed native maintenance uses."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

WORKFLOW_MAINTENANCE_TABLES = (
    "workflow_commands",
    "workflow_events",
    "workflow_instances",
    "workflow_step_runs",
)
ALLOCATED_MAINTENANCE_TABLES = tuple(sorted((*WORKFLOW_MAINTENANCE_TABLES, "jobs", "job_events")))


class NativeWorkflowMaintenanceAuthorityError(ValueError):
    def __init__(self, reason: Literal["CONTEXT_INVALID", "OWNER_REQUIRED"]) -> None:
        self.reason = reason
        super().__init__("NATIVE_WORKFLOW_MAINTENANCE_" + reason)


def require_native_workflow_maintenance_owner(
    session: Session, required_tables: tuple[str, ...]
) -> str:
    """Deployment-owner metadata authority, never runtime IAM/source permission.

    Trusted applications supply one of the two fixed table sets; callers cannot
    narrow a maintenance check to one table or claim a role through a DTO.
    """
    root = session.get_transaction()
    if (
        required_tables not in (WORKFLOW_MAINTENANCE_TABLES, ALLOCATED_MAINTENANCE_TABLES)
        or root is None
        or not root.is_active
        or session.in_nested_transaction()
        or session.new
        or session.dirty
        or session.deleted
        or session.get_bind().dialect.name != "postgresql"
    ):
        raise NativeWorkflowMaintenanceAuthorityError("CONTEXT_INVALID")
    principal, current, writable, isolation = session.execute(
        text(
            "SELECT SESSION_USER,CURRENT_USER,"
            "pg_catalog.current_setting('transaction_read_only')='off',"
            "pg_catalog.current_setting('transaction_isolation')"
        )
    ).one()
    owners = session.execute(
        text(
            "SELECT c.relname,pg_catalog.pg_get_userbyid(c.relowner) "
            "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='app' AND c.relkind='r' AND c.relname = ANY(:required_names)"
        ),
        {"required_names": list(required_tables)},
    ).all()
    if (
        not isinstance(principal, str)
        or current != principal
        or len(owners) != len(required_tables)
        or any(owner != principal for _table, owner in owners)
    ):
        raise NativeWorkflowMaintenanceAuthorityError("OWNER_REQUIRED")
    if writable is not True or isolation != "read committed":
        raise NativeWorkflowMaintenanceAuthorityError("CONTEXT_INVALID")
    return principal
