"""Admitted owner-private rooms and immutable student mappings; no provider activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0082"
down_revision = "20261116_0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kakao_rooms",
        sa.Column("room_id", sa.String(42), primary_key=True),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("identity_level", sa.String(24), nullable=False),
        sa.Column("source_identity_sha256", sa.String(71), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("current_mapping_revision_id", sa.String(48), nullable=False),
        sa.Column("evidence_artifact_id", sa.String(41), nullable=False),
        sa.Column("evidence_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("evidence_sha256", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("room_id ~ '^kakaoroom_[0-9a-f]{32}$'", name="ck_kakao_room_id"),
        sa.CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_kakao_room_state"),
        sa.CheckConstraint(
            "resource_version BETWEEN 1 AND 2147483647", name="ck_kakao_room_version"
        ),
        sa.CheckConstraint(
            "identity_level IN ('SOURCE_VERIFIED','MANUAL_CONFIRMED')",
            name="ck_kakao_room_identity_level",
        ),
        sa.CheckConstraint(
            "source_identity_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_room_hashes",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0 AND display_name !~ '[[:cntrl:]]'",
            name="ck_kakao_room_name",
        ),
        sa.UniqueConstraint(
            "owner_operator_id", "source_binding_id", "room_id", name="uq_kakao_room_owner"
        ),
        sa.UniqueConstraint(
            "source_binding_id",
            "identity_level",
            "source_identity_sha256",
            name="uq_kakao_room_source_identity",
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_room_binding_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_artifact_id", "evidence_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_room_evidence",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "kakao_room_mapping_revisions",
        sa.Column("mapping_revision_id", sa.String(48), primary_key=True),
        sa.Column("room_id", sa.String(42), nullable=False),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("previous_revision_id", sa.String(48)),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("student_id", sa.String(45)),
        sa.Column("student_display_revision_id", sa.String(48)),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("sha256", sa.String(71), nullable=False),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("request_sha256", sa.String(71)),
        sa.Column(
            "created_by",
            sa.String(41),
            sa.ForeignKey("operators.operator_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mapping_revision_id ~ '^kakaomappingrev_[0-9a-f]{32}$'", name="ck_kakao_mapping_id"
        ),
        sa.CheckConstraint(
            "(revision_number = 1 AND previous_revision_id IS NULL "
            "AND idempotency_key IS NULL AND request_sha256 IS NULL) OR "
            "(revision_number > 1 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> mapping_revision_id "
            "AND idempotency_key IS NOT NULL AND request_sha256 IS NOT NULL)",
            name="ck_kakao_mapping_lineage",
        ),
        sa.CheckConstraint(
            "(state = 'MAPPED' AND student_id IS NOT NULL "
            "AND student_display_revision_id IS NOT NULL) OR "
            "(state = 'UNMAPPED' AND student_id IS NULL AND student_display_revision_id IS NULL)",
            name="ck_kakao_mapping_state",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND (request_sha256 IS NULL OR request_sha256 ~ '^sha256:[0-9a-f]{64}$') "
            "AND (idempotency_key IS NULL OR idempotency_key ~ '^[!-~]{16,128}$')",
            name="ck_kakao_mapping_hashes",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0 AND reason !~ '[[:cntrl:]]'", name="ck_kakao_mapping_reason"
        ),
        sa.UniqueConstraint("room_id", "mapping_revision_id", name="uq_kakao_mapping_room"),
        sa.UniqueConstraint("room_id", "revision_number", name="uq_kakao_mapping_number"),
        sa.UniqueConstraint(
            "owner_operator_id", "room_id", "idempotency_key", name="uq_kakao_mapping_replay"
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_mapping_room_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["room_id", "previous_revision_id"],
            [
                "kakao_room_mapping_revisions.room_id",
                "kakao_room_mapping_revisions.mapping_revision_id",
            ],
            name="fk_kakao_mapping_previous",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "student_id"],
            ["kakao_students.owner_operator_id", "kakao_students.student_id"],
            name="fk_kakao_mapping_student_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["student_id", "student_display_revision_id"],
            [
                "kakao_student_display_revisions.student_id",
                "kakao_student_display_revisions.display_revision_id",
            ],
            name="fk_kakao_mapping_student_display",
            ondelete="RESTRICT",
        ),
    )
    op.create_foreign_key(
        "fk_kakao_room_current_mapping",
        "kakao_rooms",
        "kakao_room_mapping_revisions",
        ["room_id", "current_mapping_revision_id"],
        ["room_id", "mapping_revision_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "kakao_room_admissions",
        sa.Column("command_id", sa.String(45), primary_key=True),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("room_id", sa.String(42), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("evidence_artifact_id", sa.String(41), nullable=False),
        sa.Column("evidence_artifact_revision_id", sa.String(36), nullable=False),
        sa.Column("evidence_sha256", sa.String(71), nullable=False),
        sa.Column("result_mapping_revision_id", sa.String(48), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$'", name="ck_kakao_room_admission_id"
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_room_admission_hashes",
        ),
        sa.UniqueConstraint(
            "owner_operator_id",
            "source_binding_id",
            "idempotency_key",
            name="uq_kakao_room_admission_replay",
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_room_admission_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["room_id", "result_mapping_revision_id"],
            [
                "kakao_room_mapping_revisions.room_id",
                "kakao_room_mapping_revisions.mapping_revision_id",
            ],
            name="fk_kakao_room_admission_mapping",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_artifact_id", "evidence_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_room_admission_evidence",
            ondelete="RESTRICT",
        ),
    )
    for table, trigger in (
        ("kakao_room_mapping_revisions", "trg_kakao_room_mapping_immutable"),
        ("kakao_room_admissions", "trg_kakao_room_admission_immutable"),
    ):
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
        )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM kakao_rooms)")):
        raise RuntimeError("KAKAO_ROOM_HISTORY_PRESENT")
    op.drop_table("kakao_room_admissions")
    op.drop_constraint("fk_kakao_room_current_mapping", "kakao_rooms", type_="foreignkey")
    op.drop_table("kakao_room_mapping_revisions")
    op.drop_table("kakao_rooms")
