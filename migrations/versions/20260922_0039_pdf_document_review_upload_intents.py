"""Add bounded PDF document-review upload intents.

Revision ID: 20260922_0039
Revises: 20260922_0038
Create Date: 2026-09-22 00:30:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0039"
down_revision: str | None = "20260922_0038"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "pdf_document_review_upload_intents",
        sa.Column("upload_intent_id", sa.String(length=48), nullable=False),
        sa.Column("operator_id", sa.String(length=41), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=240), nullable=False),
        sa.Column("content_length", sa.BigInteger(), nullable=False),
        sa.Column("preset_key", sa.String(length=32), nullable=False),
        sa.Column("additional_guidance", sa.Text(), nullable=True),
        sa.Column("additional_guidance_sha256", sa.String(length=71), nullable=True),
        sa.Column("upload_sha256", sa.String(length=71), nullable=True),
        sa.Column("workflow_id", sa.String(length=41), nullable=True),
        sa.Column("workflow_command_id", sa.String(length=38), nullable=True),
        sa.Column("document_id", sa.String(length=41), nullable=True),
        sa.Column("document_revision_id", sa.String(length=44), nullable=True),
        sa.Column("source_artifact_id", sa.String(length=41), nullable=True),
        sa.Column("source_artifact_revision_id", sa.String(length=36), nullable=True),
        sa.Column("source_sha256", sa.String(length=71), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('AWAITING_UPLOAD','PROCESSING','STARTED','FAILED_RETRYABLE','FAILED_FINAL')",
            name="ck_pdf_review_upload_intents_state",
        ),
        sa.CheckConstraint(
            "content_length BETWEEN 8 AND 268435456 AND attempts >= 0 "
            "AND lock_version >= 1 AND (page_count BETWEEN 1 AND 2000 OR page_count IS NULL)",
            name="ck_pdf_review_upload_intents_bounds",
        ),
        sa.CheckConstraint(
            "preset_key IN ('PROBLEM_SET','WEEKLY_WORKBOOK','MOCK_EXAM')",
            name="ck_pdf_review_upload_intents_preset",
        ),
        sa.CheckConstraint(
            "(additional_guidance IS NULL AND additional_guidance_sha256 IS NULL) OR "
            "(additional_guidance IS NOT NULL AND additional_guidance_sha256 IS NOT NULL)",
            name="ck_pdf_review_upload_intents_guidance",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_pdf_review_upload_intents_lease",
        ),
        sa.CheckConstraint(
            "(document_id IS NULL AND document_revision_id IS NULL "
            "AND source_artifact_id IS NULL AND source_artifact_revision_id IS NULL "
            "AND source_sha256 IS NULL AND page_count IS NULL) OR "
            "(document_id IS NOT NULL AND document_revision_id IS NOT NULL "
            "AND source_artifact_id IS NOT NULL AND source_artifact_revision_id IS NOT NULL "
            "AND source_sha256 IS NOT NULL AND page_count IS NOT NULL)",
            name="ck_pdf_review_upload_intents_document",
        ),
        sa.CheckConstraint(
            "(state = 'AWAITING_UPLOAD' AND upload_sha256 IS NULL AND workflow_id IS NULL "
            "AND workflow_command_id IS NULL AND failure_code IS NULL AND lease_owner IS NULL "
            "AND attempts = 0) OR "
            "(state = 'PROCESSING' AND upload_sha256 IS NOT NULL AND workflow_id IS NULL "
            "AND workflow_command_id IS NULL AND failure_code IS NULL AND lease_owner IS NOT NULL "
            "AND attempts >= 1) OR "
            "(state = 'STARTED' AND upload_sha256 IS NOT NULL AND workflow_id IS NOT NULL "
            "AND workflow_command_id IS NOT NULL AND failure_code IS NULL AND lease_owner IS NULL "
            "AND document_id IS NOT NULL AND attempts >= 1) OR "
            "(state IN ('FAILED_RETRYABLE','FAILED_FINAL') AND upload_sha256 IS NOT NULL "
            "AND workflow_id IS NULL AND workflow_command_id IS NULL AND failure_code IS NOT NULL "
            "AND lease_owner IS NULL AND attempts >= 1)",
            name="ck_pdf_review_upload_intents_payload",
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.operator_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("upload_intent_id"),
        sa.UniqueConstraint("workflow_id", name="uq_pdf_review_upload_intent_workflow"),
    )
    op.create_index(
        "ix_pdf_review_upload_intent_owner",
        "pdf_document_review_upload_intents",
        ["operator_id", sa.text("created_at DESC"), "upload_intent_id"],
        unique=False,
    )
    op.create_index(
        "ix_pdf_review_upload_intent_lease",
        "pdf_document_review_upload_intents",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("state = 'PROCESSING'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pdf_review_upload_intent_lease",
        table_name="pdf_document_review_upload_intents",
    )
    op.drop_index(
        "ix_pdf_review_upload_intent_owner",
        table_name="pdf_document_review_upload_intents",
    )
    op.drop_table("pdf_document_review_upload_intents")
