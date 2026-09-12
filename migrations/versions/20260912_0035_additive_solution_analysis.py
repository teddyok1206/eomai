"""protect one accepted additive solution report per base analysis

Revision ID: 20260912_0035
Revises: 20260912_0034
Create Date: 2026-09-12 00:30:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0035"
down_revision: str | None = "20260912_0034"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Creation is serialized by the base-row lock. This database invariant independently
    # prevents two successful retry lineages from becoming canonical for the same base.
    op.create_index(
        "uq_knowledge_analysis_accepted_solution_predecessor",
        "knowledge_analysis_runs",
        ["predecessor_analysis_run_id"],
        unique=True,
        postgresql_where=sa.text(
            "state = 'ACCEPTED' AND predecessor_analysis_run_id IS NOT NULL "
            "AND canonical_request ->> 'schema_version' = "
            "'knowledge-analysis-request/10.0'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_knowledge_analysis_accepted_solution_predecessor",
        table_name="knowledge_analysis_runs",
    )
