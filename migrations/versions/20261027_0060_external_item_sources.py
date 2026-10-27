"""Catalog external Item source revisions, separate from approved Item revisions.

Revision ID: 20261027_0060
Revises: 20261026_0059
Create Date: 2026-10-27 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261027_0060"
down_revision: str | None = "20261026_0059"
branch_labels: str | None = None
depends_on: str | None = None

_MATCHED = "'MATCHED','MATCHED_DETECTED_HWPX','MATCHED_IDENTICAL_COPIES'"
_STATUSES = (
    _MATCHED + ",'REJECTED','REJECTION_AMBIGUOUS','DRAFT_ONLY','LINK_UNSUPPORTED',"
    "'DOCUMENT_MISSING','NAME_MISMATCH','CONTENT_CONFLICT','FORMAT_MISMATCH'"
)


def upgrade() -> None:
    op.create_table(
        "external_item_imports",
        sa.Column("import_id", sa.String(42), primary_key=True),
        sa.Column("source_namespace", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column(
            "workbook_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "workbook_source_file_id",
            sa.String(43),
            sa.ForeignKey("content_intake_source_files.source_file_id"),
            nullable=False,
        ),
        sa.Column(
            "workbook_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("workbook_sha256", sa.String(71), nullable=False),
        sa.Column("archive_sha256", sa.String(71), nullable=False),
        sa.Column("mapping_revision_id", sa.String(46), nullable=False),
        sa.Column("mapping_sha256", sa.String(71), nullable=False),
        sa.Column("mapping_document", JSONB(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("request_sha256", name="uq_external_item_import_request"),
        sa.CheckConstraint(
            "state IN ('PREPARED','IMPORTING','PARTIAL','COMPLETED','FAILED')",
            name="ck_external_item_import_state",
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_external_item_import_row_count"),
        sa.CheckConstraint(
            "jsonb_typeof(mapping_document) = 'object'",
            name="ck_external_item_import_mapping_shape",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "workbook_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "archive_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "mapping_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_external_item_import_hashes",
        ),
    )
    op.create_index(
        "ix_external_item_import_namespace_created",
        "external_item_imports",
        ["source_namespace", "created_at"],
    )
    op.execute("""
    CREATE FUNCTION protect_external_item_import_identity() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'external Item import identity is immutable' USING ERRCODE = '23514';
      END IF;
      IF OLD.import_id IS DISTINCT FROM NEW.import_id
         OR OLD.source_namespace IS DISTINCT FROM NEW.source_namespace
         OR OLD.request_sha256 IS DISTINCT FROM NEW.request_sha256
         OR OLD.workbook_artifact_id IS DISTINCT FROM NEW.workbook_artifact_id
         OR OLD.workbook_source_file_id IS DISTINCT FROM NEW.workbook_source_file_id
         OR OLD.workbook_artifact_revision_id IS DISTINCT FROM NEW.workbook_artifact_revision_id
         OR OLD.workbook_sha256 IS DISTINCT FROM NEW.workbook_sha256
         OR OLD.archive_sha256 IS DISTINCT FROM NEW.archive_sha256
         OR OLD.mapping_revision_id IS DISTINCT FROM NEW.mapping_revision_id
         OR OLD.mapping_sha256 IS DISTINCT FROM NEW.mapping_sha256
         OR OLD.mapping_document IS DISTINCT FROM NEW.mapping_document
         OR OLD.row_count IS DISTINCT FROM NEW.row_count
         OR OLD.created_by IS DISTINCT FROM NEW.created_by THEN
        RAISE EXCEPTION 'external Item import identity is immutable' USING ERRCODE = '23514';
      END IF;
      RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER external_item_import_identity_guard
    BEFORE UPDATE OR DELETE ON external_item_imports
    FOR EACH ROW EXECUTE FUNCTION protect_external_item_import_identity()
    """)
    op.create_table(
        "external_item_sources",
        sa.Column("source_id", sa.String(40), primary_key=True),
        sa.Column("source_namespace", sa.String(128), nullable=False),
        sa.Column("external_number", sa.String(5), nullable=False),
        sa.Column("current_revision_id", sa.String(43), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "source_namespace", "external_number", name="uq_external_item_source_number"
        ),
        sa.CheckConstraint("external_number ~ '^[0-9]{5}$'", name="ck_external_item_source_number"),
    )
    op.create_index(
        "ix_external_item_source_current", "external_item_sources", ["current_revision_id"]
    )
    op.create_table(
        "external_item_source_revisions",
        sa.Column("revision_id", sa.String(43), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(40),
            sa.ForeignKey("external_item_sources.source_id"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "previous_revision_id",
            sa.String(43),
            sa.ForeignKey("external_item_source_revisions.revision_id"),
            nullable=True,
        ),
        sa.Column(
            "import_id",
            sa.String(42),
            sa.ForeignKey("external_item_imports.import_id"),
            nullable=False,
        ),
        sa.Column("external_number", sa.String(5), nullable=False),
        sa.Column("worksheet_name", sa.String(128), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("observation_sha256", sa.String(71), nullable=False),
        sa.Column("cells", JSONB(), nullable=False),
        sa.Column("match_status", sa.String(32), nullable=False),
        sa.Column(
            "selected_source_file_id",
            sa.String(43),
            sa.ForeignKey("content_intake_source_files.source_file_id"),
            nullable=True,
        ),
        sa.Column("unit_major", sa.String(255), nullable=True),
        sa.Column("unit_minor", sa.String(255), nullable=True),
        sa.Column("field_label", sa.String(255), nullable=True),
        sa.Column("grade_label", sa.String(255), nullable=True),
        sa.Column("author_label", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "source_id", "revision_number", name="uq_external_item_source_revision"
        ),
        sa.UniqueConstraint("import_id", "row_number", name="uq_external_item_import_row"),
        sa.UniqueConstraint("import_id", "external_number", name="uq_external_item_import_number"),
        sa.CheckConstraint("revision_number > 0", name="ck_external_item_revision_number"),
        sa.CheckConstraint("row_number >= 2", name="ck_external_item_row_number"),
        sa.CheckConstraint(
            "external_number ~ '^[0-9]{5}$'", name="ck_external_item_revision_external_number"
        ),
        sa.CheckConstraint(
            "observation_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_external_item_observation_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cells) = 'array' AND jsonb_array_length(cells) = 32",
            name="ck_external_item_cells_shape",
        ),
        sa.CheckConstraint(f"match_status IN ({_STATUSES})", name="ck_external_item_match_status"),
        sa.CheckConstraint(
            f"(match_status IN ({_MATCHED}) AND selected_source_file_id IS NOT NULL) "
            f"OR (match_status NOT IN ({_MATCHED}) AND selected_source_file_id IS NULL)",
            name="ck_external_item_selected_file_state",
        ),
    )
    op.create_index(
        "ix_external_item_source_revisions_import_id",
        "external_item_source_revisions",
        ["import_id"],
    )
    op.create_index(
        "ix_external_item_revision_status",
        "external_item_source_revisions",
        ["match_status", "source_id"],
    )
    op.create_index(
        "ix_external_item_revision_major_unit",
        "external_item_source_revisions",
        ["unit_major", "source_id"],
    )
    op.create_index(
        "ix_external_item_revision_field",
        "external_item_source_revisions",
        ["field_label", "source_id"],
    )
    op.create_table(
        "external_item_edition_documents",
        sa.Column("edition_document_id", sa.String(43), primary_key=True),
        sa.Column(
            "source_revision_id",
            sa.String(43),
            sa.ForeignKey("external_item_source_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("edition", sa.Integer(), nullable=False),
        sa.Column("match_status", sa.String(32), nullable=False),
        sa.Column(
            "source_file_id",
            sa.String(43),
            sa.ForeignKey("content_intake_source_files.source_file_id"),
            nullable=True,
        ),
        sa.Column("document_sha256", sa.String(71), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source_revision_id", "edition", name="uq_external_item_edition"),
        sa.CheckConstraint("edition BETWEEN 1 AND 3", name="ck_external_item_edition_number"),
        sa.CheckConstraint(
            "match_status IN ('MATCHED','MATCHED_DETECTED_HWPX',"
            "'MATCHED_IDENTICAL_COPIES','LINK_UNSUPPORTED','DOCUMENT_MISSING',"
            "'NAME_MISMATCH','CONTENT_CONFLICT','FORMAT_MISMATCH')",
            name="ck_external_item_edition_status",
        ),
        sa.CheckConstraint(
            "(match_status IN ('MATCHED','MATCHED_DETECTED_HWPX',"
            "'MATCHED_IDENTICAL_COPIES') AND source_file_id IS NOT NULL AND "
            "document_sha256 IS NOT NULL) OR "
            "(match_status NOT IN ('MATCHED','MATCHED_DETECTED_HWPX',"
            "'MATCHED_IDENTICAL_COPIES') AND source_file_id IS NULL AND "
            "document_sha256 IS NULL)",
            name="ck_external_item_edition_file_state",
        ),
        sa.CheckConstraint(
            "document_sha256 IS NULL OR document_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_external_item_edition_hash",
        ),
    )
    op.create_index(
        "ix_external_item_edition_source_file",
        "external_item_edition_documents",
        ["source_file_id"],
    )
    op.create_foreign_key(
        "fk_external_item_source_current_revision",
        "external_item_sources",
        "external_item_source_revisions",
        ["current_revision_id"],
        ["revision_id"],
    )
    op.execute("""
    CREATE FUNCTION protect_external_item_source_revision() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE previous_source TEXT;
    DECLARE previous_number INTEGER;
    DECLARE expected_external_number TEXT;
    DECLARE expected_namespace TEXT;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'external Item source revisions are immutable' USING ERRCODE = '23514';
      END IF;
      SELECT external_number INTO expected_external_number
        FROM external_item_sources WHERE source_id = NEW.source_id;
      SELECT source_namespace INTO expected_namespace
        FROM external_item_imports WHERE import_id = NEW.import_id;
      IF expected_external_number IS NULL OR expected_external_number <> NEW.external_number
         OR expected_namespace IS NULL OR expected_namespace <> (
           SELECT source_namespace FROM external_item_sources WHERE source_id = NEW.source_id
         ) THEN
        RAISE EXCEPTION 'external Item revision identity differs' USING ERRCODE = '23514';
      END IF;
      IF NEW.previous_revision_id IS NULL THEN
        IF NEW.revision_number <> 1 THEN
          RAISE EXCEPTION 'external Item first revision number is invalid' USING ERRCODE = '23514';
        END IF;
      ELSE
        SELECT source_id, revision_number INTO previous_source, previous_number
          FROM external_item_source_revisions WHERE revision_id = NEW.previous_revision_id;
        IF previous_source IS DISTINCT FROM NEW.source_id
           OR previous_number IS NULL OR NEW.revision_number <> previous_number + 1 THEN
          RAISE EXCEPTION 'external Item predecessor differs' USING ERRCODE = '23514';
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER external_item_source_revision_guard
    BEFORE INSERT OR UPDATE OR DELETE ON external_item_source_revisions
    FOR EACH ROW EXECUTE FUNCTION protect_external_item_source_revision()
    """)
    op.execute("""
    CREATE FUNCTION protect_external_item_edition_document() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'external Item edition documents are immutable' USING ERRCODE = '23514';
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER external_item_edition_document_guard
    BEFORE UPDATE OR DELETE ON external_item_edition_documents
    FOR EACH ROW EXECUTE FUNCTION protect_external_item_edition_document()
    """)
    op.execute("""
    CREATE FUNCTION protect_external_item_source_identity() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'external Item source identity is immutable' USING ERRCODE = '23514';
      END IF;
      IF OLD.source_namespace IS DISTINCT FROM NEW.source_namespace
         OR OLD.external_number IS DISTINCT FROM NEW.external_number
         OR OLD.source_id IS DISTINCT FROM NEW.source_id THEN
        RAISE EXCEPTION 'external Item source identity is immutable' USING ERRCODE = '23514';
      END IF;
      IF NEW.current_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM external_item_source_revisions
        WHERE revision_id = NEW.current_revision_id AND source_id = NEW.source_id
      ) THEN
        RAISE EXCEPTION 'external Item current revision belongs to another source'
          USING ERRCODE = '23514';
      END IF;
      RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER external_item_source_identity_guard
    BEFORE UPDATE OR DELETE ON external_item_sources
    FOR EACH ROW EXECUTE FUNCTION protect_external_item_source_identity()
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM external_item_sources LIMIT 1)
         OR EXISTS (SELECT 1 FROM external_item_edition_documents LIMIT 1)
         OR EXISTS (SELECT 1 FROM external_item_imports LIMIT 1) THEN
        RAISE EXCEPTION 'cannot discard external Item source history' USING ERRCODE = '23514';
      END IF;
    END $$
    """)
    op.execute("DROP TRIGGER external_item_source_identity_guard ON external_item_sources")
    op.execute("DROP FUNCTION protect_external_item_source_identity()")
    op.execute(
        "DROP TRIGGER external_item_edition_document_guard ON external_item_edition_documents"
    )
    op.execute("DROP FUNCTION protect_external_item_edition_document()")
    op.execute("DROP TRIGGER external_item_source_revision_guard ON external_item_source_revisions")
    op.execute("DROP FUNCTION protect_external_item_source_revision()")
    op.drop_constraint(
        "fk_external_item_source_current_revision", "external_item_sources", type_="foreignkey"
    )
    op.drop_table("external_item_edition_documents")
    op.drop_table("external_item_source_revisions")
    op.drop_table("external_item_sources")
    op.execute("DROP TRIGGER external_item_import_identity_guard ON external_item_imports")
    op.execute("DROP FUNCTION protect_external_item_import_identity()")
    op.drop_table("external_item_imports")
