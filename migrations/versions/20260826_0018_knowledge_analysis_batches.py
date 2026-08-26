"""Add durable Knowledge Analysis batch execution aggregates.

Revision ID: 20260826_0018
Revises: 20260825_0017
Create Date: 2026-08-26 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0018"
down_revision: str | None = "20260825_0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_analysis_batches",
        sa.Column("batch_id", sa.String(46), primary_key=True),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("preset_id", sa.String(43), nullable=False),
        sa.Column("preset_revision_id", sa.String(46), nullable=False),
        sa.Column("preset_sha256", sa.String(71), nullable=False),
        sa.Column("risk_policy_revision_id", sa.String(48), nullable=False),
        sa.Column("risk_policy_sha256", sa.String(71), nullable=False),
        sa.Column("general_knowledge_mode", sa.String(32), nullable=False),
        sa.Column("review_policy", sa.String(48), nullable=False),
        sa.Column("authorized_by_operator_id", sa.String(41), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("total_range_count", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED','RUNNING','BLOCKED','SUCCEEDED','CANCELLED')",
            name="ck_knowledge_analysis_batch_state",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND preset_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND risk_policy_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_batch_hashes",
        ),
        sa.CheckConstraint(
            "general_knowledge_mode = 'AUXILIARY_UNATTRIBUTED'",
            name="ck_knowledge_analysis_batch_general_knowledge",
        ),
        sa.CheckConstraint(
            "review_policy = 'PREAUTHORIZED_APPROVE_VALIDATED'",
            name="ck_knowledge_analysis_batch_review_policy",
        ),
        sa.CheckConstraint(
            "total_range_count BETWEEN 1 AND 1000",
            name="ck_knowledge_analysis_batch_range_count",
        ),
        sa.CheckConstraint("resource_version >= 1", name="ck_knowledge_analysis_batch_version"),
        sa.ForeignKeyConstraint(
            ["preset_id"], ["execution_presets.preset_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["preset_revision_id"],
            ["execution_preset_revisions.preset_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["risk_policy_revision_id"],
            ["knowledge_analysis_risk_policy_revisions.risk_policy_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["authorized_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_knowledge_analysis_batch_idempotency"),
    )
    op.create_index(
        "ix_knowledge_analysis_batch_state_created",
        "knowledge_analysis_batches",
        ["state", sa.text("created_at DESC"), "batch_id"],
    )
    op.create_table(
        "knowledge_analysis_batch_ranges",
        sa.Column("range_id", sa.String(46), primary_key=True),
        sa.Column("batch_id", sa.String(46), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(39), nullable=False),
        sa.Column("document_revision_id", sa.String(42), nullable=False),
        sa.Column("first_physical_page", sa.Integer(), nullable=False),
        sa.Column("last_physical_page", sa.Integer(), nullable=False),
        sa.Column("curriculum_unit_keys", postgresql.ARRAY(sa.String(16)), nullable=False),
        sa.Column("source_artifact_id", sa.String(41), nullable=False),
        sa.Column("source_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("source_sha256", sa.String(71), nullable=False),
        sa.Column("source_media_type", sa.String(64), nullable=False),
        sa.Column("source_schema_ref", sa.String(256), nullable=False),
        sa.Column("analysis_artifact_id", sa.String(41), nullable=False),
        sa.Column("analysis_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("analysis_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("analysis_media_type", sa.String(64), nullable=False),
        sa.Column("analysis_schema_ref", sa.String(256), nullable=False),
        sa.Column("rights_artifact_id", sa.String(41), nullable=False),
        sa.Column("rights_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("rights_attestation_sha256", sa.String(71), nullable=False),
        sa.Column("rights_media_type", sa.String(64), nullable=False),
        sa.Column("rights_schema_ref", sa.String(256), nullable=False),
        sa.Column("execution_mode", sa.String(24), nullable=False),
        sa.Column("predecessor_analysis_run_id", sa.String(44), nullable=True),
        sa.Column("reuse_accepted_analysis_run_id", sa.String(44), nullable=True),
        sa.Column("analysis_run_id", sa.String(44), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("submission_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_action_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "state IN ('PENDING','CLAIMED','SUBMITTED','ACCEPTED','FAILED','CANCELLED')",
            name="ck_knowledge_analysis_batch_range_state",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('EXECUTE','REUSE_ACCEPTED')",
            name="ck_knowledge_analysis_batch_range_mode",
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 999 AND first_physical_page >= 1 "
            "AND last_physical_page >= first_physical_page "
            "AND last_physical_page - first_physical_page + 1 <= 32",
            name="ck_knowledge_analysis_batch_range_bounds",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND analysis_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND rights_attestation_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_batch_range_hashes",
        ),
        sa.CheckConstraint(
            "source_media_type = 'application/pdf' AND "
            "source_schema_ref = 'eom://schemas/educational-document/pdf-source/1.0' AND "
            "analysis_media_type = 'application/json' AND "
            "analysis_schema_ref = "
            "'eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0' AND "
            "rights_media_type = 'application/json' AND "
            "rights_schema_ref = "
            "'eom://schemas/educational-document/rights-attestation/1.0'",
            name="ck_knowledge_analysis_batch_range_pointer_contract",
        ),
        sa.CheckConstraint(
            "(execution_mode = 'EXECUTE' AND reuse_accepted_analysis_run_id IS NULL) OR "
            "(execution_mode = 'REUSE_ACCEPTED' AND predecessor_analysis_run_id IS NULL "
            "AND reuse_accepted_analysis_run_id IS NOT NULL "
            "AND analysis_run_id = reuse_accepted_analysis_run_id "
            "AND state = 'ACCEPTED' AND submission_attempts = 0)",
            name="ck_knowledge_analysis_batch_range_execution",
        ),
        sa.CheckConstraint(
            "(state = 'CLAIMED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state <> 'CLAIMED' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_knowledge_analysis_batch_range_lease",
        ),
        sa.CheckConstraint(
            "state NOT IN ('SUBMITTED','ACCEPTED') OR analysis_run_id IS NOT NULL",
            name="ck_knowledge_analysis_batch_range_run_pointer",
        ),
        sa.CheckConstraint(
            "submission_attempts BETWEEN 0 AND 1",
            name="ck_knowledge_analysis_batch_range_attempts",
        ),
        sa.CheckConstraint(
            "resource_version >= 1", name="ck_knowledge_analysis_batch_range_version"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["knowledge_analysis_batches.batch_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["educational_documents.document_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "document_revision_id"],
            [
                "educational_document_revisions.document_id",
                "educational_document_revisions.document_revision_id",
            ],
            name="fk_knowledge_analysis_batch_range_document_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_revision_id"], ["artifact_revisions.revision_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_artifact_revision_id"],
            ["artifact_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rights_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["rights_artifact_revision_id"], ["artifact_revisions.revision_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_analysis_run_id"],
            ["knowledge_analysis_runs.analysis_run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reuse_accepted_analysis_run_id"],
            ["knowledge_analysis_runs.analysis_run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["knowledge_analysis_runs.analysis_run_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "batch_id", "ordinal", name="uq_knowledge_analysis_batch_range_ordinal"
        ),
        sa.UniqueConstraint(
            "batch_id", "range_id", name="uq_knowledge_analysis_batch_range_identity"
        ),
    )
    op.create_index(
        "uq_knowledge_analysis_batch_active_range",
        "knowledge_analysis_batch_ranges",
        ["batch_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('CLAIMED','SUBMITTED')"),
    )
    op.create_index(
        "uq_knowledge_analysis_batch_analysis_run",
        "knowledge_analysis_batch_ranges",
        ["batch_id", "analysis_run_id"],
        unique=True,
        postgresql_where=sa.text("analysis_run_id IS NOT NULL"),
    )
    op.create_index(
        "ix_knowledge_analysis_batch_range_claim",
        "knowledge_analysis_batch_ranges",
        ["state", "next_action_at", "batch_id", "ordinal"],
        postgresql_where=sa.text("state IN ('PENDING','CLAIMED','SUBMITTED')"),
    )
    op.create_index(
        "ix_knowledge_analysis_batch_range_document_pages",
        "knowledge_analysis_batch_ranges",
        ["document_revision_id", "first_physical_page", "last_physical_page"],
    )
    op.create_table(
        "knowledge_analysis_batch_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("batch_id", sa.String(46), nullable=False),
        sa.Column("range_id", sa.String(46), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("prior_state", sa.String(16), nullable=True),
        sa.Column("new_state", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_knowledge_analysis_batch_event_sequence"),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["knowledge_analysis_batches.batch_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "range_id"],
            [
                "knowledge_analysis_batch_ranges.batch_id",
                "knowledge_analysis_batch_ranges.range_id",
            ],
            name="fk_knowledge_analysis_batch_event_range",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "batch_id", "sequence", name="uq_knowledge_analysis_batch_event_sequence"
        ),
    )
    op.create_index(
        "ix_knowledge_analysis_batch_event_range",
        "knowledge_analysis_batch_events",
        ["range_id", "event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_analysis_batch_event_range", table_name="knowledge_analysis_batch_events"
    )
    op.drop_table("knowledge_analysis_batch_events")
    op.drop_index(
        "ix_knowledge_analysis_batch_range_document_pages",
        table_name="knowledge_analysis_batch_ranges",
    )
    op.drop_index(
        "ix_knowledge_analysis_batch_range_claim", table_name="knowledge_analysis_batch_ranges"
    )
    op.drop_index(
        "uq_knowledge_analysis_batch_analysis_run",
        table_name="knowledge_analysis_batch_ranges",
    )
    op.drop_index(
        "uq_knowledge_analysis_batch_active_range",
        table_name="knowledge_analysis_batch_ranges",
    )
    op.drop_table("knowledge_analysis_batch_ranges")
    op.drop_index(
        "ix_knowledge_analysis_batch_state_created", table_name="knowledge_analysis_batches"
    )
    op.drop_table("knowledge_analysis_batches")
