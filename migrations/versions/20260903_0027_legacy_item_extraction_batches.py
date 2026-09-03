"""add durable pointer-only legacy item extraction batches

Revision ID: 20260903_0027
Revises: 20260903_0026
Create Date: 2026-09-03 00:00:01 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260903_0027"
down_revision: str | None = "20260903_0026"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "legacy_item_extraction_batches",
        sa.Column("extraction_batch_id", sa.String(44), primary_key=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("manifest_sha256", sa.String(71), nullable=False),
        sa.Column("inventory_id", sa.String(48), nullable=False),
        sa.Column("inventory_sha256", sa.String(71), nullable=False),
        sa.Column("manifest_artifact_id", sa.String(41), nullable=False),
        sa.Column("manifest_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("manifest_artifact_member_path", sa.String(512), nullable=False),
        sa.Column("manifest_artifact_schema_ref", sa.String(256), nullable=False),
        sa.Column("manifest_artifact_media_type", sa.String(128), nullable=False),
        sa.Column("manifest_artifact_sha256", sa.String(71), nullable=False),
        sa.Column("failure_policy", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("total_work_unit_count", sa.Integer(), nullable=False),
        sa.Column("requested_by_operator_id", sa.String(128), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED','RUNNING','AWAITING_REVIEW','SUCCEEDED',"
            "'COMPLETED_WITH_GAPS','CANCELLED')",
            name="ck_legacy_item_extraction_batch_state",
        ),
        sa.CheckConstraint(
            "schema_version = 'legacy-item-extraction-batch/1.1'",
            name="ck_legacy_item_extraction_batch_schema",
        ),
        sa.CheckConstraint(
            "failure_policy = 'CONTINUE_AND_COLLECT'",
            name="ck_legacy_item_extraction_batch_failure_policy",
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND inventory_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND manifest_artifact_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_legacy_item_extraction_batch_hashes",
        ),
        sa.CheckConstraint(
            "total_work_unit_count BETWEEN 1 AND 10000",
            name="ck_legacy_item_extraction_batch_count",
        ),
        sa.CheckConstraint("resource_version >= 1", name="ck_legacy_item_extraction_batch_version"),
        sa.ForeignKeyConstraint(
            ["manifest_artifact_id", "manifest_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_legacy_item_extraction_batch_manifest_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_legacy_item_extraction_batch_idempotency"),
        sa.UniqueConstraint("manifest_sha256", name="uq_legacy_item_extraction_batch_manifest"),
    )
    op.create_index(
        "ix_legacy_item_extraction_batch_state_created",
        "legacy_item_extraction_batches",
        ["state", sa.text("created_at DESC"), "extraction_batch_id"],
    )
    op.create_table(
        "legacy_item_extraction_batch_work_units",
        sa.Column("work_unit_id", sa.String(47), primary_key=True),
        sa.Column("extraction_batch_id", sa.String(44), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("extraction_request_id", sa.String(47), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("assessment_source_bundle_id", sa.String(45), nullable=False),
        sa.Column("assessment_source_bundle_revision_id", sa.String(48), nullable=False),
        sa.Column("bundle_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("expected_item_numbers_sha256", sa.String(71), nullable=False),
        sa.Column("corpus_source_bindings_sha256", sa.String(71), nullable=False),
        sa.Column("execution_mode", sa.String(24), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("submission_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workflow_id", sa.String(41)),
        sa.Column("platform_job_id", sa.String(36)),
        sa.Column("receipt_artifact_id", sa.String(41)),
        sa.Column("receipt_artifact_revision_id", sa.String(36)),
        sa.Column("receipt_artifact_sha256", sa.String(71)),
        sa.Column("extraction_result_id", sa.String(50)),
        sa.Column("result_sha256", sa.String(71)),
        sa.Column("acceptance_id", sa.String(47)),
        sa.Column("acceptance_sha256", sa.String(71)),
        sa.Column("error_code", sa.String(96)),
        sa.Column("resource_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING','CLAIMED','SUBMITTED','AWAITING_REVIEW',"
            "'ACCEPTED','FAILED','CANCELLED')",
            name="ck_legacy_item_extraction_batch_work_unit_state",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('EXECUTE','REUSE_ACCEPTED')",
            name="ck_legacy_item_extraction_batch_work_unit_mode",
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 999999 AND submission_attempts BETWEEN 0 AND 1",
            name="ck_legacy_item_extraction_batch_work_unit_bounds",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND bundle_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND expected_item_numbers_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND corpus_source_bindings_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_legacy_item_extraction_batch_work_unit_hashes",
        ),
        sa.CheckConstraint(
            "(state = 'CLAIMED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'CLAIMED' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_legacy_item_extraction_batch_work_unit_lease",
        ),
        sa.CheckConstraint(
            "(execution_mode = 'REUSE_ACCEPTED' AND state = 'ACCEPTED' "
            "AND submission_attempts = 0 AND workflow_id IS NULL "
            "AND acceptance_id IS NOT NULL) OR execution_mode = 'EXECUTE'",
            name="ck_legacy_item_extraction_batch_work_unit_reuse",
        ),
        sa.CheckConstraint(
            "(receipt_artifact_id IS NULL AND receipt_artifact_revision_id IS NULL "
            "AND receipt_artifact_sha256 IS NULL AND extraction_result_id IS NULL "
            "AND result_sha256 IS NULL) OR "
            "(receipt_artifact_id IS NOT NULL AND receipt_artifact_revision_id IS NOT NULL "
            "AND receipt_artifact_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND extraction_result_id IS NOT NULL "
            "AND result_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_legacy_item_extraction_batch_work_unit_result_pointer",
        ),
        sa.CheckConstraint(
            "state NOT IN ('AWAITING_REVIEW','ACCEPTED') OR extraction_result_id IS NOT NULL",
            name="ck_legacy_item_extraction_batch_work_unit_result_state",
        ),
        sa.CheckConstraint(
            "state <> 'ACCEPTED' OR acceptance_id IS NOT NULL",
            name="ck_legacy_item_extraction_batch_work_unit_acceptance_state",
        ),
        sa.CheckConstraint(
            "(acceptance_id IS NULL AND acceptance_sha256 IS NULL) OR "
            "(acceptance_id IS NOT NULL AND acceptance_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_legacy_item_extraction_batch_work_unit_acceptance_pointer",
        ),
        sa.CheckConstraint(
            "(state = 'FAILED' AND error_code IS NOT NULL) OR "
            "(state <> 'FAILED' AND error_code IS NULL)",
            name="ck_legacy_item_extraction_batch_work_unit_error",
        ),
        sa.CheckConstraint(
            "resource_version >= 1", name="ck_legacy_item_extraction_work_unit_version"
        ),
        sa.ForeignKeyConstraint(
            ["extraction_batch_id"],
            ["legacy_item_extraction_batches.extraction_batch_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["platform_job_id"], ["jobs.job_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["receipt_artifact_id", "receipt_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_legacy_item_extraction_batch_receipt_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["acceptance_id"],
            ["legacy_item_extraction_acceptances.acceptance_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "extraction_request_id",
            name="uq_legacy_item_extraction_batch_work_unit_request",
        ),
        sa.UniqueConstraint(
            "extraction_batch_id",
            "ordinal",
            name="uq_legacy_item_extraction_batch_work_unit_ordinal",
        ),
        sa.UniqueConstraint(
            "extraction_batch_id",
            "work_unit_id",
            name="uq_legacy_item_extraction_batch_work_unit_identity",
        ),
        sa.UniqueConstraint(
            "extraction_batch_id",
            "assessment_source_bundle_revision_id",
            "ordinal",
            "expected_item_numbers_sha256",
            name="uq_legacy_item_extraction_batch_work_unit_source",
        ),
    )
    op.create_index(
        "ix_legacy_item_extraction_batch_work_unit_claim",
        "legacy_item_extraction_batch_work_units",
        ["state", "next_action_at", "extraction_batch_id", "ordinal"],
        postgresql_where=sa.text("state IN ('PENDING','CLAIMED','SUBMITTED')"),
    )
    op.create_index(
        "uq_legacy_item_extraction_batch_work_unit_workflow",
        "legacy_item_extraction_batch_work_units",
        ["workflow_id"],
        unique=True,
        postgresql_where=sa.text("workflow_id IS NOT NULL"),
    )
    op.create_table(
        "legacy_item_extraction_batch_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("extraction_batch_id", sa.String(44), nullable=False),
        sa.Column("work_unit_id", sa.String(47)),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("prior_state", sa.String(32)),
        sa.Column("new_state", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_legacy_item_extraction_batch_event_sequence"),
        sa.ForeignKeyConstraint(
            ["extraction_batch_id"],
            ["legacy_item_extraction_batches.extraction_batch_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_batch_id", "work_unit_id"],
            [
                "legacy_item_extraction_batch_work_units.extraction_batch_id",
                "legacy_item_extraction_batch_work_units.work_unit_id",
            ],
            name="fk_legacy_item_extraction_batch_event_work_unit",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "extraction_batch_id",
            "sequence",
            name="uq_legacy_item_extraction_batch_event_sequence",
        ),
    )
    op.create_index(
        "ix_legacy_item_extraction_batch_event_work_unit",
        "legacy_item_extraction_batch_events",
        ["work_unit_id", "event_id"],
    )
    op.execute(
        "CREATE TRIGGER trg_legacy_item_extraction_batch_events_immutable "
        "BEFORE UPDATE OR DELETE ON legacy_item_extraction_batch_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_legacy_assessment_immutable_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_legacy_item_extraction_batch_events_immutable "
        "ON legacy_item_extraction_batch_events"
    )
    op.drop_index(
        "ix_legacy_item_extraction_batch_event_work_unit",
        table_name="legacy_item_extraction_batch_events",
    )
    op.drop_table("legacy_item_extraction_batch_events")
    op.drop_index(
        "uq_legacy_item_extraction_batch_work_unit_workflow",
        table_name="legacy_item_extraction_batch_work_units",
    )
    op.drop_index(
        "ix_legacy_item_extraction_batch_work_unit_claim",
        table_name="legacy_item_extraction_batch_work_units",
    )
    op.drop_table("legacy_item_extraction_batch_work_units")
    op.drop_index(
        "ix_legacy_item_extraction_batch_state_created",
        table_name="legacy_item_extraction_batches",
    )
    op.drop_table("legacy_item_extraction_batches")
