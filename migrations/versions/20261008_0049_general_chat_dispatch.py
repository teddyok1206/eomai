"""Pin canonical general-chat execution provenance without rewriting old history.

Revision ID: 20261008_0049
Revises: 20261007_0048
Create Date: 2026-10-08 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261008_0049"
down_revision: str | None = "20261007_0048"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE general_chat_turns
        ADD COLUMN dispatch_artifact_id VARCHAR(41),
        ADD COLUMN dispatch_revision_id VARCHAR(36),
        ADD COLUMN dispatch_sha256 VARCHAR(71),
        ADD CONSTRAINT ck_chat_dispatch_pointer CHECK (
            (dispatch_artifact_id IS NULL AND dispatch_revision_id IS NULL
                AND dispatch_sha256 IS NULL) OR
            (dispatch_artifact_id IS NOT NULL AND dispatch_revision_id IS NOT NULL
                AND dispatch_sha256 IS NOT NULL AND
                dispatch_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
                request_artifact_id IS NOT NULL AND
                state IN ('RUNNING','COMMITTING','COMPLETED','FAILED'))),
        ADD CONSTRAINT fk_chat_dispatch_revision FOREIGN KEY (
            dispatch_artifact_id, dispatch_revision_id) REFERENCES
            artifact_revisions (logical_artifact_id, revision_id) ON DELETE RESTRICT
    """)
    op.execute("""
    CREATE FUNCTION protect_general_chat_dispatch() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'UPDATE' AND OLD.dispatch_artifact_id IS NOT NULL AND
            (NEW.dispatch_artifact_id, NEW.dispatch_revision_id, NEW.dispatch_sha256)
            IS DISTINCT FROM
            (OLD.dispatch_artifact_id, OLD.dispatch_revision_id, OLD.dispatch_sha256) THEN
            RAISE EXCEPTION 'chat dispatch identity is immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.state IN ('RUNNING','COMMITTING','COMPLETED') AND
            NEW.dispatch_artifact_id IS NULL AND
            (TG_OP = 'INSERT' OR OLD.state IS DISTINCT FROM NEW.state) THEN
            RAISE EXCEPTION 'new chat execution requires pinned dispatch'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER general_chat_dispatch_guard BEFORE INSERT OR UPDATE
    ON general_chat_turns FOR EACH ROW EXECUTE FUNCTION protect_general_chat_dispatch()
    """)


def downgrade() -> None:
    # A provenance-bearing turn cannot be downgraded into unrecorded history.
    # Empty predecessor/test schemas may still exercise the migration cycle.
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM general_chat_turns WHERE dispatch_artifact_id IS NOT NULL) THEN
            RAISE EXCEPTION 'cannot discard pinned chat dispatch provenance';
        END IF;
    END $$
    """)
    op.execute("DROP TRIGGER general_chat_dispatch_guard ON general_chat_turns")
    op.execute("DROP FUNCTION protect_general_chat_dispatch()")
    op.execute("""
    ALTER TABLE general_chat_turns DROP CONSTRAINT fk_chat_dispatch_revision,
        DROP CONSTRAINT ck_chat_dispatch_pointer,
        DROP COLUMN dispatch_artifact_id,
        DROP COLUMN dispatch_revision_id,
        DROP COLUMN dispatch_sha256
    """)
