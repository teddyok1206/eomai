"""Add explicit continue-and-collect policy for Knowledge Analysis batches.

Revision ID: 20260828_0021
Revises: 20260827_0020
Create Date: 2026-08-28 04:30:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0021"
down_revision: str | None = "20260827_0020"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_analysis_batches",
        sa.Column(
            "range_failure_policy",
            sa.String(length=32),
            server_default="STOP_ON_FIRST_FAILURE",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_knowledge_analysis_batch_range_failure_policy",
        "knowledge_analysis_batches",
        "range_failure_policy IN ('STOP_ON_FIRST_FAILURE','CONTINUE_AND_COLLECT')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_knowledge_analysis_batch_range_failure_policy",
        "knowledge_analysis_batches",
        type_="check",
    )
    op.drop_column("knowledge_analysis_batches", "range_failure_policy")
