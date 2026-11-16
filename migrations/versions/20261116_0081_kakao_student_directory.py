"""Private student identities and immutable display revisions; no room auto-mapping."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0081"
down_revision = "20261116_0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kakao_students",
        sa.Column("student_id", sa.String(45), primary_key=True),
        sa.Column(
            "owner_operator_id",
            sa.String(41),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("current_display_revision_id", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "student_id ~ '^kakaostudent_[0-9a-f]{32}$'", name="ck_kakao_student_id"
        ),
        sa.CheckConstraint("resource_version >= 1", name="ck_kakao_student_version"),
        sa.CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_kakao_student_state"),
        sa.UniqueConstraint("owner_operator_id", "student_id", name="uq_kakao_student_owner"),
    )
    op.create_table(
        "kakao_student_display_revisions",
        sa.Column("display_revision_id", sa.String(48), primary_key=True),
        sa.Column(
            "student_id",
            sa.String(45),
            sa.ForeignKey("kakao_students.student_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_revision_id", sa.String(48)),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("sha256", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            sa.String(41),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "display_revision_id ~ '^kakaostudentrev_[0-9a-f]{32}$'",
            name="ck_kakao_student_display_id",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_kakao_student_display_hash"
        ),
        sa.CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_kakao_student_display_state"),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0 AND display_name !~ '[[:cntrl:]]'",
            name="ck_kakao_student_display_name",
        ),
        sa.CheckConstraint(
            "(revision_number = 1 AND previous_revision_id IS NULL) OR "
            "(revision_number > 1 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> display_revision_id)",
            name="ck_kakao_student_display_lineage",
        ),
        sa.UniqueConstraint(
            "student_id", "display_revision_id", name="uq_kakao_student_display_parent"
        ),
        sa.UniqueConstraint(
            "student_id", "revision_number", name="uq_kakao_student_display_number"
        ),
        sa.ForeignKeyConstraint(
            ["student_id", "previous_revision_id"],
            [
                "kakao_student_display_revisions.student_id",
                "kakao_student_display_revisions.display_revision_id",
            ],
            name="fk_kakao_student_display_previous",
            ondelete="RESTRICT",
        ),
    )
    op.create_foreign_key(
        "fk_kakao_student_current",
        "kakao_students",
        "kakao_student_display_revisions",
        ["student_id", "current_display_revision_id"],
        ["student_id", "display_revision_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "kakao_student_commands",
        sa.Column("command_id", sa.String(45), primary_key=True),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("student_id", sa.String(45), nullable=False),
        sa.Column("idempotency_scope", sa.String(96), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("result_display_revision_id", sa.String(48), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$'", name="ck_kakao_student_command_id"
        ),
        sa.CheckConstraint(
            "action IN ('CREATE','RENAME','RETIRE')", name="ck_kakao_student_command_action"
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_student_command_request",
        ),
        sa.UniqueConstraint(
            "owner_operator_id",
            "idempotency_scope",
            "idempotency_key",
            name="uq_kakao_student_command_replay",
        ),
        sa.UniqueConstraint(
            "student_id", "result_display_revision_id", name="uq_kakao_student_command_result"
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "student_id"],
            ["kakao_students.owner_operator_id", "kakao_students.student_id"],
            name="fk_kakao_student_command_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id", "result_display_revision_id"],
            [
                "kakao_student_display_revisions.student_id",
                "kakao_student_display_revisions.display_revision_id",
            ],
            name="fk_kakao_student_command_result",
            ondelete="RESTRICT",
        ),
    )
    for table, trigger in (
        ("kakao_student_display_revisions", "trg_kakao_student_display_immutable"),
        ("kakao_student_commands", "trg_kakao_student_command_immutable"),
    ):
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
        )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM kakao_students)")):
        raise RuntimeError("KAKAO_STUDENT_HISTORY_PRESENT")
    op.drop_table("kakao_student_commands")
    op.drop_constraint("fk_kakao_student_current", "kakao_students", type_="foreignkey")
    op.drop_table("kakao_student_display_revisions")
    op.drop_table("kakao_students")
