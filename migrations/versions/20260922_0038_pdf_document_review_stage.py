"""Add the PDF document-review Workflow stage and owner index.

Revision ID: 20260922_0038
Revises: 20260917_0037
Create Date: 2026-09-22 00:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0038"
down_revision: str | None = "20260917_0037"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_workflow_instances_stage", "workflow_instances", type_="check")
    op.create_check_constraint(
        "ck_workflow_instances_stage",
        "workflow_instances",
        "stage IN ('KNOWLEDGE_ANALYSIS','CUSTOMER_SUPPORT','DOCUMENT_REVIEW','AUTHORING',"
        "'IMAGE_REQUIRED','IMAGE_SKIPPED','REVIEWING','AWAITING_HUMAN_APPROVAL',"
        "'REGISTERING','COMPLETED','FAILED','CANCELLED')",
    )
    op.create_index(
        "ix_workflow_pdf_document_review_owner",
        "workflow_instances",
        ["created_actor_id", "created_at", "workflow_id"],
        unique=False,
        postgresql_where=sa.text(
            "definition_key = 'pdf-document-review' AND created_actor_type = 'human'"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_pdf_document_review_owner", table_name="workflow_instances")
    op.drop_constraint("ck_workflow_instances_stage", "workflow_instances", type_="check")
    op.create_check_constraint(
        "ck_workflow_instances_stage",
        "workflow_instances",
        "stage IN ('KNOWLEDGE_ANALYSIS','CUSTOMER_SUPPORT','AUTHORING','IMAGE_REQUIRED',"
        "'IMAGE_SKIPPED','REVIEWING','AWAITING_HUMAN_APPROVAL','REGISTERING','COMPLETED',"
        "'FAILED','CANCELLED')",
    )
