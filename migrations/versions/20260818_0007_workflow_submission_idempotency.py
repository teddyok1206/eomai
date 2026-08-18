"""scope workflow submission idempotency to active occurrences

Revision ID: 20260818_0007
Revises: 20260817_0006
Create Date: 2026-08-18 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0007"
down_revision: str | Sequence[str] | None = "20260817_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_WORKFLOW_PREDICATE = sa.text(
    "state IN ('REQUESTED','RUNNING','AWAITING_HUMAN_APPROVAL',"
    "'REWORK_REQUESTED','APPROVED','REGISTERING')"
)


def upgrade() -> None:
    op.create_index(
        "ix_workflow_instances_request_hash",
        "workflow_instances",
        ["request_hash"],
        unique=False,
    )
    op.create_index(
        "uq_workflow_active_request_hash",
        "workflow_instances",
        ["request_hash"],
        unique=True,
        postgresql_where=ACTIVE_WORKFLOW_PREDICATE,
    )


def downgrade() -> None:
    op.drop_index("uq_workflow_active_request_hash", table_name="workflow_instances")
    op.drop_index("ix_workflow_instances_request_hash", table_name="workflow_instances")
