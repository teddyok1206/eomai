"""Allow durable source pointers before document-review projection success.

Revision ID: 20260923_0043
Revises: 20260922_0042
Create Date: 2026-09-23 14:45:00+00:00
"""

from __future__ import annotations

from alembic import op

revision: str = "20260923_0043"
down_revision: str | None = "20260922_0042"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_pdf_review_upload_intents_document",
        "pdf_document_review_upload_intents",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pdf_review_upload_intents_document",
        "pdf_document_review_upload_intents",
        "((source_artifact_id IS NULL AND source_artifact_revision_id IS NULL "
        "AND source_sha256 IS NULL) OR "
        "(source_artifact_id IS NOT NULL AND source_artifact_revision_id IS NOT NULL "
        "AND source_sha256 IS NOT NULL)) AND "
        "((document_id IS NULL AND document_revision_id IS NULL AND page_count IS NULL) OR "
        "(document_id IS NOT NULL AND document_revision_id IS NOT NULL "
        "AND page_count IS NOT NULL)) AND "
        "(document_id IS NULL OR source_artifact_id IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_document_review_set_members_document",
        "document_review_set_members",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_review_set_members_document",
        "document_review_set_members",
        "((source_artifact_id IS NULL AND source_artifact_revision_id IS NULL) OR "
        "(source_artifact_id IS NOT NULL AND source_artifact_revision_id IS NOT NULL)) AND "
        "((document_id IS NULL AND document_revision_id IS NULL "
        "AND source_pdf_sha256 IS NULL AND page_count IS NULL "
        "AND review_document_pointer IS NULL) OR "
        "(document_id IS NOT NULL AND document_revision_id IS NOT NULL "
        "AND source_pdf_sha256 IS NOT NULL AND page_count IS NOT NULL "
        "AND review_document_pointer IS NOT NULL)) AND "
        "(document_id IS NULL OR source_artifact_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_review_set_members_document",
        "document_review_set_members",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_review_set_members_document",
        "document_review_set_members",
        "(document_id IS NULL AND document_revision_id IS NULL "
        "AND source_artifact_id IS NULL AND source_artifact_revision_id IS NULL "
        "AND source_pdf_sha256 IS NULL AND page_count IS NULL "
        "AND review_document_pointer IS NULL) OR "
        "(document_id IS NOT NULL AND document_revision_id IS NOT NULL "
        "AND source_artifact_id IS NOT NULL AND source_artifact_revision_id IS NOT NULL "
        "AND source_pdf_sha256 IS NOT NULL AND page_count IS NOT NULL "
        "AND review_document_pointer IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_pdf_review_upload_intents_document",
        "pdf_document_review_upload_intents",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pdf_review_upload_intents_document",
        "pdf_document_review_upload_intents",
        "(document_id IS NULL AND document_revision_id IS NULL "
        "AND source_artifact_id IS NULL AND source_artifact_revision_id IS NULL "
        "AND source_sha256 IS NULL AND page_count IS NULL) OR "
        "(document_id IS NOT NULL AND document_revision_id IS NOT NULL "
        "AND source_artifact_id IS NOT NULL AND source_artifact_revision_id IS NOT NULL "
        "AND source_sha256 IS NOT NULL AND page_count IS NOT NULL)",
    )
