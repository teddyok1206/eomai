"""Index owner-scoped recent curated document assemblies.

Revision ID: 20261027_0062
Revises: 20261027_0061
Create Date: 2026-10-27 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20261027_0062"
down_revision: str | None = "20261027_0061"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_curated_document_owner_recent",
        "curated_document_assemblies",
        ["created_by", sa.text("created_at DESC"), sa.text("assembly_id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_curated_document_owner_recent", table_name="curated_document_assemblies")
