"""Queue small validation intents without granting API Job/Artifact ownership.

Revision ID: 20261009_0050
Revises: 20261008_0049
Create Date: 2026-10-09 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261009_0050"
down_revision: str | None = "20261008_0049"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "execution_preset_validations",
        sa.Column("validation_id", sa.String(36), nullable=False),
        sa.Column("preset_revision_id", sa.String(46), nullable=False),
        sa.Column("base_revision_id", sa.String(46), nullable=False),
        sa.Column("requested_by", sa.String(41), nullable=False),
        sa.Column("idempotency_key", sa.String(96), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("canonical_request", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(96), nullable=True),
        sa.CheckConstraint("validation_id ~ '^job_[0-9a-f]{32}$'", name="ck_preset_validation_id"),
        sa.CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_preset_validation_request_hash",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_preset_validation_state",
        ),
        sa.CheckConstraint(
            "((state IN ('PENDING','PROCESSING') AND completed_at IS NULL "
            "AND error_code IS NULL) OR (state = 'SUCCEEDED' AND completed_at IS NOT NULL "
            "AND error_code IS NULL) OR (state = 'FAILED' AND completed_at IS NOT NULL "
            "AND error_code IS NOT NULL)) AND "
            "(completed_at IS NULL OR completed_at >= requested_at)",
            name="ck_preset_validation_lifecycle",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,95}$'",
            name="ck_preset_validation_error_code",
        ),
        sa.CheckConstraint(
            "(jsonb_typeof(canonical_request) = 'object' AND "
            "canonical_request ->> 'schema_version' = 'preset-model-validation-request/1.0' "
            "AND canonical_request ->> 'preset_revision_id' = preset_revision_id "
            "AND canonical_request ->> 'base_revision_id' = base_revision_id "
            "AND canonical_request ->> 'requested_by' = requested_by) IS TRUE "
            "AND octet_length(canonical_request::text) <= 8192",
            name="ck_preset_validation_request_identity",
        ),
        sa.ForeignKeyConstraint(
            ["preset_revision_id"],
            ["execution_preset_revisions.preset_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_revision_id"],
            ["execution_preset_revisions.preset_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["operators.operator_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("validation_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_preset_validation_idempotency"),
    )
    op.create_index(
        "ix_preset_validation_pending",
        "execution_preset_validations",
        ["requested_at", "validation_id"],
        postgresql_where=sa.text("state IN ('PENDING','PROCESSING')"),
    )
    op.execute("""
    CREATE FUNCTION protect_execution_preset_validation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'preset validation history is immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF NEW.state <> 'PENDING' THEN
                RAISE EXCEPTION 'preset validation must begin pending' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END IF;
        IF (to_jsonb(OLD) - ARRAY['state','completed_at','error_code']) IS DISTINCT FROM
            (to_jsonb(NEW) - ARRAY['state','completed_at','error_code']) THEN
            RAISE EXCEPTION 'preset validation request is immutable' USING ERRCODE = '23514';
        END IF;
        IF OLD.state IN ('SUCCEEDED','FAILED') THEN
            RAISE EXCEPTION 'terminal preset validation is immutable' USING ERRCODE = '23514';
        END IF;
        IF NOT (
            (OLD.state = 'PENDING' AND NEW.state IN ('PROCESSING','FAILED')) OR
            (OLD.state = 'PROCESSING' AND NEW.state IN ('PROCESSING','SUCCEEDED','FAILED'))
        ) THEN
            RAISE EXCEPTION 'invalid preset validation transition' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER execution_preset_validation_guard BEFORE INSERT OR UPDATE OR DELETE
    ON execution_preset_validations FOR EACH ROW
    EXECUTE FUNCTION protect_execution_preset_validation()
    """)


def downgrade() -> None:
    # Only an empty disposable schema may discard this immutable command history.
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM execution_preset_validations) THEN
            RAISE EXCEPTION 'cannot discard preset validation history';
        END IF;
    END $$
    """)
    op.execute("DROP TRIGGER execution_preset_validation_guard ON execution_preset_validations")
    op.execute("DROP FUNCTION protect_execution_preset_validation()")
    op.drop_index("ix_preset_validation_pending", table_name="execution_preset_validations")
    op.drop_table("execution_preset_validations")
