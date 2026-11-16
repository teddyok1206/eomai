"""Shared profile gate and immutable collection browser lifetimes, without activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0092"
down_revision = "20261116_0091"
branch_labels = None
depends_on = None

_RUN_GUARD = """
CREATE OR REPLACE FUNCTION protect_kakao_collection_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.state <> 'QUEUED' OR NEW.resource_version <> 1 OR
       NEW.created_at <> NEW.updated_at THEN
      RAISE EXCEPTION 'KAKAO_COLLECTION_INITIAL_STATE_INVALID';
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'KAKAO_COLLECTION_HISTORY_IMMUTABLE';
  END IF;
  IF OLD.state IN ('COMPLETED','PARTIAL','FAILED','CANCELLED') OR
     (to_jsonb(NEW) - ARRAY['state','stop_target','resource_version','updated_at'@browser@])
       IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['state','stop_target','resource_version','updated_at'@browser@]) OR
     NEW.resource_version <> OLD.resource_version + 1 OR NEW.updated_at < OLD.updated_at THEN
    RAISE EXCEPTION 'KAKAO_COLLECTION_INTENT_IMMUTABLE';
  END IF;
  RETURN NEW;
END $$;
"""

_MANUAL_IDENTITY_GUARD = """
CREATE OR REPLACE FUNCTION guard_kakao_manual_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'kakao_profile_runtime' THEN
    IF (NEW.slot_key, NEW.profile_id, NEW.owner_operator_id, @new_binding@ NEW.created_at)
       IS DISTINCT FROM
       (OLD.slot_key, OLD.profile_id, OLD.owner_operator_id, @old_binding@ OLD.created_at) THEN
      RAISE EXCEPTION 'immutable Kakao profile assignment';
    END IF;
    @switch_guard@
  ELSIF (NEW.lease_id, NEW.owner_operator_id, NEW.source_binding_id, NEW.profile_id,
         NEW.identity_session_id, NEW.browser_run_id, NEW.command_sha256, NEW.dispatch_boot_id,
         NEW.fence_epoch, NEW.gateway_epoch, NEW.created_at, NEW.absolute_expires_at)
      IS DISTINCT FROM
        (OLD.lease_id, OLD.owner_operator_id, OLD.source_binding_id, OLD.profile_id,
         OLD.identity_session_id, OLD.browser_run_id, OLD.command_sha256, OLD.dispatch_boot_id,
         OLD.fence_epoch, OLD.gateway_epoch, OLD.created_at, OLD.absolute_expires_at) THEN
    RAISE EXCEPTION 'immutable Kakao manual identity';
  END IF;
  RETURN NEW;
END $$;
"""

_BINDING_SWITCH_GUARD = """
    IF NEW.source_binding_id IS DISTINCT FROM OLD.source_binding_id AND (
       OLD.mode <> 'STOPPED' OR OLD.current_lease_id IS NOT NULL OR
       OLD.current_collection_browser_run_id IS NOT NULL OR
       NEW.fence_epoch <> OLD.fence_epoch + 1 OR NEW.mode NOT IN ('MANUAL','AUTO')) THEN
      RAISE EXCEPTION 'KAKAO_PROFILE_BINDING_SWITCH_REQUIRES_CLOSED_FENCE';
    END IF;
"""


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_kakao_profile_operator", "kakao_profile_runtime", ["owner_operator_id", "profile_id"]
    )
    op.drop_constraint("fk_kakao_manual_profile_owner", "kakao_manual_sessions", type_="foreignkey")
    op.create_foreign_key(
        "fk_kakao_manual_profile_owner",
        "kakao_manual_sessions",
        "kakao_profile_runtime",
        ["owner_operator_id", "profile_id"],
        ["owner_operator_id", "profile_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_kakao_manual_binding_owner",
        "kakao_manual_sessions",
        "kakao_channel_bindings",
        ["owner_operator_id", "source_binding_id"],
        ["owner_operator_id", "source_binding_id"],
        ondelete="RESTRICT",
    )
    op.execute("""
        CREATE TABLE kakao_collection_browsers (
        browser_run_id VARCHAR(48) NOT NULL,
        run_id VARCHAR(41) NOT NULL,
        owner_operator_id VARCHAR(41) NOT NULL,
        source_binding_id VARCHAR(45) NOT NULL,
        profile_id VARCHAR(45) NOT NULL,
        fence_epoch INTEGER NOT NULL,
        epoch_number INTEGER NOT NULL,
        command_sha256 VARCHAR(71) NOT NULL,
        dispatch_boot_id VARCHAR(36) NOT NULL,
        phase VARCHAR(16) NOT NULL,
        resource_version INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        closed_at TIMESTAMP WITH TIME ZONE,
        close_kind VARCHAR(32),
        browser_invocation_id VARCHAR(32),
        browser_pid INTEGER,
        browser_monotonic_us BIGINT,
        browser_observed_at TIMESTAMP WITH TIME ZONE,
        last_error VARCHAR(32),
        PRIMARY KEY (browser_run_id),
        CONSTRAINT fk_kakao_collection_browser_run FOREIGN KEY(owner_operator_id,
        source_binding_id, run_id) REFERENCES kakao_collection_runs (owner_operator_id,
        source_binding_id, run_id) ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_collection_browser_profile FOREIGN KEY(owner_operator_id,
        profile_id) REFERENCES kakao_profile_runtime (owner_operator_id, profile_id) ON DELETE
        RESTRICT,
        CONSTRAINT uq_kakao_collection_browser_run UNIQUE (run_id, browser_run_id),
        CONSTRAINT uq_kakao_collection_browser_pointer UNIQUE (profile_id, browser_run_id,
        fence_epoch),
        CONSTRAINT uq_kakao_collection_browser_fence UNIQUE (profile_id, fence_epoch),
        CONSTRAINT uq_kakao_collection_browser_epoch UNIQUE (run_id, epoch_number),
        CONSTRAINT ck_kakao_collection_browser_values CHECK (browser_run_id ~
        '^kakaobrowserrun_[0-9a-f]{32}$' AND command_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
        dispatch_boot_id ~ '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$'),
        CONSTRAINT ck_kakao_collection_browser_versions CHECK (fence_epoch BETWEEN 1 AND
        2147483647 AND epoch_number BETWEEN 1 AND 2147483647 AND resource_version BETWEEN 1 AND
        2147483647),
        CONSTRAINT ck_kakao_collection_browser_phase CHECK (phase IN
        ('PREPARING','RUNNING','STOPPING','CLOSED')),
        CONSTRAINT ck_kakao_collection_browser_closed CHECK ((phase = 'CLOSED') = (closed_at IS
        NOT NULL) AND (phase = 'CLOSED') = (close_kind IS NOT NULL) AND (closed_at IS NULL OR
        closed_at >= created_at)),
        CONSTRAINT ck_kakao_collection_browser_closure CHECK (close_kind IS NULL OR close_kind
        IN ('STOPPED','PRE_READY_FAILED','REBOOT_UNCLEAN')),
        CONSTRAINT ck_kakao_collection_browser_error CHECK (last_error IS NULL OR last_error IN
        ('START_FAILED','RUNTIME_LOST','OWNER_UNAVAILABLE','REBOOT_UNCLEAN')),
        CONSTRAINT ck_kakao_collection_browser_handle CHECK ((browser_invocation_id IS NULL AND
        browser_pid IS NULL AND browser_monotonic_us IS NULL AND browser_observed_at IS NULL) OR
        (browser_invocation_id IS NOT NULL AND browser_pid IS NOT NULL AND browser_monotonic_us
        IS NOT NULL AND browser_observed_at IS NOT NULL AND browser_invocation_id ~
        '^[0-9a-f]{32}$' AND browser_pid > 0 AND browser_monotonic_us > 0 AND
        browser_observed_at >= created_at)),
        CONSTRAINT ck_kakao_collection_browser_running CHECK (phase <> 'RUNNING' OR
        browser_invocation_id IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_kakao_collection_browser_open ON kakao_collection_browsers
        (profile_id) WHERE phase <> 'CLOSED'
    """)
    op.add_column(
        "kakao_profile_runtime", sa.Column("current_collection_browser_run_id", sa.String(48))
    )
    op.add_column("kakao_collection_runs", sa.Column("current_browser_run_id", sa.String(48)))
    op.create_foreign_key(
        "fk_kakao_collection_current_browser",
        "kakao_collection_runs",
        "kakao_collection_browsers",
        ["run_id", "current_browser_run_id"],
        ["run_id", "browser_run_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_kakao_profile_current_collection_browser",
        "kakao_profile_runtime",
        "kakao_collection_browsers",
        ["profile_id", "current_collection_browser_run_id", "fence_epoch"],
        ["profile_id", "browser_run_id", "fence_epoch"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.drop_constraint("ck_kakao_profile_stopped", "kakao_profile_runtime", type_="check")
    op.create_check_constraint(
        "ck_kakao_profile_stopped",
        "kakao_profile_runtime",
        "mode <> 'STOPPED' OR "
        "(current_lease_id IS NULL AND current_collection_browser_run_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_kakao_profile_dispatch_owner",
        "kakao_profile_runtime",
        "(current_lease_id IS NULL OR current_collection_browser_run_id IS NULL) AND "
        "(mode <> 'MANUAL' OR current_lease_id IS NOT NULL) AND "
        "(mode <> 'AUTO' OR current_collection_browser_run_id IS NOT NULL)",
    )
    op.execute(_RUN_GUARD.replace("@browser@", ", 'current_browser_run_id'"))
    op.execute(
        _MANUAL_IDENTITY_GUARD.replace("@new_binding@", "")
        .replace("@old_binding@", "")
        .replace("@switch_guard@", _BINDING_SWITCH_GUARD)
    )
    op.execute("""
        CREATE FUNCTION protect_kakao_collection_browser() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.phase <> 'PREPARING' OR NEW.resource_version <> 1 OR
               NEW.browser_invocation_id IS NOT NULL OR NEW.closed_at IS NOT NULL THEN
              RAISE EXCEPTION 'KAKAO_COLLECTION_BROWSER_INITIAL_STATE_INVALID';
            END IF;
            RETURN NEW;
          END IF;
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_BROWSER_IMMUTABLE';
          END IF;
          IF OLD.phase = 'CLOSED' OR NEW.resource_version <> OLD.resource_version + 1 OR
             (to_jsonb(NEW) - ARRAY['phase','resource_version','closed_at','close_kind',
                'browser_invocation_id','browser_pid','browser_monotonic_us',
                'browser_observed_at','last_error']) IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['phase','resource_version','closed_at','close_kind',
                'browser_invocation_id','browser_pid','browser_monotonic_us',
                'browser_observed_at','last_error']) OR
             (OLD.browser_invocation_id IS NOT NULL AND
              ROW(NEW.browser_invocation_id,NEW.browser_pid,NEW.browser_monotonic_us,
                  NEW.browser_observed_at) IS DISTINCT FROM
              ROW(OLD.browser_invocation_id,OLD.browser_pid,OLD.browser_monotonic_us,
                  OLD.browser_observed_at)) OR
             (OLD.last_error IS NOT NULL AND NEW.last_error IS DISTINCT FROM OLD.last_error) OR
             (OLD.phase,NEW.phase) NOT IN (('PREPARING','RUNNING'),('PREPARING','STOPPING'),
                                          ('RUNNING','STOPPING'),('STOPPING','CLOSED')) THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_BROWSER_IMMUTABLE';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER protect_kakao_collection_browser BEFORE INSERT OR UPDATE OR DELETE
          ON kakao_collection_browsers FOR EACH ROW
          EXECUTE FUNCTION protect_kakao_collection_browser();
    """)


def downgrade() -> None:
    # A code rollback is not permission to discard browser history or rewrite old leases.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM kakao_collection_browsers) OR EXISTS (
              SELECT 1 FROM kakao_manual_sessions s JOIN kakao_profile_runtime p
              ON p.profile_id = s.profile_id
              WHERE s.owner_operator_id <> p.owner_operator_id OR
                    s.source_binding_id <> p.source_binding_id) THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_DOWNGRADE_HISTORY_REQUIRES_REVIEW';
          END IF;
        END $$;
    """)
    op.drop_constraint(
        "fk_kakao_collection_current_browser", "kakao_collection_runs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_kakao_profile_current_collection_browser", "kakao_profile_runtime", type_="foreignkey"
    )
    op.execute(_RUN_GUARD.replace("@browser@", ""))
    op.execute(
        _MANUAL_IDENTITY_GUARD.replace("@new_binding@", "NEW.source_binding_id,")
        .replace("@old_binding@", "OLD.source_binding_id,")
        .replace("@switch_guard@", "")
    )
    op.drop_column("kakao_collection_runs", "current_browser_run_id")
    op.drop_constraint("ck_kakao_profile_dispatch_owner", "kakao_profile_runtime", type_="check")
    op.drop_constraint("ck_kakao_profile_stopped", "kakao_profile_runtime", type_="check")
    op.drop_column("kakao_profile_runtime", "current_collection_browser_run_id")
    op.create_check_constraint(
        "ck_kakao_profile_stopped",
        "kakao_profile_runtime",
        "mode <> 'STOPPED' OR current_lease_id IS NULL",
    )
    op.drop_table("kakao_collection_browsers")
    op.execute("DROP FUNCTION protect_kakao_collection_browser()")
    op.drop_constraint("fk_kakao_manual_binding_owner", "kakao_manual_sessions", type_="foreignkey")
    op.drop_constraint("fk_kakao_manual_profile_owner", "kakao_manual_sessions", type_="foreignkey")
    op.create_foreign_key(
        "fk_kakao_manual_profile_owner",
        "kakao_manual_sessions",
        "kakao_profile_runtime",
        ["owner_operator_id", "source_binding_id", "profile_id"],
        ["owner_operator_id", "source_binding_id", "profile_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("uq_kakao_profile_operator", "kakao_profile_runtime", type_="unique")
