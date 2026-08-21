"""Add Item Revision based HWPX Application API build resources.

Revision ID: 20260821_0008
Revises: 20260818_0007
Create Date: 2026-08-21 10:00:00Z
"""

from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0008"
down_revision: str | None = "20260818_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stable_id(prefix: str, key: str) -> str:
    return prefix + sha256(f"eom-api-v1:{prefix}:{key}".encode()).hexdigest()[:32]


def upgrade() -> None:
    permission_table = sa.table(
        "permissions",
        sa.column("permission_id", sa.String),
        sa.column("permission_key", sa.String),
        sa.column("description", sa.String),
    )
    role_permission_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.String),
        sa.column("permission_id", sa.String),
    )
    permission_keys = ("hwpx:read", "hwpx:build_create")
    op.bulk_insert(
        permission_table,
        [
            {
                "permission_id": _stable_id("permission_", key),
                "permission_key": key,
                "description": f"Allows {key}",
            }
            for key in permission_keys
        ],
    )
    assignments = {
        "VIEWER": ("hwpx:read",),
        "AUTHOR": ("hwpx:read",),
        "REVIEWER": ("hwpx:read",),
        "EDITOR": permission_keys,
        "ADMIN": permission_keys,
    }
    op.bulk_insert(
        role_permission_table,
        [
            {
                "role_id": _stable_id("role_", role),
                "permission_id": _stable_id("permission_", permission),
            }
            for role, permissions in assignments.items()
            for permission in permissions
        ],
    )
    op.create_table(
        "hwpx_application_builds",
        sa.Column("build_id", sa.String(length=42), nullable=False),
        sa.Column("item_id", sa.String(length=37), nullable=False),
        sa.Column("item_revision_id", sa.String(length=40), nullable=False),
        sa.Column("source_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("source_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=71), nullable=False),
        sa.Column("source_schema_ref", sa.String(length=256), nullable=False),
        sa.Column("source_media_type", sa.String(length=128), nullable=False),
        sa.Column("renderer", sa.String(length=32), nullable=False),
        sa.Column("renderer_version", sa.String(length=32), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_sha256", sa.String(length=71), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("created_by_operator_id", sa.String(length=41), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("validation_state", sa.String(length=32), nullable=False),
        sa.Column("native_equation_count", sa.Integer(), nullable=True),
        sa.Column("native_table_count", sa.Integer(), nullable=True),
        sa.Column("platform_job_id", sa.String(length=36), nullable=True),
        sa.Column("output_artifact_id", sa.String(length=41), nullable=True),
        sa.Column("output_artifact_revision_id", sa.String(length=36), nullable=True),
        sa.Column("output_sha256", sa.String(length=71), nullable=True),
        sa.Column("output_filename", sa.String(length=160), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_detail_sanitized", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "state IN ('REQUESTED','RUNNING','VALIDATING','SUCCEEDED','FAILED')",
            name="ck_hwpx_application_builds_state",
        ),
        sa.CheckConstraint(
            "validation_state IN ('PENDING','PASS','FAIL')",
            name="ck_hwpx_application_builds_validation_state",
        ),
        sa.CheckConstraint(
            "(state IN ('REQUESTED','RUNNING','VALIDATING') AND validation_state = 'PENDING') "
            "OR (state = 'SUCCEEDED' AND validation_state = 'PASS' "
            "AND native_equation_count IS NOT NULL AND native_table_count IS NOT NULL "
            "AND output_artifact_id IS NOT NULL AND output_artifact_revision_id IS NOT NULL "
            "AND output_sha256 IS NOT NULL AND output_filename IS NOT NULL) "
            "OR (state = 'FAILED' AND validation_state = 'FAIL' AND failure_code IS NOT NULL)",
            name="ck_hwpx_application_builds_terminal_evidence",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.item_id"]),
        sa.ForeignKeyConstraint(["item_revision_id"], ["item_revisions.item_revision_id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["source_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.ForeignKeyConstraint(["created_by_operator_id"], ["operators.operator_id"]),
        sa.ForeignKeyConstraint(["platform_job_id"], ["jobs.job_id"]),
        sa.ForeignKeyConstraint(["output_artifact_id"], ["artifacts.logical_artifact_id"]),
        sa.ForeignKeyConstraint(
            ["output_artifact_revision_id"], ["artifact_revisions.revision_id"]
        ),
        sa.PrimaryKeyConstraint("build_id"),
        sa.UniqueConstraint("platform_job_id"),
        sa.UniqueConstraint(
            "created_by_operator_id",
            "idempotency_key",
            name="uq_hwpx_application_builds_operator_idempotency",
        ),
    )
    op.create_index("ix_hwpx_application_builds_item_id", "hwpx_application_builds", ["item_id"])
    op.create_index(
        "ix_hwpx_application_builds_created_by_operator_id",
        "hwpx_application_builds",
        ["created_by_operator_id"],
    )
    op.create_index("ix_hwpx_application_builds_state", "hwpx_application_builds", ["state"])
    op.create_index(
        "ix_hwpx_application_builds_item_revision_history",
        "hwpx_application_builds",
        ["item_revision_id", "created_at", "build_id"],
    )
    op.create_index(
        "ix_hwpx_application_builds_created",
        "hwpx_application_builds",
        ["created_at", "build_id"],
    )
    op.create_index(
        "ix_hwpx_application_builds_requested_fifo",
        "hwpx_application_builds",
        ["created_at", "build_id"],
        postgresql_where=sa.text("state = 'REQUESTED'"),
    )


def downgrade() -> None:
    op.drop_index("ix_hwpx_application_builds_requested_fifo", table_name="hwpx_application_builds")
    op.drop_index("ix_hwpx_application_builds_created", table_name="hwpx_application_builds")
    op.drop_index(
        "ix_hwpx_application_builds_item_revision_history",
        table_name="hwpx_application_builds",
    )
    op.drop_index("ix_hwpx_application_builds_state", table_name="hwpx_application_builds")
    op.drop_index(
        "ix_hwpx_application_builds_created_by_operator_id",
        table_name="hwpx_application_builds",
    )
    op.drop_index("ix_hwpx_application_builds_item_id", table_name="hwpx_application_builds")
    op.drop_table("hwpx_application_builds")
    read_permission_id = _stable_id("permission_", "hwpx:read")
    create_permission_id = _stable_id("permission_", "hwpx:build_create")
    op.execute(
        sa.text(
            "DELETE FROM role_permissions "
            "WHERE permission_id IN (:read_permission_id, :create_permission_id)"
        ).bindparams(
            read_permission_id=read_permission_id,
            create_permission_id=create_permission_id,
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM permissions "
            "WHERE permission_id IN (:read_permission_id, :create_permission_id)"
        ).bindparams(
            read_permission_id=read_permission_id,
            create_permission_id=create_permission_id,
        )
    )
