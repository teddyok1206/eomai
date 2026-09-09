"""persist exact PDF learning completion observations and alias indexes

Revision ID: 20260909_0033
Revises: 20260908_0032
Create Date: 2026-09-09 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0033"
down_revision: str | None = "20260908_0032"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_knowledge_analysis_source_artifact_scope",
        "knowledge_analysis_runs",
        [
            "source_artifact_id",
            "source_artifact_revision_id",
            "source_sha256",
            "created_at",
            "analysis_run_id",
        ],
    )
    op.create_index(
        "ix_knowledge_analysis_result_artifact_scope",
        "knowledge_analysis_runs",
        [
            "accepted_result_artifact_id",
            "accepted_result_artifact_revision_id",
            "accepted_result_sha256",
            "created_at",
            "analysis_run_id",
        ],
        postgresql_where=sa.text("accepted_result_artifact_revision_id IS NOT NULL"),
    )
    op.create_table(
        "pdf_learning_completion_observations",
        sa.Column("completion_identity_sha256", sa.String(length=71), nullable=False),
        sa.Column("mutable_fingerprint_sha256", sa.String(length=71), nullable=False),
        sa.Column("source_commit", sa.String(length=40), nullable=False),
        sa.Column("source_tree", sa.String(length=40), nullable=False),
        sa.Column("source_archive_sha256", sa.String(length=71), nullable=False),
        sa.Column("inventory_id", sa.String(length=48), nullable=False),
        sa.Column("inventory_sha256", sa.String(length=71), nullable=False),
        sa.Column("original_batch_id", sa.String(length=44), nullable=False),
        sa.Column("successor_batch_id", sa.String(length=44), nullable=False),
        sa.Column("recovery_sha256", sa.String(length=71), nullable=False),
        sa.Column("coverage_id", sa.String(length=45), nullable=False),
        sa.Column("graph_snapshot_revision_id", sa.String(length=41), nullable=False),
        sa.Column("graph_snapshot_sha256", sa.String(length=71), nullable=False),
        sa.Column("requested_by_operator_id", sa.String(length=128), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "completion_identity_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND mutable_fingerprint_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND source_archive_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND inventory_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND graph_snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_pdf_learning_completion_observation_hashes",
        ),
        sa.CheckConstraint(
            "source_commit ~ '^[0-9a-f]{40}$' AND source_tree ~ '^[0-9a-f]{40}$'",
            name="ck_pdf_learning_completion_observation_source_release",
        ),
        sa.ForeignKeyConstraint(
            ["graph_snapshot_revision_id"],
            ["knowledge_graph_snapshots.graph_snapshot_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("completion_identity_sha256"),
    )


def downgrade() -> None:
    op.drop_table("pdf_learning_completion_observations")
    op.drop_index(
        "ix_knowledge_analysis_result_artifact_scope", table_name="knowledge_analysis_runs"
    )
    op.drop_index(
        "ix_knowledge_analysis_source_artifact_scope", table_name="knowledge_analysis_runs"
    )
