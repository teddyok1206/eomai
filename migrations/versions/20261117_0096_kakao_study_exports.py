"""Optional immutable source link; existing PDF history and formats stay unchanged."""

from alembic import op

revision = "20261117_0096"
down_revision = "20261117_0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE kakao_export_studies (
        export_id VARCHAR(44) PRIMARY KEY, owner_operator_id VARCHAR(41) NOT NULL,
        source_binding_id VARCHAR(45) NOT NULL, study_id VARCHAR(43) NOT NULL,
        study_revision_id VARCHAR(46) NOT NULL, manifest_sha256 VARCHAR(71) NOT NULL,
        CONSTRAINT fk_kakao_export_study_owner
          FOREIGN KEY(owner_operator_id,source_binding_id,export_id)
          REFERENCES kakao_exports(owner_operator_id,source_binding_id,export_id)
          ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_export_study_source_owner
          FOREIGN KEY(owner_operator_id,source_binding_id,study_id)
          REFERENCES kakao_studies(owner_operator_id,source_binding_id,study_id) ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_export_study_revision FOREIGN KEY(study_id,study_revision_id)
          REFERENCES kakao_study_revisions(study_id,study_revision_id) ON DELETE RESTRICT,
        CONSTRAINT ck_kakao_export_study_hash CHECK(manifest_sha256 ~ '^sha256:[0-9a-f]{64}$')
      );
      CREATE INDEX ix_kakao_export_studies_study_id ON kakao_export_studies(study_id);
      CREATE TRIGGER trg_kakao_export_study_immutable BEFORE UPDATE OR DELETE
        ON kakao_export_studies FOR EACH ROW
        EXECUTE FUNCTION reject_control_plane_immutable_mutation();
      CREATE FUNCTION guard_kakao_export_study_initial() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NOT EXISTS(SELECT 1 FROM kakao_exports e JOIN kakao_studies s
          ON s.study_id=NEW.study_id JOIN kakao_study_revisions r
          ON r.study_id=s.study_id AND r.study_revision_id=NEW.study_revision_id
          WHERE e.export_id=NEW.export_id AND e.owner_operator_id=NEW.owner_operator_id
          AND e.source_binding_id=NEW.source_binding_id AND e.attempt_number=0
          AND e.current_attempt_id IS NULL AND e.profile->>'layout_policy'='student-study-a4/1.0'
          AND e.packet_id=s.packet_id AND e.packet_revision_id=s.packet_revision_id
          AND e.student_id=s.student_id AND r.manifest_sha256=NEW.manifest_sha256) THEN
          RAISE EXCEPTION 'KAKAO_STUDY_EXPORT_INITIAL_INVALID'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER trg_kakao_export_study_initial BEFORE INSERT ON kakao_export_studies
        FOR EACH ROW EXECUTE FUNCTION guard_kakao_export_study_initial();
    """)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM kakao_export_studies) THEN
      RAISE EXCEPTION 'KAKAO_STUDY_EXPORT_HISTORY_REQUIRES_REVIEW'; END IF; END $$;""")
    op.drop_table("kakao_export_studies")
    op.execute("DROP FUNCTION guard_kakao_export_study_initial();")
