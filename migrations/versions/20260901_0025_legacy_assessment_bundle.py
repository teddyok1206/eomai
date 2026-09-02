"""add reviewed legacy assessment bundle and extraction acceptance pointers

Revision ID: 20260901_0025
Revises: 20260901_0024
Create Date: 2026-09-01 00:30:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0025"
down_revision: str | None = "20260901_0024"
branch_labels: str | None = None
depends_on: str | None = None

_IMMUTABLE_TABLES = (
    "assessment_source_bundle_revisions",
    "assessment_source_bundle_members",
    "assessment_layout_observations",
    "legacy_item_extraction_acceptances",
    "legacy_item_extraction_decisions",
    "legacy_item_corpus_coverages",
    "legacy_item_corpus_bundle_coverages",
)


def upgrade() -> None:
    _create_guard_functions()
    _create_bundle_tables()
    _create_layout_table()
    _create_acceptance_tables()
    _create_coverage_tables()
    for table_name in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_legacy_assessment_immutable_mutation()"
        )
    op.execute(
        "CREATE TRIGGER trg_assessment_source_bundles_controlled_update "
        "BEFORE INSERT OR UPDATE OR DELETE ON assessment_source_bundles "
        "FOR EACH ROW EXECUTE FUNCTION enforce_assessment_source_bundle_logical_update()"
    )


def _create_guard_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_legacy_assessment_immutable_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'immutable legacy assessment record cannot be changed';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_assessment_source_bundle_logical_update() RETURNS trigger AS $$
        DECLARE
          target_owner_id text;
          target_previous_revision_id text;
          target_revision_state text;
          target_revision_number integer;
          old_revision_number integer;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'assessment source bundle logical identity cannot be deleted';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.current_revision_id IS NOT NULL
               OR NEW.lock_version <> 1
               OR NEW.lifecycle_state <> 'ACTIVE' THEN
              RAISE EXCEPTION 'assessment source bundle must start active without a revision';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.lock_version <> OLD.lock_version + 1 THEN
            RAISE EXCEPTION 'assessment source bundle lock version must advance exactly once';
          END IF;
          IF OLD.lifecycle_state = 'RETIRED' THEN
            RAISE EXCEPTION 'retired assessment source bundle cannot be changed';
          END IF;
          IF NEW.assessment_source_bundle_id IS DISTINCT FROM OLD.assessment_source_bundle_id
             OR NEW.bundle_key IS DISTINCT FROM OLD.bundle_key
             OR NEW.created_at IS DISTINCT FROM OLD.created_at
             OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
            RAISE EXCEPTION 'assessment source bundle immutable identity cannot be changed';
          END IF;
          IF NEW.current_revision_id IS NOT DISTINCT FROM OLD.current_revision_id
             AND NEW.lifecycle_state = OLD.lifecycle_state THEN
            RAISE EXCEPTION 'assessment source bundle update must change state or revision';
          END IF;
          IF NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id THEN
            SELECT assessment_source_bundle_id, previous_revision_id, state, revision_number
              INTO target_owner_id, target_previous_revision_id,
                   target_revision_state, target_revision_number
              FROM assessment_source_bundle_revisions
             WHERE assessment_source_bundle_revision_id = NEW.current_revision_id;
            IF NOT FOUND
               OR target_owner_id IS DISTINCT FROM NEW.assessment_source_bundle_id
               OR target_previous_revision_id IS DISTINCT FROM OLD.current_revision_id
               OR target_revision_state <> 'REVIEWED'
               OR NEW.lifecycle_state <> 'ACTIVE' THEN
              RAISE EXCEPTION 'assessment source bundle current revision pointer is invalid';
            END IF;
            IF OLD.current_revision_id IS NULL THEN
              old_revision_number := 0;
            ELSE
              SELECT revision_number INTO STRICT old_revision_number
                FROM assessment_source_bundle_revisions
               WHERE assessment_source_bundle_revision_id = OLD.current_revision_id;
            END IF;
            IF target_revision_number <> old_revision_number + 1 THEN
              RAISE EXCEPTION 'assessment source bundle revision sequence must advance once';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def _create_bundle_tables() -> None:
    op.create_table(
        "assessment_source_bundles",
        sa.Column("assessment_source_bundle_id", sa.String(45), primary_key=True),
        sa.Column("bundle_key", sa.String(160), nullable=False, unique=True),
        sa.Column("current_revision_id", sa.String(48)),
        sa.Column("lifecycle_state", sa.String(16), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')",
            name="ck_assessment_source_bundles_state",
        ),
        sa.CheckConstraint("lock_version > 0", name="ck_assessment_source_bundles_lock_version"),
    )
    op.create_table(
        "assessment_source_bundle_revisions",
        sa.Column("assessment_source_bundle_revision_id", sa.String(48), primary_key=True),
        sa.Column("assessment_source_bundle_id", sa.String(45), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.String(48)),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("inventory_id", sa.String(48), nullable=False),
        sa.Column("inventory_sha256", sa.String(71), nullable=False),
        sa.Column("inventory_artifact_id", sa.String(41), nullable=False),
        sa.Column("inventory_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("inventory_artifact_member_path", sa.String(512), nullable=False),
        sa.Column("inventory_artifact_schema_ref", sa.String(256), nullable=False),
        sa.Column("inventory_artifact_media_type", sa.String(128), nullable=False),
        sa.Column("inventory_artifact_sha256", sa.String(71), nullable=False),
        sa.Column("assessment_occurrence_id", sa.String(43), nullable=False),
        sa.Column("assessment_occurrence_revision_id", sa.String(41), nullable=False),
        sa.Column("occurrence_revision_sha256", sa.String(71), nullable=False),
        sa.Column("rights_policy_id", sa.String(45), nullable=False),
        sa.Column("rights_policy_revision_id", sa.String(48), nullable=False),
        sa.Column("rights_policy_sha256", sa.String(71), nullable=False),
        sa.Column("bundle_manifest_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_source_bundle_id"],
            ["assessment_source_bundles.assessment_source_bundle_id"],
        ),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            ["assessment_source_bundle_revisions.assessment_source_bundle_revision_id"],
        ),
        sa.ForeignKeyConstraint(
            ["inventory_artifact_id", "inventory_artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_assessment_bundle_inventory_artifact_revision_identity",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_occurrence_id", "assessment_occurrence_revision_id"],
            [
                "assessment_occurrence_revisions.assessment_occurrence_id",
                "assessment_occurrence_revisions.assessment_occurrence_revision_id",
            ],
            name="fk_assessment_source_bundle_occurrence_revision_identity",
        ),
        sa.UniqueConstraint(
            "assessment_source_bundle_id",
            "revision_number",
            name="uq_assessment_source_bundle_revision_number",
        ),
        sa.UniqueConstraint(
            "assessment_source_bundle_id",
            "assessment_source_bundle_revision_id",
            name="uq_assessment_source_bundle_revision_identity",
        ),
        sa.CheckConstraint(
            "revision_number > 0", name="ck_assessment_source_bundle_revision_number"
        ),
        sa.CheckConstraint(
            "state IN ('REVIEWED','SUPERSEDED','WITHDRAWN')",
            name="ck_assessment_source_bundle_revision_state",
        ),
    )
    op.create_index(
        "ix_assessment_source_bundle_revisions_occurrence",
        "assessment_source_bundle_revisions",
        ["assessment_occurrence_revision_id"],
    )
    op.create_index(
        "ix_assessment_source_bundle_revisions_inventory",
        "assessment_source_bundle_revisions",
        ["inventory_id", "inventory_sha256"],
    )
    op.create_foreign_key(
        "fk_assessment_source_bundle_current_revision",
        "assessment_source_bundles",
        "assessment_source_bundle_revisions",
        ["current_revision_id"],
        ["assessment_source_bundle_revision_id"],
    )
    op.create_table(
        "assessment_source_bundle_members",
        sa.Column("assessment_source_bundle_member_id", sa.String(51), primary_key=True),
        sa.Column("assessment_source_bundle_revision_id", sa.String(48), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("source_artifact_id", sa.String(41), nullable=False),
        sa.Column("source_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("source_member_path", sa.String(512), nullable=False),
        sa.Column("source_schema_ref", sa.String(256), nullable=False),
        sa.Column("source_media_type", sa.String(128), nullable=False),
        sa.Column("source_sha256", sa.String(71), nullable=False),
        sa.Column("inventory_id", sa.String(48), nullable=False),
        sa.Column("inventory_sha256", sa.String(71), nullable=False),
        sa.Column("inventory_entry_key", sa.String(44), nullable=False),
        sa.Column("inventory_content_sha256", sa.String(71), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_source_bundle_revision_id"],
            ["assessment_source_bundle_revisions.assessment_source_bundle_revision_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id", "source_artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_assessment_source_bundle_member_artifact_revision_identity",
        ),
        sa.UniqueConstraint(
            "assessment_source_bundle_revision_id",
            "ordinal",
            name="uq_assessment_source_bundle_member_ordinal",
        ),
        sa.UniqueConstraint(
            "assessment_source_bundle_revision_id",
            "source_artifact_revision_id",
            "source_member_path",
            name="uq_assessment_source_bundle_member_source",
        ),
        sa.UniqueConstraint(
            "assessment_source_bundle_revision_id",
            "inventory_entry_key",
            name="uq_assessment_source_bundle_member_inventory_entry",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_assessment_source_bundle_member_ordinal"),
        sa.CheckConstraint(
            "role IN ('PROBLEM_DOCUMENT','ANSWER_EXPLANATION_DOCUMENT',"
            "'STRUCTURED_RECONSTRUCTION','ITEM_CLASSIFICATION_WORKBOOK',"
            "'TYPE_CODE_REFERENCE','OTHER_REVIEWED_EVIDENCE')",
            name="ck_assessment_source_bundle_member_role",
        ),
    )
    op.create_index(
        "ix_assessment_source_bundle_members_artifact",
        "assessment_source_bundle_members",
        ["source_artifact_revision_id"],
    )
    op.create_index(
        "ix_assessment_source_bundle_members_inventory",
        "assessment_source_bundle_members",
        ["inventory_id", "inventory_entry_key"],
    )


def _create_layout_table() -> None:
    op.create_table(
        "assessment_layout_observations",
        sa.Column("assessment_layout_observation_id", sa.String(49), primary_key=True),
        sa.Column("assessment_source_bundle_id", sa.String(45), nullable=False),
        sa.Column("assessment_source_bundle_revision_id", sa.String(48), nullable=False),
        sa.Column("bundle_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("artifact_id", sa.String(41), nullable=False),
        sa.Column("artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("artifact_member_path", sa.String(512), nullable=False),
        sa.Column("artifact_schema_ref", sa.String(256), nullable=False),
        sa.Column("artifact_media_type", sa.String(128), nullable=False),
        sa.Column("artifact_sha256", sa.String(71), nullable=False),
        sa.Column("expected_item_count", sa.Integer(), nullable=False),
        sa.Column("observation_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_source_bundle_id", "assessment_source_bundle_revision_id"],
            [
                "assessment_source_bundle_revisions.assessment_source_bundle_id",
                "assessment_source_bundle_revisions.assessment_source_bundle_revision_id",
            ],
            name="fk_assessment_layout_bundle_revision_identity",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_assessment_layout_artifact_revision_identity",
        ),
        sa.UniqueConstraint(
            "artifact_revision_id",
            "artifact_member_path",
            name="uq_assessment_layout_artifact_member",
        ),
        sa.CheckConstraint(
            "expected_item_count > 0", name="ck_assessment_layout_expected_item_count"
        ),
    )
    op.create_index(
        "ix_assessment_layout_observations_bundle",
        "assessment_layout_observations",
        ["assessment_source_bundle_revision_id"],
    )


def _create_acceptance_tables() -> None:
    op.create_table(
        "legacy_item_extraction_acceptances",
        sa.Column("acceptance_id", sa.String(47), primary_key=True),
        sa.Column("extraction_result_id", sa.String(50), nullable=False),
        sa.Column("result_artifact_id", sa.String(41), nullable=False),
        sa.Column("result_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("result_artifact_member_path", sa.String(512), nullable=False),
        sa.Column("result_artifact_schema_ref", sa.String(256), nullable=False),
        sa.Column("result_artifact_media_type", sa.String(128), nullable=False),
        sa.Column("result_artifact_sha256", sa.String(71), nullable=False),
        sa.Column("result_sha256", sa.String(71), nullable=False),
        sa.Column("acceptance_artifact_id", sa.String(41), nullable=False),
        sa.Column("acceptance_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("acceptance_artifact_member_path", sa.String(512), nullable=False),
        sa.Column("acceptance_artifact_schema_ref", sa.String(256), nullable=False),
        sa.Column("acceptance_artifact_media_type", sa.String(128), nullable=False),
        sa.Column("acceptance_artifact_sha256", sa.String(71), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("coverage_state", sa.String(16), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(128), nullable=False),
        sa.Column("acceptance_sha256", sa.String(71), nullable=False, unique=True),
        sa.ForeignKeyConstraint(
            ["result_artifact_id", "result_artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_legacy_item_acceptance_result_artifact_revision_identity",
        ),
        sa.ForeignKeyConstraint(
            ["acceptance_artifact_id", "acceptance_artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_legacy_item_acceptance_artifact_revision_identity",
        ),
        sa.CheckConstraint(
            "state IN ('ACCEPTED','ACCEPTED_WITH_CORRECTIONS','REJECTED')",
            name="ck_legacy_item_extraction_acceptance_state",
        ),
        sa.CheckConstraint(
            "coverage_state IN ('COMPLETE','INCOMPLETE','CONFLICT')",
            name="ck_legacy_item_extraction_acceptance_coverage",
        ),
    )
    op.create_index(
        "ix_legacy_item_extraction_acceptances_result",
        "legacy_item_extraction_acceptances",
        ["extraction_result_id"],
    )
    op.create_table(
        "legacy_item_extraction_decisions",
        sa.Column("decision_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("acceptance_id", sa.String(47), nullable=False),
        sa.Column("item_proposal_id", sa.String(45), nullable=False),
        sa.Column("item_number", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.ForeignKeyConstraint(
            ["acceptance_id"],
            ["legacy_item_extraction_acceptances.acceptance_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "acceptance_id", "item_number", name="uq_legacy_item_acceptance_item_number"
        ),
        sa.UniqueConstraint(
            "acceptance_id",
            "item_proposal_id",
            name="uq_legacy_item_acceptance_item_proposal",
        ),
        sa.CheckConstraint("item_number > 0", name="ck_legacy_item_acceptance_item_number"),
        sa.CheckConstraint(
            "decision IN ('ACCEPT','CORRECT_AND_ACCEPT','REJECT')",
            name="ck_legacy_item_acceptance_item_decision",
        ),
    )


def _create_coverage_tables() -> None:
    op.create_table(
        "legacy_item_corpus_coverages",
        sa.Column("coverage_id", sa.String(45), primary_key=True),
        sa.Column("inventory_id", sa.String(48), nullable=False),
        sa.Column("inventory_sha256", sa.String(71), nullable=False),
        sa.Column("artifact_id", sa.String(41), nullable=False),
        sa.Column("artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("artifact_member_path", sa.String(512), nullable=False),
        sa.Column("artifact_schema_ref", sa.String(256), nullable=False),
        sa.Column("artifact_media_type", sa.String(128), nullable=False),
        sa.Column("artifact_sha256", sa.String(71), nullable=False),
        sa.Column("expected_item_count", sa.Integer(), nullable=False),
        sa.Column("accepted_item_count", sa.Integer(), nullable=False),
        sa.Column("missing_item_count", sa.Integer(), nullable=False),
        sa.Column("conflict_item_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_sha256", sa.String(71), nullable=False, unique=True),
        sa.ForeignKeyConstraint(
            ["artifact_id", "artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_legacy_item_corpus_coverage_artifact_revision_identity",
        ),
        sa.CheckConstraint(
            "state IN ('COMPLETE','INCOMPLETE','CONFLICT')",
            name="ck_legacy_item_corpus_coverage_state",
        ),
        sa.CheckConstraint(
            "expected_item_count >= 0 AND accepted_item_count >= 0 "
            "AND missing_item_count >= 0 AND conflict_item_count >= 0",
            name="ck_legacy_item_corpus_coverage_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "expected_item_count = accepted_item_count + missing_item_count + conflict_item_count",
            name="ck_legacy_item_corpus_coverage_exact_partition",
        ),
    )
    op.create_index(
        "ix_legacy_item_corpus_coverages_inventory",
        "legacy_item_corpus_coverages",
        ["inventory_id", "created_at", "coverage_id"],
    )
    op.create_table(
        "legacy_item_corpus_bundle_coverages",
        sa.Column("bundle_coverage_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("coverage_id", sa.String(45), nullable=False),
        sa.Column("assessment_source_bundle_id", sa.String(45), nullable=False),
        sa.Column("assessment_source_bundle_revision_id", sa.String(48), nullable=False),
        sa.Column("bundle_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("expected_item_count", sa.Integer(), nullable=False),
        sa.Column("accepted_item_count", sa.Integer(), nullable=False),
        sa.Column("missing_item_count", sa.Integer(), nullable=False),
        sa.Column("conflict_item_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["coverage_id"],
            ["legacy_item_corpus_coverages.coverage_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_source_bundle_id", "assessment_source_bundle_revision_id"],
            [
                "assessment_source_bundle_revisions.assessment_source_bundle_id",
                "assessment_source_bundle_revisions.assessment_source_bundle_revision_id",
            ],
            name="fk_legacy_item_corpus_coverage_bundle_revision_identity",
        ),
        sa.UniqueConstraint(
            "coverage_id",
            "assessment_source_bundle_revision_id",
            name="uq_legacy_item_corpus_bundle_coverage",
        ),
        sa.CheckConstraint(
            "expected_item_count > 0 AND accepted_item_count >= 0 "
            "AND missing_item_count >= 0 AND conflict_item_count >= 0",
            name="ck_legacy_item_corpus_bundle_coverage_counts",
        ),
        sa.CheckConstraint(
            "expected_item_count = accepted_item_count + missing_item_count + conflict_item_count",
            name="ck_legacy_item_corpus_bundle_coverage_exact_partition",
        ),
    )
    op.create_index(
        "ix_legacy_item_corpus_bundle_coverages_bundle",
        "legacy_item_corpus_bundle_coverages",
        ["assessment_source_bundle_revision_id", "coverage_id"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM assessment_source_bundles LIMIT 1)
             OR EXISTS (SELECT 1 FROM assessment_layout_observations LIMIT 1)
             OR EXISTS (SELECT 1 FROM legacy_item_extraction_acceptances LIMIT 1)
             OR EXISTS (SELECT 1 FROM legacy_item_corpus_coverages LIMIT 1) THEN
            RAISE EXCEPTION 'legacy assessment history prevents safe downgrade';
          END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_assessment_source_bundles_controlled_update "
        "ON assessment_source_bundles"
    )
    for table_name in reversed(_IMMUTABLE_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.drop_table("legacy_item_corpus_bundle_coverages")
    op.drop_table("legacy_item_corpus_coverages")
    op.drop_table("legacy_item_extraction_decisions")
    op.drop_table("legacy_item_extraction_acceptances")
    op.drop_table("assessment_layout_observations")
    op.drop_table("assessment_source_bundle_members")
    op.drop_constraint(
        "fk_assessment_source_bundle_current_revision",
        "assessment_source_bundles",
        type_="foreignkey",
    )
    op.drop_table("assessment_source_bundle_revisions")
    op.drop_table("assessment_source_bundles")
    op.execute("DROP FUNCTION enforce_assessment_source_bundle_logical_update()")
    op.execute("DROP FUNCTION reject_legacy_assessment_immutable_mutation()")
