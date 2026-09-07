"""add whole-assessment HWPX application build queue

Revision ID: 20260907_0031
Revises: 20260906_0030
Create Date: 2026-09-07 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0031"
down_revision: str | None = "20260906_0030"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "hwpx_assessment_assembly_builds",
        sa.Column("build_id", sa.String(42), primary_key=True),
        sa.Column("assessment_assembly_id", sa.String(41), nullable=False),
        sa.Column("assessment_assembly_revision_id", sa.String(44), nullable=False),
        sa.Column("assembly_manifest_sha256", sa.String(71), nullable=False),
        sa.Column("policy_revision_id", sa.String(50), nullable=False),
        sa.Column("policy_sha256", sa.String(71), nullable=False),
        sa.Column("graph_snapshot_revision_id", sa.String(41), nullable=False),
        sa.Column("graph_snapshot_sha256", sa.String(71), nullable=False),
        sa.Column("item_set_sha256", sa.String(71), nullable=False),
        sa.Column("renderer", sa.String(64), nullable=False),
        sa.Column("renderer_version", sa.String(32), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_by_operator_id", sa.String(41), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("validation_state", sa.String(32), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("section_count", sa.Integer()),
        sa.Column("native_equation_count", sa.Integer()),
        sa.Column("native_table_count", sa.Integer()),
        sa.Column("visual_count", sa.Integer()),
        sa.Column("platform_job_id", sa.String(37), unique=True),
        sa.Column("output_artifact_id", sa.String(41)),
        sa.Column("output_artifact_revision_id", sa.String(36)),
        sa.Column("output_sha256", sa.String(71)),
        sa.Column("output_filename", sa.String(160)),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("failure_detail_sanitized", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("resource_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "state IN ('REQUESTED','RUNNING','VALIDATING','SUCCEEDED','FAILED')",
            name="ck_hwpx_assembly_builds_state",
        ),
        sa.CheckConstraint(
            "validation_state IN ('PENDING','PASS','FAIL')",
            name="ck_hwpx_assembly_builds_validation_state",
        ),
        sa.CheckConstraint(
            "(state IN ('REQUESTED','RUNNING','VALIDATING') AND validation_state = 'PENDING') "
            "OR (state = 'SUCCEEDED' AND validation_state = 'PASS' AND item_count > 0 "
            "AND section_count = item_count AND native_equation_count IS NOT NULL "
            "AND native_table_count IS NOT NULL AND visual_count IS NOT NULL "
            "AND output_artifact_id IS NOT NULL AND output_artifact_revision_id IS NOT NULL "
            "AND output_sha256 IS NOT NULL AND output_filename IS NOT NULL) "
            "OR (state = 'FAILED' AND validation_state = 'FAIL' AND failure_code IS NOT NULL)",
            name="ck_hwpx_assembly_builds_terminal_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_assembly_id"], ["assessment_assemblies.assessment_assembly_id"]
        ),
        sa.ForeignKeyConstraint(
            ["assessment_assembly_revision_id"],
            ["assessment_assembly_revisions.assessment_assembly_revision_id"],
        ),
        sa.ForeignKeyConstraint(["created_by_operator_id"], ["operators.operator_id"]),
        sa.ForeignKeyConstraint(["platform_job_id"], ["jobs.job_id"]),
        sa.ForeignKeyConstraint(["output_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["output_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.UniqueConstraint(
            "created_by_operator_id",
            "idempotency_key",
            name="uq_hwpx_assembly_builds_operator_idempotency",
        ),
    )
    op.create_index(
        "ix_hwpx_assembly_builds_revision_history",
        "hwpx_assessment_assembly_builds",
        ["assessment_assembly_revision_id", "created_at", "build_id"],
    )
    op.create_index(
        "ix_hwpx_assembly_builds_requested_fifo",
        "hwpx_assessment_assembly_builds",
        ["created_at", "build_id"],
        postgresql_where=sa.text("state = 'REQUESTED'"),
    )
    op.create_index(
        "ix_hwpx_assembly_builds_operator",
        "hwpx_assessment_assembly_builds",
        ["created_by_operator_id"],
    )


def downgrade() -> None:
    op.drop_table("hwpx_assessment_assembly_builds")
