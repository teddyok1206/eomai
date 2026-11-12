"""Small administrator chat-model revisions, not a new execution queue."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261112_0079"
down_revision = "20261112_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "general_chat_model_setting_revisions",
        sa.Column("revision_id", sa.String(45), primary_key=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(71), nullable=False),
        sa.Column("request_key_sha256", sa.String(71), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("canonical_document", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("revision_number", name="uq_chat_model_revision_number"),
        sa.UniqueConstraint("request_key_sha256", name="uq_chat_model_request_key"),
        sa.CheckConstraint("revision_number >= 1", name="ck_chat_model_revision_number"),
        sa.CheckConstraint(
            "revision_id ~ '^chatmodelrev_[0-9a-f]{32}$'", name="ck_chat_model_revision_id"
        ),
    )
    op.create_table(
        "general_chat_model_settings",
        sa.Column("settings_id", sa.String(12), primary_key=True),
        sa.Column(
            "current_revision_id",
            sa.String(45),
            sa.ForeignKey("general_chat_model_setting_revisions.revision_id", ondelete="RESTRICT"),
        ),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("settings_id = 'general-chat'", name="ck_chat_model_singleton"),
        sa.CheckConstraint(
            "resource_version >= 1 AND ((resource_version = 1 AND current_revision_id IS NULL) "
            "OR (resource_version > 1 AND current_revision_id IS NOT NULL))",
            name="ck_chat_model_current",
        ),
    )
    op.execute(
        "INSERT INTO general_chat_model_settings(settings_id,resource_version) "
        "VALUES ('general-chat',1)"
    )
    op.execute(
        "CREATE TRIGGER trg_chat_model_revision_immutable BEFORE UPDATE OR DELETE "
        "ON general_chat_model_setting_revisions FOR EACH ROW EXECUTE FUNCTION "
        "reject_control_plane_immutable_mutation()"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM general_chat_model_setting_revisions)")
    ):
        raise RuntimeError("CHAT_MODEL_SETTINGS_HISTORY_EXISTS")
    op.drop_table("general_chat_model_settings")
    op.drop_table("general_chat_model_setting_revisions")
