"""Immutable private packet acceptance; no collector or PDF worker activation."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0086"
down_revision = "20261116_0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE kakao_packets (
packet_id VARCHAR(44) NOT NULL,
owner_operator_id VARCHAR(41) NOT NULL,
source_binding_id VARCHAR(45) NOT NULL,
current_revision_id VARCHAR(47) NOT NULL,
resource_version INTEGER NOT NULL,
PRIMARY KEY (packet_id),
CONSTRAINT fk_kakao_packet_binding FOREIGN KEY(owner_operator_id, source_binding_id) REFERENCES
kakao_channel_bindings (owner_operator_id, source_binding_id) ON DELETE RESTRICT,
CONSTRAINT uq_kakao_packet_owner UNIQUE (owner_operator_id, source_binding_id, packet_id),
CONSTRAINT ck_kakao_packet_id_version CHECK (packet_id ~ '^kakaopacket_[0-9a-f]{32}$' AND
resource_version BETWEEN 1 AND 2147483647)
)
""")
    op.execute("""
CREATE TABLE kakao_packet_commands (
command_id VARCHAR(45) NOT NULL,
owner_operator_id VARCHAR(41) NOT NULL,
source_binding_id VARCHAR(45) NOT NULL,
idempotency_scope VARCHAR(96) NOT NULL,
idempotency_key VARCHAR(128) NOT NULL,
request_sha256 VARCHAR(71) NOT NULL,
packet_id VARCHAR(44) NOT NULL,
packet_revision_id VARCHAR(47) NOT NULL,
previous_revision_id VARCHAR(47),
expected_version INTEGER NOT NULL,
state VARCHAR(16) NOT NULL,
reserved_at TIMESTAMP WITH TIME ZONE NOT NULL,
completed_at TIMESTAMP WITH TIME ZONE,
PRIMARY KEY (command_id),
CONSTRAINT fk_kakao_packet_command_binding FOREIGN KEY(owner_operator_id, source_binding_id)
REFERENCES kakao_channel_bindings (owner_operator_id, source_binding_id) ON DELETE RESTRICT,
CONSTRAINT uq_kakao_packet_command_replay UNIQUE (owner_operator_id, idempotency_scope,
idempotency_key),
CONSTRAINT uq_kakao_packet_command_result UNIQUE (command_id, packet_id, packet_revision_id),
CONSTRAINT ck_kakao_packet_command_ids CHECK (command_id ~ '^kakaocommand_[0-9a-f]{32}$' AND
packet_id ~ '^kakaopacket_[0-9a-f]{32}$' AND packet_revision_id ~
'^kakaopacketrev_[0-9a-f]{32}$'),
CONSTRAINT ck_kakao_packet_command_request CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
idempotency_key ~ '^[!-~]{16,128}$'),
CONSTRAINT ck_kakao_packet_command_parent CHECK ((expected_version = 0 AND previous_revision_id
IS NULL) OR (expected_version BETWEEN 1 AND 2147483646 AND previous_revision_id IS NOT NULL)),
CONSTRAINT ck_kakao_packet_command_state CHECK ((state = 'RESERVED' AND completed_at IS NULL) OR
(state = 'COMPLETED' AND completed_at IS NOT NULL AND completed_at >= reserved_at))
)
""")
    op.execute("""
CREATE TABLE kakao_packet_revisions (
packet_revision_id VARCHAR(47) NOT NULL,
packet_id VARCHAR(44) NOT NULL,
owner_operator_id VARCHAR(41) NOT NULL,
source_binding_id VARCHAR(45) NOT NULL,
command_id VARCHAR(45) NOT NULL,
previous_revision_id VARCHAR(47),
resource_version INTEGER NOT NULL,
title VARCHAR(128) NOT NULL,
mode VARCHAR(8) NOT NULL,
include_replies BOOLEAN NOT NULL,
display_start_date DATE NOT NULL,
display_end_date_inclusive DATE NOT NULL,
question_count INTEGER NOT NULL,
student_count INTEGER NOT NULL,
manifest_artifact_id VARCHAR(41) NOT NULL,
manifest_artifact_revision_id VARCHAR(36) NOT NULL,
manifest_sha256 VARCHAR(71) NOT NULL,
publication_job_id VARCHAR(36) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE NOT NULL,
PRIMARY KEY (packet_revision_id),
CONSTRAINT fk_kakao_packet_revision_parent FOREIGN KEY(owner_operator_id, source_binding_id,
packet_id) REFERENCES kakao_packets (owner_operator_id, source_binding_id, packet_id) ON DELETE
RESTRICT,
CONSTRAINT fk_kakao_packet_revision_command FOREIGN KEY(command_id, packet_id,
packet_revision_id) REFERENCES kakao_packet_commands (command_id, packet_id, packet_revision_id)
ON DELETE RESTRICT,
CONSTRAINT fk_kakao_packet_previous FOREIGN KEY(packet_id, previous_revision_id) REFERENCES
kakao_packet_revisions (packet_id, packet_revision_id) ON DELETE RESTRICT,
CONSTRAINT fk_kakao_packet_manifest FOREIGN KEY(manifest_artifact_id,
manifest_artifact_revision_id) REFERENCES artifact_revisions (logical_artifact_id, revision_id)
ON DELETE RESTRICT,
CONSTRAINT uq_kakao_packet_revision UNIQUE (packet_id, packet_revision_id),
CONSTRAINT uq_kakao_packet_version UNIQUE (packet_id, resource_version),
CONSTRAINT uq_kakao_packet_current_version UNIQUE (packet_id, packet_revision_id,
resource_version),
CONSTRAINT ck_kakao_packet_revision_ids CHECK (packet_revision_id ~
'^kakaopacketrev_[0-9a-f]{32}$' AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'),
CONSTRAINT ck_kakao_packet_lineage CHECK ((resource_version = 1 AND previous_revision_id IS
NULL) OR (resource_version BETWEEN 2 AND 2147483647 AND previous_revision_id IS NOT NULL AND
previous_revision_id <> packet_revision_id)),
CONSTRAINT ck_kakao_packet_selection CHECK (mode IN ('DRAFT','FINAL') AND question_count BETWEEN
1 AND 200 AND student_count BETWEEN 1 AND question_count AND display_end_date_inclusive >=
display_start_date),
CONSTRAINT ck_kakao_packet_title CHECK (length(btrim(title)) BETWEEN 1 AND 128 AND title !~
'[[:cntrl:]]'),
FOREIGN KEY(publication_job_id) REFERENCES jobs (job_id) ON DELETE RESTRICT
)
""")
    op.execute("""
ALTER TABLE kakao_packets ADD CONSTRAINT fk_kakao_packet_current FOREIGN KEY(packet_id,
current_revision_id, resource_version) REFERENCES kakao_packet_revisions (packet_id,
packet_revision_id, resource_version) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
""")
    op.execute("""
CREATE INDEX ix_kakao_packet_page ON kakao_packets (owner_operator_id, source_binding_id,
packet_id)
""")
    op.execute("""
CREATE TRIGGER trg_kakao_packet_revision_immutable BEFORE UPDATE OR DELETE ON
kakao_packet_revisions FOR EACH ROW EXECUTE FUNCTION reject_control_plane_immutable_mutation()
""")
    op.execute("""
CREATE FUNCTION guard_kakao_packet_command() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.state = 'COMPLETED' THEN
        RAISE EXCEPTION 'KAKAO_PACKET_COMMAND_IMMUTABLE';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['state','completed_at']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['state','completed_at']) THEN
        RAISE EXCEPTION 'KAKAO_PACKET_INTENT_IMMUTABLE';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_packet_command_guard BEFORE UPDATE OR DELETE ON kakao_packet_commands
FOR EACH ROW EXECUTE FUNCTION guard_kakao_packet_command()
""")
    op.execute("""
CREATE FUNCTION guard_kakao_packet_head() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'KAKAO_PACKET_HISTORY_PROTECTED';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['current_revision_id','resource_version']) IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['current_revision_id','resource_version'])
       OR NEW.resource_version <> OLD.resource_version + 1
       OR NEW.current_revision_id = OLD.current_revision_id THEN
        RAISE EXCEPTION 'KAKAO_PACKET_CURRENT_INVALID';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER trg_kakao_packet_head_guard BEFORE UPDATE OR DELETE ON kakao_packets FOR EACH ROW
EXECUTE FUNCTION guard_kakao_packet_head()
""")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM kakao_packet_commands)")):
        raise RuntimeError("KAKAO_PACKET_HISTORY_PRESENT")
    op.drop_constraint("fk_kakao_packet_current", "kakao_packets", type_="foreignkey")
    op.drop_table("kakao_packet_revisions")
    op.drop_table("kakao_packet_commands")
    op.drop_table("kakao_packets")
    op.execute("DROP FUNCTION guard_kakao_packet_command()")
    op.execute("DROP FUNCTION guard_kakao_packet_head()")
