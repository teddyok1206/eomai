"""Preserve the first browser observation independently of later lease checks."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0097"
down_revision = "20261117_0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL on historical rows is deliberate: latest observation is not proof of first readiness.
    op.add_column(
        "kakao_manual_sessions",
        sa.Column("browser_first_observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_kakao_manual_first_browser_observation",
        "kakao_manual_sessions",
        "browser_first_observed_at IS NULL OR (browser_invocation_id IS NOT NULL "
        "AND browser_first_observed_at >= created_at "
        "AND browser_first_observed_at <= browser_observed_at)",
    )
    op.execute("""
      CREATE FUNCTION guard_kakao_first_browser_observation() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.browser_first_observed_at IS DISTINCT FROM OLD.browser_first_observed_at THEN
          IF OLD.browser_first_observed_at IS NOT NULL OR OLD.phase <> 'PREPARING'
            OR OLD.browser_invocation_id IS NOT NULL OR NEW.browser_invocation_id IS NULL
            OR NEW.browser_first_observed_at IS NULL THEN
            RAISE EXCEPTION 'KAKAO_MANUAL_FIRST_OBSERVATION_IMMUTABLE';
          END IF;
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER trg_kakao_first_browser_observation BEFORE UPDATE ON kakao_manual_sessions
        FOR EACH ROW EXECUTE FUNCTION guard_kakao_first_browser_observation();
    """)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM kakao_manual_sessions WHERE browser_first_observed_at IS NOT NULL)
      THEN RAISE EXCEPTION 'KAKAO_MANUAL_FIRST_OBSERVATION_HISTORY_REQUIRES_REVIEW'; END IF;
      END $$;""")
    op.execute("DROP TRIGGER trg_kakao_first_browser_observation ON kakao_manual_sessions;")
    op.execute("DROP FUNCTION guard_kakao_first_browser_observation();")
    op.drop_constraint(
        "ck_kakao_manual_first_browser_observation", "kakao_manual_sessions", type_="check"
    )
    op.drop_column("kakao_manual_sessions", "browser_first_observed_at")
