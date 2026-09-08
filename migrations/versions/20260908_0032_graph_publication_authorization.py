"""persist Graph publication authorization time

Revision ID: 20260908_0032
Revises: 20260907_0031
Create Date: 2026-09-08 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0032"
down_revision: str | None = "20260907_0031"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_graph_publications",
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE knowledge_graph_publications SET authorized_at = requested_at "
        "WHERE authorized_at IS NULL"
    )
    op.alter_column(
        "knowledge_graph_publications",
        "authorized_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("knowledge_graph_publications", "authorized_at")
