"""Add owner-scoped logical deletion without removing immutable chat evidence.

Revision ID: 20261026_0059
Revises: 20261019_0058
Create Date: 2026-10-26 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261026_0059"
down_revision: str | None = "20261019_0058"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE general_chat_conversations
      ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE,
      ADD COLUMN delete_key_sha256 VARCHAR(71),
      ADD COLUMN delete_request_sha256 VARCHAR(71),
      ADD CONSTRAINT ck_chat_conversation_deletion CHECK (
        (deleted_at IS NULL AND delete_key_sha256 IS NULL AND delete_request_sha256 IS NULL)
        OR (deleted_at IS NOT NULL AND
            delete_key_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
            delete_request_sha256 ~ '^sha256:[0-9a-f]{64}$')
      )
    """)
    op.execute("""
    CREATE FUNCTION protect_general_chat_deletion() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.deleted_at IS NOT NULL THEN
            RAISE EXCEPTION 'deleted chat conversation is immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.deleted_at IS NOT NULL THEN
            IF NEW.title IS DISTINCT FROM OLD.title
               OR NEW.next_sequence IS DISTINCT FROM OLD.next_sequence
               OR NEW.resource_version <> OLD.resource_version + 1
               OR NEW.updated_at IS DISTINCT FROM NEW.deleted_at
               OR EXISTS (
                   SELECT 1 FROM general_chat_turns
                   WHERE conversation_id = OLD.conversation_id
                     AND state IN ('QUEUED','CLAIMED','RUNNING','COMMITTING')
               ) THEN
                RAISE EXCEPTION 'chat deletion requires a terminal conversation'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER general_chat_deletion_guard
    BEFORE UPDATE ON general_chat_conversations
    FOR EACH ROW EXECUTE FUNCTION protect_general_chat_deletion()
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM general_chat_conversations WHERE deleted_at IS NOT NULL) THEN
            RAISE EXCEPTION 'cannot expose deleted chat conversations on downgrade'
                USING ERRCODE = '23514';
        END IF;
    END $$
    """)
    op.execute("DROP TRIGGER general_chat_deletion_guard ON general_chat_conversations")
    op.execute("DROP FUNCTION protect_general_chat_deletion()")
    op.execute("""
    ALTER TABLE general_chat_conversations
      DROP CONSTRAINT ck_chat_conversation_deletion,
      DROP COLUMN delete_request_sha256,
      DROP COLUMN delete_key_sha256,
      DROP COLUMN deleted_at
    """)
