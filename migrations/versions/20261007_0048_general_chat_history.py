"""Add pointer-only general-chat receipts and independent dedicated capacity.

Revision ID: 20261007_0048
Revises: 20261007_0047
Create Date: 2026-10-07 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261007_0048"
down_revision: str | None = "20261007_0047"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE general_chat_conversations (
        conversation_id VARCHAR(37) NOT NULL,
        owner_id VARCHAR(41) NOT NULL,
        title VARCHAR(120) NOT NULL,
        resource_version INTEGER NOT NULL,
        next_sequence BIGINT NOT NULL,
        create_key_sha256 VARCHAR(71) NOT NULL,
        create_request_sha256 VARCHAR(71) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (conversation_id),
        CONSTRAINT uq_chat_owner_create UNIQUE (owner_id, create_key_sha256),
        CONSTRAINT ck_chat_conversation_version CHECK (resource_version >= 1
            AND next_sequence >= 1 AND next_sequence % 2 = 1),
        CONSTRAINT ck_chat_conversation_id CHECK (conversation_id ~ '^chat_[0-9a-f]{32}$'),
        CONSTRAINT ck_chat_create_hashes CHECK (create_key_sha256 ~ '^sha256:[0-9a-f]{64}$'
            AND create_request_sha256 ~ '^sha256:[0-9a-f]{64}$'),
        FOREIGN KEY(owner_id) REFERENCES operators (operator_id) ON DELETE RESTRICT
    )
    """)
    op.execute("""
    CREATE INDEX ix_chat_owner_history ON general_chat_conversations (owner_id, updated_at,
            conversation_id)
    """)
    op.execute("""
    CREATE TABLE general_chat_turns (
        turn_id VARCHAR(41) NOT NULL,
        conversation_id VARCHAR(37) NOT NULL,
        user_sequence BIGINT NOT NULL,
        expected_version INTEGER NOT NULL,
        submission_key_sha256 VARCHAR(71) NOT NULL,
        submission_request_sha256 VARCHAR(71) NOT NULL,
        state VARCHAR(16) NOT NULL,
        input_artifact_id VARCHAR(41) NOT NULL,
        input_revision_id VARCHAR(36) NOT NULL,
        input_sha256 VARCHAR(71) NOT NULL,
        request_artifact_id VARCHAR(41),
        request_revision_id VARCHAR(36),
        request_sha256 VARCHAR(71),
        output_artifact_id VARCHAR(41),
        output_revision_id VARCHAR(36),
        output_sha256 VARCHAR(71),
        claim_id VARCHAR(42),
        result_sha256 VARCHAR(71),
        result_status VARCHAR(9),
        failure_code VARCHAR(64),
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        completed_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (turn_id),
        CONSTRAINT uq_chat_turn_intent UNIQUE (conversation_id, submission_key_sha256),
        CONSTRAINT uq_chat_turn_sequence UNIQUE (conversation_id, user_sequence),
        CONSTRAINT ck_chat_turn_id CHECK (turn_id ~ '^chatturn_[0-9a-f]{32}$'),
        CONSTRAINT ck_chat_turn_sequence CHECK (user_sequence >= 1 AND user_sequence % 2 = 1
            AND expected_version >= 1),
        CONSTRAINT ck_chat_turn_state CHECK (state IN
            ('QUEUED','CLAIMED','RUNNING','COMMITTING','COMPLETED','FAILED','CANCELLED')),
        CONSTRAINT ck_chat_turn_hashes CHECK (submission_key_sha256 ~ '^sha256:[0-9a-f]{64}$'
            AND submission_request_sha256 ~ '^sha256:[0-9a-f]{64}$'
            AND input_sha256 ~ '^sha256:[0-9a-f]{64}$'),
        CONSTRAINT ck_chat_turn_claim CHECK ((state IN ('QUEUED','CANCELLED')
            AND claim_id IS NULL) OR (state NOT IN ('QUEUED','CANCELLED')
            AND claim_id IS NOT NULL AND claim_id ~ '^chatclaim_[0-9a-f]{32}$')),
        CONSTRAINT ck_chat_request_pointer CHECK ((request_artifact_id IS NULL
            AND request_revision_id IS NULL AND request_sha256 IS NULL)
            OR (request_artifact_id IS NOT NULL AND request_revision_id IS NOT NULL
            AND request_sha256 IS NOT NULL AND request_sha256 ~ '^sha256:[0-9a-f]{64}$')),
        CONSTRAINT ck_chat_output_pointer CHECK ((output_artifact_id IS NULL
            AND output_revision_id IS NULL AND output_sha256 IS NULL)
            OR (output_artifact_id IS NOT NULL AND output_revision_id IS NOT NULL
            AND output_sha256 IS NOT NULL AND output_sha256 ~ '^sha256:[0-9a-f]{64}$')),
        CONSTRAINT ck_chat_running_request CHECK (
            state NOT IN ('RUNNING','COMMITTING','COMPLETED') OR request_artifact_id IS NOT NULL),
        CONSTRAINT ck_chat_completed_output CHECK ((state <> 'COMPLETED'
            OR output_artifact_id IS NOT NULL) AND (output_artifact_id IS NULL
            OR state IN ('COMPLETED','FAILED'))),
        CONSTRAINT ck_chat_result_hash CHECK ((state NOT IN ('COMMITTING','COMPLETED')
            OR result_sha256 IS NOT NULL) AND (result_sha256 IS NULL
            OR state IN ('COMMITTING','COMPLETED','FAILED'))),
        CONSTRAINT ck_chat_result_format CHECK (result_sha256 IS NULL
            OR result_sha256 ~ '^sha256:[0-9a-f]{64}$'),
        CONSTRAINT ck_chat_failure CHECK (
            (state = 'FAILED' OR (state = 'COMMITTING' AND
            COALESCE(result_status = 'FAILED', false))) = (failure_code IS NOT NULL)),
        CONSTRAINT ck_chat_result_status CHECK (
            (result_status IS NULL) = (result_sha256 IS NULL) AND
            (result_status IS NULL OR result_status IN ('SUCCEEDED','FAILED')) AND
            (state <> 'COMPLETED' OR result_status = 'SUCCEEDED') AND
            (state <> 'FAILED' OR result_status IS NULL OR result_status = 'FAILED')),
        CONSTRAINT ck_chat_output_result CHECK (
            output_artifact_id IS NULL OR (result_sha256 IS NOT NULL AND
            output_sha256 = result_sha256)),
        CONSTRAINT ck_chat_failure_format CHECK (failure_code IS NULL
            OR failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
        CONSTRAINT ck_chat_terminal_time CHECK (
            (state IN ('COMPLETED','FAILED','CANCELLED')) = (completed_at IS NOT NULL)),
        CONSTRAINT fk_chat_input_revision FOREIGN KEY(input_artifact_id,
            input_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
            revision_id) ON DELETE RESTRICT,
        CONSTRAINT fk_chat_request_revision FOREIGN KEY(request_artifact_id,
            request_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
            revision_id) ON DELETE RESTRICT,
        CONSTRAINT fk_chat_output_revision FOREIGN KEY(output_artifact_id,
            output_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
            revision_id) ON DELETE RESTRICT,
        FOREIGN KEY(conversation_id) REFERENCES general_chat_conversations (conversation_id)
            ON DELETE RESTRICT
    )
    """)
    op.execute("""
    CREATE INDEX ix_chat_fifo ON general_chat_turns (created_at, turn_id) WHERE state = 'QUEUED'
    """)
    op.execute("""
    CREATE UNIQUE INDEX uq_chat_one_active ON general_chat_turns (conversation_id)
        WHERE state IN ('QUEUED','CLAIMED','RUNNING','COMMITTING')
    """)
    op.execute("""
    CREATE TABLE general_chat_capacity (
        slot_key VARCHAR(4) NOT NULL,
        runtime_id VARCHAR(64),
        heartbeat_at TIMESTAMP WITH TIME ZONE,
        active_turn_id VARCHAR(41),
        claim_id VARCHAR(42),
        expires_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (slot_key),
        CONSTRAINT ck_chat_capacity_key CHECK (slot_key = 'chat'),
        CONSTRAINT ck_chat_heartbeat CHECK ((runtime_id IS NULL) = (heartbeat_at IS NULL)),
        CONSTRAINT ck_chat_capacity_claim CHECK ((active_turn_id IS NULL
            AND claim_id IS NULL AND expires_at IS NULL) OR (active_turn_id IS NOT NULL
            AND claim_id IS NOT NULL AND claim_id ~ '^chatclaim_[0-9a-f]{32}$'
            AND expires_at IS NOT NULL AND runtime_id IS NOT NULL)),
        FOREIGN KEY(active_turn_id) REFERENCES general_chat_turns (turn_id) ON DELETE RESTRICT
    )
    """)
    op.execute("INSERT INTO general_chat_capacity (slot_key) VALUES ('chat')")
    op.execute("""
    CREATE FUNCTION protect_general_chat_history() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'chat history is immutable' USING ERRCODE = '23514';
        END IF;
        IF (NEW.turn_id, NEW.conversation_id, NEW.user_sequence, NEW.expected_version,
            NEW.submission_key_sha256, NEW.submission_request_sha256,
            NEW.input_artifact_id, NEW.input_revision_id, NEW.input_sha256, NEW.created_at)
            IS DISTINCT FROM
           (OLD.turn_id, OLD.conversation_id, OLD.user_sequence, OLD.expected_version,
            OLD.submission_key_sha256, OLD.submission_request_sha256,
            OLD.input_artifact_id, OLD.input_revision_id, OLD.input_sha256, OLD.created_at)
           OR (OLD.claim_id IS NOT NULL AND NEW.claim_id IS DISTINCT FROM OLD.claim_id)
           OR (OLD.request_artifact_id IS NOT NULL AND
               (NEW.request_artifact_id, NEW.request_revision_id, NEW.request_sha256)
               IS DISTINCT FROM
               (OLD.request_artifact_id, OLD.request_revision_id, OLD.request_sha256))
           OR (OLD.result_sha256 IS NOT NULL AND
               (NEW.result_sha256, NEW.result_status, NEW.failure_code) IS DISTINCT FROM
               (OLD.result_sha256, OLD.result_status, OLD.failure_code))
           OR OLD.state IN ('COMPLETED','FAILED','CANCELLED') THEN
            RAISE EXCEPTION 'chat turn identity or terminal history is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.state <> OLD.state AND NOT (
           (OLD.state = 'QUEUED' AND NEW.state IN ('CLAIMED','CANCELLED')) OR
           (OLD.state = 'CLAIMED' AND NEW.state IN ('RUNNING','FAILED')) OR
           (OLD.state = 'RUNNING' AND NEW.state IN ('COMMITTING','FAILED')) OR
           (OLD.state = 'COMMITTING' AND NEW.state IN ('COMPLETED','FAILED'))) THEN
            RAISE EXCEPTION 'invalid chat transition' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER general_chat_turn_history_guard
    BEFORE UPDATE OR DELETE ON general_chat_turns
    FOR EACH ROW EXECUTE FUNCTION protect_general_chat_history()
    """)
    op.execute("""
    CREATE FUNCTION protect_general_chat_conversation() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'chat conversation identity is immutable' USING ERRCODE = '23514';
        END IF;
        IF (NEW.conversation_id, NEW.owner_id, NEW.create_key_sha256,
            NEW.create_request_sha256, NEW.created_at) IS DISTINCT FROM
           (OLD.conversation_id, OLD.owner_id, OLD.create_key_sha256,
            OLD.create_request_sha256, OLD.created_at)
           OR NEW.resource_version < OLD.resource_version
           OR NEW.next_sequence < OLD.next_sequence THEN
            RAISE EXCEPTION 'chat conversation identity is immutable' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END;
    $$
    """)
    op.execute("""
    CREATE TRIGGER general_chat_conversation_guard
    BEFORE UPDATE OR DELETE ON general_chat_conversations
    FOR EACH ROW EXECUTE FUNCTION protect_general_chat_conversation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER general_chat_conversation_guard ON general_chat_conversations")
    op.execute("DROP FUNCTION protect_general_chat_conversation()")
    op.execute("DROP TRIGGER general_chat_turn_history_guard ON general_chat_turns")
    op.execute("DROP FUNCTION protect_general_chat_history()")
    op.drop_table("general_chat_capacity")
    op.drop_table("general_chat_turns")
    op.drop_table("general_chat_conversations")
