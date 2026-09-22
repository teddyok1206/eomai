"""Add Office document-review identity and corrected HWPX pointers.

Revision ID: 20260922_0040
Revises: 20260922_0039
Create Date: 2026-09-22 06:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0040"
down_revision: str | None = "20260922_0039"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "pdf_document_review_upload_intents",
        sa.Column("source_format", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "pdf_document_review_upload_intents",
        sa.Column("source_media_type", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE pdf_document_review_upload_intents "
        "SET source_format = 'PDF', source_media_type = 'application/pdf'"
    )
    op.alter_column("pdf_document_review_upload_intents", "source_format", nullable=False)
    op.alter_column("pdf_document_review_upload_intents", "source_media_type", nullable=False)
    op.create_check_constraint(
        "ck_pdf_review_upload_intents_source_format",
        "pdf_document_review_upload_intents",
        "(source_format = 'PDF' AND source_media_type = 'application/pdf') OR "
        "(source_format = 'HWP' AND source_media_type = 'application/vnd.hancom.hwp') OR "
        "(source_format = 'HWPX' AND source_media_type = 'application/vnd.hancom.hwpx')",
    )

    op.create_table(
        "document_review_hwpx_corrections",
        sa.Column("correction_id", sa.String(length=46), nullable=False),
        sa.Column("operator_id", sa.String(length=41), nullable=False),
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("applied_finding_ids", sa.JSON(), nullable=False),
        sa.Column("finding_set_sha256", sa.String(length=71), nullable=False),
        sa.Column("review_result_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("review_result_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("review_result_sha256", sa.String(length=71), nullable=False),
        sa.Column("base_hwpx_sha256", sa.String(length=71), nullable=False),
        sa.Column("output_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("output_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("output_member_path", sa.String(length=240), nullable=False),
        sa.Column("output_sha256", sa.String(length=71), nullable=False),
        sa.Column("output_content_length", sa.BigInteger(), nullable=False),
        sa.Column("output_media_type", sa.String(length=64), nullable=False),
        sa.Column("output_schema_ref", sa.String(length=160), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "output_content_length BETWEEN 1 AND 268435456 AND lock_version >= 1",
            name="ck_document_review_hwpx_corrections_bounds",
        ),
        sa.CheckConstraint(
            "output_member_path = 'corrected/document-review-redline.hwpx' AND "
            "output_media_type = 'application/vnd.hancom.hwpx' AND "
            "output_schema_ref = 'eom://schemas/document-review/corrected-hwpx/1.0'",
            name="ck_document_review_hwpx_corrections_output_contract",
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.operator_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("correction_id"),
    )
    op.create_index(
        "ix_document_review_hwpx_correction_owner",
        "document_review_hwpx_corrections",
        ["operator_id", sa.text("created_at DESC"), "correction_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_review_hwpx_correction_workflow",
        "document_review_hwpx_corrections",
        ["workflow_id", sa.text("created_at DESC"), "correction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_review_hwpx_correction_workflow",
        table_name="document_review_hwpx_corrections",
    )
    op.drop_index(
        "ix_document_review_hwpx_correction_owner",
        table_name="document_review_hwpx_corrections",
    )
    op.drop_table("document_review_hwpx_corrections")
    op.drop_constraint(
        "ck_pdf_review_upload_intents_source_format",
        "pdf_document_review_upload_intents",
        type_="check",
    )
    op.drop_column("pdf_document_review_upload_intents", "source_media_type")
    op.drop_column("pdf_document_review_upload_intents", "source_format")
