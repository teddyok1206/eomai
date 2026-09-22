"""Add immutable annotated document-review PDF authorization pointers.

Revision ID: 20260922_0042
Revises: 20260922_0041
Create Date: 2026-09-22 12:00:00+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0042"
down_revision: str | None = "20260922_0041"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "document_review_pdf_annotations",
        sa.Column("annotation_id", sa.String(length=46), nullable=False),
        sa.Column("operator_id", sa.String(length=41), nullable=False),
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("request_sha256", sa.String(length=71), nullable=False),
        sa.Column("review_result_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("review_result_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("review_result_sha256", sa.String(length=71), nullable=False),
        sa.Column("annotation_set_sha256", sa.String(length=71), nullable=False),
        sa.Column("manifest_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("manifest_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("manifest_member_sha256", sa.String(length=71), nullable=False),
        sa.Column("manifest_self_sha256", sa.String(length=71), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "lock_version >= 1",
            name="ck_document_review_pdf_annotations_bounds",
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operators.operator_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("annotation_id"),
        sa.UniqueConstraint(
            "operator_id",
            "workflow_id",
            "request_sha256",
            name="uq_document_review_pdf_annotations_request",
        ),
    )
    op.create_index(
        "ix_document_review_pdf_annotation_owner",
        "document_review_pdf_annotations",
        ["operator_id", sa.text("created_at DESC"), "annotation_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_review_pdf_annotation_workflow",
        "document_review_pdf_annotations",
        ["workflow_id", sa.text("created_at DESC"), "annotation_id"],
        unique=False,
    )
    op.create_table(
        "document_review_pdf_annotation_outputs",
        sa.Column("annotation_id", sa.String(length=46), nullable=False),
        sa.Column("document_role", sa.String(length=16), nullable=False),
        sa.Column("artifact_id", sa.String(length=41), nullable=False),
        sa.Column("artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("member_path", sa.String(length=240), nullable=False),
        sa.Column("sha256", sa.String(length=71), nullable=False),
        sa.Column("content_length", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("schema_ref", sa.String(length=160), nullable=False),
        sa.CheckConstraint(
            "document_role IN ('DOCUMENT','QUESTION','SOLUTION')",
            name="ck_document_review_pdf_annotation_outputs_role",
        ),
        sa.CheckConstraint(
            "content_length BETWEEN 1 AND 536870912 AND media_type = 'application/pdf' "
            "AND schema_ref = 'eom://schemas/document-review/annotated-pdf/1.0'",
            name="ck_document_review_pdf_annotation_outputs_contract",
        ),
        sa.ForeignKeyConstraint(
            ["annotation_id"],
            ["document_review_pdf_annotations.annotation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("annotation_id", "document_role"),
    )


def downgrade() -> None:
    op.drop_table("document_review_pdf_annotation_outputs")
    op.drop_index(
        "ix_document_review_pdf_annotation_workflow",
        table_name="document_review_pdf_annotations",
    )
    op.drop_index(
        "ix_document_review_pdf_annotation_owner",
        table_name="document_review_pdf_annotations",
    )
    op.drop_table("document_review_pdf_annotations")
