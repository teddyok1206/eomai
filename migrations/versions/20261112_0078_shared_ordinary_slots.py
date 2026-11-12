"""Admit shared ordinary-slot capacity without modifying historical policies.

Revision ID: 20261112_0078
Revises: 20261110_0077
Create Date: 2026-11-12 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261112_0078"
down_revision = "20261110_0077"
branch_labels = None
depends_on = None

_BEFORE = (
    "(max_configured_slots BETWEEN 1 AND 6 AND max_active_codex BETWEEN 1 AND 3 "
    "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
    "AND max_active_gpu = 1 AND (max_active_knowledge_analysis BETWEEN 1 AND 2 "
    "OR (schema_version = 'worker-capacity-policy/1.4' AND max_active_knowledge_analysis = 3))) OR "
    "(schema_version IN ('worker-capacity-policy/1.5','worker-capacity-policy/1.6') "
    "AND max_configured_slots = 6 AND max_active_codex = 4 AND max_active_per_slot = 1 "
    "AND max_active_gpu = 1 AND max_active_knowledge_analysis = 4)"
)
_AFTER = (
    "(" + _BEFORE + ") OR (schema_version = 'worker-capacity-policy/1.7' "
    "AND max_configured_slots = 6 AND max_active_codex = 4 AND max_active_per_slot = 1 "
    "AND max_active_gpu = 1 AND max_active_knowledge_analysis = 4)"
)


def _replace(predicate: str) -> None:
    op.drop_constraint(
        "ck_capacity_policy_host_limits", "worker_capacity_policy_revisions", type_="check"
    )
    op.create_check_constraint(
        "ck_capacity_policy_host_limits", "worker_capacity_policy_revisions", predicate
    )


def upgrade() -> None:
    _replace(_AFTER)


def downgrade() -> None:
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM worker_capacity_policy_revisions "
            "WHERE schema_version='worker-capacity-policy/1.7')"
        )
    ):
        raise RuntimeError("SHARED_ORDINARY_CAPACITY_HISTORY_EXISTS")
    _replace(_BEFORE)
