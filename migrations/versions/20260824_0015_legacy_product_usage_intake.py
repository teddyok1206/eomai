"""add immutable legacy Product and Usage intake

Revision ID: 20260824_0015
Revises: 20260824_0014
Create Date: 2026-08-24 09:30:00Z
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0015"
down_revision: str | Sequence[str] | None = "20260824_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_legacy_usage_immutable_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'immutable legacy product/usage record cannot be changed';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_legacy_usage_import_transition() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'legacy usage import cannot be deleted';
          END IF;
          IF NEW.legacy_usage_import_id IS DISTINCT FROM OLD.legacy_usage_import_id
             OR NEW.intake_batch_id IS DISTINCT FROM OLD.intake_batch_id
             OR NEW.source_file_id IS DISTINCT FROM OLD.source_file_id
             OR NEW.source_artifact_id IS DISTINCT FROM OLD.source_artifact_id
             OR NEW.source_artifact_revision_id IS DISTINCT FROM OLD.source_artifact_revision_id
             OR NEW.source_member_path IS DISTINCT FROM OLD.source_member_path
             OR NEW.source_schema_ref IS DISTINCT FROM OLD.source_schema_ref
             OR NEW.source_media_type IS DISTINCT FROM OLD.source_media_type
             OR NEW.source_sha256 IS DISTINCT FROM OLD.source_sha256
             OR NEW.mapping_contract_revision_id IS DISTINCT FROM OLD.mapping_contract_revision_id
             OR NEW.mapping_contract_sha256 IS DISTINCT FROM OLD.mapping_contract_sha256
             OR NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256
             OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
             OR NEW.row_count IS DISTINCT FROM OLD.row_count
             OR NEW.resolved_count IS DISTINCT FROM OLD.resolved_count
             OR NEW.unresolved_count IS DISTINCT FROM OLD.unresolved_count
             OR NEW.conflict_count IS DISTINCT FROM OLD.conflict_count
             OR NEW.rejected_count IS DISTINCT FROM OLD.rejected_count
             OR NEW.created_at IS DISTINCT FROM OLD.created_at
             OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
            RAISE EXCEPTION 'legacy usage import immutable fields cannot be changed';
          END IF;
          IF NOT (
            (OLD.state = 'PROPOSED' AND NEW.state IN ('REVIEWED','FAILED'))
            OR (OLD.state = 'REVIEWED' AND NEW.state IN ('COMMITTED','FAILED'))
          ) THEN
            RAISE EXCEPTION 'invalid legacy usage import state transition';
          END IF;
          IF NEW.lock_version <> OLD.lock_version + 1 THEN
            RAISE EXCEPTION 'legacy usage import lock version must advance exactly once';
          END IF;
          IF NEW.state = 'COMMITTED' THEN
            IF NEW.commit_sha256 IS NULL
               OR NEW.committed_at IS NULL
               OR NEW.committed_by IS NULL THEN
              RAISE EXCEPTION 'committed legacy usage import requires commit provenance';
            END IF;
          ELSIF NEW.commit_sha256 IS NOT NULL
             OR NEW.committed_at IS NOT NULL
             OR NEW.committed_by IS NOT NULL THEN
            RAISE EXCEPTION 'uncommitted legacy usage import cannot carry commit provenance';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.create_table(
        "assessment_forms",
        sa.Column("assessment_form_id", sa.String(37), primary_key=True),
        sa.Column("deliverable_id", sa.String(44), nullable=False),
        sa.Column("form_key", sa.String(128), nullable=False),
        sa.Column("current_revision_id", sa.String(40)),
        sa.Column("lifecycle_state", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["deliverable_id"], ["deliverables.deliverable_id"]),
        sa.UniqueConstraint("deliverable_id", "form_key", name="uq_assessment_form_product_key"),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')", name="ck_assessment_forms_state"
        ),
    )
    op.create_index("ix_assessment_forms_deliverable_id", "assessment_forms", ["deliverable_id"])
    op.create_table(
        "assessment_form_revisions",
        sa.Column("assessment_form_revision_id", sa.String(40), primary_key=True),
        sa.Column("assessment_form_id", sa.String(37), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.String(40)),
        sa.Column("deliverable_revision_id", sa.String(41), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("display_label", sa.String(128), nullable=False),
        sa.Column("assessment_assembly_revision_id", sa.String(44)),
        sa.Column("revision_state", sa.String(16), nullable=False),
        sa.Column("revision_sha256", sa.String(71), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["assessment_form_id"], ["assessment_forms.assessment_form_id"]),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"], ["assessment_form_revisions.assessment_form_revision_id"]
        ),
        sa.ForeignKeyConstraint(
            ["deliverable_revision_id"], ["deliverable_revisions.deliverable_revision_id"]
        ),
        sa.UniqueConstraint(
            "assessment_form_id", "revision_number", name="uq_assessment_form_revision_number"
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_assessment_form_revision_number"),
        sa.CheckConstraint("ordinal > 0", name="ck_assessment_form_revision_ordinal"),
        sa.CheckConstraint(
            "revision_state IN ('DRAFT','RELEASED','SUPERSEDED','WITHDRAWN')",
            name="ck_assessment_form_revision_state",
        ),
    )
    op.create_index(
        "ix_assessment_form_revisions_form", "assessment_form_revisions", ["assessment_form_id"]
    )
    op.create_index(
        "ix_assessment_form_revisions_product",
        "assessment_form_revisions",
        ["deliverable_revision_id"],
    )
    op.create_foreign_key(
        "fk_assessment_form_current_revision",
        "assessment_forms",
        "assessment_form_revisions",
        ["current_revision_id"],
        ["assessment_form_revision_id"],
    )
    op.create_table(
        "assessment_assemblies",
        sa.Column("assessment_assembly_id", sa.String(41), primary_key=True),
        sa.Column("assessment_form_id", sa.String(37), nullable=False, unique=True),
        sa.Column("current_revision_id", sa.String(44)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["assessment_form_id"], ["assessment_forms.assessment_form_id"]),
    )
    op.create_table(
        "assessment_assembly_revisions",
        sa.Column("assessment_assembly_revision_id", sa.String(44), primary_key=True),
        sa.Column("assessment_assembly_id", sa.String(41), nullable=False),
        sa.Column("assessment_form_id", sa.String(37), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.String(44)),
        sa.Column("revision_state", sa.String(16), nullable=False),
        sa.Column("total_points_milli", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("canonical_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_assembly_id"], ["assessment_assemblies.assessment_assembly_id"]
        ),
        sa.ForeignKeyConstraint(["assessment_form_id"], ["assessment_forms.assessment_form_id"]),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            ["assessment_assembly_revisions.assessment_assembly_revision_id"],
        ),
        sa.UniqueConstraint(
            "assessment_assembly_id",
            "revision_number",
            name="uq_assessment_assembly_revision_number",
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_assessment_assembly_revision_number"),
        sa.CheckConstraint(
            "total_points_milli >= 0", name="ck_assessment_assembly_revision_total_points"
        ),
        sa.CheckConstraint(
            "revision_state IN ('RELEASED','SUPERSEDED','WITHDRAWN')",
            name="ck_assessment_assembly_revision_state",
        ),
    )
    op.create_index(
        "ix_assessment_assembly_revisions_assembly",
        "assessment_assembly_revisions",
        ["assessment_assembly_id"],
    )
    op.create_index(
        "ix_assessment_assembly_revisions_form",
        "assessment_assembly_revisions",
        ["assessment_form_id"],
    )
    op.create_foreign_key(
        "fk_assessment_assembly_current_revision",
        "assessment_assemblies",
        "assessment_assembly_revisions",
        ["current_revision_id"],
        ["assessment_assembly_revision_id"],
    )
    op.create_foreign_key(
        "fk_assessment_form_revision_assembly",
        "assessment_form_revisions",
        "assessment_assembly_revisions",
        ["assessment_assembly_revision_id"],
        ["assessment_assembly_revision_id"],
    )
    op.create_table(
        "assessment_item_placements",
        sa.Column("placement_id", sa.String(42), primary_key=True),
        sa.Column("assessment_assembly_revision_id", sa.String(44), nullable=False),
        sa.Column("section_key", sa.String(128), nullable=False),
        sa.Column("section_ordinal", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("display_number", sa.String(32), nullable=False),
        sa.Column("item_id", sa.String(37), nullable=False),
        sa.Column("item_revision_id", sa.String(40), nullable=False),
        sa.Column("item_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("points_milli", sa.Integer(), nullable=False),
        sa.Column("usage_role", sa.String(32), nullable=False),
        sa.Column("source_usage_plan_id", sa.String(42), unique=True),
        sa.ForeignKeyConstraint(
            ["assessment_assembly_revision_id"],
            ["assessment_assembly_revisions.assessment_assembly_revision_id"],
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.item_id"]),
        sa.ForeignKeyConstraint(["item_revision_id"], ["item_revisions.item_revision_id"]),
        sa.ForeignKeyConstraint(["source_usage_plan_id"], ["usage_plans.usage_plan_id"]),
        sa.UniqueConstraint(
            "assessment_assembly_revision_id",
            "section_key",
            "position",
            name="uq_assessment_placement_position",
        ),
        sa.CheckConstraint("section_ordinal > 0", name="ck_assessment_placement_section_ordinal"),
        sa.CheckConstraint("position > 0", name="ck_assessment_placement_position"),
        sa.CheckConstraint("points_milli >= 0", name="ck_assessment_placement_points"),
        sa.CheckConstraint(
            "usage_role IN ('PRIMARY','PRACTICE','REVIEW','EXAMPLE','OTHER_REVIEWED')",
            name="ck_assessment_placement_usage_role",
        ),
    )
    op.create_index(
        "ix_assessment_item_placements_assembly",
        "assessment_item_placements",
        ["assessment_assembly_revision_id"],
    )
    op.create_index(
        "ix_assessment_item_placements_item_revision",
        "assessment_item_placements",
        ["item_revision_id"],
    )
    op.create_table(
        "publications",
        sa.Column("publication_id", sa.String(44), primary_key=True),
        sa.Column("assessment_form_id", sa.String(37), nullable=False),
        sa.Column("publication_key", sa.String(128), nullable=False),
        sa.Column("current_revision_id", sa.String(47)),
        sa.Column("lifecycle_state", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["assessment_form_id"], ["assessment_forms.assessment_form_id"]),
        sa.UniqueConstraint(
            "assessment_form_id", "publication_key", name="uq_publication_form_key"
        ),
        sa.CheckConstraint("lifecycle_state IN ('ACTIVE','RETIRED')", name="ck_publications_state"),
    )
    op.create_index("ix_publications_form", "publications", ["assessment_form_id"])
    op.create_table(
        "publication_revisions",
        sa.Column("publication_revision_id", sa.String(47), primary_key=True),
        sa.Column("publication_id", sa.String(44), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("deliverable_revision_id", sa.String(41), nullable=False),
        sa.Column("assessment_form_revision_id", sa.String(40), nullable=False),
        sa.Column("assessment_assembly_revision_id", sa.String(44), nullable=False),
        sa.Column("assembly_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("revision_state", sa.String(16), nullable=False),
        sa.Column("publication_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_artifact_id", sa.String(41), nullable=False),
        sa.Column("source_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("source_sha256", sa.String(71), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.publication_id"]),
        sa.ForeignKeyConstraint(
            ["deliverable_revision_id"], ["deliverable_revisions.deliverable_revision_id"]
        ),
        sa.ForeignKeyConstraint(
            ["assessment_form_revision_id"],
            ["assessment_form_revisions.assessment_form_revision_id"],
        ),
        sa.ForeignKeyConstraint(
            ["assessment_assembly_revision_id"],
            ["assessment_assembly_revisions.assessment_assembly_revision_id"],
        ),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["source_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.UniqueConstraint(
            "publication_id", "revision_number", name="uq_publication_revision_number"
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_publication_revision_number"),
        sa.CheckConstraint(
            "revision_state IN ('RELEASED','WITHDRAWN')", name="ck_publication_revision_state"
        ),
        sa.CheckConstraint(
            "source_kind IN ('LEGACY_WORKBOOK','RENDERED_OUTPUT')",
            name="ck_publication_revision_source_kind",
        ),
    )
    op.create_index(
        "ix_publication_revisions_publication", "publication_revisions", ["publication_id"]
    )
    op.create_index(
        "ix_publication_revisions_product", "publication_revisions", ["deliverable_revision_id"]
    )
    op.create_index(
        "ix_publication_revisions_form", "publication_revisions", ["assessment_form_revision_id"]
    )
    op.create_foreign_key(
        "fk_publication_current_revision",
        "publications",
        "publication_revisions",
        ["current_revision_id"],
        ["publication_revision_id"],
    )
    op.create_table(
        "usage_records_v1",
        sa.Column("usage_record_id", sa.String(44), primary_key=True),
        sa.Column("contract_version", sa.String(32), nullable=False),
        sa.Column("legacy_usage_import_id", sa.String(45), nullable=False),
        sa.Column("legacy_usage_row_id", sa.String(42), nullable=False),
        sa.Column("item_id", sa.String(37), nullable=False),
        sa.Column("item_revision_id", sa.String(40), nullable=False),
        sa.Column("deliverable_id", sa.String(44), nullable=False),
        sa.Column("deliverable_revision_id", sa.String(41), nullable=False),
        sa.Column("assessment_form_id", sa.String(37), nullable=False),
        sa.Column("assessment_form_revision_id", sa.String(40), nullable=False),
        sa.Column("assessment_assembly_revision_id", sa.String(44), nullable=False),
        sa.Column("placement_id", sa.String(42), nullable=False),
        sa.Column("publication_revision_id", sa.String(47), nullable=False),
        sa.Column("section_key", sa.String(128), nullable=False),
        sa.Column("section_ordinal", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("points_milli", sa.Integer(), nullable=False),
        sa.Column("usage_role", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(200), nullable=False),
        sa.Column("source_hash", sa.String(71), nullable=False),
        sa.Column("detail_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("recorded_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.item_id"]),
        sa.ForeignKeyConstraint(["item_revision_id"], ["item_revisions.item_revision_id"]),
        sa.ForeignKeyConstraint(["deliverable_id"], ["deliverables.deliverable_id"]),
        sa.ForeignKeyConstraint(
            ["deliverable_revision_id"], ["deliverable_revisions.deliverable_revision_id"]
        ),
        sa.ForeignKeyConstraint(["assessment_form_id"], ["assessment_forms.assessment_form_id"]),
        sa.ForeignKeyConstraint(
            ["assessment_form_revision_id"],
            ["assessment_form_revisions.assessment_form_revision_id"],
        ),
        sa.ForeignKeyConstraint(
            ["assessment_assembly_revision_id"],
            ["assessment_assembly_revisions.assessment_assembly_revision_id"],
        ),
        sa.ForeignKeyConstraint(["placement_id"], ["assessment_item_placements.placement_id"]),
        sa.ForeignKeyConstraint(
            ["publication_revision_id"], ["publication_revisions.publication_revision_id"]
        ),
        sa.UniqueConstraint(
            "publication_revision_id", "placement_id", name="uq_usage_v1_publication_placement"
        ),
        sa.UniqueConstraint("source_kind", "source_key", name="uq_usage_v1_source_key"),
        sa.UniqueConstraint("legacy_usage_row_id", name="uq_usage_v1_legacy_row"),
        sa.CheckConstraint("contract_version = 'usage-record/1.0'", name="ck_usage_v1_contract"),
        sa.CheckConstraint("points_milli >= 0", name="ck_usage_v1_points"),
        sa.CheckConstraint("section_ordinal > 0", name="ck_usage_v1_section_ordinal"),
        sa.CheckConstraint("position > 0", name="ck_usage_v1_position"),
        sa.CheckConstraint(
            "usage_role IN ('PRIMARY','PRACTICE','REVIEW','EXAMPLE','OTHER_REVIEWED')",
            name="ck_usage_v1_role",
        ),
        sa.CheckConstraint(
            "source_kind IN ('LEGACY_WORKBOOK','PLANNED_FULFILLMENT','MANUAL_REVIEWED')",
            name="ck_usage_v1_source_kind",
        ),
    )
    op.create_index(
        "ix_usage_v1_item_reverse", "usage_records_v1", ["item_revision_id", "recorded_at"]
    )
    op.create_index("ix_usage_v1_product_revision", "usage_records_v1", ["deliverable_revision_id"])
    op.create_index(
        "ix_usage_v1_form_revision", "usage_records_v1", ["assessment_form_revision_id"]
    )
    op.create_index("ix_usage_v1_publication", "usage_records_v1", ["publication_revision_id"])
    op.create_index("ix_usage_v1_import", "usage_records_v1", ["legacy_usage_import_id"])
    op.create_table(
        "legacy_usage_mapping_contracts",
        sa.Column("mapping_contract_id", sa.String(42), primary_key=True),
        sa.Column("mapping_key", sa.String(128), nullable=False, unique=True),
        sa.Column("current_revision_id", sa.String(45)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
    )
    op.create_table(
        "legacy_usage_mapping_contract_revisions",
        sa.Column("mapping_contract_revision_id", sa.String(45), primary_key=True),
        sa.Column("mapping_contract_id", sa.String(42), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("contract_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("canonical_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["mapping_contract_id"], ["legacy_usage_mapping_contracts.mapping_contract_id"]
        ),
        sa.UniqueConstraint(
            "mapping_contract_id", "revision_number", name="uq_legacy_mapping_revision_number"
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_legacy_mapping_revision_number"),
        sa.CheckConstraint("state = 'RELEASED'", name="ck_legacy_mapping_revision_state"),
    )
    op.create_index(
        "ix_legacy_mapping_revisions_contract",
        "legacy_usage_mapping_contract_revisions",
        ["mapping_contract_id"],
    )
    op.create_foreign_key(
        "fk_legacy_mapping_current_revision",
        "legacy_usage_mapping_contracts",
        "legacy_usage_mapping_contract_revisions",
        ["current_revision_id"],
        ["mapping_contract_revision_id"],
    )
    op.create_table(
        "legacy_usage_imports",
        sa.Column("legacy_usage_import_id", sa.String(45), primary_key=True),
        sa.Column("intake_batch_id", sa.String(39), nullable=False),
        sa.Column("source_file_id", sa.String(43), nullable=False),
        sa.Column("source_artifact_id", sa.String(41), nullable=False),
        sa.Column("source_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("source_member_path", sa.String(512), nullable=False),
        sa.Column("source_schema_ref", sa.String(256), nullable=False),
        sa.Column("source_media_type", sa.String(128), nullable=False),
        sa.Column("source_sha256", sa.String(71), nullable=False),
        sa.Column("mapping_contract_revision_id", sa.String(45), nullable=False),
        sa.Column("mapping_contract_sha256", sa.String(71), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("resolved_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("commit_sha256", sa.String(71)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("committed_by", sa.String(128)),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["intake_batch_id"], ["content_intake_batches.intake_batch_id"]),
        sa.ForeignKeyConstraint(["source_file_id"], ["content_intake_source_files.source_file_id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["source_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.ForeignKeyConstraint(
            ["mapping_contract_revision_id"],
            ["legacy_usage_mapping_contract_revisions.mapping_contract_revision_id"],
        ),
        sa.UniqueConstraint(
            "source_file_id",
            "source_artifact_revision_id",
            "mapping_contract_revision_id",
            name="uq_legacy_import_source_mapping",
        ),
        sa.CheckConstraint(
            "state IN ('PROPOSED','REVIEWED','COMMITTED','FAILED')", name="ck_legacy_import_state"
        ),
        sa.CheckConstraint(
            "source_schema_ref = 'eom://schemas/legacy-usage/workbook/1.0'",
            name="ck_legacy_import_source_schema",
        ),
        sa.CheckConstraint(
            "source_media_type = "
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'",
            name="ck_legacy_import_source_media",
        ),
        sa.CheckConstraint(
            "row_count >= 0 AND resolved_count >= 0 AND unresolved_count >= 0 "
            "AND conflict_count >= 0 AND rejected_count >= 0",
            name="ck_legacy_import_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "row_count = resolved_count + unresolved_count + conflict_count + rejected_count",
            name="ck_legacy_import_counts_sum",
        ),
        sa.CheckConstraint(
            "(state = 'COMMITTED' AND commit_sha256 IS NOT NULL AND committed_at IS NOT NULL "
            "AND committed_by IS NOT NULL) OR "
            "(state <> 'COMMITTED' AND commit_sha256 IS NULL AND committed_at IS NULL "
            "AND committed_by IS NULL)",
            name="ck_legacy_import_commit_provenance",
        ),
    )
    op.create_index("ix_legacy_usage_imports_batch", "legacy_usage_imports", ["intake_batch_id"])
    op.execute(
        "CREATE TRIGGER legacy_usage_imports_transition BEFORE UPDATE OR DELETE "
        "ON legacy_usage_imports FOR EACH ROW "
        "EXECUTE FUNCTION enforce_legacy_usage_import_transition()"
    )
    op.create_table(
        "legacy_usage_row_proposals",
        sa.Column("legacy_usage_row_id", sa.String(42), primary_key=True),
        sa.Column("legacy_usage_import_id", sa.String(45), nullable=False),
        sa.Column("source_row_key", sa.String(128), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("normalized_row_sha256", sa.String(71), nullable=False),
        sa.Column("proposal_state", sa.String(16), nullable=False),
        sa.Column("canonical_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["legacy_usage_import_id"], ["legacy_usage_imports.legacy_usage_import_id"]
        ),
        sa.UniqueConstraint(
            "legacy_usage_import_id",
            "source_row_number",
            name="uq_legacy_usage_source_row_number",
        ),
        sa.CheckConstraint(
            "proposal_state IN ('RESOLVED','UNRESOLVED','CONFLICT','REJECTED')",
            name="ck_legacy_usage_row_state",
        ),
    )
    op.create_index(
        "ix_legacy_usage_rows_import_state",
        "legacy_usage_row_proposals",
        ["legacy_usage_import_id", "proposal_state"],
    )
    op.create_index(
        "ix_legacy_usage_rows_import_source_key",
        "legacy_usage_row_proposals",
        ["legacy_usage_import_id", "source_row_key"],
    )
    op.create_table(
        "legacy_usage_row_reviews",
        sa.Column("legacy_usage_review_id", sa.String(45), primary_key=True),
        sa.Column("legacy_usage_row_id", sa.String(42), nullable=False, unique=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("decision_sha256", sa.String(71), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["legacy_usage_row_id"], ["legacy_usage_row_proposals.legacy_usage_row_id"]
        ),
        sa.CheckConstraint(
            "decision IN ('APPROVE','REJECT')", name="ck_legacy_usage_review_decision"
        ),
    )
    op.create_foreign_key(
        "fk_usage_v1_import",
        "usage_records_v1",
        "legacy_usage_imports",
        ["legacy_usage_import_id"],
        ["legacy_usage_import_id"],
    )
    op.create_foreign_key(
        "fk_usage_v1_row",
        "usage_records_v1",
        "legacy_usage_row_proposals",
        ["legacy_usage_row_id"],
        ["legacy_usage_row_id"],
    )
    op.create_table(
        "product_usage_projections",
        sa.Column("product_usage_projection_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("legacy_usage_import_id", sa.String(45), nullable=False, unique=True),
        sa.Column("projection_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("canonical_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["legacy_usage_import_id"], ["legacy_usage_imports.legacy_usage_import_id"]
        ),
    )
    for table in (
        "assessment_form_revisions",
        "assessment_assembly_revisions",
        "assessment_item_placements",
        "publication_revisions",
        "usage_records_v1",
        "legacy_usage_mapping_contract_revisions",
        "legacy_usage_row_proposals",
        "legacy_usage_row_reviews",
        "product_usage_projections",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_legacy_usage_immutable_mutation()"
        )


def downgrade() -> None:
    for table in (
        "product_usage_projections",
        "legacy_usage_row_reviews",
        "legacy_usage_row_proposals",
        "legacy_usage_mapping_contract_revisions",
        "usage_records_v1",
        "publication_revisions",
        "assessment_item_placements",
        "assessment_assembly_revisions",
        "assessment_form_revisions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP TRIGGER IF EXISTS legacy_usage_imports_transition ON legacy_usage_imports")
    op.drop_table("product_usage_projections")
    op.drop_table("usage_records_v1")
    op.drop_table("legacy_usage_row_reviews")
    op.drop_table("legacy_usage_row_proposals")
    op.drop_table("legacy_usage_imports")
    op.drop_constraint(
        "fk_legacy_mapping_current_revision", "legacy_usage_mapping_contracts", type_="foreignkey"
    )
    op.drop_table("legacy_usage_mapping_contract_revisions")
    op.drop_table("legacy_usage_mapping_contracts")
    op.drop_constraint("fk_publication_current_revision", "publications", type_="foreignkey")
    op.drop_table("publication_revisions")
    op.drop_table("publications")
    op.drop_table("assessment_item_placements")
    op.drop_constraint(
        "fk_assessment_form_revision_assembly", "assessment_form_revisions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_assessment_assembly_current_revision", "assessment_assemblies", type_="foreignkey"
    )
    op.drop_table("assessment_assembly_revisions")
    op.drop_table("assessment_assemblies")
    op.drop_constraint(
        "fk_assessment_form_current_revision", "assessment_forms", type_="foreignkey"
    )
    op.drop_table("assessment_form_revisions")
    op.drop_table("assessment_forms")
    op.execute("DROP FUNCTION reject_legacy_usage_immutable_mutation()")
    op.execute("DROP FUNCTION enforce_legacy_usage_import_transition()")
