"""Add the customer-support Workflow stage and owner-history index.

Revision ID: 20260917_0036
Revises: 20260912_0035
Create Date: 2026-09-17 00:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0036"
down_revision: str | None = "20260912_0035"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_workflow_instances_stage", "workflow_instances", type_="check")
    op.create_check_constraint(
        "ck_workflow_instances_stage",
        "workflow_instances",
        "stage IN ('KNOWLEDGE_ANALYSIS','CUSTOMER_SUPPORT','AUTHORING','IMAGE_REQUIRED',"
        "'IMAGE_SKIPPED','REVIEWING','AWAITING_HUMAN_APPROVAL','REGISTERING','COMPLETED',"
        "'FAILED','CANCELLED')",
    )
    op.create_index(
        "ix_workflow_customer_support_owner",
        "workflow_instances",
        ["created_actor_id", "created_at", "workflow_id"],
        unique=False,
        postgresql_where=sa.text(
            "definition_key = 'customer-support' AND created_actor_type = 'human'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_customer_support_owner",
        table_name="workflow_instances",
    )
    op.drop_constraint("ck_workflow_instances_stage", "workflow_instances", type_="check")
    op.create_check_constraint(
        "ck_workflow_instances_stage",
        "workflow_instances",
        "stage IN ('KNOWLEDGE_ANALYSIS','AUTHORING','IMAGE_REQUIRED','IMAGE_SKIPPED',"
        "'REVIEWING','AWAITING_HUMAN_APPROVAL','REGISTERING','COMPLETED','FAILED',"
        "'CANCELLED')",
    )
