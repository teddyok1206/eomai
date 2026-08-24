"""Seed the additive knowledge-analysis RBAC permissions.

Revision ID: 20260824_0012
Revises: 20260823_0011
Create Date: 2026-08-24 02:25:00Z
"""

from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0012"
down_revision: str | Sequence[str] | None = "20260823_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = (
    "knowledge_analysis:read",
    "knowledge_analysis:create",
    "knowledge_analysis:review",
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
                "role_id": _stable_id("role_", "ADMIN"),
                "permission_id": _stable_id("permission_", key),
            }
            for key in NEW_PERMISSIONS
        ],
    )


def downgrade() -> None:
    for key in NEW_PERMISSIONS:
        permission_id = _stable_id("permission_", key)
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
