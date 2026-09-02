"""add immutable organization, assessment occurrence, and item origin records

Revision ID: 20260901_0024
Revises: 20260831_0023
Create Date: 2026-09-01 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0024"
down_revision: str | None = "20260831_0023"
branch_labels: str | None = None
depends_on: str | None = None

_IMMUTABLE_TABLES = (
    "organization_revisions",
    "organization_aliases",
    "organization_source_evidence",
    "assessment_occurrence_revisions",
    "assessment_occurrence_source_evidence",
    "item_origin_profiles",
    "item_origin_occurrences",
    "item_origin_derivations",
    "item_origin_provenance",
)


def upgrade() -> None:
    _create_guard_functions()
    op.create_unique_constraint(
        "uq_artifact_revision_identity",
        "artifact_revisions",
        ["logical_artifact_id", "revision_id"],
    )
    op.create_unique_constraint(
        "uq_item_revision_identity",
        "item_revisions",
        ["item_id", "item_revision_id"],
    )
    op.create_table(
        "organizations",
        sa.Column("organization_id", sa.String(36), primary_key=True),
        sa.Column("organization_key", sa.String(160), nullable=False, unique=True),
        sa.Column("current_revision_id", sa.String(39)),
        sa.Column("lifecycle_state", sa.String(16), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')", name="ck_organizations_state"
        ),
        sa.CheckConstraint("lock_version > 0", name="ck_organizations_lock_version"),
    )
    op.create_table(
        "organization_revisions",
        sa.Column("organization_revision_id", sa.String(39), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.String(39)),
        sa.Column("revision_state", sa.String(16), nullable=False),
        sa.Column("organization_class", sa.String(40), nullable=False),
        sa.Column("class_detail", sa.String(256)),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("jurisdiction_level", sa.String(16), nullable=False),
        sa.Column("jurisdiction_code", sa.String(64)),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("rights_policy_id", sa.String(45), nullable=False),
        sa.Column("rights_policy_revision_id", sa.String(48), nullable=False),
        sa.Column("rights_policy_sha256", sa.String(71), nullable=False),
        sa.Column("revision_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.organization_id"]),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"], ["organization_revisions.organization_revision_id"]
        ),
        sa.UniqueConstraint(
            "organization_id", "revision_number", name="uq_organization_revision_number"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "organization_revision_id",
            name="uq_organization_revision_identity",
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_organization_revision_number"),
        sa.CheckConstraint(
            "revision_state IN ('REVIEWED','SUPERSEDED','RETIRED')",
            name="ck_organization_revision_state",
        ),
        sa.CheckConstraint(
            "organization_class IN ('EOM_INTERNAL','NATIONAL_ASSESSMENT_AGENCY',"
            "'EDUCATION_AUTHORITY','SCHOOL','UNIVERSITY','PUBLISHER',"
            "'PRIVATE_EDUCATION_PROVIDER','OTHER_REVIEWED')",
            name="ck_organization_revision_class",
        ),
        sa.CheckConstraint(
            "(organization_class = 'OTHER_REVIEWED') = (class_detail IS NOT NULL)",
            name="ck_organization_revision_class_detail",
        ),
        sa.CheckConstraint(
            "jurisdiction_level IN ('NATIONAL','PROVINCE','METROPOLITAN','CITY',"
            "'COUNTY','DISTRICT','INSTITUTION','OTHER')",
            name="ck_organization_revision_jurisdiction",
        ),
        sa.CheckConstraint(
            "effective_from IS NULL OR effective_to IS NULL OR effective_from <= effective_to",
            name="ck_organization_revision_effective_interval",
        ),
    )
    op.create_index(
        "ix_organization_revisions_organization", "organization_revisions", ["organization_id"]
    )
    op.create_index(
        "ix_organization_revisions_class", "organization_revisions", ["organization_class"]
    )
    op.create_foreign_key(
        "fk_organization_current_revision",
        "organizations",
        "organization_revisions",
        ["current_revision_id"],
        ["organization_revision_id"],
    )
    op.create_table(
        "organization_aliases",
        sa.Column("organization_alias_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("organization_revision_id", sa.String(39), nullable=False),
        sa.Column("alias_kind", sa.String(16), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("display_value", sa.String(256), nullable=False),
        sa.Column("normalized_value", sa.String(256), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_revision_id"],
            ["organization_revisions.organization_revision_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_revision_id",
            "locale",
            "normalized_value",
            name="uq_organization_alias_revision_value",
        ),
        sa.CheckConstraint(
            "alias_kind IN ('OFFICIAL','ABBREVIATION','FORMER','LEGACY_SOURCE')",
            name="ck_organization_alias_kind",
        ),
    )
    op.create_index(
        "ix_organization_alias_lookup",
        "organization_aliases",
        ["normalized_value", "locale", "organization_revision_id"],
    )
    _create_source_evidence_table(
        "organization_source_evidence",
        "organization_source_evidence_id",
        "organization_revision_id",
        "organization_revisions",
        "organization_revision_id",
        "uq_organization_source_evidence",
        "fk_organization_source_evidence_artifact_revision_identity",
    )
    op.create_table(
        "assessment_occurrences",
        sa.Column("assessment_occurrence_id", sa.String(43), primary_key=True),
        sa.Column("occurrence_key", sa.String(160), nullable=False, unique=True),
        sa.Column("current_revision_id", sa.String(41)),
        sa.Column("lifecycle_state", sa.String(16), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')",
            name="ck_assessment_occurrences_state",
        ),
        sa.CheckConstraint("lock_version > 0", name="ck_assessment_occurrences_lock_version"),
    )
    op.create_table(
        "assessment_occurrence_revisions",
        sa.Column("assessment_occurrence_revision_id", sa.String(41), primary_key=True),
        sa.Column("assessment_occurrence_id", sa.String(43), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.String(41)),
        sa.Column("revision_state", sa.String(16), nullable=False),
        sa.Column("issuing_organization_id", sa.String(36), nullable=False),
        sa.Column("issuing_organization_revision_id", sa.String(39), nullable=False),
        sa.Column("issuing_organization_revision_sha256", sa.String(71), nullable=False),
        sa.Column("occurrence_kind", sa.String(32), nullable=False),
        sa.Column("exam_family_key", sa.String(160), nullable=False),
        sa.Column("administration_year", sa.Integer(), nullable=False),
        sa.Column("administration_date", sa.Date()),
        sa.Column("session_key", sa.String(160)),
        sa.Column("subject_key", sa.String(160), nullable=False),
        sa.Column("form_key", sa.String(160)),
        sa.Column("region_key", sa.String(160)),
        sa.Column("display_label", sa.String(512), nullable=False),
        sa.Column("rights_policy_id", sa.String(45), nullable=False),
        sa.Column("rights_policy_revision_id", sa.String(48), nullable=False),
        sa.Column("rights_policy_sha256", sa.String(71), nullable=False),
        sa.Column("revision_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["assessment_occurrence_id"], ["assessment_occurrences.assessment_occurrence_id"]
        ),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            ["assessment_occurrence_revisions.assessment_occurrence_revision_id"],
        ),
        sa.ForeignKeyConstraint(
            ["issuing_organization_id", "issuing_organization_revision_id"],
            [
                "organization_revisions.organization_id",
                "organization_revisions.organization_revision_id",
            ],
            name="fk_assessment_occurrence_organization_revision_identity",
        ),
        sa.UniqueConstraint(
            "assessment_occurrence_id",
            "revision_number",
            name="uq_assessment_occurrence_revision_number",
        ),
        sa.UniqueConstraint(
            "assessment_occurrence_id",
            "assessment_occurrence_revision_id",
            name="uq_assessment_occurrence_revision_identity",
        ),
        sa.UniqueConstraint(
            "issuing_organization_id",
            "exam_family_key",
            "administration_year",
            "administration_date",
            "session_key",
            "subject_key",
            "form_key",
            "region_key",
            name="uq_assessment_occurrence_reviewed_identity",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("revision_number > 0", name="ck_assessment_occurrence_revision_number"),
        sa.CheckConstraint(
            "revision_state IN ('REVIEWED','SUPERSEDED','WITHDRAWN')",
            name="ck_assessment_occurrence_revision_state",
        ),
        sa.CheckConstraint(
            "occurrence_kind IN ('NATIONAL_ENTRANCE','NATIONAL_ACHIEVEMENT',"
            "'EDUCATION_AUTHORITY_EXAM','SCHOOL_EXAM','INSTITUTIONAL_EXAM','OTHER_REVIEWED')",
            name="ck_assessment_occurrence_revision_kind",
        ),
    )
    op.create_index(
        "ix_assessment_occurrence_lookup",
        "assessment_occurrence_revisions",
        ["exam_family_key", "administration_year", "subject_key"],
    )
    op.create_index(
        "ix_assessment_occurrence_organization",
        "assessment_occurrence_revisions",
        ["issuing_organization_revision_id"],
    )
    op.create_foreign_key(
        "fk_assessment_occurrence_current_revision",
        "assessment_occurrences",
        "assessment_occurrence_revisions",
        ["current_revision_id"],
        ["assessment_occurrence_revision_id"],
    )
    _create_source_evidence_table(
        "assessment_occurrence_source_evidence",
        "assessment_occurrence_source_evidence_id",
        "assessment_occurrence_revision_id",
        "assessment_occurrence_revisions",
        "assessment_occurrence_revision_id",
        "uq_assessment_occurrence_source_evidence",
        "fk_assessment_occ_source_evidence_artifact_revision_identity",
    )
    _create_item_origin_tables()
    for table_name in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION reject_item_origin_immutable_mutation()"
        )
    for table_name in ("organizations", "assessment_occurrences"):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_controlled_update "
            f"BEFORE INSERT OR UPDATE OR DELETE ON {table_name} "
            "FOR EACH ROW EXECUTE FUNCTION enforce_item_origin_logical_update()"
        )


def _create_guard_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_item_origin_immutable_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'immutable item origin record cannot be changed';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_item_origin_logical_update() RETURNS trigger AS $$
        DECLARE
          target_owner_id text;
          target_previous_revision_id text;
          target_revision_state text;
          target_revision_number integer;
          old_revision_number integer;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'item origin logical identity cannot be deleted';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.current_revision_id IS NOT NULL
               OR NEW.lock_version <> 1
               OR NEW.lifecycle_state <> 'ACTIVE' THEN
              RAISE EXCEPTION 'item origin logical identity must start active without a revision';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.lock_version <> OLD.lock_version + 1 THEN
            RAISE EXCEPTION 'item origin logical lock version must advance exactly once';
          END IF;
          IF OLD.lifecycle_state = 'RETIRED' THEN
            RAISE EXCEPTION 'retired item origin identity cannot be changed';
          END IF;
          IF NEW.current_revision_id IS NOT DISTINCT FROM OLD.current_revision_id
             AND NEW.lifecycle_state = OLD.lifecycle_state THEN
            RAISE EXCEPTION 'item origin logical update must change state or revision';
          END IF;
          IF TG_TABLE_NAME = 'organizations' THEN
            IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.organization_key IS DISTINCT FROM OLD.organization_key
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
              RAISE EXCEPTION 'organization immutable identity cannot be changed';
            END IF;
            IF NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id THEN
              SELECT organization_id, previous_revision_id, revision_state, revision_number
                INTO target_owner_id, target_previous_revision_id,
                     target_revision_state, target_revision_number
                FROM organization_revisions
               WHERE organization_revision_id = NEW.current_revision_id;
              IF NOT FOUND
                 OR target_owner_id IS DISTINCT FROM NEW.organization_id
                 OR target_previous_revision_id IS DISTINCT FROM OLD.current_revision_id
                 OR target_revision_state <> 'REVIEWED'
                 OR NEW.lifecycle_state <> 'ACTIVE' THEN
                RAISE EXCEPTION 'organization current revision pointer is invalid';
              END IF;
              IF OLD.current_revision_id IS NULL THEN
                old_revision_number := 0;
              ELSE
                SELECT revision_number INTO STRICT old_revision_number
                  FROM organization_revisions
                 WHERE organization_revision_id = OLD.current_revision_id;
              END IF;
            END IF;
          ELSE
            IF NEW.assessment_occurrence_id IS DISTINCT FROM OLD.assessment_occurrence_id
               OR NEW.occurrence_key IS DISTINCT FROM OLD.occurrence_key
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.created_by IS DISTINCT FROM OLD.created_by THEN
              RAISE EXCEPTION 'assessment occurrence immutable identity cannot be changed';
            END IF;
            IF NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id THEN
              SELECT assessment_occurrence_id, previous_revision_id,
                     revision_state, revision_number
                INTO target_owner_id, target_previous_revision_id,
                     target_revision_state, target_revision_number
                FROM assessment_occurrence_revisions
               WHERE assessment_occurrence_revision_id = NEW.current_revision_id;
              IF NOT FOUND
                 OR target_owner_id IS DISTINCT FROM NEW.assessment_occurrence_id
                 OR target_previous_revision_id IS DISTINCT FROM OLD.current_revision_id
                 OR target_revision_state <> 'REVIEWED'
                 OR NEW.lifecycle_state <> 'ACTIVE' THEN
                RAISE EXCEPTION 'assessment occurrence current revision pointer is invalid';
              END IF;
              IF OLD.current_revision_id IS NULL THEN
                old_revision_number := 0;
              ELSE
                SELECT revision_number INTO STRICT old_revision_number
                  FROM assessment_occurrence_revisions
                 WHERE assessment_occurrence_revision_id = OLD.current_revision_id;
              END IF;
            END IF;
          END IF;
          IF NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id
             AND target_revision_number <> old_revision_number + 1 THEN
            RAISE EXCEPTION 'item origin revision sequence must advance exactly once';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def _create_source_evidence_table(
    table_name: str,
    primary_key: str,
    owner_column: str,
    owner_table: str,
    owner_target: str,
    unique_name: str,
    artifact_revision_foreign_key_name: str,
) -> None:
    op.create_table(
        table_name,
        sa.Column(primary_key, sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            owner_column,
            sa.String(39 if owner_column.startswith("organization_") else 41),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.String(41), nullable=False),
        sa.Column("artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("member_path", sa.String(512), nullable=False),
        sa.Column("schema_ref", sa.String(256), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(71), nullable=False),
        sa.ForeignKeyConstraint(
            [owner_column], [f"{owner_table}.{owner_target}"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name=artifact_revision_foreign_key_name,
        ),
        sa.UniqueConstraint(owner_column, "artifact_revision_id", "member_path", name=unique_name),
    )
    op.create_index(f"ix_{table_name}_owner", table_name, [owner_column])


def _create_item_origin_tables() -> None:
    op.create_table(
        "item_origin_profiles",
        sa.Column("item_origin_profile_id", sa.String(46), primary_key=True),
        sa.Column("item_id", sa.String(37), nullable=False),
        sa.Column("item_revision_id", sa.String(40), nullable=False, unique=True),
        sa.Column("item_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("source_domain", sa.String(32), nullable=False),
        sa.Column("creation_method", sa.String(24), nullable=False),
        sa.Column("source_organization_id", sa.String(36)),
        sa.Column("source_organization_revision_id", sa.String(39)),
        sa.Column("source_organization_revision_sha256", sa.String(71)),
        sa.Column("rights_policy_id", sa.String(45), nullable=False),
        sa.Column("rights_policy_revision_id", sa.String(48), nullable=False),
        sa.Column("rights_policy_sha256", sa.String(71), nullable=False),
        sa.Column("profile_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id", "item_revision_id"],
            ["item_revisions.item_id", "item_revisions.item_revision_id"],
            name="fk_item_origin_profile_item_revision_identity",
        ),
        sa.ForeignKeyConstraint(
            ["source_organization_id", "source_organization_revision_id"],
            [
                "organization_revisions.organization_id",
                "organization_revisions.organization_revision_id",
            ],
            name="fk_item_origin_profile_organization_revision_identity",
        ),
        sa.CheckConstraint(
            "source_domain IN ('INTERNAL_EOM','EXTERNAL_INSTITUTION',"
            "'EXTERNAL_INDIVIDUAL','LEGACY_UNKNOWN')",
            name="ck_item_origin_profile_domain",
        ),
        sa.CheckConstraint(
            "creation_method IN ('HUMAN_AUTHORED','AI_ASSISTED','AI_GENERATED',"
            "'IMPORTED','ADAPTED','UNKNOWN')",
            name="ck_item_origin_profile_method",
        ),
        sa.CheckConstraint(
            "((source_organization_id IS NULL) = (source_organization_revision_id IS NULL))"
            " AND ((source_organization_id IS NULL) = "
            "(source_organization_revision_sha256 IS NULL))",
            name="ck_item_origin_profile_organization_pointer",
        ),
        sa.CheckConstraint(
            "source_domain NOT IN ('INTERNAL_EOM','EXTERNAL_INSTITUTION')"
            " OR source_organization_revision_id IS NOT NULL",
            name="ck_item_origin_profile_institutional_organization",
        ),
    )
    op.create_index("ix_item_origin_profiles_item", "item_origin_profiles", ["item_id"])
    op.create_index(
        "ix_item_origin_profiles_domain_method",
        "item_origin_profiles",
        ["source_domain", "creation_method"],
    )
    op.create_index(
        "ix_item_origin_profiles_organization",
        "item_origin_profiles",
        ["source_organization_revision_id"],
    )
    op.create_table(
        "item_origin_occurrences",
        sa.Column("item_origin_occurrence_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("item_origin_profile_id", sa.String(46), nullable=False),
        sa.Column("assessment_occurrence_id", sa.String(43), nullable=False),
        sa.Column("assessment_occurrence_revision_id", sa.String(41), nullable=False),
        sa.Column("occurrence_revision_sha256", sa.String(71), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_origin_profile_id"],
            ["item_origin_profiles.item_origin_profile_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_occurrence_id", "assessment_occurrence_revision_id"],
            [
                "assessment_occurrence_revisions.assessment_occurrence_id",
                "assessment_occurrence_revisions.assessment_occurrence_revision_id",
            ],
            name="fk_item_origin_occurrence_revision_identity",
        ),
        sa.UniqueConstraint(
            "item_origin_profile_id",
            "assessment_occurrence_revision_id",
            name="uq_item_origin_occurrence",
        ),
    )
    op.create_index(
        "ix_item_origin_occurrences_reverse",
        "item_origin_occurrences",
        ["assessment_occurrence_revision_id"],
    )
    op.create_table(
        "item_origin_derivations",
        sa.Column("item_origin_derivation_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("item_origin_profile_id", sa.String(46), nullable=False),
        sa.Column("source_kind", sa.String(48), nullable=False),
        sa.Column("logical_id", sa.String(64), nullable=False),
        sa.Column("revision_id", sa.String(64), nullable=False),
        sa.Column("manifest_sha256", sa.String(71), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_origin_profile_id"],
            ["item_origin_profiles.item_origin_profile_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "item_origin_profile_id",
            "source_kind",
            "logical_id",
            "revision_id",
            name="uq_item_origin_derivation",
        ),
        sa.CheckConstraint(
            "source_kind IN ('ITEM_REVISION','DOCUMENT_REVISION',"
            "'ASSESSMENT_SOURCE_BUNDLE_REVISION')",
            name="ck_item_origin_derivation_kind",
        ),
        sa.CheckConstraint(
            "relation IN ('DERIVED_FROM','TRANSLATED_FROM','DIGITIZED_FROM','RECONSTRUCTED_FROM')",
            name="ck_item_origin_derivation_relation",
        ),
        sa.CheckConstraint(
            "(source_kind = 'ITEM_REVISION' AND logical_id ~ '^item_[0-9a-f]{32}$' "
            "AND revision_id ~ '^itemrev_[0-9a-f]{32}$') OR "
            "(source_kind = 'DOCUMENT_REVISION' AND logical_id ~ '^edudoc_[0-9a-f]{32}$' "
            "AND revision_id ~ '^edudocrev_[0-9a-f]{32}$') OR "
            "(source_kind = 'ASSESSMENT_SOURCE_BUNDLE_REVISION' "
            "AND logical_id ~ '^assessbundle_[0-9a-f]{32}$' "
            "AND revision_id ~ '^assessbundlerev_[0-9a-f]{32}$')",
            name="ck_item_origin_derivation_typed_pointer",
        ),
    )
    op.create_index(
        "ix_item_origin_derivations_reverse",
        "item_origin_derivations",
        ["source_kind", "revision_id"],
    )
    op.create_table(
        "item_origin_provenance",
        sa.Column("item_origin_provenance_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("item_origin_profile_id", sa.String(46), nullable=False),
        sa.Column("provenance_kind", sa.String(24), nullable=False),
        sa.Column("logical_id", sa.String(128), nullable=False),
        sa.Column("revision_id", sa.String(128)),
        sa.Column("evidence_sha256", sa.String(71), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_origin_profile_id"],
            ["item_origin_profiles.item_origin_profile_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "item_origin_profile_id",
            "provenance_kind",
            "logical_id",
            "revision_id",
            name="uq_item_origin_provenance",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            "provenance_kind IN ('WORKFLOW','CONTENT_INTAKE','ITEM_PROVENANCE','MANUAL_REVIEW')",
            name="ck_item_origin_provenance_kind",
        ),
        sa.CheckConstraint(
            "(provenance_kind = 'WORKFLOW' AND logical_id ~ '^workflow_[0-9a-f]{32}$' "
            "AND revision_id ~ '^execplan_[0-9a-f]{32}$') OR "
            "(provenance_kind = 'CONTENT_INTAKE' AND logical_id ~ '^intake_[0-9a-f]{32}$' "
            "AND revision_id ~ '^rev_[0-9a-f]{32}$') OR "
            "(provenance_kind = 'ITEM_PROVENANCE' "
            "AND logical_id ~ '^provenance_[0-9a-f]{32}$' AND revision_id IS NULL) OR "
            "(provenance_kind = 'MANUAL_REVIEW' "
            "AND logical_id ~ '^itemacceptance_[0-9a-f]{32}$' "
            "AND revision_id ~ '^rev_[0-9a-f]{32}$')",
            name="ck_item_origin_provenance_typed_pointer",
        ),
    )
    op.create_index(
        "ix_item_origin_provenance_reverse",
        "item_origin_provenance",
        ["provenance_kind", "logical_id"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM organizations LIMIT 1)
             OR EXISTS (SELECT 1 FROM assessment_occurrences LIMIT 1)
             OR EXISTS (SELECT 1 FROM item_origin_profiles LIMIT 1) THEN
            RAISE EXCEPTION 'item origin history prevents safe downgrade';
          END IF;
        END;
        $$
        """
    )
    for table_name in ("organizations", "assessment_occurrences"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_controlled_update ON {table_name}")
    for table_name in reversed(_IMMUTABLE_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    for table_name in (
        "item_origin_provenance",
        "item_origin_derivations",
        "item_origin_occurrences",
        "item_origin_profiles",
        "assessment_occurrence_source_evidence",
    ):
        op.drop_table(table_name)
    op.drop_constraint(
        "fk_assessment_occurrence_current_revision",
        "assessment_occurrences",
        type_="foreignkey",
    )
    op.drop_table("assessment_occurrence_revisions")
    op.drop_table("assessment_occurrences")
    op.drop_table("organization_source_evidence")
    op.drop_table("organization_aliases")
    op.drop_constraint("fk_organization_current_revision", "organizations", type_="foreignkey")
    op.drop_table("organization_revisions")
    op.drop_table("organizations")
    op.drop_constraint("uq_item_revision_identity", "item_revisions", type_="unique")
    op.drop_constraint("uq_artifact_revision_identity", "artifact_revisions", type_="unique")
    op.execute("DROP FUNCTION enforce_item_origin_logical_update()")
    op.execute("DROP FUNCTION reject_item_origin_immutable_mutation()")
