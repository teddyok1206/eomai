"""Add paired problem/solution document-review coordination records.

Revision ID: 20260922_0041
Revises: 20260922_0040
Create Date: 2026-09-22 09:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0041"
down_revision: str | None = "20260922_0040"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "document_review_sets",
        sa.Column("review_set_id", sa.String(length=45), nullable=False),
        sa.Column("operator_id", sa.String(length=41), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("preset_key", sa.String(length=32), nullable=False),
        sa.Column("additional_guidance", sa.Text(), nullable=True),
        sa.Column("additional_guidance_sha256", sa.String(length=71), nullable=True),
        sa.Column("workflow_id", sa.String(length=41), nullable=True),
        sa.Column("workflow_command_id", sa.String(length=38), nullable=True),
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
            "state IN ('AWAITING_UPLOADS','STARTING','STARTED','FAILED_RETRYABLE','FAILED_FINAL')",
            name="ck_document_review_sets_state",
        ),
        sa.CheckConstraint(
            "preset_key IN ('PROBLEM_SET','WEEKLY_WORKBOOK','MOCK_EXAM') "
            "AND attempts >= 0 AND lock_version >= 1",
            name="ck_document_review_sets_bounds",
        ),
        sa.CheckConstraint(
            "(additional_guidance IS NULL AND additional_guidance_sha256 IS NULL) OR "
            "(additional_guidance IS NOT NULL AND additional_guidance_sha256 IS NOT NULL)",
            name="ck_document_review_sets_guidance",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_document_review_sets_lease",
        ),
        sa.CheckConstraint(
            "(state = 'AWAITING_UPLOADS' AND workflow_id IS NULL "
            "AND workflow_command_id IS NULL AND failure_code IS NULL "
            "AND lease_owner IS NULL) OR "
            "(state = 'STARTING' AND workflow_id IS NULL AND workflow_command_id IS NULL "
            "AND failure_code IS NULL AND lease_owner IS NOT NULL AND attempts >= 1) OR "
            "(state = 'STARTED' AND workflow_id IS NOT NULL "
            "AND workflow_command_id IS NOT NULL AND failure_code IS NULL "
            "AND lease_owner IS NULL AND attempts >= 1) OR "
            "(state IN ('FAILED_RETRYABLE','FAILED_FINAL') AND workflow_id IS NULL "
            "AND workflow_command_id IS NULL AND failure_code IS NOT NULL "
            "AND lease_owner IS NULL AND attempts >= 1)",
            name="ck_document_review_sets_payload",
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.operator_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("review_set_id"),
        sa.UniqueConstraint("workflow_id", name="uq_document_review_sets_workflow"),
    )
    op.create_index(
        "ix_document_review_set_owner",
        "document_review_sets",
        ["operator_id", sa.text("created_at DESC"), "review_set_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_review_set_lease",
        "document_review_sets",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("state = 'STARTING'"),
    )

    op.create_table(
        "document_review_set_members",
        sa.Column("review_set_id", sa.String(length=45), nullable=False),
        sa.Column("document_role", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("original_filename", sa.String(length=240), nullable=False),
        sa.Column("source_format", sa.String(length=8), nullable=False),
        sa.Column("source_media_type", sa.String(length=64), nullable=False),
        sa.Column("content_length", sa.BigInteger(), nullable=False),
        sa.Column("upload_sha256", sa.String(length=71), nullable=True),
        sa.Column("document_id", sa.String(length=41), nullable=True),
        sa.Column("document_revision_id", sa.String(length=44), nullable=True),
        sa.Column("source_artifact_id", sa.String(length=41), nullable=True),
        sa.Column("source_artifact_revision_id", sa.String(length=36), nullable=True),
        sa.Column("source_pdf_sha256", sa.String(length=71), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("review_document_pointer", sa.JSON(), nullable=True),
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
        sa.CheckConstraint(
            "document_role IN ('QUESTION','SOLUTION')",
            name="ck_document_review_set_members_role",
        ),
        sa.CheckConstraint(
            "state IN ('AWAITING_UPLOAD','PROCESSING','COMMITTED','FAILED_RETRYABLE',"
            "'FAILED_FINAL')",
            name="ck_document_review_set_members_state",
        ),
        sa.CheckConstraint(
            "content_length BETWEEN 8 AND 268435456 AND attempts >= 0 AND lock_version >= 1",
            name="ck_document_review_set_members_bounds",
        ),
        sa.CheckConstraint(
            "(source_format = 'PDF' AND source_media_type = 'application/pdf') OR "
            "(source_format = 'HWP' AND source_media_type = 'application/vnd.hancom.hwp') OR "
            "(source_format = 'HWPX' AND source_media_type = 'application/vnd.hancom.hwpx')",
            name="ck_document_review_set_members_source_format",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_document_review_set_members_lease",
        ),
        sa.CheckConstraint(
            "(document_id IS NULL AND document_revision_id IS NULL "
            "AND source_artifact_id IS NULL AND source_artifact_revision_id IS NULL "
            "AND source_pdf_sha256 IS NULL AND page_count IS NULL "
            "AND review_document_pointer IS NULL) OR "
            "(document_id IS NOT NULL AND document_revision_id IS NOT NULL "
            "AND source_artifact_id IS NOT NULL AND source_artifact_revision_id IS NOT NULL "
            "AND source_pdf_sha256 IS NOT NULL AND page_count IS NOT NULL "
            "AND review_document_pointer IS NOT NULL)",
            name="ck_document_review_set_members_document",
        ),
        sa.CheckConstraint(
            "(state = 'AWAITING_UPLOAD' AND upload_sha256 IS NULL "
            "AND failure_code IS NULL AND lease_owner IS NULL AND attempts = 0 "
            "AND document_id IS NULL) OR "
            "(state = 'PROCESSING' AND upload_sha256 IS NOT NULL "
            "AND failure_code IS NULL AND lease_owner IS NOT NULL AND attempts >= 1 "
            "AND document_id IS NULL) OR "
            "(state = 'COMMITTED' AND upload_sha256 IS NOT NULL "
            "AND failure_code IS NULL AND lease_owner IS NULL AND attempts >= 1 "
            "AND document_id IS NOT NULL) OR "
            "(state IN ('FAILED_RETRYABLE','FAILED_FINAL') AND upload_sha256 IS NOT NULL "
            "AND failure_code IS NOT NULL AND lease_owner IS NULL AND attempts >= 1)",
            name="ck_document_review_set_members_payload",
        ),
        sa.ForeignKeyConstraint(
            ["review_set_id"], ["document_review_sets.review_set_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("review_set_id", "document_role"),
    )
    op.create_index(
        "ix_document_review_set_member_lease",
        "document_review_set_members",
        ["lease_expires_at"],
        unique=False,
        postgresql_where=sa.text("state = 'PROCESSING'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_review_set_member_lease",
        table_name="document_review_set_members",
    )
    op.drop_table("document_review_set_members")
    op.drop_index("ix_document_review_set_lease", table_name="document_review_sets")
    op.drop_index("ix_document_review_set_owner", table_name="document_review_sets")
    op.drop_table("document_review_sets")
