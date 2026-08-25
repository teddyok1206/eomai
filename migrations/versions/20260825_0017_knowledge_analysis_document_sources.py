"""Add Educational Document pointers to Knowledge Analysis.

Revision ID: 20260825_0017
Revises: 20260825_0016
Create Date: 2026-08-25 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0017"
down_revision: str | None = "20260825_0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_educational_document_revision_identity",
        "educational_document_revisions",
        ["document_id", "document_revision_id"],
    )
    op.add_column(
        "knowledge_analysis_runs",
        sa.Column("educational_document_id", sa.String(39), nullable=True),
    )
    op.add_column(
        "knowledge_analysis_runs",
        sa.Column("educational_document_revision_id", sa.String(42), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_analysis_educational_document",
        "knowledge_analysis_runs",
        "educational_documents",
        ["educational_document_id"],
        ["document_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_knowledge_analysis_educational_document_revision_identity",
        "knowledge_analysis_runs",
        "educational_document_revisions",
        ["educational_document_id", "educational_document_revision_id"],
        ["document_id", "document_revision_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_knowledge_analysis_source_kind", "knowledge_analysis_runs", type_="check"
    )
    op.drop_constraint(
        "ck_knowledge_analysis_source_pointer_family", "knowledge_analysis_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_knowledge_analysis_source_kind",
        "knowledge_analysis_runs",
        "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION','DOCUMENT_REVISION')",
    )
    op.create_check_constraint(
        "ck_knowledge_analysis_source_pointer_family",
        "knowledge_analysis_runs",
        "(source_kind = 'CONTENT_INTAKE_FILE' AND source_file_id IS NOT NULL "
        "AND item_id IS NULL AND item_revision_id IS NULL "
        "AND educational_document_id IS NULL AND educational_document_revision_id IS NULL) OR "
        "(source_kind = 'APPROVED_ITEM_REVISION' AND source_file_id IS NULL "
        "AND item_id IS NOT NULL AND item_revision_id IS NOT NULL "
        "AND educational_document_id IS NULL AND educational_document_revision_id IS NULL) OR "
        "(source_kind = 'DOCUMENT_REVISION' AND source_file_id IS NULL "
        "AND item_id IS NULL AND item_revision_id IS NULL "
        "AND educational_document_id IS NOT NULL "
        "AND educational_document_revision_id IS NOT NULL)",
    )
    op.create_index(
        "ix_knowledge_analysis_document_revision",
        "knowledge_analysis_runs",
        ["educational_document_revision_id", "created_at"],
        postgresql_where=sa.text("educational_document_revision_id IS NOT NULL"),
    )
    op.drop_constraint(
        "ck_knowledge_snapshot_analysis_source_kind",
        "knowledge_snapshot_analyses",
        type_="check",
    )
    op.create_check_constraint(
        "ck_knowledge_snapshot_analysis_source_kind",
        "knowledge_snapshot_analyses",
        "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION','DOCUMENT_REVISION')",
    )
    op.add_column(
        "evidence_bundle_entries",
        sa.Column("educational_document_id", sa.String(39), nullable=True),
    )
    op.add_column(
        "evidence_bundle_entries",
        sa.Column("educational_document_revision_id", sa.String(42), nullable=True),
    )
    op.create_foreign_key(
        "fk_evidence_entry_educational_document",
        "evidence_bundle_entries",
        "educational_documents",
        ["educational_document_id"],
        ["document_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_evidence_entry_educational_document_revision_identity",
        "evidence_bundle_entries",
        "educational_document_revisions",
        ["educational_document_id", "educational_document_revision_id"],
        ["document_id", "document_revision_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_evidence_bundle_entry_source_kind", "evidence_bundle_entries", type_="check"
    )
    op.drop_constraint(
        "ck_evidence_bundle_entry_source_family", "evidence_bundle_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_evidence_bundle_entry_source_kind",
        "evidence_bundle_entries",
        "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION','DOCUMENT_REVISION')",
    )
    op.create_check_constraint(
        "ck_evidence_bundle_entry_source_family",
        "evidence_bundle_entries",
        "(source_kind = 'CONTENT_INTAKE_FILE' AND intake_batch_id IS NOT NULL "
        "AND source_file_id IS NOT NULL AND item_id IS NULL AND item_revision_id IS NULL "
        "AND educational_document_id IS NULL AND educational_document_revision_id IS NULL) OR "
        "(source_kind = 'APPROVED_ITEM_REVISION' AND intake_batch_id IS NULL "
        "AND source_file_id IS NULL AND item_id IS NOT NULL AND item_revision_id IS NOT NULL "
        "AND educational_document_id IS NULL AND educational_document_revision_id IS NULL) OR "
        "(source_kind = 'DOCUMENT_REVISION' AND intake_batch_id IS NULL "
        "AND source_file_id IS NULL AND item_id IS NULL AND item_revision_id IS NULL "
        "AND educational_document_id IS NOT NULL "
        "AND educational_document_revision_id IS NOT NULL)",
    )
    op.create_index(
        "ix_evidence_bundle_entry_document_revision",
        "evidence_bundle_entries",
        ["educational_document_revision_id"],
        postgresql_where=sa.text("educational_document_revision_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evidence_bundle_entry_document_revision", table_name="evidence_bundle_entries"
    )
    op.drop_constraint(
        "ck_evidence_bundle_entry_source_family", "evidence_bundle_entries", type_="check"
    )
    op.drop_constraint(
        "ck_evidence_bundle_entry_source_kind", "evidence_bundle_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_evidence_bundle_entry_source_kind",
        "evidence_bundle_entries",
        "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION')",
    )
    op.create_check_constraint(
        "ck_evidence_bundle_entry_source_family",
        "evidence_bundle_entries",
        "(source_kind = 'CONTENT_INTAKE_FILE' AND intake_batch_id IS NOT NULL "
        "AND source_file_id IS NOT NULL AND item_id IS NULL AND item_revision_id IS NULL) OR "
        "(source_kind = 'APPROVED_ITEM_REVISION' AND intake_batch_id IS NULL "
        "AND source_file_id IS NULL AND item_id IS NOT NULL AND item_revision_id IS NOT NULL)",
    )
    op.drop_constraint(
        "fk_evidence_entry_educational_document_revision_identity",
        "evidence_bundle_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_evidence_entry_educational_document",
        "evidence_bundle_entries",
        type_="foreignkey",
    )
    op.drop_column("evidence_bundle_entries", "educational_document_revision_id")
    op.drop_column("evidence_bundle_entries", "educational_document_id")
    op.drop_constraint(
        "ck_knowledge_snapshot_analysis_source_kind",
        "knowledge_snapshot_analyses",
        type_="check",
    )
    op.create_check_constraint(
        "ck_knowledge_snapshot_analysis_source_kind",
        "knowledge_snapshot_analyses",
        "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION')",
    )
    op.drop_index("ix_knowledge_analysis_document_revision", table_name="knowledge_analysis_runs")
    op.drop_constraint(
        "ck_knowledge_analysis_source_pointer_family", "knowledge_analysis_runs", type_="check"
    )
    op.drop_constraint(
        "ck_knowledge_analysis_source_kind", "knowledge_analysis_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_knowledge_analysis_source_kind",
        "knowledge_analysis_runs",
        "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION')",
    )
    op.create_check_constraint(
        "ck_knowledge_analysis_source_pointer_family",
        "knowledge_analysis_runs",
        "(source_kind = 'CONTENT_INTAKE_FILE' AND source_file_id IS NOT NULL "
        "AND item_id IS NULL AND item_revision_id IS NULL) OR "
        "(source_kind = 'APPROVED_ITEM_REVISION' AND source_file_id IS NULL "
        "AND item_id IS NOT NULL AND item_revision_id IS NOT NULL)",
    )
    op.drop_constraint(
        "fk_knowledge_analysis_educational_document_revision_identity",
        "knowledge_analysis_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_knowledge_analysis_educational_document",
        "knowledge_analysis_runs",
        type_="foreignkey",
    )
    op.drop_column("knowledge_analysis_runs", "educational_document_revision_id")
    op.drop_column("knowledge_analysis_runs", "educational_document_id")
    op.drop_constraint(
        "uq_educational_document_revision_identity",
        "educational_document_revisions",
        type_="unique",
    )
