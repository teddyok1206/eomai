"""Collection intentions and ordered room checkpoints, not automatic activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0091"
down_revision = "20261116_0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kakao_collection_runs",
        sa.Column("run_id", sa.String(41), primary_key=True),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("anchor_room_id", sa.String(42), nullable=False),
        sa.Column("capability_revision_id", sa.String(51), nullable=False),
        sa.Column("policy_revision_id", sa.String(47), nullable=False),
        sa.Column("policy_sha256", sa.String(71), nullable=False),
        sa.Column("adapter_release_sha256", sa.String(71), nullable=False),
        sa.Column("accepted_binding_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("stop_target", sa.String(16)),
        sa.Column("resource_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "owner_operator_id",
            "source_binding_id",
            "idempotency_key",
            name="uq_kakao_collection_replay",
        ),
        sa.UniqueConstraint(
            "owner_operator_id", "source_binding_id", "run_id", name="uq_kakao_collection_owner"
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "anchor_room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_collection_room",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_binding_id", "capability_revision_id"],
            [
                "kakao_capability_acceptances.source_binding_id",
                "kakao_capability_acceptances.capability_revision_id",
            ],
            name="fk_kakao_collection_capability",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_binding_id", "policy_revision_id"],
            [
                "kakao_collection_policy_revisions.source_binding_id",
                "kakao_collection_policy_revisions.policy_revision_id",
            ],
            name="fk_kakao_collection_policy",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "run_id ~ '^kakaorun_[0-9a-f]{32}$' AND "
            "idempotency_key ~ '^[!-~]{16,128}$' AND "
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "policy_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "adapter_release_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_collection_values",
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED','INVENTORY','COLLECTING','RECONCILING','PAUSING','PAUSED',"
            "'AUTH_REQUIRED','COMPLETED','PARTIAL','FAILED','CANCELLED')",
            name="ck_kakao_collection_state",
        ),
        sa.CheckConstraint(
            "resource_version BETWEEN 1 AND 2147483647 AND "
            "accepted_binding_version BETWEEN 1 AND 2147483647 AND updated_at >= created_at",
            name="ck_kakao_collection_version",
        ),
        sa.CheckConstraint(
            "(state = 'PAUSING' AND stop_target IS NOT NULL "
            "AND stop_target IN ('PAUSED','CANCELLED')) OR "
            "(state <> 'PAUSING' AND stop_target IS NULL)",
            name="ck_kakao_collection_stop_target",
        ),
    )
    op.create_index(
        "uq_kakao_collection_active_binding",
        "kakao_collection_runs",
        ["source_binding_id"],
        unique=True,
        postgresql_where=sa.text("state NOT IN ('COMPLETED','PARTIAL','FAILED','CANCELLED')"),
    )
    op.create_index(
        "ix_kakao_collection_pending", "kakao_collection_runs", ["state", "created_at", "run_id"]
    )
    op.create_table(
        "kakao_collection_tasks",
        sa.Column("task_id", sa.String(42), primary_key=True),
        sa.Column("run_id", sa.String(41), nullable=False),
        sa.Column("owner_operator_id", sa.String(41), nullable=False),
        sa.Column("source_binding_id", sa.String(45), nullable=False),
        sa.Column("room_id", sa.String(42), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_kakao_collection_task_order"),
        sa.UniqueConstraint("run_id", "room_id", name="uq_kakao_collection_task_room"),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "run_id"],
            [
                "kakao_collection_runs.owner_operator_id",
                "kakao_collection_runs.source_binding_id",
                "kakao_collection_runs.run_id",
            ],
            name="fk_kakao_collection_task_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_collection_task_room",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "task_id ~ '^kakaotask_[0-9a-f]{32}$' AND ordinal BETWEEN 1 AND 10000",
            name="ck_kakao_collection_task_values",
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED','RUNNING','LOCAL_ACCEPTED','COMPLETED','PARTIAL',"
            "'FAILED','CANCELLED')",
            name="ck_kakao_collection_task_state",
        ),
    )
    op.create_index(
        "ix_kakao_collection_task_claim", "kakao_collection_tasks", ["run_id", "state", "ordinal"]
    )
    op.execute("""
        CREATE FUNCTION protect_kakao_collection_run() RETURNS trigger LANGUAGE plpgsql AS $$
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
             (to_jsonb(NEW) - ARRAY['state','stop_target','resource_version','updated_at'])
               IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['state','stop_target','resource_version','updated_at']) OR
             NEW.resource_version <> OLD.resource_version + 1 OR
             NEW.updated_at < OLD.updated_at THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_INTENT_IMMUTABLE';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER protect_kakao_collection_run
          BEFORE INSERT OR UPDATE OR DELETE ON kakao_collection_runs
          FOR EACH ROW EXECUTE FUNCTION protect_kakao_collection_run();
        CREATE FUNCTION protect_kakao_collection_task() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.state <> 'QUEUED' THEN
              RAISE EXCEPTION 'KAKAO_COLLECTION_INITIAL_STATE_INVALID';
            END IF;
            RETURN NEW;
          END IF;
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_HISTORY_IMMUTABLE';
          END IF;
          IF OLD.state IN ('COMPLETED','PARTIAL','FAILED','CANCELLED') OR
             (to_jsonb(NEW) - 'state') IS DISTINCT FROM (to_jsonb(OLD) - 'state') THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_TASK_IMMUTABLE';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER protect_kakao_collection_task
          BEFORE INSERT OR UPDATE OR DELETE ON kakao_collection_tasks
          FOR EACH ROW EXECUTE FUNCTION protect_kakao_collection_task();
        CREATE FUNCTION require_kakao_collection_initial_task() RETURNS trigger
          LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM kakao_collection_tasks WHERE run_id = NEW.run_id
                         AND ordinal = 1 AND room_id = NEW.anchor_room_id) THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_INITIAL_TASK_MISSING';
          END IF;
          RETURN NEW;
        END $$;
        CREATE CONSTRAINT TRIGGER require_kakao_collection_initial_task
          AFTER INSERT ON kakao_collection_runs DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION require_kakao_collection_initial_task();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER require_kakao_collection_initial_task ON kakao_collection_runs")
    op.execute("DROP FUNCTION require_kakao_collection_initial_task()")
    op.drop_table("kakao_collection_tasks")
    op.drop_table("kakao_collection_runs")
    op.execute("DROP FUNCTION protect_kakao_collection_task()")
    op.execute("DROP FUNCTION protect_kakao_collection_run()")
