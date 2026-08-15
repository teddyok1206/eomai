"""Create the EOM platform skeleton tables.

Revision ID: 20260815_0001
Revises: None
Create Date: 2026-08-15 00:00:00Z
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "protocol_versions",
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("schema_sha256", sa.String(length=71), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("version"),
    )
    op.create_table(
        "worker_slots",
        sa.Column("slot_id", sa.String(length=2), nullable=False),
        sa.Column("linux_user", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("gpu", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("slot_id"),
        sa.UniqueConstraint("linux_user"),
    )
    op.create_index("ix_worker_slots_role", "worker_slots", ["role"])
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("protocol_version", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=71), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("logical_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("worker_slot_id", sa.String(length=2), nullable=True),
        sa.Column("worker_exit_code", sa.Integer(), nullable=True),
        sa.Column("worker_stdout_path", sa.Text(), nullable=True),
        sa.Column("worker_stderr_path", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('CREATED','VALIDATED','QUEUED','CLAIMED','RUNNING',"
            "'VALIDATING_RESULT','COMMITTING','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_jobs_status",
        ),
        sa.ForeignKeyConstraint(["protocol_version"], ["protocol_versions.version"]),
        sa.ForeignKeyConstraint(["worker_slot_id"], ["worker_slots.slot_id"]),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("logical_artifact_id"),
        sa.UniqueConstraint("revision_id"),
    )
    op.create_table(
        "job_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=True),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_job_events_sequence"),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])
    op.create_table(
        "artifacts",
        sa.Column("logical_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"]),
        sa.PrimaryKeyConstraint("logical_artifact_id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_table(
        "artifact_revisions",
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("logical_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("manifest_hash", sa.String(length=71), nullable=False),
        sa.Column("content_bytes", sa.BigInteger(), nullable=False),
        sa.Column("nas_path", sa.Text(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"]),
        sa.ForeignKeyConstraint(["logical_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint("job_id"),
        sa.UniqueConstraint("logical_artifact_id", "content_hash", name="uq_artifact_content_hash"),
    )
    op.create_index(
        "ix_artifact_revisions_logical_artifact_id",
        "artifact_revisions",
        ["logical_artifact_id"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_approved_artifact_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.approved THEN
            RAISE EXCEPTION 'approved EOM artifacts and revisions are immutable';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER artifacts_immutable BEFORE UPDATE OR DELETE ON artifacts "
        "FOR EACH ROW EXECUTE FUNCTION reject_approved_artifact_mutation()"
    )
    op.execute(
        "CREATE TRIGGER artifact_revisions_immutable BEFORE UPDATE OR DELETE ON artifact_revisions "
        "FOR EACH ROW EXECUTE FUNCTION reject_approved_artifact_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS artifact_revisions_immutable ON artifact_revisions")
    op.execute("DROP TRIGGER IF EXISTS artifacts_immutable ON artifacts")
    op.execute("DROP FUNCTION IF EXISTS reject_approved_artifact_mutation()")
    op.drop_index("ix_artifact_revisions_logical_artifact_id", table_name="artifact_revisions")
    op.drop_table("artifact_revisions")
    op.drop_table("artifacts")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_table("jobs")
    op.drop_index("ix_worker_slots_role", table_name="worker_slots")
    op.drop_table("worker_slots")
    op.drop_table("protocol_versions")
