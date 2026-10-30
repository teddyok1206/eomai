"""Admit the exact three-report purpose without changing predecessor limits.

Revision ID: 20261030_0064
Revises: 20261029_0063
Create Date: 2026-10-30 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261030_0064"
down_revision = "20261029_0063"
branch_labels = None
depends_on = None

_PREDECESSOR = (
    "max_configured_slots BETWEEN 1 AND 6 AND max_active_codex BETWEEN 1 AND 3 "
    "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
    "AND max_active_gpu = 1 AND max_active_knowledge_analysis BETWEEN 1 AND 2"
)
_SUCCESSOR = (
    "max_configured_slots BETWEEN 1 AND 6 AND max_active_codex BETWEEN 1 AND 3 "
    "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
    "AND max_active_gpu = 1 AND (max_active_knowledge_analysis BETWEEN 1 AND 2 "
    "OR (schema_version = 'worker-capacity-policy/1.4' "
    "AND max_active_knowledge_analysis = 3))"
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


def downgrade() -> None:
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM worker_capacity_policy_revisions "
            "WHERE max_active_knowledge_analysis = 3)"
        )
    ):
        raise RuntimeError("CREATIVE_REPORT_CAPACITY_HISTORY_EXISTS")
    _replace(_PREDECESSOR)
