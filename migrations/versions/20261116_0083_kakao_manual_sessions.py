"""Bounded private manual-login owner; no provider capability or channel activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0083"
down_revision = "20261116_0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kakao_profile_runtime",
        sa.Column("slot_key", sa.String(16), primary_key=True),
        sa.Column("profile_id", sa.String(45), nullable=False),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("fence_epoch", sa.Integer(), nullable=False),
        sa.Column("gateway_epoch", sa.Integer(), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("current_lease_id", sa.String(49)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("slot_key = 'primary'", name="ck_kakao_profile_slot"),
        sa.CheckConstraint(
            "profile_id ~ '^kakaoprofile_[0-9a-f]{32}$'", name="ck_kakao_profile_id"
        ),
        sa.CheckConstraint(
            "mode IN ('STOPPED','MANUAL','AUTO','PAUSING','ERROR')", name="ck_kakao_profile_mode"
        ),
        sa.CheckConstraint(
            "fence_epoch >= 0 AND gateway_epoch >= 0 AND resource_version >= 1",
            name="ck_kakao_profile_versions",
        ),
        sa.CheckConstraint(
            "mode <> 'STOPPED' OR current_lease_id IS NULL", name="ck_kakao_profile_stopped"
        ),
        sa.UniqueConstraint("profile_id", name="uq_kakao_profile_id"),
        sa.UniqueConstraint(
            "owner_operator_id", "source_binding_id", "profile_id", name="uq_kakao_profile_owner"
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_profile_owner",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "kakao_manual_sessions",
        sa.Column("lease_id", sa.String(49), primary_key=True),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("profile_id", sa.String(45), nullable=False),
        sa.Column(
            "identity_session_id",
            sa.String(43),
            sa.ForeignKey("api_sessions.api_session_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("browser_run_id", sa.String(48), nullable=False),
        sa.Column("command_sha256", sa.String(71), nullable=False),
        sa.Column("dispatch_boot_id", sa.String(36), nullable=False),
        sa.Column("fence_epoch", sa.Integer(), nullable=False),
        sa.Column("gateway_epoch", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("grant_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(32)),
        sa.Column("ended_reason", sa.String(32)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("browser_invocation_id", sa.String(32)),
        sa.Column("browser_pid", sa.Integer()),
        sa.Column("browser_monotonic_us", sa.BigInteger()),
        sa.Column("browser_observed_at", sa.DateTime(timezone=True)),
        sa.Column("gateway_invocation_id", sa.String(32)),
        sa.CheckConstraint(
            "lease_id ~ '^kakaoremotelease_[0-9a-f]{32}$'", name="ck_kakao_manual_id"
        ),
        sa.CheckConstraint("command_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_kakao_manual_hash"),
        sa.CheckConstraint(
            "phase IN ('PREPARING','ACTIVE','STOPPING','ENDED','ERROR')",
            name="ck_kakao_manual_phase",
        ),
        sa.CheckConstraint(
            "resource_version >= 1 AND fence_epoch >= 1 "
            "AND gateway_epoch >= 1 AND grant_revision >= 0",
            name="ck_kakao_manual_versions",
        ),
        sa.CheckConstraint(
            "absolute_expires_at > created_at "
            "AND absolute_expires_at <= created_at + interval '20 minutes'",
            name="ck_kakao_manual_absolute",
        ),
        sa.CheckConstraint(
            "(grant_revision = 0 AND authorized_at IS NULL AND expires_at IS NULL) OR "
            "(grant_revision > 0 AND authorized_at IS NOT NULL AND expires_at IS NOT NULL "
            "AND authorized_at >= created_at AND expires_at > authorized_at "
            "AND expires_at <= authorized_at + interval '30 seconds' "
            "AND expires_at <= absolute_expires_at)",
            name="ck_kakao_manual_grant",
        ),
        sa.CheckConstraint(
            "(phase = 'ENDED') = (closed_at IS NOT NULL)", name="ck_kakao_manual_closed"
        ),
        sa.CheckConstraint(
            "(browser_invocation_id IS NULL AND browser_pid IS NULL "
            "AND browser_monotonic_us IS NULL AND browser_observed_at IS NULL) OR "
            "(browser_invocation_id IS NOT NULL AND browser_pid IS NOT NULL "
            "AND browser_monotonic_us IS NOT NULL AND browser_observed_at IS NOT NULL "
            "AND browser_pid > 0 AND browser_monotonic_us > 0 "
            "AND browser_observed_at >= created_at)",
            name="ck_kakao_manual_browser",
        ),
        sa.CheckConstraint(
            "phase <> 'ACTIVE' OR (grant_revision > 0 "
            "AND browser_invocation_id IS NOT NULL AND gateway_invocation_id IS NOT NULL)",
            name="ck_kakao_manual_active",
        ),
        sa.UniqueConstraint("profile_id", "lease_id", name="uq_kakao_manual_profile"),
        sa.UniqueConstraint("owner_operator_id", "lease_id", name="uq_kakao_manual_owner"),
        sa.UniqueConstraint("profile_id", "fence_epoch", name="uq_kakao_manual_fence"),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "profile_id"],
            [
                "kakao_profile_runtime.owner_operator_id",
                "kakao_profile_runtime.source_binding_id",
                "kakao_profile_runtime.profile_id",
            ],
            name="fk_kakao_manual_profile_owner",
            ondelete="RESTRICT",
        ),
    )
    op.create_foreign_key(
        "fk_kakao_profile_current_lease",
        "kakao_profile_runtime",
        "kakao_manual_sessions",
        ["profile_id", "current_lease_id"],
        ["profile_id", "lease_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "kakao_remote_commands",
        sa.Column("command_id", sa.String(45), primary_key=True),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("lease_id", sa.String(49), nullable=False),
        sa.Column("idempotency_scope", sa.String(96), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("result_phase", sa.String(16), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=False),
        sa.Column("result_grant_revision", sa.Integer(), nullable=False),
        sa.Column("result_expires_at", sa.DateTime(timezone=True)),
        sa.Column("result_ready", sa.Boolean(), nullable=False),
        sa.Column("result_error", sa.String(32)),
        sa.Column("result_ended_reason", sa.String(32)),
        sa.Column("result_closed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('START','RENEW','END')", name="ck_kakao_remote_command_action"
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_remote_command_request",
        ),
        sa.UniqueConstraint(
            "owner_operator_id",
            "idempotency_scope",
            "idempotency_key",
            name="uq_kakao_remote_command_replay",
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "lease_id"],
            ["kakao_manual_sessions.owner_operator_id", "kakao_manual_sessions.lease_id"],
            name="fk_kakao_remote_command_owner",
            ondelete="RESTRICT",
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_kakao_remote_commands_immutable BEFORE UPDATE OR DELETE "
        "ON kakao_remote_commands FOR EACH ROW "
        "EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
    )
    # Protect immutable owner/dispatch fields even from accidental whole-row updates.
    op.execute("""
        CREATE FUNCTION guard_kakao_manual_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME = 'kakao_profile_runtime' THEN
            IF (NEW.slot_key, NEW.profile_id, NEW.owner_operator_id,
                NEW.source_binding_id, NEW.created_at)
               IS DISTINCT FROM (OLD.slot_key, OLD.profile_id, OLD.owner_operator_id,
                OLD.source_binding_id, OLD.created_at) THEN
              RAISE EXCEPTION 'immutable Kakao profile assignment';
            END IF;
          ELSIF (NEW.lease_id, NEW.owner_operator_id, NEW.source_binding_id, NEW.profile_id,
                 NEW.identity_session_id, NEW.browser_run_id,
                 NEW.command_sha256, NEW.dispatch_boot_id,
                 NEW.fence_epoch, NEW.gateway_epoch, NEW.created_at, NEW.absolute_expires_at)
              IS DISTINCT FROM (OLD.lease_id, OLD.owner_operator_id,
                 OLD.source_binding_id, OLD.profile_id, OLD.identity_session_id, OLD.browser_run_id,
                 OLD.command_sha256, OLD.dispatch_boot_id,
                 OLD.fence_epoch, OLD.gateway_epoch, OLD.created_at, OLD.absolute_expires_at) THEN
            RAISE EXCEPTION 'immutable Kakao manual identity';
          END IF;
          RETURN NEW;
        END $$
    """)
    for table in ("kakao_profile_runtime", "kakao_manual_sessions"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_identity BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION guard_kakao_manual_identity()"
        )


def downgrade() -> None:
    op.drop_table("kakao_remote_commands")
    op.drop_constraint(
        "fk_kakao_profile_current_lease", "kakao_profile_runtime", type_="foreignkey"
    )
    op.drop_table("kakao_manual_sessions")
    op.drop_table("kakao_profile_runtime")
    op.execute("DROP FUNCTION guard_kakao_manual_identity()")
