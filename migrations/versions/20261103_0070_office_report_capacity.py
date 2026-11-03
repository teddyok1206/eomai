"""Admit only the exact native Office four-report capacity, preserving old ceilings.

Revision ID: 20261103_0070
Revises: 20261102_0069
Create Date: 2026-11-03 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261103_0070"
down_revision = "20261102_0069"
branch_labels = None
depends_on = None

_PREDECESSOR = (
    "max_configured_slots BETWEEN 1 AND 6 AND max_active_codex BETWEEN 1 AND 3 "
    "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
    "AND max_active_gpu = 1 AND (max_active_knowledge_analysis BETWEEN 1 AND 2 "
    "OR (schema_version = 'worker-capacity-policy/1.4' "
    "AND max_active_knowledge_analysis = 3))"
)
_SUCCESSOR = (
    "(" + _PREDECESSOR + ") OR "
    "(schema_version = 'worker-capacity-policy/1.5' AND max_configured_slots = 6 "
    "AND max_active_codex = 4 AND max_active_per_slot = 1 AND max_active_gpu = 1 "
    "AND max_active_knowledge_analysis = 4)"
)


def _replace(predicate: str) -> None:
    op.drop_constraint(
        "ck_capacity_policy_host_limits", "worker_capacity_policy_revisions", type_="check"
    )
    op.create_check_constraint(
        "ck_capacity_policy_host_limits", "worker_capacity_policy_revisions", predicate
    )


def upgrade() -> None:
    _replace(_SUCCESSOR)
    # The parent policy retains the exact purpose/global ceiling. The child
    # pool envelope admits four without changing any predecessor parent row.
    op.drop_constraint("ck_worker_capacity_pool_limit", "worker_capacity_pools", type_="check")
    op.create_check_constraint(
        "ck_worker_capacity_pool_limit", "worker_capacity_pools", "max_active BETWEEN 1 AND 4"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM worker_capacity_policy_revisions "
            "WHERE schema_version='worker-capacity-policy/1.5') "
            "OR EXISTS (SELECT 1 FROM worker_capacity_pools WHERE max_active=4)"
        )
    ):
        raise RuntimeError("OFFICE_REPORT_CAPACITY_HISTORY_EXISTS")
    op.drop_constraint("ck_worker_capacity_pool_limit", "worker_capacity_pools", type_="check")
    op.create_check_constraint(
        "ck_worker_capacity_pool_limit", "worker_capacity_pools", "max_active BETWEEN 1 AND 3"
    )
    _replace(_PREDECESSOR)
