"""Private student PDF exports and preserved execution attempts."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0087"
down_revision = "20261116_0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE kakao_exports (
	export_id VARCHAR(44) NOT NULL,
	owner_operator_id VARCHAR(41) NOT NULL,
	source_binding_id VARCHAR(45) NOT NULL,
	packet_id VARCHAR(44) NOT NULL,
	packet_revision_id VARCHAR(47) NOT NULL,
	student_id VARCHAR(45) NOT NULL,
	build_sha256 VARCHAR(71) NOT NULL,
	subset_sha256 VARCHAR(71) NOT NULL,
	profile JSONB NOT NULL,
	mode VARCHAR(8) NOT NULL,
	question_count INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	current_attempt_id VARCHAR(45),
	attempt_number INTEGER NOT NULL,
	PRIMARY KEY (export_id),
CONSTRAINT fk_kakao_export_packet_owner FOREIGN KEY(owner_operator_id, source_binding_id,
packet_id) REFERENCES kakao_packets (owner_operator_id, source_binding_id, packet_id) ON DELETE
RESTRICT,
CONSTRAINT fk_kakao_export_packet_revision FOREIGN KEY(packet_id, packet_revision_id) REFERENCES
kakao_packet_revisions (packet_id, packet_revision_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_export_student FOREIGN KEY(student_id) REFERENCES kakao_students
(student_id) ON DELETE RESTRICT,
	CONSTRAINT uq_kakao_export_owner UNIQUE (owner_operator_id, source_binding_id, export_id),
	CONSTRAINT uq_kakao_export_build UNIQUE (owner_operator_id, build_sha256),
CONSTRAINT ck_kakao_export_ids CHECK (export_id ~ '^kakaoexport_[0-9a-f]{32}$' AND build_sha256
~ '^sha256:[0-9a-f]{64}$' AND subset_sha256 ~ '^sha256:[0-9a-f]{64}$'),
CONSTRAINT ck_kakao_export_input CHECK (mode IN ('DRAFT','FINAL') AND question_count BETWEEN 1
AND 200 AND jsonb_typeof(profile) = 'object' AND octet_length(profile::text) <= 2048),
CONSTRAINT ck_kakao_export_attempt_pointer CHECK ((attempt_number = 0 AND current_attempt_id IS
NULL) OR (attempt_number BETWEEN 1 AND 2147483647 AND current_attempt_id IS NOT NULL))
)
""")
    op.execute("""
CREATE TABLE kakao_export_requests (
	owner_operator_id VARCHAR(41) NOT NULL,
	source_binding_id VARCHAR(45) NOT NULL,
	idempotency_key VARCHAR(128) NOT NULL,
	request_sha256 VARCHAR(71) NOT NULL,
	export_id VARCHAR(44) NOT NULL,
	PRIMARY KEY (owner_operator_id, source_binding_id, idempotency_key),
CONSTRAINT fk_kakao_export_request_owner FOREIGN KEY(owner_operator_id, source_binding_id,
export_id) REFERENCES kakao_exports (owner_operator_id, source_binding_id, export_id) ON DELETE
RESTRICT,
CONSTRAINT ck_kakao_export_request CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
idempotency_key ~ '^[!-~]{16,128}$')
)
""")
    op.execute("""
CREATE TABLE kakao_export_attempts (
	attempt_id VARCHAR(45) NOT NULL,
	export_id VARCHAR(44) NOT NULL,
	previous_attempt_id VARCHAR(45),
	command_id VARCHAR(45) NOT NULL,
	task_id VARCHAR(42) NOT NULL,
	attempt_number INTEGER NOT NULL,
	command JSONB,
	state VARCHAR(24) NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	error_code VARCHAR(80),
	export_revision_id VARCHAR(47),
	artifact_id VARCHAR(41),
	artifact_revision_id VARCHAR(36),
	pdf_sha256 VARCHAR(71),
	layout_sha256 VARCHAR(71),
	publication_job_id VARCHAR(36),
	page_count INTEGER NOT NULL,
	PRIMARY KEY (attempt_id),
CONSTRAINT fk_kakao_export_attempt_parent FOREIGN KEY(export_id) REFERENCES kakao_exports
(export_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_export_attempt_previous FOREIGN KEY(export_id, previous_attempt_id)
REFERENCES kakao_export_attempts (export_id, attempt_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_export_output FOREIGN KEY(artifact_id, artifact_revision_id) REFERENCES
artifact_revisions (logical_artifact_id, revision_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_export_publication FOREIGN KEY(publication_job_id) REFERENCES jobs (job_id)
ON DELETE RESTRICT,
	CONSTRAINT uq_kakao_export_attempt UNIQUE (export_id, attempt_id),
	CONSTRAINT uq_kakao_export_attempt_number UNIQUE (export_id, attempt_number),
	CONSTRAINT uq_kakao_export_attempt_current UNIQUE (export_id, attempt_id, attempt_number),
	CONSTRAINT uq_kakao_export_output_revision UNIQUE (export_revision_id),
CONSTRAINT ck_kakao_export_attempt_ids CHECK (attempt_id ~ '^kakaoattempt_[0-9a-f]{32}$' AND
command_id ~ '^kakaocommand_[0-9a-f]{32}$' AND task_id ~ '^kakaotask_[0-9a-f]{32}$'),
CONSTRAINT ck_kakao_export_attempt_lineage CHECK ((attempt_number = 1 AND previous_attempt_id IS
NULL) OR (attempt_number BETWEEN 2 AND 2147483647 AND previous_attempt_id IS NOT NULL AND
previous_attempt_id <> attempt_id)),
CONSTRAINT ck_kakao_export_attempt_command CHECK (command IS NULL OR (jsonb_typeof(command) =
'object' AND octet_length(command::text) <= 8192)),
CONSTRAINT ck_kakao_export_attempt_state CHECK ((state = 'RUNNING' AND completed_at IS NULL AND
error_code IS NULL) OR (state = 'COMPLETED' AND completed_at IS NOT NULL AND completed_at >=
started_at AND command IS NOT NULL AND error_code IS NULL) OR (state IN
('FAILED','NEEDS_LAYOUT_REVIEW') AND completed_at IS NOT NULL AND completed_at >= started_at AND
error_code IS NOT NULL AND error_code ~ '^[A-Z][A-Z0-9_]{2,79}$')),
CONSTRAINT ck_kakao_export_attempt_output CHECK ((state = 'COMPLETED' AND export_revision_id IS
NOT NULL AND artifact_id IS NOT NULL AND artifact_revision_id IS NOT NULL AND pdf_sha256 IS NOT
NULL AND layout_sha256 IS NOT NULL AND publication_job_id IS NOT NULL AND page_count BETWEEN 1
AND 200) OR (state <> 'COMPLETED' AND export_revision_id IS NULL AND artifact_id IS NULL AND
artifact_revision_id IS NULL AND pdf_sha256 IS NULL AND layout_sha256 IS NULL AND
publication_job_id IS NULL AND page_count = 0)),
CONSTRAINT ck_kakao_export_output_ids CHECK ((export_revision_id IS NULL OR export_revision_id ~
'^kakaoexportrev_[0-9a-f]{32}$') AND (pdf_sha256 IS NULL OR pdf_sha256 ~
'^sha256:[0-9a-f]{64}$') AND (layout_sha256 IS NULL OR layout_sha256 ~ '^sha256:[0-9a-f]{64}$'))
)
""")
    op.execute("""
ALTER TABLE kakao_exports ADD CONSTRAINT fk_kakao_export_current_attempt FOREIGN KEY(export_id,
current_attempt_id, attempt_number) REFERENCES kakao_export_attempts (export_id, attempt_id,
attempt_number) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
""")
    for table in ("kakao_export_requests",):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_control_plane_immutable_mutation()"
        )
    op.execute("""
CREATE FUNCTION guard_kakao_export_head() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'KAKAO_EXPORT_HISTORY_PROTECTED';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['current_attempt_id','attempt_number']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['current_attempt_id','attempt_number'])
       OR NEW.attempt_number <> OLD.attempt_number + 1
       OR NEW.current_attempt_id IS NOT DISTINCT FROM OLD.current_attempt_id
       OR (OLD.current_attempt_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM kakao_export_attempts WHERE attempt_id = OLD.current_attempt_id
           AND export_id = OLD.export_id AND state = 'FAILED'))
       OR NOT EXISTS (SELECT 1 FROM kakao_export_attempts
           WHERE attempt_id = NEW.current_attempt_id AND export_id = NEW.export_id
           AND attempt_number = NEW.attempt_number
           AND previous_attempt_id IS NOT DISTINCT FROM OLD.current_attempt_id) THEN
        RAISE EXCEPTION 'KAKAO_EXPORT_ATTEMPT_TRANSITION_INVALID';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_export_head BEFORE UPDATE OR DELETE ON kakao_exports
FOR EACH ROW EXECUTE FUNCTION guard_kakao_export_head()
""")
    op.execute("""
CREATE FUNCTION guard_kakao_export_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.state <> 'RUNNING' THEN
        RAISE EXCEPTION 'KAKAO_EXPORT_ATTEMPT_IMMUTABLE';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['command','state','completed_at','error_code',
            'export_revision_id','artifact_id','artifact_revision_id','pdf_sha256',
            'layout_sha256','publication_job_id','page_count']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['command','state','completed_at','error_code',
            'export_revision_id','artifact_id','artifact_revision_id','pdf_sha256',
            'layout_sha256','publication_job_id','page_count'])
       OR (OLD.command IS NOT NULL AND NEW.command IS DISTINCT FROM OLD.command) THEN
        RAISE EXCEPTION 'KAKAO_EXPORT_EXECUTION_PINS_IMMUTABLE';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_export_attempt BEFORE UPDATE OR DELETE ON kakao_export_attempts
FOR EACH ROW EXECUTE FUNCTION guard_kakao_export_attempt()
""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM kakao_exports)")):
        raise RuntimeError("KAKAO_EXPORT_HISTORY_PRESENT")
    op.drop_constraint("fk_kakao_export_current_attempt", "kakao_exports", type_="foreignkey")
    op.drop_table("kakao_export_attempts")
    op.drop_table("kakao_export_requests")
    op.drop_table("kakao_exports")
    op.execute("DROP FUNCTION guard_kakao_export_attempt()")
    op.execute("DROP FUNCTION guard_kakao_export_head()")
