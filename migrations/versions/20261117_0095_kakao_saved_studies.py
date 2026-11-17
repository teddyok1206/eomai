"""Editable student study selections pin their original packet and concept results."""

from alembic import op

revision = "20261117_0095"
down_revision = "20261117_0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE kakao_studies (
        study_id VARCHAR(43) PRIMARY KEY, owner_operator_id VARCHAR(41) NOT NULL,
        source_binding_id VARCHAR(45) NOT NULL, packet_id VARCHAR(44) NOT NULL,
        packet_revision_id VARCHAR(47) NOT NULL, student_id VARCHAR(45) NOT NULL,
        current_revision_id VARCHAR(46) NOT NULL, resource_version INTEGER NOT NULL,
        CONSTRAINT fk_kakao_study_packet FOREIGN KEY(owner_operator_id,source_binding_id,packet_id)
          REFERENCES kakao_packets(owner_operator_id,source_binding_id,packet_id)
          ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_study_packet_revision FOREIGN KEY(packet_id,packet_revision_id)
          REFERENCES kakao_packet_revisions(packet_id,packet_revision_id) ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_study_student FOREIGN KEY(student_id)
          REFERENCES kakao_students(student_id) ON DELETE RESTRICT,
        CONSTRAINT uq_kakao_study_owner UNIQUE(owner_operator_id,source_binding_id,study_id),
        CONSTRAINT ck_kakao_study_head CHECK(study_id ~ '^kakaostudy_[0-9a-f]{32}$'
          AND resource_version BETWEEN 1 AND 2147483647)
      );
      CREATE INDEX ix_kakao_study_page
        ON kakao_studies(owner_operator_id,source_binding_id,study_id);
      CREATE TABLE kakao_study_commands (
        command_id VARCHAR(45) PRIMARY KEY, owner_operator_id VARCHAR(41) NOT NULL,
        source_binding_id VARCHAR(45) NOT NULL, idempotency_key VARCHAR(128) NOT NULL,
        request_sha256 VARCHAR(71) NOT NULL, study_id VARCHAR(43) NOT NULL,
        study_revision_id VARCHAR(46) NOT NULL, previous_revision_id VARCHAR(46),
        expected_version INTEGER NOT NULL, state VARCHAR(16) NOT NULL,
        reserved_at TIMESTAMP WITH TIME ZONE NOT NULL, completed_at TIMESTAMP WITH TIME ZONE,
        CONSTRAINT fk_kakao_study_command_binding FOREIGN KEY(owner_operator_id,source_binding_id)
          REFERENCES kakao_channel_bindings(owner_operator_id,source_binding_id) ON DELETE RESTRICT,
        CONSTRAINT uq_kakao_study_replay UNIQUE(owner_operator_id,idempotency_key),
        CONSTRAINT uq_kakao_study_command_result UNIQUE(command_id,study_id,study_revision_id),
        CONSTRAINT ck_kakao_study_command_ids CHECK(command_id ~ '^kakaocommand_[0-9a-f]{32}$'
          AND study_id ~ '^kakaostudy_[0-9a-f]{32}$'
          AND study_revision_id ~ '^kakaostudyrev_[0-9a-f]{32}$'),
        CONSTRAINT ck_kakao_study_command_hash CHECK(request_sha256 ~ '^sha256:[0-9a-f]{64}$'
          AND idempotency_key ~ '^[!-~]{16,128}$'),
        CONSTRAINT ck_kakao_study_command_parent CHECK(
          (expected_version=0 AND previous_revision_id IS NULL) OR
          (expected_version BETWEEN 1 AND 2147483646 AND previous_revision_id IS NOT NULL)),
        CONSTRAINT ck_kakao_study_command_state CHECK(
          (state='RESERVED' AND completed_at IS NULL) OR
          (state='COMPLETED' AND completed_at IS NOT NULL AND completed_at >= reserved_at))
      );
      CREATE TABLE kakao_study_revisions (
        study_revision_id VARCHAR(46) PRIMARY KEY, study_id VARCHAR(43) NOT NULL,
        owner_operator_id VARCHAR(41) NOT NULL, source_binding_id VARCHAR(45) NOT NULL,
        command_id VARCHAR(45) NOT NULL, previous_revision_id VARCHAR(46),
        resource_version INTEGER NOT NULL, title VARCHAR(128) NOT NULL,
        question_count INTEGER NOT NULL, manifest_artifact_id VARCHAR(41) NOT NULL,
        manifest_artifact_revision_id VARCHAR(36) NOT NULL, manifest_sha256 VARCHAR(71) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        CONSTRAINT fk_kakao_study_revision_owner
          FOREIGN KEY(owner_operator_id,source_binding_id,study_id)
          REFERENCES kakao_studies(owner_operator_id,source_binding_id,study_id) ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_study_revision_command
          FOREIGN KEY(command_id,study_id,study_revision_id)
          REFERENCES kakao_study_commands(command_id,study_id,study_revision_id) ON DELETE RESTRICT,
        CONSTRAINT uq_kakao_study_revision UNIQUE(study_id,study_revision_id),
        CONSTRAINT uq_kakao_study_version UNIQUE(study_id,resource_version),
        CONSTRAINT uq_kakao_study_current_version
          UNIQUE(study_id,study_revision_id,resource_version),
        CONSTRAINT fk_kakao_study_previous FOREIGN KEY(study_id,previous_revision_id)
          REFERENCES kakao_study_revisions(study_id,study_revision_id) ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_study_manifest
          FOREIGN KEY(manifest_artifact_id,manifest_artifact_revision_id)
          REFERENCES artifact_revisions(logical_artifact_id,revision_id) ON DELETE RESTRICT,
        CONSTRAINT ck_kakao_study_revision_ids CHECK(
          study_revision_id ~ '^kakaostudyrev_[0-9a-f]{32}$'
          AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'),
        CONSTRAINT ck_kakao_study_revision_parent CHECK(
          (resource_version=1 AND previous_revision_id IS NULL) OR
          (resource_version BETWEEN 2 AND 2147483647 AND previous_revision_id IS NOT NULL
          AND previous_revision_id <> study_revision_id)),
        CONSTRAINT ck_kakao_study_revision_summary CHECK(question_count BETWEEN 1 AND 200
          AND length(btrim(title)) BETWEEN 1 AND 128 AND title !~ '[[:cntrl:]]')
      );
      ALTER TABLE kakao_studies ADD CONSTRAINT fk_kakao_study_current
        FOREIGN KEY(study_id,current_revision_id,resource_version)
        REFERENCES kakao_study_revisions(study_id,study_revision_id,resource_version)
        ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
      CREATE TRIGGER trg_kakao_study_revision_immutable BEFORE UPDATE OR DELETE
        ON kakao_study_revisions FOR EACH ROW
        EXECUTE FUNCTION reject_control_plane_immutable_mutation();
      CREATE FUNCTION guard_kakao_study_command() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' OR OLD.state='COMPLETED' OR NEW.state <> 'COMPLETED' OR
          (to_jsonb(OLD) - ARRAY['state','completed_at']) IS DISTINCT FROM
          (to_jsonb(NEW) - ARRAY['state','completed_at']) THEN
          RAISE EXCEPTION 'KAKAO_STUDY_COMMAND_IMMUTABLE'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER trg_kakao_study_command_guard BEFORE UPDATE OR DELETE
        ON kakao_study_commands FOR EACH ROW EXECUTE FUNCTION guard_kakao_study_command();
      CREATE FUNCTION guard_kakao_study_head() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='DELETE' OR NEW.resource_version <> OLD.resource_version+1 OR
          NEW.current_revision_id=OLD.current_revision_id OR
          (to_jsonb(OLD) - ARRAY['current_revision_id','resource_version']) IS DISTINCT FROM
          (to_jsonb(NEW) - ARRAY['current_revision_id','resource_version']) THEN
          RAISE EXCEPTION 'KAKAO_STUDY_HEAD_IMMUTABLE'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER trg_kakao_study_head_guard BEFORE UPDATE OR DELETE
        ON kakao_studies FOR EACH ROW EXECUTE FUNCTION guard_kakao_study_head();
    """)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM kakao_study_commands) THEN
      RAISE EXCEPTION 'KAKAO_STUDY_HISTORY_REQUIRES_REVIEW'; END IF; END $$;""")
    op.drop_constraint("fk_kakao_study_current", "kakao_studies", type_="foreignkey")
    op.drop_table("kakao_study_revisions")
    op.drop_table("kakao_study_commands")
    op.drop_table("kakao_studies")
    op.execute("DROP FUNCTION guard_kakao_study_command(); DROP FUNCTION guard_kakao_study_head();")
