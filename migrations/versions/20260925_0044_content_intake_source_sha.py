"""Index immutable Content Intake source hashes for corpus deduplication.

Revision ID: 20260925_0044
Revises: 20260923_0043
Create Date: 2026-09-25 15:30:00+00:00
"""

from __future__ import annotations

from alembic import op

revision: str = "20260925_0044"
down_revision: str | None = "20260923_0043"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_content_intake_source_sha256",
        "content_intake_source_files",
        ["sha256"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_intake_source_sha256",
        table_name="content_intake_source_files",
    )
