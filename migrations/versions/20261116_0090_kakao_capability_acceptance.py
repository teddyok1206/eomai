"""Exact immutable capability receipts; source/automatic activation remains separate."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0090"
down_revision = "20261116_0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kakao_capability_acceptances",
        sa.Column("capability_revision_id", sa.String(51), primary_key=True),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("room_id", sa.String(42), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("manifest_artifact_id", sa.String(41), nullable=False),
        sa.Column("manifest_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("manifest_sha256", sa.String(71), nullable=False),
        sa.Column("adapter_release_sha256", sa.String(71), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "owner_operator_id",
            "source_binding_id",
            "idempotency_key",
            name="uq_kakao_capability_replay",
        ),
        sa.UniqueConstraint(
            "source_binding_id", "capability_revision_id", name="uq_kakao_capability_binding"
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_capability_room",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["manifest_artifact_id", "manifest_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_capability_manifest",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "capability_revision_id ~ '^kakaocapabilityrev_[0-9a-f]{32}$' "
            "AND request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND adapter_release_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_capability_values",
        ),
    )
    op.execute(
        "CREATE TRIGGER protect_kakao_capability_acceptance BEFORE UPDATE OR DELETE ON "
        "kakao_capability_acceptances FOR EACH ROW "
        "EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
    )


def downgrade() -> None:
    op.drop_table("kakao_capability_acceptances")
