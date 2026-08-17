"""Add manual content intake and content pack persistence.

Revision ID: 20260817_0004
Revises: 20260815_0003
Create Date: 2026-08-17 15:00:00Z
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_0004"
down_revision: str | None = "20260815_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "content_intake_batches",
        sa.Column("intake_batch_id", sa.String(39), primary_key=True),
        sa.Column("batch_name", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("received_by", sa.String(128), nullable=False),
        sa.Column("source_owner_type", sa.String(32), nullable=False),
        sa.Column("source_owner_reference", sa.String(128), nullable=False),
        sa.Column(
            "source_manifest_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=True,
        ),
        sa.Column(
            "source_manifest_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=True,
        ),
        sa.Column("source_manifest_sha256", sa.String(71), nullable=True),
        sa.Column("source_fingerprint", sa.String(71), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "state IN ('RECEIVED','HASHED','ANALYSIS_PENDING','ANALYSIS_ATTACHED',"
            "'VALIDATING','NEEDS_DECISION','ACCEPTED','REJECTED','SUPERSEDED','IMPORTED','FAILED')",
            name="ck_content_intake_batches_state",
        ),
    )
    op.create_table(
        "content_intake_source_files",
        sa.Column("source_file_id", sa.String(43), primary_key=True),
        sa.Column(
            "intake_batch_id",
            sa.String(39),
            sa.ForeignKey("content_intake_batches.intake_batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("normalized_filename", sa.String(255), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(71), nullable=False),
        sa.Column(
            "artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("declared_role", sa.String(32), nullable=False),
        sa.Column("declared_description", sa.String(500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("intake_batch_id", "relative_path", name="uq_intake_source_path"),
        sa.UniqueConstraint(
            "intake_batch_id", "sha256", "declared_role", name="uq_intake_source_hash_role"
        ),
    )
    op.create_index(
        "ix_content_intake_source_files_intake_batch_id",
        "content_intake_source_files",
        ["intake_batch_id"],
    )
    op.create_table(
        "content_intake_analyses",
        sa.Column("analysis_id", sa.String(41), primary_key=True),
        sa.Column(
            "intake_batch_id",
            sa.String(39),
            sa.ForeignKey("content_intake_batches.intake_batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("proposal_key", sa.String(128), nullable=False),
        sa.Column("analysis_source_type", sa.String(40), nullable=False),
        sa.Column(
            "analysis_report_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "analysis_report_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("analysis_report_sha256", sa.String(71), nullable=False),
        sa.Column(
            "mapping_proposal_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "mapping_proposal_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("mapping_proposal_sha256", sa.String(71), nullable=False),
        sa.Column(
            "uncertainties_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "uncertainties_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("uncertainties_sha256", sa.String(71), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("immutable", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_content_intake_analyses_intake_batch_id", "content_intake_analyses", ["intake_batch_id"]
    )
    op.create_table(
        "content_intake_decisions",
        sa.Column("decision_id", sa.String(41), primary_key=True),
        sa.Column(
            "intake_batch_id",
            sa.String(39),
            sa.ForeignKey("content_intake_batches.intake_batch_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "analysis_id",
            sa.String(41),
            sa.ForeignKey("content_intake_analyses.analysis_id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column(
            "decision_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "decision_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("decision_sha256", sa.String(71), nullable=False),
        sa.Column("decided_by", sa.String(128), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("immutable", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "content_intake_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "intake_batch_id",
            sa.String(39),
            sa.ForeignKey("content_intake_batches.intake_batch_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("prior_state", sa.String(32), nullable=True),
        sa.Column("new_state", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("intake_batch_id", "sequence", name="uq_intake_event_sequence"),
    )
    op.create_index(
        "ix_content_intake_events_intake_batch_id", "content_intake_events", ["intake_batch_id"]
    )

    op.create_table(
        "content_packs",
        sa.Column("content_pack_id", sa.String(41), primary_key=True),
        sa.Column("pack_key", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("domain_key", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "content_pack_releases",
        sa.Column("content_pack_release_id", sa.String(40), primary_key=True),
        sa.Column(
            "content_pack_id",
            sa.String(41),
            sa.ForeignKey("content_packs.content_pack_id"),
            nullable=False,
        ),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("source_tree_sha256", sa.String(71), nullable=False),
        sa.Column("bundle_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("manifest_sha256", sa.String(71), nullable=False),
        sa.Column(
            "bundle_artifact_id",
            sa.String(41),
            sa.ForeignKey("artifacts.logical_artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "bundle_artifact_revision_id",
            sa.String(36),
            sa.ForeignKey("artifact_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column(
            "canonical_manifest_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("compatibility_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.String(128), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "state IN ('DRAFT','VALIDATED','RELEASED','DEPRECATED','RETIRED','REJECTED')",
            name="ck_content_pack_release_state",
        ),
        sa.UniqueConstraint("content_pack_id", "version", name="uq_content_pack_version"),
    )
    op.create_index(
        "ix_content_pack_releases_content_pack_id", "content_pack_releases", ["content_pack_id"]
    )
    op.create_table(
        "content_pack_files",
        sa.Column("content_pack_file_id", sa.String(41), primary_key=True),
        sa.Column(
            "content_pack_release_id",
            sa.String(40),
            sa.ForeignKey("content_pack_releases.content_pack_release_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(71), nullable=False),
        sa.Column("logical_role", sa.String(64), nullable=False),
        sa.Column("schema_ref", sa.String(256), nullable=True),
        sa.UniqueConstraint("content_pack_release_id", "relative_path", name="uq_pack_file_path"),
    )
    op.create_index(
        "ix_content_pack_files_content_pack_release_id",
        "content_pack_files",
        ["content_pack_release_id"],
    )
    op.create_table(
        "content_pack_profiles",
        sa.Column("content_pack_profile_id", sa.String(44), primary_key=True),
        sa.Column(
            "content_pack_release_id",
            sa.String(40),
            sa.ForeignKey("content_pack_releases.content_pack_release_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_type", sa.String(32), nullable=False),
        sa.Column("profile_key", sa.String(128), nullable=False),
        sa.Column("profile_version", sa.String(32), nullable=False),
        sa.Column("profile_sha256", sa.String(71), nullable=False),
        sa.Column("template_relative_path", sa.Text(), nullable=False),
        sa.Column("input_schema_ref", sa.String(256), nullable=False),
        sa.Column("output_schema_ref", sa.String(256), nullable=False),
        sa.Column("compiled_profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.UniqueConstraint(
            "content_pack_release_id", "profile_type", "profile_key", name="uq_pack_profile"
        ),
    )
    op.create_index(
        "ix_content_pack_profiles_content_pack_release_id",
        "content_pack_profiles",
        ["content_pack_release_id"],
    )
    op.create_table(
        "content_pack_activations",
        sa.Column("activation_id", sa.String(43), primary_key=True),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("pack_key", sa.String(64), nullable=False),
        sa.Column(
            "content_pack_release_id",
            sa.String(40),
            sa.ForeignKey("content_pack_releases.content_pack_release_id"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("activated_by", sa.String(128), nullable=False),
        sa.Column(
            "activated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "uq_active_pack_environment",
        "content_pack_activations",
        ["environment", "pack_key"],
        unique=True,
        postgresql_where=sa.text("active = true"),
    )
    op.create_table(
        "content_pack_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "content_pack_release_id",
            sa.String(40),
            sa.ForeignKey("content_pack_releases.content_pack_release_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("prior_state", sa.String(32), nullable=True),
        sa.Column("new_state", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "content_pack_release_id", "sequence", name="uq_content_pack_event_sequence"
        ),
    )
    op.create_index(
        "ix_content_pack_events_content_pack_release_id",
        "content_pack_events",
        ["content_pack_release_id"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_intake_immutable_mutation() RETURNS trigger AS $$
        BEGIN
          IF TG_TABLE_NAME IN (
            'content_intake_source_files',
            'content_intake_analyses',
            'content_intake_decisions'
          ) THEN
            RAISE EXCEPTION 'content intake evidence is immutable';
          END IF;
          IF OLD.state IN ('REJECTED','SUPERSEDED','IMPORTED','FAILED') THEN
            RAISE EXCEPTION 'terminal content intake batch is immutable';
          END IF;
          IF OLD.state = 'ACCEPTED' AND (
            NEW.state IS DISTINCT FROM 'IMPORTED' OR
            NEW.batch_name IS DISTINCT FROM OLD.batch_name OR
            NEW.purpose IS DISTINCT FROM OLD.purpose OR
            NEW.received_by IS DISTINCT FROM OLD.received_by OR
            NEW.source_owner_type IS DISTINCT FROM OLD.source_owner_type OR
            NEW.source_owner_reference IS DISTINCT FROM OLD.source_owner_reference OR
            NEW.source_manifest_artifact_id IS DISTINCT FROM OLD.source_manifest_artifact_id OR
            NEW.source_manifest_artifact_revision_id IS DISTINCT FROM
              OLD.source_manifest_artifact_revision_id OR
            NEW.source_manifest_sha256 IS DISTINCT FROM OLD.source_manifest_sha256 OR
            NEW.source_fingerprint IS DISTINCT FROM OLD.source_fingerprint
          ) THEN
            RAISE EXCEPTION 'accepted content intake batch payload is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "content_intake_source_files",
        "content_intake_analyses",
        "content_intake_decisions",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_intake_immutable_mutation()"
        )
    op.execute(
        "CREATE TRIGGER content_intake_batches_terminal_immutable BEFORE UPDATE OR DELETE "
        "ON content_intake_batches FOR EACH ROW EXECUTE FUNCTION reject_intake_immutable_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_released_content_pack() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND OLD.state IN ('RELEASED','DEPRECATED','RETIRED') THEN
            RAISE EXCEPTION 'released content pack cannot be deleted';
          END IF;
          IF OLD.state IN ('RELEASED','DEPRECATED','RETIRED') AND (
            NEW.content_pack_id IS DISTINCT FROM OLD.content_pack_id OR
            NEW.version IS DISTINCT FROM OLD.version OR
            NEW.source_tree_sha256 IS DISTINCT FROM OLD.source_tree_sha256 OR
            NEW.bundle_sha256 IS DISTINCT FROM OLD.bundle_sha256 OR
            NEW.manifest_sha256 IS DISTINCT FROM OLD.manifest_sha256 OR
            NEW.bundle_artifact_id IS DISTINCT FROM OLD.bundle_artifact_id OR
            NEW.bundle_artifact_revision_id IS DISTINCT FROM OLD.bundle_artifact_revision_id OR
            NEW.canonical_manifest_json IS DISTINCT FROM OLD.canonical_manifest_json OR
            NEW.compatibility_json IS DISTINCT FROM OLD.compatibility_json
          ) THEN
            RAISE EXCEPTION 'released content pack payload is immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER content_pack_release_immutable BEFORE UPDATE OR DELETE "
        "ON content_pack_releases FOR EACH ROW EXECUTE FUNCTION protect_released_content_pack()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS content_pack_release_immutable ON content_pack_releases")
    op.execute("DROP FUNCTION IF EXISTS protect_released_content_pack()")
    op.execute(
        "DROP TRIGGER IF EXISTS content_intake_batches_terminal_immutable ON content_intake_batches"
    )
    for table in (
        "content_intake_source_files",
        "content_intake_analyses",
        "content_intake_decisions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_intake_immutable_mutation()")
    op.drop_index(
        "ix_content_pack_events_content_pack_release_id", table_name="content_pack_events"
    )
    op.drop_table("content_pack_events")
    op.drop_index("uq_active_pack_environment", table_name="content_pack_activations")
    op.drop_table("content_pack_activations")
    op.drop_index(
        "ix_content_pack_profiles_content_pack_release_id", table_name="content_pack_profiles"
    )
    op.drop_table("content_pack_profiles")
    op.drop_index("ix_content_pack_files_content_pack_release_id", table_name="content_pack_files")
    op.drop_table("content_pack_files")
    op.drop_index("ix_content_pack_releases_content_pack_id", table_name="content_pack_releases")
    op.drop_table("content_pack_releases")
    op.drop_table("content_packs")
    op.drop_index("ix_content_intake_events_intake_batch_id", table_name="content_intake_events")
    op.drop_table("content_intake_events")
    op.drop_table("content_intake_decisions")
    op.drop_index(
        "ix_content_intake_analyses_intake_batch_id", table_name="content_intake_analyses"
    )
    op.drop_table("content_intake_analyses")
    op.drop_index(
        "ix_content_intake_source_files_intake_batch_id", table_name="content_intake_source_files"
    )
    op.drop_table("content_intake_source_files")
    op.drop_table("content_intake_batches")
