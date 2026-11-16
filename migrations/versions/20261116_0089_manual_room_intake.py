"""Immutable manual channel evidence pins; no automatic collector activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0089"
down_revision = "20261116_0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kakao_manual_channel_pins",
        sa.Column("source_binding_id", sa.String(45), primary_key=True),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("channel_key_sha256", sa.String(71), nullable=False),
        sa.Column("evidence_artifact_id", sa.String(41), nullable=False),
        sa.Column("evidence_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("evidence_sha256", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "channel_key_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_manual_channel_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_manual_channel_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_artifact_id", "evidence_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_manual_channel_evidence",
            ondelete="RESTRICT",
        ),
    )
    op.execute(
        "CREATE TRIGGER protect_kakao_manual_channel_pin BEFORE UPDATE OR DELETE ON "
        "kakao_manual_channel_pins FOR EACH ROW "
        "EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
    )


def downgrade() -> None:
    op.drop_table("kakao_manual_channel_pins")
