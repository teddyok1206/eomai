"""Add knowledge-analysis lifecycle and workflow stage.

Revision ID: 20260823_0011
Revises: 20260823_0010
Create Date: 2026-08-23 22:00:00Z
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0011"
down_revision: str | Sequence[str] | None = "20260823_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_workflow_instances_stage", "workflow_instances", type_="check")
    op.create_check_constraint(
        "ck_workflow_instances_stage",
        "workflow_instances",
        "stage IN ('KNOWLEDGE_ANALYSIS','AUTHORING','IMAGE_REQUIRED','IMAGE_SKIPPED',"
        "'REVIEWING','AWAITING_HUMAN_APPROVAL','REGISTERING','COMPLETED','FAILED','CANCELLED')",
    )
    risk_policy_table = op.create_table(
        "knowledge_analysis_risk_policy_revisions",
        sa.Column("risk_policy_revision_id", sa.String(48), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("content_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("canonical_document", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state = 'RELEASED'", name="ck_knowledge_analysis_risk_policy_state"),
        sa.CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_risk_policy_hash",
        ),
    )
    policy_document = {
        "schema_version": "knowledge-analysis-risk-policy/1.0",
        "risk_policy_revision_id": "analysisriskrev_7f0f1d7c2f7c4a3cb97c090938e8ac30",
        "state": "RELEASED",
        "minimum_confidence_milli": 700,
        "review_source_classes": ["PAST_EXAM"],
        "review_when_general_knowledge_used": True,
        "review_when_blocking_ambiguity_present": True,
        "maximum_auto_accept_counts": {
            "anchors": 800,
            "nodes": 400,
            "edges": 800,
            "claims": 400,
            "component_observations": 400,
            "ambiguities": 64,
        },
        "created_at": "2026-08-23T00:00:00Z",
        "content_sha256": (
            "sha256:fa6efb2e77a3e639061317ca7d7617f072c01ecae807859f0222eaeccd208c0f"
        ),
    }
    op.bulk_insert(
        risk_policy_table,
        [
            {
                "risk_policy_revision_id": policy_document["risk_policy_revision_id"],
                "schema_version": policy_document["schema_version"],
                "state": policy_document["state"],
                "content_sha256": policy_document["content_sha256"],
                "canonical_document": policy_document,
                "created_by": "system:phase7-migration",
                "created_at": datetime(2026, 8, 23, tzinfo=UTC),
            }
        ],
    )
    op.create_table(
        "knowledge_analysis_runs",
        sa.Column("analysis_run_id", sa.String(44), primary_key=True),
        sa.Column("analysis_request_id", sa.String(50), nullable=False),
        sa.Column("predecessor_analysis_run_id", sa.String(44), nullable=True),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("submission_sha256", sa.String(71), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("canonical_request", postgresql.JSONB(), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_revision_id", sa.String(43), nullable=False),
        sa.Column("source_file_id", sa.String(43), nullable=True),
        sa.Column("item_id", sa.String(37), nullable=True),
        sa.Column("item_revision_id", sa.String(40), nullable=True),
        sa.Column("source_artifact_id", sa.String(41), nullable=False),
        sa.Column("source_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("source_sha256", sa.String(71), nullable=False),
        sa.Column("workflow_id", sa.String(41), nullable=False),
        sa.Column("plan_id", sa.String(41), nullable=False),
        sa.Column("platform_job_id", sa.String(36), nullable=True),
        sa.Column("preset_id", sa.String(43), nullable=False),
        sa.Column("preset_revision_id", sa.String(46), nullable=False),
        sa.Column("risk_policy_revision_id", sa.String(48), nullable=False),
        sa.Column("risk_policy_sha256", sa.String(71), nullable=False),
        sa.Column("proposal_artifact_id", sa.String(41), nullable=True),
        sa.Column("proposal_artifact_revision_id", sa.String(36), nullable=True),
        sa.Column("proposal_content_set_sha256", sa.String(71), nullable=True),
        sa.Column("accepted_result_artifact_id", sa.String(41), nullable=True),
        sa.Column("accepted_result_artifact_revision_id", sa.String(36), nullable=True),
        sa.Column("accepted_result_sha256", sa.String(71), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("anchor_count", sa.Integer(), nullable=True),
        sa.Column("node_count", sa.Integer(), nullable=True),
        sa.Column("edge_count", sa.Integer(), nullable=True),
        sa.Column("claim_count", sa.Integer(), nullable=True),
        sa.Column("component_count", sa.Integer(), nullable=True),
        sa.Column("ambiguity_count", sa.Integer(), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("created_by_operator_id", sa.String(41), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING',"
            "'NEEDS_REVIEW','ACCEPTED','REJECTED','FAILED','CANCELLED')",
            name="ck_knowledge_analysis_run_state",
        ),
        sa.CheckConstraint(
            "submission_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_submission_hash",
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND risk_policy_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_dependency_hashes",
        ),
        sa.CheckConstraint(
            "(source_kind = 'CONTENT_INTAKE_FILE' AND source_file_id IS NOT NULL "
            "AND item_id IS NULL AND item_revision_id IS NULL) OR "
            "(source_kind = 'APPROVED_ITEM_REVISION' AND source_file_id IS NULL "
            "AND item_id IS NOT NULL AND item_revision_id IS NOT NULL)",
            name="ck_knowledge_analysis_source_pointer_family",
        ),
        sa.CheckConstraint(
            "(proposal_artifact_id IS NULL AND proposal_artifact_revision_id IS NULL "
            "AND proposal_content_set_sha256 IS NULL) OR "
            "(proposal_artifact_id IS NOT NULL AND proposal_artifact_revision_id IS NOT NULL "
            "AND proposal_content_set_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_knowledge_analysis_proposal_pointer_complete",
        ),
        sa.CheckConstraint(
            "(accepted_result_artifact_id IS NULL "
            "AND accepted_result_artifact_revision_id IS NULL AND accepted_result_sha256 IS NULL) "
            "OR (accepted_result_artifact_id IS NOT NULL "
            "AND accepted_result_artifact_revision_id IS NOT NULL "
            "AND accepted_result_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_knowledge_analysis_result_pointer_complete",
        ),
        sa.CheckConstraint(
            "state <> 'ACCEPTED' OR accepted_result_artifact_revision_id IS NOT NULL",
            name="ck_knowledge_analysis_accepted_has_result",
        ),
        sa.CheckConstraint(
            "state = 'ACCEPTED' OR accepted_result_artifact_revision_id IS NULL",
            name="ck_knowledge_analysis_result_only_when_accepted",
        ),
        sa.CheckConstraint(
            "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION')",
            name="ck_knowledge_analysis_source_kind",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_request_hash",
        ),
        sa.CheckConstraint("lock_version >= 1", name="ck_knowledge_analysis_lock_version"),
        sa.CheckConstraint(
            "predecessor_analysis_run_id IS NULL OR predecessor_analysis_run_id <> analysis_run_id",
            name="ck_knowledge_analysis_predecessor_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_analysis_run_id"],
            ["knowledge_analysis_runs.analysis_run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["content_intake_source_files.source_file_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.item_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["item_revision_id"], ["item_revisions.item_revision_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_revision_id"], ["artifact_revisions.revision_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"], ["workflow_instances.workflow_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["resolved_execution_plans.plan_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["platform_job_id"], ["jobs.job_id"], ondelete="RESTRICT"),
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
            ["proposal_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_artifact_revision_id"],
            ["artifact_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_result_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_result_artifact_revision_id"],
            ["artifact_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("analysis_request_id", name="uq_knowledge_analysis_request"),
        sa.UniqueConstraint("idempotency_key", name="uq_knowledge_analysis_idempotency"),
        sa.UniqueConstraint("workflow_id", name="uq_knowledge_analysis_workflow"),
    )
    op.create_index(
        "ix_knowledge_analysis_runs_predecessor_analysis_run_id",
        "knowledge_analysis_runs",
        ["predecessor_analysis_run_id"],
    )
    op.create_index(
        "ix_knowledge_analysis_source_history",
        "knowledge_analysis_runs",
        ["source_kind", "source_revision_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_knowledge_analysis_intake_file",
        "knowledge_analysis_runs",
        ["source_file_id", "created_at"],
        postgresql_where=sa.text("source_file_id IS NOT NULL"),
    )
    op.create_index(
        "ix_knowledge_analysis_runnable",
        "knowledge_analysis_runs",
        ["state", "created_at", "analysis_run_id"],
        postgresql_where=sa.text(
            "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING')"
        ),
    )
    op.create_index(
        "ix_knowledge_analysis_runs_platform_job_id",
        "knowledge_analysis_runs",
        ["platform_job_id"],
    )
    op.create_index(
        "ix_knowledge_analysis_created",
        "knowledge_analysis_runs",
        [sa.text("created_at DESC"), sa.text("analysis_run_id DESC")],
    )
    op.create_index(
        "ix_knowledge_analysis_state_history",
        "knowledge_analysis_runs",
        ["state", sa.text("created_at DESC"), sa.text("analysis_run_id DESC")],
    )
    op.create_table(
        "knowledge_analysis_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("analysis_run_id", sa.String(44), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("prior_state", sa.String(24), nullable=True),
        sa.Column("new_state", sa.String(24), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["knowledge_analysis_runs.analysis_run_id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "analysis_run_id", "sequence", name="uq_knowledge_analysis_event_sequence"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_knowledge_analysis_event_sequence"),
    )
    op.create_index(
        "ix_knowledge_analysis_events_analysis_run_id",
        "knowledge_analysis_events",
        ["analysis_run_id"],
    )
    op.create_table(
        "knowledge_analysis_reviews",
        sa.Column("decision_id", sa.String(49), primary_key=True),
        sa.Column("analysis_run_id", sa.String(44), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("submission_sha256", sa.String(71), nullable=False),
        sa.Column("decided_by_operator_id", sa.String(41), nullable=False),
        sa.Column("risk_policy_revision_id", sa.String(48), nullable=False),
        sa.Column("risk_policy_sha256", sa.String(71), nullable=False),
        sa.Column("decision_sha256", sa.String(71), nullable=False),
        sa.Column("decision_artifact_id", sa.String(41), nullable=False),
        sa.Column("decision_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('APPROVE','REJECT')", name="ck_knowledge_analysis_review_decision"
        ),
        sa.CheckConstraint(
            "submission_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND decision_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND risk_policy_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_review_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["knowledge_analysis_runs.analysis_run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["risk_policy_revision_id"],
            ["knowledge_analysis_risk_policy_revisions.risk_policy_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["decision_artifact_revision_id"],
            ["artifact_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("analysis_run_id", name="uq_knowledge_analysis_review_run"),
        sa.UniqueConstraint(
            "decision_artifact_revision_id", name="uq_knowledge_analysis_review_artifact"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_knowledge_analysis_review_idempotency"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_analysis_reviews")
    op.drop_index(
        "ix_knowledge_analysis_runs_predecessor_analysis_run_id",
        table_name="knowledge_analysis_runs",
    )
    op.drop_index(
        "ix_knowledge_analysis_events_analysis_run_id", table_name="knowledge_analysis_events"
    )
    op.drop_table("knowledge_analysis_events")
    op.drop_index("ix_knowledge_analysis_state_history", table_name="knowledge_analysis_runs")
    op.drop_index("ix_knowledge_analysis_created", table_name="knowledge_analysis_runs")
    op.drop_index(
        "ix_knowledge_analysis_runs_platform_job_id", table_name="knowledge_analysis_runs"
    )
    op.drop_index("ix_knowledge_analysis_runnable", table_name="knowledge_analysis_runs")
    op.drop_index("ix_knowledge_analysis_intake_file", table_name="knowledge_analysis_runs")
    op.drop_index("ix_knowledge_analysis_source_history", table_name="knowledge_analysis_runs")
    op.drop_table("knowledge_analysis_runs")
    op.drop_table("knowledge_analysis_risk_policy_revisions")
    op.drop_constraint("ck_workflow_instances_stage", "workflow_instances", type_="check")
    op.create_check_constraint(
        "ck_workflow_instances_stage",
        "workflow_instances",
        "stage IN ('AUTHORING','IMAGE_REQUIRED','IMAGE_SKIPPED','REVIEWING',"
        "'AWAITING_HUMAN_APPROVAL','REGISTERING','COMPLETED','FAILED','CANCELLED')",
    )
