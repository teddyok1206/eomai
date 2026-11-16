"""Private source admission and exact immutable resolution; no collector activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0084"
down_revision = "20261116_0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE kakao_source_heads (
	room_id VARCHAR(42) NOT NULL,
	owner_operator_id VARCHAR(41) NOT NULL,
	source_binding_id VARCHAR(45) NOT NULL,
	current_source_revision_id VARCHAR(47),
	resource_version INTEGER NOT NULL,
	PRIMARY KEY (room_id),
    CONSTRAINT fk_kakao_source_head_room FOREIGN KEY(owner_operator_id, source_binding_id,
        room_id) REFERENCES kakao_rooms (owner_operator_id, source_binding_id, room_id) ON
        DELETE RESTRICT,
    CONSTRAINT ck_kakao_source_head_version CHECK ((resource_version = 0 AND
        current_source_revision_id IS NULL) OR (resource_version BETWEEN 1 AND 2147483647 AND
        current_source_revision_id IS NOT NULL))
)
""")
    op.execute("""
CREATE TABLE kakao_source_commands (
	command_id VARCHAR(45) NOT NULL,
	owner_operator_id VARCHAR(41) NOT NULL,
	source_binding_id VARCHAR(45) NOT NULL,
	room_id VARCHAR(42) NOT NULL,
	idempotency_key VARCHAR(128) NOT NULL,
	request_sha256 VARCHAR(71) NOT NULL,
	capture_attempt_id VARCHAR(45) NOT NULL,
	source_revision_id VARCHAR(47) NOT NULL,
	previous_revision_id VARCHAR(47),
	expected_resource_version INTEGER NOT NULL,
	state VARCHAR(16) NOT NULL,
	reserved_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (command_id),
	CONSTRAINT uq_kakao_source_command_replay UNIQUE (owner_operator_id, room_id, idempotency_key),
	CONSTRAINT uq_kakao_source_attempt UNIQUE (source_binding_id, capture_attempt_id),
	CONSTRAINT uq_kakao_source_command_result UNIQUE (command_id, room_id, source_revision_id),
    CONSTRAINT fk_kakao_source_command_room
        FOREIGN KEY(owner_operator_id, source_binding_id, room_id)
        REFERENCES kakao_rooms (owner_operator_id, source_binding_id, room_id) ON DELETE
        RESTRICT,
    CONSTRAINT ck_kakao_source_command_ids CHECK (command_id ~ '^kakaocommand_[0-9a-f]{32}$' AND
        source_revision_id ~ '^kakaosourcerev_[0-9a-f]{32}$'),
    CONSTRAINT ck_kakao_source_command_attempt
        CHECK (capture_attempt_id ~ '^kakaoattempt_[0-9a-f]{32}$'),
    CONSTRAINT ck_kakao_source_command_request CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
        idempotency_key ~ '^[!-~]{16,128}$'),
    CONSTRAINT ck_kakao_source_command_previous CHECK ((expected_resource_version = 0 AND
        previous_revision_id IS NULL) OR (expected_resource_version BETWEEN 1 AND 2147483646 AND
        previous_revision_id IS NOT NULL)),
    CONSTRAINT ck_kakao_source_command_state CHECK ((state = 'RESERVED' AND completed_at IS NULL) OR
        (state = 'COMPLETED' AND completed_at IS NOT NULL AND completed_at >= reserved_at))
)
""")
    op.execute("""
CREATE TABLE kakao_source_revisions (
	source_revision_id VARCHAR(47) NOT NULL,
	owner_operator_id VARCHAR(41) NOT NULL,
	source_binding_id VARCHAR(45) NOT NULL,
	room_id VARCHAR(42) NOT NULL,
	command_id VARCHAR(45) NOT NULL,
	previous_revision_id VARCHAR(47),
	resource_version INTEGER NOT NULL,
	snapshot_revision_id VARCHAR(49) NOT NULL,
	normalization_revision_id VARCHAR(54) NOT NULL,
	manifest_artifact_id VARCHAR(41) NOT NULL,
	manifest_artifact_revision_id VARCHAR(36) NOT NULL,
	manifest_sha256 VARCHAR(71) NOT NULL,
	publication_job_id VARCHAR(36) NOT NULL,
	row_count INTEGER NOT NULL,
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (source_revision_id),
	CONSTRAINT uq_kakao_source_room_revision UNIQUE (room_id, source_revision_id),
	CONSTRAINT uq_kakao_source_version UNIQUE (room_id, resource_version),
	CONSTRAINT uq_kakao_source_normalization UNIQUE (source_binding_id, normalization_revision_id),
    CONSTRAINT fk_kakao_source_room FOREIGN KEY(owner_operator_id, source_binding_id, room_id)
        REFERENCES kakao_rooms (owner_operator_id, source_binding_id, room_id) ON DELETE
        RESTRICT,
    CONSTRAINT fk_kakao_source_command FOREIGN KEY(command_id, room_id, source_revision_id)
        REFERENCES kakao_source_commands (command_id, room_id, source_revision_id) ON DELETE
        RESTRICT,
    CONSTRAINT fk_kakao_source_previous FOREIGN KEY(room_id, previous_revision_id) REFERENCES
        kakao_source_revisions (room_id, source_revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kakao_source_manifest FOREIGN KEY(manifest_artifact_id,
        manifest_artifact_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
        revision_id) ON DELETE RESTRICT,
    CONSTRAINT ck_kakao_source_ids CHECK (source_revision_id ~ '^kakaosourcerev_[0-9a-f]{32}$'
        AND snapshot_revision_id ~ '^kakaosnapshotrev_[0-9a-f]{32}$' AND
        normalization_revision_id ~ '^kakaonormalizationrev_[0-9a-f]{32}$'),
	CONSTRAINT ck_kakao_source_hash CHECK (manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_kakao_source_lineage CHECK ((resource_version = 1 AND previous_revision_id IS
        NULL) OR (resource_version BETWEEN 2 AND 2147483647 AND previous_revision_id IS NOT NULL
        AND previous_revision_id <> source_revision_id)),
    CONSTRAINT ck_kakao_source_bounds CHECK (row_count BETWEEN 0 AND 100000 AND observed_at <=
        created_at),
	FOREIGN KEY(publication_job_id) REFERENCES jobs (job_id) ON DELETE RESTRICT
)
""")
    op.execute("""
    ALTER TABLE kakao_source_heads ADD CONSTRAINT fk_kakao_source_head_current FOREIGN
        KEY(room_id, current_source_revision_id) REFERENCES kakao_source_revisions (room_id,
        source_revision_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
""")
    op.execute("""
    ALTER TABLE kakao_source_commands ADD CONSTRAINT fk_kakao_source_command_previous FOREIGN
        KEY(room_id, previous_revision_id) REFERENCES kakao_source_revisions (room_id,
        source_revision_id) ON DELETE RESTRICT
""")
    op.execute("""
CREATE TRIGGER trg_kakao_source_immutable BEFORE UPDATE OR DELETE ON kakao_source_revisions
FOR EACH ROW EXECUTE FUNCTION reject_control_plane_immutable_mutation()
""")
    op.execute("""
CREATE FUNCTION guard_kakao_source_command() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.state = 'COMPLETED' THEN
        RAISE EXCEPTION 'KAKAO_SOURCE_COMMAND_IMMUTABLE';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['state','completed_at']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['state','completed_at']) THEN
        RAISE EXCEPTION 'KAKAO_SOURCE_INTENT_IMMUTABLE';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_source_command_guard BEFORE UPDATE OR DELETE ON kakao_source_commands
FOR EACH ROW EXECUTE FUNCTION guard_kakao_source_command()
""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM kakao_source_commands)")):
        raise RuntimeError("KAKAO_SOURCE_HISTORY_PRESENT")
    op.drop_constraint("fk_kakao_source_head_current", "kakao_source_heads", type_="foreignkey")
    op.drop_constraint(
        "fk_kakao_source_command_previous", "kakao_source_commands", type_="foreignkey"
    )
    op.drop_table("kakao_source_revisions")
    op.drop_table("kakao_source_commands")
    op.drop_table("kakao_source_heads")
    op.execute("DROP FUNCTION guard_kakao_source_command()")
