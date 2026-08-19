"""Sanitized liveness and readiness checks."""

from __future__ import annotations

from eom_identity_service.models import (
    OperatorRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RoleRecord,
)
from sqlalchemy import func, select, text

from eom_api.lifespan import AppServices
from eom_api.runtime_privileges import runtime_table_privileges_ready

EXPECTED_MIGRATION_HEAD = "20260818_0007"


def readiness(services: AppServices) -> bool:
    try:
        with services.engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            role_count = connection.scalar(select(func.count()).select_from(RoleRecord))
            permission_count = connection.scalar(select(func.count()).select_from(PermissionRecord))
            runtime_privileges = runtime_table_privileges_ready(connection)
        return bool(
            revision == EXPECTED_MIGRATION_HEAD
            and role_count == 5
            and permission_count == 34
            and runtime_privileges
            and services.settings.server.host in {"127.0.0.1", "localhost", "::1"}
        )
    except Exception:
        return False


def runtime_database_privileges(services: AppServices) -> bool:
    """Check the reviewed positive grant matrix without exposing connection details."""

    try:
        with services.engine.connect() as connection:
            return runtime_table_privileges_ready(connection)
    except Exception:
        return False


def active_admin_exists(services: AppServices) -> bool:
    with services.engine.connect() as connection:
        count = connection.scalar(
            select(func.count())
            .select_from(OperatorRecord)
            .join(
                OperatorRoleAssignmentRecord,
                OperatorRoleAssignmentRecord.operator_id == OperatorRecord.operator_id,
            )
            .join(RoleRecord, RoleRecord.role_id == OperatorRoleAssignmentRecord.role_id)
            .where(
                OperatorRecord.status == "ACTIVE",
                OperatorRoleAssignmentRecord.revoked_at.is_(None),
                RoleRecord.role_key == "ADMIN",
            )
        )
        return bool(count)
