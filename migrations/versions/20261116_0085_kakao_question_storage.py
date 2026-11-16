"""Immutable private question storage; no collection or renderer activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0085"
down_revision = "20261116_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE kakao_questions (
question_id VARCHAR(46) NOT NULL,
owner_operator_id VARCHAR(41) NOT NULL,
source_binding_id VARCHAR(45) NOT NULL,
room_id VARCHAR(42) NOT NULL,
origin_source_revision_id VARCHAR(47) NOT NULL,
origin_candidate_ordinal INTEGER NOT NULL,
origin_occurrence_id VARCHAR(45) NOT NULL,
current_revision_id VARCHAR(49) NOT NULL,
resource_version INTEGER NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
PRIMARY KEY (question_id),
CONSTRAINT fk_kakao_question_room FOREIGN KEY(owner_operator_id, source_binding_id, room_id)
REFERENCES kakao_rooms (owner_operator_id, source_binding_id, room_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_question_origin_source FOREIGN KEY(room_id, origin_source_revision_id)
REFERENCES kakao_source_revisions (room_id, source_revision_id) ON DELETE RESTRICT,
CONSTRAINT uq_kakao_question_origin UNIQUE (room_id, origin_occurrence_id),
CONSTRAINT uq_kakao_question_owner UNIQUE (owner_operator_id, question_id),
CONSTRAINT uq_kakao_question_room UNIQUE (question_id, room_id),
CONSTRAINT ck_kakao_question_id CHECK (question_id ~ '^kakaoquestion_[0-9a-f]{32}$'),
CONSTRAINT ck_kakao_question_origin CHECK (origin_occurrence_id ~
'^kakaomessage_[0-9a-f]{32}$'),
CONSTRAINT ck_kakao_question_bounds CHECK (origin_candidate_ordinal BETWEEN 1 AND 100000 AND
resource_version BETWEEN 1 AND 2147483647)
)
""")
    op.execute("""
CREATE TABLE kakao_question_commands (
command_id VARCHAR(45) NOT NULL,
owner_operator_id VARCHAR(41) NOT NULL,
source_binding_id VARCHAR(45) NOT NULL,
room_id VARCHAR(42) NOT NULL,
idempotency_scope VARCHAR(96) NOT NULL,
idempotency_key VARCHAR(128) NOT NULL,
request_sha256 VARCHAR(71) NOT NULL,
action VARCHAR(16) NOT NULL,
question_id VARCHAR(46) NOT NULL,
question_revision_id VARCHAR(49) NOT NULL,
previous_revision_id VARCHAR(49),
expected_version INTEGER NOT NULL,
mapping_revision_id VARCHAR(48) NOT NULL,
state VARCHAR(16) NOT NULL,
reserved_at TIMESTAMP WITH TIME ZONE NOT NULL,
completed_at TIMESTAMP WITH TIME ZONE,
PRIMARY KEY (command_id),
CONSTRAINT fk_kakao_question_command_room FOREIGN KEY(owner_operator_id, source_binding_id,
room_id) REFERENCES kakao_rooms (owner_operator_id, source_binding_id, room_id) ON DELETE
RESTRICT,
CONSTRAINT fk_kakao_question_command_mapping FOREIGN KEY(room_id, mapping_revision_id)
REFERENCES kakao_room_mapping_revisions (room_id, mapping_revision_id) ON DELETE RESTRICT,
CONSTRAINT uq_kakao_question_command_replay UNIQUE (owner_operator_id, idempotency_scope,
idempotency_key),
CONSTRAINT uq_kakao_question_command_result UNIQUE (command_id, question_id,
question_revision_id),
CONSTRAINT ck_kakao_question_command_ids CHECK (command_id ~ '^kakaocommand_[0-9a-f]{32}$' AND
question_id ~ '^kakaoquestion_[0-9a-f]{32}$' AND question_revision_id ~
'^kakaoquestionrev_[0-9a-f]{32}$'),
CONSTRAINT ck_kakao_question_command_request CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
idempotency_key ~ '^[!-~]{16,128}$'),
CONSTRAINT ck_kakao_question_command_parent CHECK ((action = 'CREATE' AND expected_version = 0
AND previous_revision_id IS NULL) OR (action = 'EDIT' AND expected_version BETWEEN 1 AND
2147483646 AND previous_revision_id IS NOT NULL)),
CONSTRAINT ck_kakao_question_command_state CHECK ((state = 'RESERVED' AND completed_at IS NULL)
OR (state = 'COMPLETED' AND completed_at IS NOT NULL AND completed_at >= reserved_at))
)
""")
    op.execute("""
CREATE TABLE kakao_question_revisions (
question_revision_id VARCHAR(49) NOT NULL,
question_id VARCHAR(46) NOT NULL,
room_id VARCHAR(42) NOT NULL,
command_id VARCHAR(45) NOT NULL,
previous_revision_id VARCHAR(49),
resource_version INTEGER NOT NULL,
mapping_revision_id VARCHAR(48) NOT NULL,
review_state VARCHAR(16) NOT NULL,
first_student_at_utc TIMESTAMP WITH TIME ZONE,
manifest_artifact_id VARCHAR(41) NOT NULL,
manifest_artifact_revision_id VARCHAR(36) NOT NULL,
manifest_sha256 VARCHAR(71) NOT NULL,
publication_job_id VARCHAR(36) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
PRIMARY KEY (question_revision_id),
CONSTRAINT uq_kakao_question_revision UNIQUE (question_id, question_revision_id),
CONSTRAINT uq_kakao_question_version UNIQUE (question_id, resource_version),
CONSTRAINT uq_kakao_question_current_version UNIQUE (question_id, question_revision_id,
resource_version),
CONSTRAINT fk_kakao_question_revision_parent FOREIGN KEY(question_id, room_id) REFERENCES
kakao_questions (question_id, room_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_question_previous FOREIGN KEY(question_id, previous_revision_id) REFERENCES
kakao_question_revisions (question_id, question_revision_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_question_revision_command FOREIGN KEY(command_id, question_id,
question_revision_id) REFERENCES kakao_question_commands (command_id, question_id,
question_revision_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_question_revision_mapping FOREIGN KEY(room_id, mapping_revision_id)
REFERENCES kakao_room_mapping_revisions (room_id, mapping_revision_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_question_manifest FOREIGN KEY(manifest_artifact_id,
manifest_artifact_revision_id) REFERENCES artifact_revisions (logical_artifact_id, revision_id)
ON DELETE RESTRICT,
CONSTRAINT ck_kakao_question_revision_ids CHECK (question_revision_id ~
'^kakaoquestionrev_[0-9a-f]{32}$' AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'),
CONSTRAINT ck_kakao_question_lineage CHECK ((resource_version = 1 AND previous_revision_id IS
NULL) OR (resource_version BETWEEN 2 AND 2147483647 AND previous_revision_id IS NOT NULL AND
previous_revision_id <> question_revision_id)),
CONSTRAINT ck_kakao_question_review CHECK (review_state IN
('UNREVIEWED','CONFIRMED','EXCLUDED')),
FOREIGN KEY(publication_job_id) REFERENCES jobs (job_id) ON DELETE RESTRICT
)
""")
    op.execute("""
ALTER TABLE kakao_questions ADD CONSTRAINT fk_kakao_question_current FOREIGN KEY(question_id,
current_revision_id, resource_version) REFERENCES kakao_question_revisions (question_id,
question_revision_id, resource_version) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
""")
    op.execute("""
CREATE INDEX ix_kakao_question_binding_page ON kakao_questions (owner_operator_id,
source_binding_id, question_id)
""")
    op.execute("""
CREATE INDEX ix_kakao_question_page ON kakao_questions (owner_operator_id, source_binding_id,
room_id, question_id)
""")
    op.execute("""
CREATE TRIGGER trg_kakao_question_revision_immutable BEFORE UPDATE OR DELETE ON
kakao_question_revisions FOR EACH ROW EXECUTE FUNCTION reject_control_plane_immutable_mutation()
""")
    op.execute("""
CREATE FUNCTION guard_kakao_question_command() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.state = 'COMPLETED' THEN
        RAISE EXCEPTION 'KAKAO_QUESTION_COMMAND_IMMUTABLE';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['state','completed_at']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['state','completed_at']) THEN
        RAISE EXCEPTION 'KAKAO_QUESTION_INTENT_IMMUTABLE';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_question_command_guard BEFORE UPDATE OR DELETE ON
kakao_question_commands FOR EACH ROW EXECUTE FUNCTION guard_kakao_question_command()
""")
    op.execute("""
CREATE FUNCTION guard_kakao_question_head() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'KAKAO_QUESTION_HISTORY_PROTECTED';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['current_revision_id','resource_version']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['current_revision_id','resource_version'])
       OR NEW.resource_version <> OLD.resource_version + 1
       OR NEW.current_revision_id = OLD.current_revision_id THEN
        RAISE EXCEPTION 'KAKAO_QUESTION_CURRENT_INVALID';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_question_head_guard BEFORE UPDATE OR DELETE ON kakao_questions FOR EACH
ROW EXECUTE FUNCTION guard_kakao_question_head()
""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM kakao_question_commands)")):
        raise RuntimeError("KAKAO_QUESTION_HISTORY_PRESENT")
    op.drop_constraint("fk_kakao_question_current", "kakao_questions", type_="foreignkey")
    op.drop_table("kakao_question_revisions")
    op.drop_table("kakao_question_commands")
    op.drop_table("kakao_questions")
    op.execute("DROP FUNCTION guard_kakao_question_command()")
    op.execute("DROP FUNCTION guard_kakao_question_head()")
