"""Pinned mixed-source document assembly identity and typed placement index.

Revision ID: 20261027_0061
Revises: 20261027_0060
Create Date: 2026-10-27 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261027_0061"
down_revision: str | None = "20261027_0060"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "curated_document_assemblies",
        sa.Column("assembly_id", sa.String(41), primary_key=True),
        sa.Column("current_revision_id", sa.String(44), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "curated_document_assembly_revisions",
        sa.Column("assembly_revision_id", sa.String(44), primary_key=True),
        sa.Column(
            "assembly_id",
            sa.String(41),
            sa.ForeignKey("curated_document_assemblies.assembly_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id",
            sa.String(44),
            sa.ForeignKey(
                "curated_document_assembly_revisions.assembly_revision_id", ondelete="RESTRICT"
            ),
            nullable=True,
        ),
        sa.Column("revision_state", sa.String(16), nullable=False),
        sa.Column("selection_sha256", sa.String(71), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("manifest_sha256", sa.String(71), nullable=False),
        sa.Column("canonical_document", JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "assembly_id", "revision_number", name="uq_curated_document_assembly_revision"
        ),
        sa.UniqueConstraint(
            "assembly_id",
            "assembly_revision_id",
            name="uq_curated_document_assembly_revision_owner",
        ),
        sa.UniqueConstraint(
            "created_by", "idempotency_key", name="uq_curated_document_assembly_replay"
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_curated_document_revision_number"),
        sa.CheckConstraint("revision_state = 'INPUT_PINNED'", name="ck_curated_document_state"),
        sa.CheckConstraint(
            "selection_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_curated_document_hashes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(canonical_document) = 'object'",
            name="ck_curated_document_manifest_shape",
        ),
    )
    op.create_index(
        "ix_curated_document_revision_assembly",
        "curated_document_assembly_revisions",
        ["assembly_id", "revision_number"],
    )
    op.create_foreign_key(
        "fk_curated_document_assembly_current_revision",
        "curated_document_assemblies",
        "curated_document_assembly_revisions",
        ["assembly_id", "current_revision_id"],
        ["assembly_id", "assembly_revision_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "curated_document_assembly_placements",
        sa.Column(
            "assembly_revision_id",
            sa.String(44),
            sa.ForeignKey(
                "curated_document_assembly_revisions.assembly_revision_id", ondelete="RESTRICT"
            ),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("placement_kind", sa.String(40), nullable=False),
        sa.Column(
            "source_id",
            sa.String(40),
            sa.ForeignKey("external_item_sources.source_id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "source_revision_id",
            sa.String(43),
            sa.ForeignKey("external_item_source_revisions.revision_id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "source_file_id",
            sa.String(43),
            sa.ForeignKey("content_intake_source_files.source_file_id", ondelete="RESTRICT"),
        ),
        sa.Column("item_id", sa.String(37), sa.ForeignKey("items.item_id", ondelete="RESTRICT")),
        sa.Column(
            "item_revision_id",
            sa.String(40),
            sa.ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "graph_snapshot_revision_id",
            sa.String(41),
            sa.ForeignKey(
                "knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT"
            ),
        ),
        sa.CheckConstraint("position BETWEEN 1 AND 200", name="ck_curated_placement_position"),
        sa.CheckConstraint(
            "placement_kind IN ('EXTERNAL_SOURCE_DOCUMENT','REGISTERED_ITEM_REVISION',"
            "'PAST_EXAM_ITEM_REVISION')",
            name="ck_curated_placement_kind",
        ),
        sa.CheckConstraint(
            "(placement_kind = 'EXTERNAL_SOURCE_DOCUMENT' AND source_id IS NOT NULL "
            "AND source_revision_id IS NOT NULL AND source_file_id IS NOT NULL "
            "AND item_id IS NULL AND item_revision_id IS NULL "
            "AND graph_snapshot_revision_id IS NULL) OR "
            "(placement_kind <> 'EXTERNAL_SOURCE_DOCUMENT' AND source_id IS NULL "
            "AND source_revision_id IS NULL AND source_file_id IS NULL "
            "AND item_id IS NOT NULL AND item_revision_id IS NOT NULL "
            "AND graph_snapshot_revision_id IS NOT NULL)",
            name="ck_curated_placement_pointer_shape",
        ),
    )
    op.create_index(
        "uq_curated_placement_external",
        "curated_document_assembly_placements",
        ["assembly_revision_id", "source_id"],
        unique=True,
        postgresql_where=sa.text("placement_kind = 'EXTERNAL_SOURCE_DOCUMENT'"),
    )
    op.create_index(
        "uq_curated_placement_item",
        "curated_document_assembly_placements",
        ["assembly_revision_id", "item_revision_id"],
        unique=True,
        postgresql_where=sa.text("placement_kind <> 'EXTERNAL_SOURCE_DOCUMENT'"),
    )
    op.create_index(
        "ix_curated_placement_source_revision",
        "curated_document_assembly_placements",
        ["source_revision_id"],
    )
    op.create_index(
        "ix_curated_placement_item_revision",
        "curated_document_assembly_placements",
        ["item_revision_id"],
    )
    op.execute("""
    CREATE FUNCTION reject_curated_document_revision_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'curated assembly revisions and placements are immutable'
        USING ERRCODE = '23514';
    END;
    $$
    """)
    for table in (
        "curated_document_assembly_revisions",
        "curated_document_assembly_placements",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_curated_document_revision_change()"
        )


def downgrade() -> None:
    for table in (
        "curated_document_assembly_placements",
        "curated_document_assembly_revisions",
    ):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.execute("DROP FUNCTION reject_curated_document_revision_change()")
    op.drop_table("curated_document_assembly_placements")
    op.drop_constraint(
        "fk_curated_document_assembly_current_revision",
        "curated_document_assemblies",
        type_="foreignkey",
    )
    op.drop_table("curated_document_assembly_revisions")
    op.drop_table("curated_document_assemblies")
