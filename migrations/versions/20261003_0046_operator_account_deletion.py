"""add permanent Operator account tombstones

Revision ID: 20261003_0046
Revises: 20261002_0045
Create Date: 2026-10-03 00:00:00.000000
"""

from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_0046"
down_revision: str | None = "20261002_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION_KEY = "operator:delete"


def _stable_id(prefix: str, key: str) -> str:
    return prefix + sha256(f"eom-api-v1:{prefix}:{key}".encode()).hexdigest()[:32]


def upgrade() -> None:
    op.add_column("operators", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("operators", sa.Column("deleted_by", sa.String(length=128)))
    op.add_column("operators", sa.Column("delete_reason", sa.Text()))
    op.create_index("ix_operators_deleted", "operators", ["deleted_at"])

    permission_id = _stable_id("permission_", PERMISSION_KEY)
    permissions = sa.table(
        "permissions",
        sa.column("permission_id", sa.String),
        sa.column("permission_key", sa.String),
        sa.column("description", sa.String),
    )
    op.bulk_insert(
        permissions,
        [
            {
                "permission_id": permission_id,
                "permission_key": PERMISSION_KEY,
                "description": "Allows permanent Operator account deletion",
            }
        ],
    )
    op.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT role_id, :permission_id FROM roles WHERE role_key = 'ADMIN'"
        ).bindparams(permission_id=permission_id)
    )


def downgrade() -> None:
    permission_id = _stable_id("permission_", PERMISSION_KEY)
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
    op.drop_index("ix_operators_deleted", table_name="operators")
    op.drop_column("operators", "delete_reason")
    op.drop_column("operators", "deleted_by")
    op.drop_column("operators", "deleted_at")
