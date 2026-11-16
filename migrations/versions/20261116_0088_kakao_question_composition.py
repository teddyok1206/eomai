"""Atomic private question split/merge reservations. No collection activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0088"
down_revision = "20261116_0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE kakao_question_compositions (
    composition_id VARCHAR(49) NOT NULL,
    owner_operator_id VARCHAR(41) NOT NULL,
    source_binding_id VARCHAR(45) NOT NULL,
    room_id VARCHAR(42) NOT NULL,
    mapping_revision_id VARCHAR(48) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_sha256 VARCHAR(71) NOT NULL,
    operation VARCHAR(16) NOT NULL,
    state VARCHAR(16) NOT NULL,
    reserved_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (composition_id),
    CONSTRAINT fk_kakao_composition_room FOREIGN KEY(owner_operator_id, source_binding_id,
room_id) REFERENCES kakao_rooms (owner_operator_id, source_binding_id, room_id) ON DELETE
RESTRICT,
    CONSTRAINT fk_kakao_composition_mapping FOREIGN KEY(room_id, mapping_revision_id) REFERENCES
kakao_room_mapping_revisions (room_id, mapping_revision_id) ON DELETE RESTRICT,
    CONSTRAINT uq_kakao_composition_replay UNIQUE (owner_operator_id, idempotency_key),
    CONSTRAINT uq_kakao_composition_room UNIQUE (composition_id, room_id),
    CONSTRAINT ck_kakao_composition_id CHECK (composition_id ~ '^kakaocomposition_[0-9a-f]{32}$'),
    CONSTRAINT ck_kakao_composition_operation CHECK (operation IN ('SPLIT','MERGE')),
    CONSTRAINT ck_kakao_composition_request CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
idempotency_key ~ '^[!-~]{16,128}$'),
    CONSTRAINT ck_kakao_composition_state CHECK ((state = 'RESERVED' AND completed_at IS NULL)
OR (state = 'COMPLETED' AND completed_at IS NOT NULL AND completed_at >= reserved_at))
)
""")
    op.execute("""
CREATE TABLE kakao_question_composition_inputs (
    composition_id VARCHAR(49) NOT NULL,
    ordinal INTEGER NOT NULL,
    room_id VARCHAR(42) NOT NULL,
    question_id VARCHAR(46) NOT NULL,
    question_revision_id VARCHAR(49) NOT NULL,
    resource_version INTEGER NOT NULL,
    PRIMARY KEY (composition_id, ordinal),
    CONSTRAINT fk_kakao_composition_input_command FOREIGN KEY(composition_id, room_id)
REFERENCES kakao_question_compositions (composition_id, room_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kakao_composition_input_room FOREIGN KEY(question_id, room_id) REFERENCES
kakao_questions (question_id, room_id) ON DELETE RESTRICT,
    CONSTRAINT fk_kakao_composition_input_revision FOREIGN KEY(question_id,
question_revision_id, resource_version) REFERENCES kakao_question_revisions (question_id,
question_revision_id, resource_version) ON DELETE RESTRICT,
    CONSTRAINT uq_kakao_composition_input_question UNIQUE (composition_id, question_id),
    CONSTRAINT ck_kakao_composition_input_ordinal CHECK (ordinal BETWEEN 1 AND 100)
)
""")
    op.execute("""
CREATE TABLE kakao_question_composition_outputs (
    composition_id VARCHAR(49) NOT NULL,
    ordinal INTEGER NOT NULL,
    question_id VARCHAR(46) NOT NULL,
    question_revision_id VARCHAR(49) NOT NULL,
    PRIMARY KEY (composition_id, ordinal),
    CONSTRAINT uq_kakao_composition_output_identity UNIQUE (question_id),
    CONSTRAINT uq_kakao_composition_output_revision UNIQUE (question_revision_id),
    CONSTRAINT uq_kakao_composition_output_question UNIQUE (composition_id, question_id),
    CONSTRAINT uq_kakao_composition_output_exact UNIQUE (composition_id, question_id,
question_revision_id),
    CONSTRAINT ck_kakao_composition_output_ordinal CHECK (ordinal BETWEEN 1 AND 100),
    CONSTRAINT ck_kakao_composition_output_ids CHECK (question_id ~
'^kakaoquestion_[0-9a-f]{32}$' AND question_revision_id ~ '^kakaoquestionrev_[0-9a-f]{32}$'),
    FOREIGN KEY(composition_id) REFERENCES kakao_question_compositions (composition_id) ON
DELETE RESTRICT
)
""")
    op.execute("""
ALTER TABLE kakao_questions
ALTER COLUMN origin_source_revision_id DROP NOT NULL,
ALTER COLUMN origin_candidate_ordinal DROP NOT NULL,
ALTER COLUMN origin_occurrence_id DROP NOT NULL,
ADD COLUMN origin_composition_id VARCHAR(49),
ADD COLUMN superseded_by_composition_id VARCHAR(49),
DROP CONSTRAINT ck_kakao_question_bounds,
ADD CONSTRAINT ck_kakao_question_bounds CHECK (
(origin_candidate_ordinal IS NULL OR origin_candidate_ordinal BETWEEN 1 AND 100000)
AND resource_version BETWEEN 1 AND 2147483647),
ADD CONSTRAINT ck_kakao_question_origin_kind CHECK (
(origin_composition_id IS NULL AND origin_source_revision_id IS NOT NULL
AND origin_candidate_ordinal IS NOT NULL AND origin_occurrence_id IS NOT NULL) OR
(origin_composition_id IS NOT NULL AND origin_source_revision_id IS NULL
AND origin_candidate_ordinal IS NULL AND origin_occurrence_id IS NULL)),
ADD CONSTRAINT fk_kakao_question_composed_origin FOREIGN KEY(origin_composition_id,question_id)
REFERENCES kakao_question_composition_outputs(composition_id,question_id) ON DELETE RESTRICT,
ADD CONSTRAINT fk_kakao_question_supersession FOREIGN
KEY(superseded_by_composition_id,question_id)
REFERENCES kakao_question_composition_inputs(composition_id,question_id) ON DELETE RESTRICT
""")
    op.execute("""
ALTER TABLE kakao_question_revisions
ALTER COLUMN command_id DROP NOT NULL,
ADD COLUMN composition_id VARCHAR(49),
ADD CONSTRAINT fk_kakao_question_revision_composition FOREIGN KEY(
composition_id,question_id,question_revision_id)
REFERENCES kakao_question_composition_outputs(composition_id,question_id,question_revision_id)
ON DELETE RESTRICT,
ADD CONSTRAINT ck_kakao_question_revision_authority CHECK (
(command_id IS NOT NULL AND composition_id IS NULL) OR
(command_id IS NULL AND composition_id IS NOT NULL AND resource_version = 1))
""")
    op.execute("""
CREATE OR REPLACE FUNCTION guard_kakao_question_head() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'KAKAO_QUESTION_HISTORY_PROTECTED';
    END IF;
    IF OLD.superseded_by_composition_id IS NOT NULL
       OR (to_jsonb(NEW) -
ARRAY['current_revision_id','resource_version','superseded_by_composition_id'])
       IS DISTINCT FROM
       (to_jsonb(OLD) -
ARRAY['current_revision_id','resource_version','superseded_by_composition_id'])
    THEN RAISE EXCEPTION 'KAKAO_QUESTION_CURRENT_INVALID'; END IF;
    IF NEW.superseded_by_composition_id IS NOT NULL THEN
        IF NEW.resource_version <> OLD.resource_version
           OR NEW.current_revision_id <> OLD.current_revision_id
        THEN RAISE EXCEPTION 'KAKAO_QUESTION_CURRENT_INVALID'; END IF;
    ELSIF NEW.resource_version <> OLD.resource_version + 1
       OR NEW.current_revision_id = OLD.current_revision_id
    THEN RAISE EXCEPTION 'KAKAO_QUESTION_CURRENT_INVALID'; END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE FUNCTION guard_kakao_question_composition() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE input_count integer; output_count integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'RESERVED' THEN
            RAISE EXCEPTION 'KAKAO_COMPOSITION_INITIAL_STATE_INVALID';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' OR OLD.state = 'COMPLETED' THEN
        RAISE EXCEPTION 'KAKAO_COMPOSITION_IMMUTABLE';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['state','completed_at']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['state','completed_at']) OR NEW.state <> 'COMPLETED' THEN
        RAISE EXCEPTION 'KAKAO_COMPOSITION_INTENT_IMMUTABLE';
    END IF;
    SELECT count(*) INTO input_count FROM kakao_question_composition_inputs
    WHERE composition_id=NEW.composition_id;
    SELECT count(*) INTO output_count FROM kakao_question_composition_outputs
    WHERE composition_id=NEW.composition_id;
    IF NOT ((NEW.operation='SPLIT' AND input_count=1 AND output_count BETWEEN 2 AND 100)
         OR (NEW.operation='MERGE' AND input_count BETWEEN 2 AND 100 AND output_count=1))
    THEN RAISE EXCEPTION 'KAKAO_COMPOSITION_MEMBERS_INVALID'; END IF;
    IF EXISTS (
        SELECT 1 FROM kakao_question_composition_inputs i
        JOIN kakao_questions q ON q.question_id=i.question_id
        WHERE i.composition_id=NEW.composition_id
        AND (q.superseded_by_composition_id IS DISTINCT FROM NEW.composition_id
             OR q.current_revision_id<>i.question_revision_id OR
q.resource_version<>i.resource_version)
    ) OR EXISTS (
        SELECT 1 FROM kakao_question_composition_outputs o
        LEFT JOIN kakao_questions q ON q.question_id=o.question_id
        LEFT JOIN kakao_question_revisions r ON r.question_revision_id=o.question_revision_id
        WHERE o.composition_id=NEW.composition_id
        AND (q.question_id IS NULL OR r.question_id IS NULL
             OR q.owner_operator_id<>NEW.owner_operator_id OR q.room_id<>NEW.room_id
             OR q.origin_composition_id IS DISTINCT FROM NEW.composition_id
             OR q.current_revision_id<>o.question_revision_id OR q.resource_version<>1
             OR r.composition_id IS DISTINCT FROM NEW.composition_id
             OR r.mapping_revision_id<>NEW.mapping_revision_id)
    ) THEN RAISE EXCEPTION 'KAKAO_COMPOSITION_ADOPTION_INCOMPLETE'; END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_composition_guard BEFORE INSERT OR UPDATE OR DELETE
ON kakao_question_compositions FOR EACH ROW EXECUTE FUNCTION guard_kakao_question_composition()
""")
    op.execute("""
CREATE FUNCTION guard_kakao_composition_member() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current_state text;
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'KAKAO_COMPOSITION_MEMBER_IMMUTABLE'; END IF;
    SELECT state INTO current_state FROM kakao_question_compositions
    WHERE composition_id=NEW.composition_id FOR UPDATE;
    IF current_state IS DISTINCT FROM 'RESERVED' THEN
        RAISE EXCEPTION 'KAKAO_COMPOSITION_MEMBER_IMMUTABLE';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_composition_input_guard BEFORE INSERT OR UPDATE OR DELETE
ON kakao_question_composition_inputs FOR EACH ROW EXECUTE FUNCTION
guard_kakao_composition_member()
""")
    op.execute("""
CREATE TRIGGER trg_kakao_composition_output_guard BEFORE INSERT OR UPDATE OR DELETE
ON kakao_question_composition_outputs FOR EACH ROW EXECUTE FUNCTION
guard_kakao_composition_member()
""")
    op.execute("""
CREATE FUNCTION check_kakao_composition_adopted() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM kakao_question_compositions c
        WHERE c.composition_id IN (NEW.origin_composition_id,NEW.superseded_by_composition_id)
        AND c.state <> 'COMPLETED'
    ) THEN RAISE EXCEPTION 'KAKAO_COMPOSITION_ADOPTION_INCOMPLETE'; END IF;
    RETURN NULL;
END $$
""")
    op.execute("""
CREATE CONSTRAINT TRIGGER trg_kakao_composition_atomic
AFTER INSERT OR UPDATE ON kakao_questions DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION check_kakao_composition_adopted()
""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM kakao_question_compositions)")):
        raise RuntimeError("KAKAO_COMPOSITION_HISTORY_PRESENT")
    op.execute("""
DROP TRIGGER trg_kakao_composition_atomic ON kakao_questions
""")
    op.execute("""
DROP FUNCTION check_kakao_composition_adopted()
""")
    op.execute("""
ALTER TABLE kakao_question_revisions
DROP CONSTRAINT ck_kakao_question_revision_authority,
DROP CONSTRAINT fk_kakao_question_revision_composition,
DROP COLUMN composition_id, ALTER COLUMN command_id SET NOT NULL
""")
    op.execute("""
ALTER TABLE kakao_questions
DROP CONSTRAINT fk_kakao_question_supersession,
DROP CONSTRAINT fk_kakao_question_composed_origin,
DROP CONSTRAINT ck_kakao_question_origin_kind,
DROP CONSTRAINT ck_kakao_question_bounds,
DROP COLUMN superseded_by_composition_id,
DROP COLUMN origin_composition_id,
ALTER COLUMN origin_source_revision_id SET NOT NULL,
ALTER COLUMN origin_candidate_ordinal SET NOT NULL,
ALTER COLUMN origin_occurrence_id SET NOT NULL,
ADD CONSTRAINT ck_kakao_question_bounds CHECK (
origin_candidate_ordinal BETWEEN 1 AND 100000 AND resource_version BETWEEN 1 AND 2147483647)
""")
    op.execute("""
DROP TABLE kakao_question_composition_inputs
""")
    op.execute("""
DROP TABLE kakao_question_composition_outputs
""")
    op.execute("""
DROP TABLE kakao_question_compositions
""")
    op.execute("""
DROP FUNCTION guard_kakao_composition_member()
""")
    op.execute("""
DROP FUNCTION guard_kakao_question_composition()
""")
    op.execute("""
CREATE OR REPLACE FUNCTION guard_kakao_question_head() RETURNS trigger LANGUAGE plpgsql AS $$
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
