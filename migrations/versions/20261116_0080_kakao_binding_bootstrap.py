"""Private owner-only Kakao binding bootstrap; no channel activation or collection."""

from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision = "20261116_0080"
down_revision = "20261112_0079"
branch_labels = None
depends_on = None

NEW_PERMISSIONS = (
    "kakao_archive:read",
    "kakao_archive:collect",
    "kakao_archive:edit",
    "kakao_archive:export",
    "kakao_archive:remote",
)


def _stable_id(prefix: str, key: str) -> str:
    return prefix + sha256(f"eom-api-v1:{prefix}:{key}".encode()).hexdigest()[:32]


def upgrade() -> None:
    op.create_table(
        "kakao_channel_bindings",
        sa.Column("source_binding_id", sa.String(45), primary_key=True),
        sa.Column(
            "owner_operator_id",
            sa.String(41),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("current_policy_revision_id", sa.String(47), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_binding_id ~ '^kakaobinding_[0-9a-f]{32}$'", name="ck_kakao_binding_id"
        ),
        sa.CheckConstraint("state IN ('DRAFT','RETIRED')", name="ck_kakao_binding_state"),
        sa.CheckConstraint("resource_version >= 1", name="ck_kakao_binding_version"),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0 AND display_name !~ '[[:cntrl:]]'",
            name="ck_kakao_binding_name",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_kakao_binding_time"),
        sa.UniqueConstraint(
            "owner_operator_id", "source_binding_id", name="uq_kakao_binding_owner"
        ),
    )
    op.create_table(
        "kakao_collection_policy_revisions",
        sa.Column("policy_revision_id", sa.String(47), primary_key=True),
        sa.Column(
            "source_binding_id",
            sa.String(45),
            sa.ForeignKey("kakao_channel_bindings.source_binding_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_revision_id", sa.String(47)),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(71), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("source_timezone", sa.String(16), nullable=False),
        sa.Column(
            "created_by",
            sa.String(41),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "policy_revision_id ~ '^kakaopolicyrev_[0-9a-f]{32}$'", name="ck_kakao_policy_id"
        ),
        sa.CheckConstraint(
            "(revision_number = 1 AND previous_revision_id IS NULL) OR "
            "(revision_number > 1 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> policy_revision_id)",
            name="ck_kakao_policy_lineage",
        ),
        sa.CheckConstraint("sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_kakao_policy_hash"),
        sa.CheckConstraint(
            "interval_minutes BETWEEN 60 AND 10080", name="ck_kakao_policy_interval"
        ),
        sa.CheckConstraint(
            "source_timezone IN ('unknown','Asia/Seoul')", name="ck_kakao_policy_timezone"
        ),
        sa.UniqueConstraint(
            "source_binding_id", "policy_revision_id", name="uq_kakao_policy_binding"
        ),
        sa.UniqueConstraint("source_binding_id", "revision_number", name="uq_kakao_policy_number"),
        sa.ForeignKeyConstraint(
            ["source_binding_id", "previous_revision_id"],
            [
                "kakao_collection_policy_revisions.source_binding_id",
                "kakao_collection_policy_revisions.policy_revision_id",
            ],
            name="fk_kakao_policy_previous",
            ondelete="RESTRICT",
        ),
    )
    op.create_foreign_key(
        "fk_kakao_binding_current_policy",
        "kakao_channel_bindings",
        "kakao_collection_policy_revisions",
        ["source_binding_id", "current_policy_revision_id"],
        ["source_binding_id", "policy_revision_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "kakao_binding_commands",
        sa.Column("command_id", sa.String(45), primary_key=True),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("idempotency_scope", sa.String(96), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("result_state", sa.String(16), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=False),
        sa.Column("result_policy_revision_id", sa.String(47), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$'", name="ck_kakao_command_id"
        ),
        sa.CheckConstraint(
            "action IN ('CREATE','UPDATE_COLLECTION_POLICY','RETIRE')",
            name="ck_kakao_command_action",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_command_request",
        ),
        sa.CheckConstraint(
            "result_version >= 1 AND result_state IN ('DRAFT','RETIRED')",
            name="ck_kakao_command_result",
        ),
        sa.UniqueConstraint(
            "owner_operator_id",
            "idempotency_scope",
            "idempotency_key",
            name="uq_kakao_command_replay",
        ),
        sa.UniqueConstraint("source_binding_id", "result_version", name="uq_kakao_command_version"),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_command_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_binding_id", "result_policy_revision_id"],
            [
                "kakao_collection_policy_revisions.source_binding_id",
                "kakao_collection_policy_revisions.policy_revision_id",
            ],
            name="fk_kakao_command_policy",
            ondelete="RESTRICT",
        ),
    )
    for table, trigger in (
        ("kakao_collection_policy_revisions", "trg_kakao_policy_immutable"),
        ("kakao_binding_commands", "trg_kakao_command_immutable"),
    ):
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
        )
    permissions = sa.table(
        "permissions",
        sa.column("permission_id", sa.String),
        sa.column("permission_key", sa.String),
        sa.column("description", sa.String),
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("role_id", sa.String), sa.column("permission_id", sa.String)
    )
    op.bulk_insert(
        permissions,
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
        role_permissions,
        [
            {
                "role_id": _stable_id("role_", "ADMIN"),
                "permission_id": _stable_id("permission_", key),
            }
            for key in NEW_PERMISSIONS
        ],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM kakao_channel_bindings)")):
        raise RuntimeError("KAKAO_ARCHIVE_HISTORY_EXISTS")
    op.drop_table("kakao_binding_commands")
    op.drop_constraint(
        "fk_kakao_binding_current_policy", "kakao_channel_bindings", type_="foreignkey"
    )
    op.drop_table("kakao_collection_policy_revisions")
    op.drop_table("kakao_channel_bindings")
    for key in NEW_PERMISSIONS:
        permission_id = _stable_id("permission_", key)
        op.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :id").bindparams(
                id=permission_id
            )
        )
        op.execute(
            sa.text("DELETE FROM permissions WHERE permission_id = :id").bindparams(
                id=permission_id
            )
        )
