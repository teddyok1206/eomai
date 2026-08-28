"""Add six-slot capacity and bounded-parallel Knowledge Analysis scheduling.

Revision ID: 20260828_0022
Revises: 20260828_0021
Create Date: 2026-08-28 16:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0022"
down_revision: str | None = "20260828_0021"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_capacity_policy_host_limits",
        "worker_capacity_policy_revisions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_capacity_policy_host_limits",
        "worker_capacity_policy_revisions",
        "max_configured_slots BETWEEN 1 AND 6 AND max_active_codex BETWEEN 1 AND 3 "
        "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
        "AND max_active_gpu = 1 AND max_active_knowledge_analysis BETWEEN 1 AND 2",
    )

    op.add_column(
        "knowledge_analysis_batches",
        sa.Column(
            "scheduling_mode",
            sa.String(length=24),
            server_default="SERIAL",
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_analysis_batches",
        sa.Column("max_in_flight", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        "ck_knowledge_analysis_batch_scheduling",
        "knowledge_analysis_batches",
        "(scheduling_mode = 'SERIAL' AND max_in_flight = 1) OR "
        "(scheduling_mode = 'BOUNDED_PARALLEL' AND max_in_flight = 2 "
        "AND range_failure_policy = 'CONTINUE_AND_COLLECT')",
    )

    op.drop_index(
        "uq_knowledge_analysis_batch_active_range",
        table_name="knowledge_analysis_batch_ranges",
    )
    op.create_index(
        "ix_knowledge_analysis_batch_active_range",
        "knowledge_analysis_batch_ranges",
        ["batch_id", "state", "ordinal"],
        unique=False,
        postgresql_where=sa.text("state IN ('CLAIMED','SUBMITTED')"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    active_conflict = connection.execute(
        sa.text(
            "SELECT 1 FROM knowledge_analysis_batch_ranges "
            "WHERE state IN ('CLAIMED','SUBMITTED') GROUP BY batch_id HAVING count(*) > 1 LIMIT 1"
        )
    ).scalar_one_or_none()
    parallel_history = connection.execute(
        sa.text(
            "SELECT 1 FROM knowledge_analysis_batches "
            "WHERE scheduling_mode <> 'SERIAL' OR max_in_flight <> 1 LIMIT 1"
        )
    ).scalar_one_or_none()
    capacity_v2 = connection.execute(
        sa.text(
            "SELECT 1 FROM worker_capacity_policy_revisions "
            "WHERE max_configured_slots > 5 OR max_active_knowledge_analysis > 1 LIMIT 1"
        )
    ).scalar_one_or_none()
    if active_conflict or parallel_history or capacity_v2:
        raise RuntimeError(
            "bounded-parallel history prevents downgrade; restore the verified pre-upgrade backup"
        )

    op.drop_index(
        "ix_knowledge_analysis_batch_active_range",
        table_name="knowledge_analysis_batch_ranges",
    )
    op.create_index(
        "uq_knowledge_analysis_batch_active_range",
        "knowledge_analysis_batch_ranges",
        ["batch_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('CLAIMED','SUBMITTED')"),
    )

    op.drop_constraint(
        "ck_knowledge_analysis_batch_scheduling",
        "knowledge_analysis_batches",
        type_="check",
    )
    op.drop_column("knowledge_analysis_batches", "max_in_flight")
    op.drop_column("knowledge_analysis_batches", "scheduling_mode")

    op.drop_constraint(
        "ck_capacity_policy_host_limits",
        "worker_capacity_policy_revisions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_capacity_policy_host_limits",
        "worker_capacity_policy_revisions",
        "max_configured_slots BETWEEN 1 AND 5 AND max_active_codex BETWEEN 1 AND 3 "
        "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
        "AND max_active_gpu = 1 AND max_active_knowledge_analysis = 1",
    )
