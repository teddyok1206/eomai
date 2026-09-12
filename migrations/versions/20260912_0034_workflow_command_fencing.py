"""add per-acquisition Workflow command fencing identity

Revision ID: 20260912_0034
Revises: 20260909_0033
Create Date: 2026-09-12 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0034"
down_revision: str | None = "20260909_0033"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_commands",
        sa.Column("lease_token", sa.String(length=41), nullable=True),
    )
    op.add_column(
        "workflow_commands",
        sa.Column(
            "lease_generation",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index(
        "uq_workflow_commands_lease_token",
        "workflow_commands",
        ["lease_token"],
        unique=True,
        postgresql_where=sa.text("lease_token IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_workflow_commands_lease_token", table_name="workflow_commands")
    op.drop_column("workflow_commands", "lease_generation")
    op.drop_column("workflow_commands", "lease_token")
