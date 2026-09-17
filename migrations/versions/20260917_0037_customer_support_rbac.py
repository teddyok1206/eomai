"""Seed the additive customer-support RBAC permissions.

Revision ID: 20260917_0037
Revises: 20260917_0036
Create Date: 2026-09-17 19:00:00+00:00
"""

from __future__ import annotations

from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0037"
down_revision: str | None = "20260917_0036"
branch_labels: str | None = None
depends_on: str | None = None

NEW_PERMISSIONS = (
    "customer_support:read",
    "customer_support:create",
)
BUILT_IN_ROLES = (
    "VIEWER",
    "AUTHOR",
    "REVIEWER",
    "EDITOR",
    "ADMIN",
)


def _stable_id(prefix: str, key: str) -> str:
    return prefix + sha256(f"eom-api-v1:{prefix}:{key}".encode()).hexdigest()[:32]


def upgrade() -> None:
    permission_table = sa.table(
        "permissions",
        sa.column("permission_id", sa.String),
        sa.column("permission_key", sa.String),
        sa.column("description", sa.String),
    )
    role_permission_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "permission_id": _stable_id("permission_", key),
                "permission_key": key,
                "description": f"Allows {key}",
            }
            for key in NEW_PERMISSIONS
        ],
    )
    op.bulk_insert(
        role_permission_table,
        [
            {
                "role_id": _stable_id("role_", role_key),
                "permission_id": _stable_id("permission_", permission_key),
            }
            for role_key in BUILT_IN_ROLES
            for permission_key in NEW_PERMISSIONS
        ],
    )


def downgrade() -> None:
    for permission_key in NEW_PERMISSIONS:
        permission_id = _stable_id("permission_", permission_key)
        op.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :permission_id").bindparams(
                permission_id=permission_id
            )
        )
        op.execute(
            sa.text("DELETE FROM permissions WHERE permission_id = :permission_id").bindparams(
                permission_id=permission_id
            )
        )
