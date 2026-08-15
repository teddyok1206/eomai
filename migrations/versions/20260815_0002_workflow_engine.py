"""Add domain-neutral workflow engine tables.

Revision ID: 20260815_0002
Revises: 20260815_0001
Create Date: 2026-08-15 08:00:00Z
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_0002"
down_revision: str | None = "20260815_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("definition_id", sa.String(length=38), nullable=False),
        sa.Column("definition_key", sa.String(length=64), nullable=False),
        sa.Column("definition_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("canonical_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("definition_hash", sa.String(length=71), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("definition_id"),
        sa.UniqueConstraint(
            "definition_key", "definition_version", name="uq_workflow_definition_key_version"
        ),
    )
    op.create_table(
        "workflow_instances",
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("definition_id", sa.String(length=38), nullable=False),
        sa.Column("definition_key", sa.String(length=64), nullable=False),
        sa.Column("definition_version", sa.String(length=32), nullable=False),
        sa.Column("definition_hash", sa.String(length=71), nullable=False),
        sa.Column("protocol_version", sa.String(length=32), nullable=False),
        sa.Column("role_schema_version", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("current_step_key", sa.String(length=64), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("initial_request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=71), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("rework_cycle_count", sa.Integer(), nullable=False),
        sa.Column("created_actor_type", sa.String(length=32), nullable=False),
        sa.Column("created_actor_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('REQUESTED','RUNNING','AWAITING_HUMAN_APPROVAL','REWORK_REQUESTED',"
            "'APPROVED','REGISTERING','COMPLETED','FAILED','CANCELLED')",
            name="ck_workflow_instances_state",
        ),
        sa.CheckConstraint(
            "stage IN ('AUTHORING','IMAGE_REQUIRED','IMAGE_SKIPPED','REVIEWING',"
            "'AWAITING_HUMAN_APPROVAL','REGISTERING','COMPLETED','FAILED','CANCELLED')",
            name="ck_workflow_instances_stage",
        ),
        sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.definition_id"]),
        sa.PrimaryKeyConstraint("workflow_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "workflow_step_runs",
        sa.Column("step_run_id", sa.String(length=40), nullable=False),
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=32), nullable=False),
        sa.Column("worker_role", sa.String(length=64), nullable=True),
        sa.Column("result_schema", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("platform_job_id", sa.String(length=36), nullable=True),
        sa.Column(
            "input_pointer_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "output_pointer_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("superseded_by_step_run_id", sa.String(length=40), nullable=True),
        sa.CheckConstraint(
            "state IN ('PENDING','READY','RUNNING','SUCCEEDED','SKIPPED',"
            "'WAITING_FOR_HUMAN','FAILED','CANCELLED','SUPERSEDED')",
            name="ck_workflow_step_runs_state",
        ),
        sa.ForeignKeyConstraint(["platform_job_id"], ["jobs.job_id"]),
        sa.ForeignKeyConstraint(["superseded_by_step_run_id"], ["workflow_step_runs.step_run_id"]),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("step_run_id"),
        sa.UniqueConstraint("workflow_id", "step_key", "attempt", name="uq_workflow_step_attempt"),
    )
    op.create_index("ix_workflow_step_runs_workflow_id", "workflow_step_runs", ["workflow_id"])
    op.create_index(
        "ix_workflow_step_runs_platform_job_id", "workflow_step_runs", ["platform_job_id"]
    )
    op.create_table(
        "workflow_commands",
        sa.Column("command_id", sa.String(length=38), nullable=False),
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("command_type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=71), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "state IN ('PENDING','LEASED','PROCESSING','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_workflow_commands_state",
        ),
        sa.CheckConstraint(
            "command_type IN ('START_WORKFLOW','ADVANCE_WORKFLOW','APPROVE_WORKFLOW',"
            "'REQUEST_REWORK','CANCEL_WORKFLOW','RETRY_STEP','RECONCILE_WORKFLOW')",
            name="ck_workflow_commands_type",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("command_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_workflow_commands_workflow_id", "workflow_commands", ["workflow_id"])
    op.create_table(
        "workflow_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("prior_state", sa.String(length=32), nullable=True),
        sa.Column("new_state", sa.String(length=32), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("command_id", sa.String(length=38), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("workflow_id", "sequence", name="uq_workflow_events_sequence"),
    )
    op.create_index("ix_workflow_events_workflow_id", "workflow_events", ["workflow_id"])
    op.create_table(
        "approval_requests",
        sa.Column("approval_request_id", sa.String(length=41), nullable=False),
        sa.Column("workflow_id", sa.String(length=41), nullable=False),
        sa.Column("step_run_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("allowed_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "allowed_rework_targets", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_actor_type", sa.String(length=32), nullable=True),
        sa.Column("resolved_actor_id", sa.String(length=128), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("rework_target_step", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REWORK_REQUESTED','CANCELLED','SUPERSEDED')",
            name="ck_approval_requests_status",
        ),
        sa.ForeignKeyConstraint(["step_run_id"], ["workflow_step_runs.step_run_id"]),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("approval_request_id"),
        sa.UniqueConstraint("step_run_id"),
    )
    op.create_index("ix_approval_requests_workflow_id", "approval_requests", ["workflow_id"])
    op.create_index(
        "uq_active_approval_per_workflow",
        "approval_requests",
        ["workflow_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.execute(
        """
        CREATE FUNCTION reject_workflow_definition_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'workflow definitions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER workflow_definitions_immutable BEFORE UPDATE OR DELETE "
        "ON workflow_definitions FOR EACH ROW EXECUTE FUNCTION "
        "reject_workflow_definition_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_workflow_snapshot_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.definition_id <> NEW.definition_id
             OR OLD.definition_key <> NEW.definition_key
             OR OLD.definition_version <> NEW.definition_version
             OR OLD.definition_hash <> NEW.definition_hash
             OR OLD.protocol_version <> NEW.protocol_version
             OR OLD.role_schema_version <> NEW.role_schema_version
             OR OLD.initial_request <> NEW.initial_request
             OR OLD.idempotency_key <> NEW.idempotency_key
             OR OLD.request_hash <> NEW.request_hash THEN
            RAISE EXCEPTION 'workflow instance snapshot fields are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER workflow_instance_snapshot_immutable BEFORE UPDATE ON workflow_instances "
        "FOR EACH ROW EXECUTE FUNCTION reject_workflow_snapshot_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS workflow_instance_snapshot_immutable ON workflow_instances")
    op.execute("DROP FUNCTION IF EXISTS reject_workflow_snapshot_mutation()")
    op.execute("DROP TRIGGER IF EXISTS workflow_definitions_immutable ON workflow_definitions")
    op.execute("DROP FUNCTION IF EXISTS reject_workflow_definition_mutation()")
    op.drop_index("uq_active_approval_per_workflow", table_name="approval_requests")
    op.drop_index("ix_approval_requests_workflow_id", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_index("ix_workflow_events_workflow_id", table_name="workflow_events")
    op.drop_table("workflow_events")
    op.drop_index("ix_workflow_commands_workflow_id", table_name="workflow_commands")
    op.drop_table("workflow_commands")
    op.drop_index("ix_workflow_step_runs_platform_job_id", table_name="workflow_step_runs")
    op.drop_index("ix_workflow_step_runs_workflow_id", table_name="workflow_step_runs")
    op.drop_table("workflow_step_runs")
    op.drop_table("workflow_instances")
    op.drop_table("workflow_definitions")
