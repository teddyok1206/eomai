"""add pointer-only legacy item editorial compatibility lifecycle

Revision ID: 20260903_0026
Revises: 20260901_0025
Create Date: 2026-09-03 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260903_0026"
down_revision: str | None = "20260901_0025"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "legacy_item_editorial_compatibility_policy_revisions",
        sa.Column("compatibility_policy_revision_id", sa.String(57), primary_key=True),
        sa.Column("schema_version", sa.String(80), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("content_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("canonical_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("released_by", sa.String(128), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state = 'RELEASED'",
            name="ck_legacy_editorial_compatibility_policy_state",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_legacy_editorial_compatibility_policy_hash",
        ),
    )
    op.create_table(
        "legacy_item_editorial_compatibility_runs",
        sa.Column("compatibility_run_id", sa.String(52), primary_key=True),
        sa.Column("predecessor_compatibility_run_id", sa.String(52)),
        sa.Column("compatibility_request_id", sa.String(51), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("submission_sha256", sa.String(71), nullable=False),
        sa.Column("compatibility_key_sha256", sa.String(71), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("canonical_request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("item_id", sa.String(37), nullable=False),
        sa.Column("item_revision_id", sa.String(40), nullable=False),
        sa.Column("item_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("item_content_artifact_id", sa.String(41), nullable=False),
        sa.Column("item_content_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("item_content_member_path", sa.String(512), nullable=False),
        sa.Column("item_content_schema_ref", sa.String(256), nullable=False),
        sa.Column("item_content_media_type", sa.String(128), nullable=False),
        sa.Column("item_content_sha256", sa.String(71), nullable=False),
        sa.Column("extraction_acceptance_id", sa.String(47), nullable=False),
        sa.Column("extraction_acceptance_sha256", sa.String(71), nullable=False),
        sa.Column("item_origin_profile_id", sa.String(46), nullable=False),
        sa.Column("item_origin_profile_sha256", sa.String(71), nullable=False),
        sa.Column("authoring_prompt_artifact_id", sa.String(41), nullable=False),
        sa.Column("authoring_prompt_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("authoring_prompt_member_path", sa.String(512), nullable=False),
        sa.Column("authoring_prompt_sha256", sa.String(71), nullable=False),
        sa.Column("hwpx_profile_artifact_id", sa.String(41), nullable=False),
        sa.Column("hwpx_profile_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("hwpx_profile_member_path", sa.String(512), nullable=False),
        sa.Column("hwpx_profile_sha256", sa.String(71), nullable=False),
        sa.Column("renderer_profile_artifact_id", sa.String(41), nullable=False),
        sa.Column("renderer_profile_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("renderer_profile_archive_sha256", sa.String(71), nullable=False),
        sa.Column("renderer_profile_sha256", sa.String(71), nullable=False),
        sa.Column("compatibility_policy_revision_id", sa.String(57), nullable=False),
        sa.Column("compatibility_policy_sha256", sa.String(71), nullable=False),
        sa.Column("workflow_id", sa.String(41)),
        sa.Column("plan_id", sa.String(41)),
        sa.Column("platform_job_id", sa.String(36)),
        sa.Column("proposal_artifact_id", sa.String(41)),
        sa.Column("proposal_artifact_revision_id", sa.String(36)),
        sa.Column("proposal_sha256", sa.String(71)),
        sa.Column("result_artifact_id", sa.String(41)),
        sa.Column("result_artifact_revision_id", sa.String(36)),
        sa.Column("result_sha256", sa.String(71)),
        sa.Column("result_status", sa.String(24)),
        sa.Column("lossless_projection", sa.Boolean()),
        sa.Column("issue_count", sa.Integer()),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_by_operator_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(96)),
        sa.Column("error_summary", sa.Text()),
        sa.ForeignKeyConstraint(
            ["predecessor_compatibility_run_id"],
            ["legacy_item_editorial_compatibility_runs.compatibility_run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["item_id", "item_revision_id"],
            ["item_revisions.item_id", "item_revisions.item_revision_id"],
            name="fk_legacy_editorial_compatibility_item_revision_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["item_content_artifact_id", "item_content_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_legacy_editorial_compatibility_item_content_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_acceptance_id"],
            ["legacy_item_extraction_acceptances.acceptance_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["item_origin_profile_id"],
            ["item_origin_profiles.item_origin_profile_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["authoring_prompt_artifact_id", "authoring_prompt_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_legacy_editorial_compatibility_prompt_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["hwpx_profile_artifact_id", "hwpx_profile_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_legacy_editorial_compatibility_hwpx_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["renderer_profile_artifact_id", "renderer_profile_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_legacy_editorial_compatibility_renderer_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["compatibility_policy_revision_id"],
            [
                "legacy_item_editorial_compatibility_policy_revisions."
                "compatibility_policy_revision_id"
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_instances.workflow_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["resolved_execution_plans.plan_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["platform_job_id"], ["jobs.job_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["proposal_artifact_id", "proposal_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_legacy_editorial_compatibility_proposal_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_artifact_id", "result_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_legacy_editorial_compatibility_result_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_operator_id"],
            ["operators.operator_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "compatibility_request_id",
            name="uq_legacy_editorial_compatibility_request",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_legacy_editorial_compatibility_idempotency",
        ),
        sa.UniqueConstraint(
            "predecessor_compatibility_run_id",
            name="uq_legacy_editorial_compatibility_predecessor",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            name="uq_legacy_editorial_compatibility_workflow",
        ),
        sa.CheckConstraint(
            "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING',"
            "'OPEN','CLOSED','FAILED','CANCELLED')",
            name="ck_legacy_editorial_compatibility_run_state",
        ),
        sa.CheckConstraint(
            "result_status IS NULL OR result_status IN ('COMPATIBLE','NEEDS_ADAPTATION','BLOCKED')",
            name="ck_legacy_editorial_compatibility_result_status",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND submission_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND compatibility_key_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND item_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND item_content_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND extraction_acceptance_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND item_origin_profile_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND authoring_prompt_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND hwpx_profile_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND renderer_profile_archive_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND renderer_profile_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND compatibility_policy_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_legacy_editorial_compatibility_dependency_hashes",
        ),
        sa.CheckConstraint(
            "(proposal_artifact_id IS NULL AND proposal_artifact_revision_id IS NULL "
            "AND proposal_sha256 IS NULL) OR "
            "(proposal_artifact_id IS NOT NULL AND proposal_artifact_revision_id IS NOT NULL "
            "AND proposal_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_legacy_editorial_compatibility_proposal_pointer_complete",
        ),
        sa.CheckConstraint(
            "(result_artifact_id IS NULL AND result_artifact_revision_id IS NULL "
            "AND result_sha256 IS NULL AND result_status IS NULL "
            "AND lossless_projection IS NULL AND issue_count IS NULL) OR "
            "(result_artifact_id IS NOT NULL AND result_artifact_revision_id IS NOT NULL "
            "AND result_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND result_status IS NOT NULL AND lossless_projection IS NOT NULL "
            "AND issue_count IS NOT NULL AND issue_count >= 0)",
            name="ck_legacy_editorial_compatibility_result_pointer_complete",
        ),
        sa.CheckConstraint(
            "(state = 'CLOSED' AND result_status = 'COMPATIBLE' "
            "AND lossless_projection IS TRUE AND issue_count = 0) OR state <> 'CLOSED'",
            name="ck_legacy_editorial_compatibility_closed_result",
        ),
        sa.CheckConstraint(
            "(state = 'OPEN' AND result_status IN ('NEEDS_ADAPTATION','BLOCKED') "
            "AND issue_count > 0) OR state <> 'OPEN'",
            name="ck_legacy_editorial_compatibility_open_result",
        ),
        sa.CheckConstraint(
            "state IN ('OPEN','CLOSED') OR result_artifact_revision_id IS NULL",
            name="ck_legacy_editorial_compatibility_result_terminal_only",
        ),
        sa.CheckConstraint(
            "lock_version >= 1",
            name="ck_legacy_editorial_compatibility_lock_version",
        ),
    )
    op.create_index(
        "ix_legacy_editorial_compatibility_item_history",
        "legacy_item_editorial_compatibility_runs",
        ["item_revision_id", sa.text("created_at DESC"), sa.text("compatibility_run_id DESC")],
    )
    op.create_index(
        "ix_legacy_editorial_compatibility_authorities",
        "legacy_item_editorial_compatibility_runs",
        [
            "authoring_prompt_artifact_revision_id",
            "hwpx_profile_artifact_revision_id",
            "renderer_profile_artifact_revision_id",
            sa.text("created_at DESC"),
        ],
    )
    op.create_index(
        "uq_legacy_editorial_compatibility_terminal_tuple",
        "legacy_item_editorial_compatibility_runs",
        ["compatibility_key_sha256"],
        unique=True,
        postgresql_where=sa.text("state IN ('OPEN','CLOSED')"),
    )
    op.create_index(
        "uq_legacy_editorial_compatibility_active_tuple",
        "legacy_item_editorial_compatibility_runs",
        ["compatibility_key_sha256"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING')"
        ),
    )
    op.create_index(
        "ix_legacy_editorial_compatibility_open_work",
        "legacy_item_editorial_compatibility_runs",
        ["state", "created_at", "compatibility_run_id"],
        postgresql_where=sa.text(
            "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING','OPEN')"
        ),
    )
    op.create_table(
        "legacy_item_editorial_compatibility_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("compatibility_run_id", sa.String(52), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("prior_state", sa.String(24)),
        sa.Column("new_state", sa.String(24), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["compatibility_run_id"],
            ["legacy_item_editorial_compatibility_runs.compatibility_run_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "compatibility_run_id",
            "sequence",
            name="uq_legacy_editorial_compatibility_event_sequence",
        ),
        sa.CheckConstraint(
            "sequence >= 1",
            name="ck_legacy_editorial_compatibility_event_sequence",
        ),
    )
    op.create_index(
        "ix_legacy_editorial_events_run",
        "legacy_item_editorial_compatibility_events",
        ["compatibility_run_id"],
    )
    op.execute(
        "CREATE TRIGGER trg_legacy_item_editorial_compatibility_policy_immutable "
        "BEFORE UPDATE OR DELETE ON legacy_item_editorial_compatibility_policy_revisions "
        "FOR EACH ROW EXECUTE FUNCTION reject_legacy_assessment_immutable_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_legacy_item_editorial_compatibility_events_immutable "
        "BEFORE UPDATE OR DELETE ON legacy_item_editorial_compatibility_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_legacy_assessment_immutable_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_legacy_item_editorial_compatibility_events_immutable "
        "ON legacy_item_editorial_compatibility_events"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_legacy_item_editorial_compatibility_policy_immutable "
        "ON legacy_item_editorial_compatibility_policy_revisions"
    )
    op.drop_index(
        "ix_legacy_editorial_events_run",
        table_name="legacy_item_editorial_compatibility_events",
    )
    op.drop_table("legacy_item_editorial_compatibility_events")
    op.drop_index(
        "uq_legacy_editorial_compatibility_terminal_tuple",
        table_name="legacy_item_editorial_compatibility_runs",
    )
    op.drop_index(
        "uq_legacy_editorial_compatibility_active_tuple",
        table_name="legacy_item_editorial_compatibility_runs",
    )
    op.drop_index(
        "ix_legacy_editorial_compatibility_open_work",
        table_name="legacy_item_editorial_compatibility_runs",
    )
    op.drop_index(
        "ix_legacy_editorial_compatibility_authorities",
        table_name="legacy_item_editorial_compatibility_runs",
    )
    op.drop_index(
        "ix_legacy_editorial_compatibility_item_history",
        table_name="legacy_item_editorial_compatibility_runs",
    )
    op.drop_table("legacy_item_editorial_compatibility_runs")
    op.drop_table("legacy_item_editorial_compatibility_policy_revisions")
