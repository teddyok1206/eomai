"""Add HWPX template, build, and validation history.

Revision ID: 20260815_0003
Revises: 20260815_0002
Create Date: 2026-08-15 18:30:00Z
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_0003"
down_revision: str | None = "20260815_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hwpx_templates",
        sa.Column("template_id", sa.String(length=40), nullable=False),
        sa.Column("logical_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("template_id"),
        sa.UniqueConstraint("logical_name"),
    )
    op.create_table(
        "hwpx_template_revisions",
        sa.Column("template_revision_id", sa.String(length=40), nullable=False),
        sa.Column("template_id", sa.String(length=40), nullable=False),
        sa.Column("source_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("source_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=71), nullable=False),
        sa.Column("binding_manifest_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("binding_manifest_revision_id", sa.String(length=36), nullable=False),
        sa.Column("binding_manifest_sha256", sa.String(length=71), nullable=False),
        sa.Column("owpml_version", sa.String(length=128), nullable=False),
        sa.Column("hancom_version_declared", sa.String(length=128), nullable=False),
        sa.Column("package_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analysis_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("immutable", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["hwpx_templates.template_id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["source_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.ForeignKeyConstraint(
            ["binding_manifest_artifact_id"], ["artifacts.logical_artifact_id"]
        ),
        sa.ForeignKeyConstraint(
            ["binding_manifest_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.PrimaryKeyConstraint("template_revision_id"),
    )
    op.create_index(
        "ix_hwpx_template_revisions_template_id", "hwpx_template_revisions", ["template_id"]
    )
    op.create_table(
        "hwpx_builds",
        sa.Column("build_id", sa.String(length=42), nullable=False),
        sa.Column("template_revision_id", sa.String(length=40), nullable=False),
        sa.Column("platform_job_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_sha256", sa.String(length=71), nullable=False),
        sa.Column("renderer_version", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("output_artifact_id", sa.String(length=41), nullable=True),
        sa.Column("output_artifact_revision_id", sa.String(length=36), nullable=True),
        sa.Column("output_sha256", sa.String(length=71), nullable=True),
        sa.Column("structural_report_artifact_id", sa.String(length=41), nullable=True),
        sa.Column("semantic_report_artifact_id", sa.String(length=41), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("sanitized_failure_summary", sa.Text(), nullable=True),
        sa.Column("manual_validation_status", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('CREATED','VALIDATING_INPUT','STAGING','RENDERING','PACKAGING',"
            "'VALIDATING_OUTPUT','COMMITTING','SUCCEEDED','FAILED','PENDING_MANUAL_VALIDATION')",
            name="ck_hwpx_builds_status",
        ),
        sa.ForeignKeyConstraint(
            ["template_revision_id"], ["hwpx_template_revisions.template_revision_id"]
        ),
        sa.ForeignKeyConstraint(["platform_job_id"], ["jobs.job_id"]),
        sa.ForeignKeyConstraint(["output_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["output_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.PrimaryKeyConstraint("build_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("platform_job_id"),
    )
    op.create_index("ix_hwpx_builds_template_revision_id", "hwpx_builds", ["template_revision_id"])
    op.create_table(
        "hwpx_validation_runs",
        sa.Column("validation_id", sa.String(length=40), nullable=False),
        sa.Column("build_id", sa.String(length=42), nullable=False),
        sa.Column("validation_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("validator_version", sa.String(length=32), nullable=False),
        sa.Column("report_artifact_id", sa.String(length=41), nullable=True),
        sa.Column("report_artifact_revision_id", sa.String(length=36), nullable=True),
        sa.Column("hancom_version", sa.String(length=128), nullable=True),
        sa.Column("windows_version", sa.String(length=128), nullable=True),
        sa.Column("performed_by", sa.String(length=128), nullable=True),
        sa.Column(
            "performed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "validation_type IN ('STRUCTURAL','SEMANTIC','MANUAL_HANCOM_OPEN',"
            "'MANUAL_HANCOM_SAVE','RESAVED_SEMANTIC_COMPARE')",
            name="ck_hwpx_validation_type",
        ),
        sa.ForeignKeyConstraint(["build_id"], ["hwpx_builds.build_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["report_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.PrimaryKeyConstraint("validation_id"),
        sa.UniqueConstraint("build_id", "validation_type", name="uq_hwpx_validation_type"),
    )
    op.create_index("ix_hwpx_validation_runs_build_id", "hwpx_validation_runs", ["build_id"])
    op.execute(
        """
        CREATE FUNCTION reject_approved_hwpx_template_revision_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.immutable OR OLD.approved_at IS NOT NULL THEN
            RAISE EXCEPTION 'approved HWPX template revisions are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER hwpx_template_revisions_immutable BEFORE UPDATE OR DELETE "
        "ON hwpx_template_revisions FOR EACH ROW EXECUTE FUNCTION "
        "reject_approved_hwpx_template_revision_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS hwpx_template_revisions_immutable ON hwpx_template_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_approved_hwpx_template_revision_mutation()")
    op.drop_index("ix_hwpx_validation_runs_build_id", table_name="hwpx_validation_runs")
    op.drop_table("hwpx_validation_runs")
    op.drop_index("ix_hwpx_builds_template_revision_id", table_name="hwpx_builds")
    op.drop_table("hwpx_builds")
    op.drop_index("ix_hwpx_template_revisions_template_id", table_name="hwpx_template_revisions")
    op.drop_table("hwpx_template_revisions")
    op.drop_table("hwpx_templates")
