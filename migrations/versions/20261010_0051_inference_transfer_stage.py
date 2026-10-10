"""Admit the dedicated comparison stage without changing historical workflow states.

Revision ID: 20261010_0051
Revises: 20261009_0050
Create Date: 2026-10-10 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261010_0051"
down_revision: str | None = "20261009_0050"
branch_labels: str | None = None
depends_on: str | None = None

_PREVIOUS_STAGES = (
    "'KNOWLEDGE_ANALYSIS','CUSTOMER_SUPPORT','DOCUMENT_REVIEW','AUTHORING',"
    "'IMAGE_REQUIRED','IMAGE_SKIPPED','REVIEWING','AWAITING_HUMAN_APPROVAL',"
    "'REGISTERING','COMPLETED','FAILED','CANCELLED'"
)
_CONSTRAINT = "ck_workflow_instances_stage"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "workflow_instances", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "workflow_instances",
        "stage IN (" + _PREVIOUS_STAGES + ",'INFERENCE_TRANSFER')",
    )


def downgrade() -> None:
    # PostgreSQL rejects the narrower CHECK if a current comparison uses this
    # stage; do not rewrite historical rows or silently reinterpret their purpose.
    op.drop_constraint(_CONSTRAINT, "workflow_instances", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "workflow_instances", "stage IN (" + _PREVIOUS_STAGES + ")"
    )
