"""Add control-plane operator commands and preset evaluation evidence.

Revision ID: 20260823_0010
Revises: 20260823_0009
Create Date: 2026-08-23 15:30:00Z
"""

from collections.abc import Sequence
from hashlib import sha256

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0010"
down_revision: str | Sequence[str] | None = "20260823_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_PERMISSIONS = (
    "codex_account:read",
    "codex_account:manage",
    "execution_preset:read",
    "execution_preset:manage",
)


def _stable_id(prefix: str, key: str) -> str:
    return prefix + sha256(f"eom-api-v1:{prefix}:{key}".encode()).hexdigest()[:32]


def upgrade() -> None:
    op.add_column(
        "workflow_commands",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_workflow_commands_claimable",
        "workflow_commands",
        ["state", "available_at", "created_at", "command_id"],
    )

    op.create_table(
        "execution_preset_evaluations",
        sa.Column("evaluation_id", sa.String(length=43), nullable=False),
        sa.Column("preset_id", sa.String(length=43), nullable=False),
        sa.Column("evaluated_preset_revision_id", sa.String(length=46), nullable=False),
        sa.Column("evaluated_policy_sha256", sa.String(length=71), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("summary_code", sa.String(length=64), nullable=False),
        sa.Column("cases_total", sa.Integer(), nullable=False),
        sa.Column("cases_passed", sa.Integer(), nullable=False),
        sa.Column("quality_score_permille", sa.Integer(), nullable=True),
        sa.Column("report_artifact_id", sa.String(length=41), nullable=False),
        sa.Column("report_artifact_revision_id", sa.String(length=36), nullable=False),
        sa.Column("report_document_sha256", sa.String(length=71), nullable=False),
        sa.Column("report_content_sha256", sa.String(length=71), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "scope IN ('STATIC','NON_LIVE','LIVE_ONE_SHOT')",
            name="ck_execution_preset_evaluation_scope",
        ),
        sa.CheckConstraint(
            "outcome IN ('PASS','FAIL')", name="ck_execution_preset_evaluation_outcome"
        ),
        sa.CheckConstraint(
            "evaluated_policy_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND report_document_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND report_content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_execution_preset_evaluation_hashes",
        ),
        sa.CheckConstraint(
            "cases_total BETWEEN 1 AND 10000 AND cases_passed BETWEEN 0 AND cases_total",
            name="ck_execution_preset_evaluation_cases",
        ),
        sa.CheckConstraint(
            "quality_score_permille IS NULL OR quality_score_permille BETWEEN 0 AND 1000",
            name="ck_execution_preset_evaluation_quality",
        ),
        sa.ForeignKeyConstraint(
            ["preset_id"], ["execution_presets.preset_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evaluated_preset_revision_id"],
            ["execution_preset_revisions.preset_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_artifact_id"], ["artifacts.logical_artifact_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["report_artifact_revision_id"],
            ["artifact_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evaluation_id"),
        sa.UniqueConstraint(
            "report_artifact_revision_id", name="uq_execution_preset_evaluation_report_revision"
        ),
    )
    op.create_index(
        "ix_execution_preset_evaluation_policy",
        "execution_preset_evaluations",
        ["preset_id", "evaluated_policy_sha256", "completed_at"],
    )
    op.execute(
        "CREATE TRIGGER execution_preset_evaluations_immutable "
        "BEFORE UPDATE OR DELETE ON execution_preset_evaluations FOR EACH ROW "
        "EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
    )

    op.create_table(
        "codex_control_commands",
        sa.Column("command_id", sa.String(length=41), nullable=False),
        sa.Column("command_type", sa.String(length=16), nullable=False),
        sa.Column("binding_id", sa.String(length=44), nullable=False),
        sa.Column("expected_resource_version", sa.Integer(), nullable=False),
        sa.Column("requested_by_operator_id", sa.String(length=41), nullable=False),
        sa.Column("idempotency_key", sa.String(length=96), nullable=False),
        sa.Column("request_sha256", sa.String(length=71), nullable=False),
        sa.Column("canonical_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_resource_version", sa.Integer(), nullable=True),
        sa.Column("result_document", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "command_type IN ('OBSERVE','ENABLE','DRAIN','DISABLE')",
            name="ck_codex_control_command_type",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_codex_control_command_state",
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_codex_control_command_attempts"),
        sa.CheckConstraint(
            "expected_resource_version >= 1",
            name="ck_codex_control_command_expected_version",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_codex_control_command_hash",
        ),
        sa.CheckConstraint(
            "(state = 'PENDING' AND attempts = 0 AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND result_resource_version IS NULL "
            "AND result_document IS NULL AND error_code IS NULL AND processed_at IS NULL) OR "
            "(state = 'PROCESSING' AND attempts BETWEEN 1 AND 3 AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND result_resource_version IS NULL "
            "AND result_document IS NULL AND error_code IS NULL AND processed_at IS NULL) OR "
            "(state = 'SUCCEEDED' AND attempts BETWEEN 1 AND 3 AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND result_resource_version IS NOT NULL "
            "AND result_document IS NOT NULL AND error_code IS NULL AND processed_at IS NOT NULL) "
            "OR (state = 'FAILED' AND attempts BETWEEN 1 AND 3 AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND error_code IS NOT NULL AND processed_at IS NOT NULL)",
            name="ck_codex_control_command_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["codex_auth_bindings.binding_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_operator_id"], ["operators.operator_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("command_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_codex_control_command_idempotency"),
    )
    op.create_index(
        "ix_codex_control_command_claim",
        "codex_control_commands",
        ["state", "lease_expires_at", "requested_at", "command_id"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_codex_control_command_identity() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Codex control command is immutable';
          END IF;
          IF (to_jsonb(OLD) - ARRAY[
                'state','attempts','lease_owner','lease_expires_at','result_resource_version',
                'result_document','error_code','processed_at'
              ]) IS DISTINCT FROM
             (to_jsonb(NEW) - ARRAY[
                'state','attempts','lease_owner','lease_expires_at','result_resource_version',
                'result_document','error_code','processed_at'
              ]) THEN
            RAISE EXCEPTION 'Codex control command identity is immutable';
          END IF;
          IF OLD.state IN ('SUCCEEDED','FAILED') THEN
            RAISE EXCEPTION 'terminal Codex control command is immutable';
          END IF;
          IF NOT (
            (OLD.state = 'PENDING' AND NEW.state = 'PROCESSING') OR
            (OLD.state = 'PROCESSING' AND NEW.state IN ('PROCESSING','SUCCEEDED','FAILED'))
          ) THEN
            RAISE EXCEPTION 'invalid Codex control command transition';
          END IF;
          IF NEW.attempts <= OLD.attempts AND NEW.state = 'PROCESSING' THEN
            RAISE EXCEPTION 'Codex control command attempt must advance';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER codex_control_commands_identity_immutable "
        "BEFORE UPDATE OR DELETE ON codex_control_commands FOR EACH ROW "
        "EXECUTE FUNCTION protect_codex_control_command_identity()"
    )

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
    op.bulk_insert(
        permission_table,
        [
            {
                "permission_id": _stable_id("permission_", key),
                "permission_key": key,
                "description": f"Allows {key}",
            }
            for key in NEW_PERMISSIONS
        ],
    )
    op.bulk_insert(
        role_permission_table,
        [
            {
                "role_id": _stable_id("role_", "ADMIN"),
                "permission_id": _stable_id("permission_", key),
            }
            for key in NEW_PERMISSIONS
        ],
    )


def downgrade() -> None:
    for key in NEW_PERMISSIONS:
        permission_id = _stable_id("permission_", key)
        op.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :permission_id").bindparams(
                permission_id=permission_id
            )
        )
        op.execute(
            sa.text("DELETE FROM permissions WHERE permission_id = :permission_id").bindparams(
                permission_id=permission_id
            )
        )
    op.execute(
        "DROP TRIGGER IF EXISTS codex_control_commands_identity_immutable ON codex_control_commands"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_codex_control_command_identity()")
    op.drop_index("ix_codex_control_command_claim", table_name="codex_control_commands")
    op.drop_table("codex_control_commands")
    op.execute(
        "DROP TRIGGER IF EXISTS execution_preset_evaluations_immutable "
        "ON execution_preset_evaluations"
    )
    op.drop_index(
        "ix_execution_preset_evaluation_policy", table_name="execution_preset_evaluations"
    )
    op.drop_table("execution_preset_evaluations")
    op.drop_index("ix_workflow_commands_claimable", table_name="workflow_commands")
    op.drop_column("workflow_commands", "available_at")
