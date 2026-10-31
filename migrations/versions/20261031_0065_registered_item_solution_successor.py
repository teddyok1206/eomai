"""Protect one accepted registered-Item public solution per immutable base.

Revision ID: 20261031_0065
Revises: 20261030_0064
Create Date: 2026-10-31 UTC
"""

import sqlalchemy as sa
from alembic import op

revision = "20261031_0065"
down_revision = "20261030_0064"
branch_labels = None
depends_on = None

INDEX = "uq_knowledge_analysis_registered_solution_predecessor"


def upgrade() -> None:
    # The base-row lock serializes creation. This constraint independently fences
    # concurrent acceptance of successful retry branches; old V10 stays intact.
    op.create_index(
        INDEX,
        "knowledge_analysis_runs",
        ["predecessor_analysis_run_id"],
        unique=True,
        postgresql_where=sa.text(
            "state = 'ACCEPTED' AND predecessor_analysis_run_id IS NOT NULL "
            "AND canonical_request ->> 'schema_version' = "
            "'knowledge-analysis-request/11.0'"
        ),
    )


def downgrade() -> None:
    # An older runtime cannot interpret an accepted V11 report. A rollback must
    # keep that history and index, not silently remove its uniqueness guarantee.
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM knowledge_analysis_runs "
            "WHERE canonical_request ->> 'schema_version' = 'knowledge-analysis-request/11.0')"
        )
    ):
        raise RuntimeError("REGISTERED_ITEM_SOLUTION_HISTORY_EXISTS")
    op.drop_index(INDEX, table_name="knowledge_analysis_runs")
