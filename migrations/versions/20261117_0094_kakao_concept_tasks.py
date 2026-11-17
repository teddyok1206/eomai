"""Private concept intent and phase source pins, without a separate worker queue."""

from alembic import op

revision = "20261117_0094"
down_revision = "20261116_0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE kakao_concept_tasks (
        task_id VARCHAR(49) PRIMARY KEY,
        owner_operator_id VARCHAR(41) NOT NULL, identity_session_id VARCHAR(64) NOT NULL,
        source_binding_id VARCHAR(45) NOT NULL, room_id VARCHAR(42) NOT NULL,
        question_id VARCHAR(46) NOT NULL, question_revision_id VARCHAR(49) NOT NULL,
        question_version INTEGER NOT NULL, idempotency_key VARCHAR(128) NOT NULL,
        request_sha256 VARCHAR(71) NOT NULL, scope JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL, prepared_at TIMESTAMP WITH TIME ZONE,
        intent_artifact_id VARCHAR(41), intent_artifact_revision_id VARCHAR(36),
        intent_sha256 VARCHAR(71),
        CONSTRAINT uq_kakao_concept_request UNIQUE(owner_operator_id,idempotency_key),
        CONSTRAINT fk_kakao_concept_room FOREIGN KEY(owner_operator_id,source_binding_id,room_id)
          REFERENCES kakao_rooms(owner_operator_id,source_binding_id,room_id) ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_concept_question FOREIGN KEY(question_id,room_id)
          REFERENCES kakao_questions(question_id,room_id) ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_concept_revision FOREIGN KEY(question_id,question_revision_id)
          REFERENCES kakao_question_revisions(question_id,question_revision_id) ON DELETE RESTRICT,
        CONSTRAINT fk_kakao_concept_intent
          FOREIGN KEY(intent_artifact_id,intent_artifact_revision_id)
          REFERENCES artifact_revisions(logical_artifact_id,revision_id) ON DELETE RESTRICT,
        CONSTRAINT ck_kakao_concept_values CHECK (
          task_id ~ '^kakaoconcepttask_[0-9a-f]{32}$' AND
          request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
          idempotency_key ~ '^[!-~]{16,128}$' AND question_version BETWEEN 1 AND 2147483647),
        CONSTRAINT ck_kakao_concept_scope CHECK (
          jsonb_typeof(scope) = 'object' AND pg_column_size(scope) <= 2048),
        CONSTRAINT ck_kakao_concept_prepared CHECK (
          (intent_artifact_id IS NULL AND intent_artifact_revision_id IS NULL AND
           intent_sha256 IS NULL AND prepared_at IS NULL) OR
          (intent_artifact_id IS NOT NULL AND intent_artifact_revision_id IS NOT NULL AND
           intent_sha256 IS NOT NULL AND intent_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
           prepared_at IS NOT NULL AND prepared_at >= created_at))
      );
      CREATE INDEX ix_kakao_concept_history
        ON kakao_concept_tasks(owner_operator_id,source_binding_id,task_id);
      CREATE TABLE kakao_concept_phases (
        task_id VARCHAR(49) NOT NULL REFERENCES kakao_concept_tasks(task_id) ON DELETE RESTRICT,
        phase VARCHAR(7) NOT NULL, work_input JSONB NOT NULL, work_sha256 VARCHAR(71) NOT NULL,
        request_artifact_id VARCHAR(41) NOT NULL, request_artifact_revision_id VARCHAR(36) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        workflow_id VARCHAR(41) REFERENCES workflow_instances(workflow_id) ON DELETE RESTRICT,
        PRIMARY KEY(task_id,phase), CONSTRAINT uq_kakao_concept_phase_workflow UNIQUE(workflow_id),
        CONSTRAINT ck_kakao_concept_phase_values CHECK (
          phase IN ('PLAN','COMPOSE') AND work_sha256 ~ '^sha256:[0-9a-f]{64}$'),
        CONSTRAINT ck_kakao_concept_phase_work CHECK (
          jsonb_typeof(work_input) = 'object' AND pg_column_size(work_input) <= 65536 AND
          work_input ?& ARRAY['task_id','phase','request_member'] AND
          work_input->>'task_id' = task_id AND work_input->>'phase' = phase),
        CONSTRAINT fk_kakao_concept_phase_request
          FOREIGN KEY(request_artifact_id,request_artifact_revision_id)
          REFERENCES artifact_revisions(logical_artifact_id,revision_id) ON DELETE RESTRICT
      );
      CREATE FUNCTION protect_kakao_concept_task() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'KAKAO_CONCEPT_TASK_IMMUTABLE'; END IF;
        IF TG_OP = 'INSERT' THEN
          IF NEW.intent_artifact_id IS NOT NULL THEN
            RAISE EXCEPTION 'KAKAO_CONCEPT_TASK_INITIAL_INVALID'; END IF;
          RETURN NEW;
        END IF;
        IF OLD.intent_artifact_id IS NOT NULL OR NEW.intent_artifact_id IS NULL OR
          (to_jsonb(OLD) - ARRAY['prepared_at','intent_artifact_id',
            'intent_artifact_revision_id','intent_sha256']) IS DISTINCT FROM
          (to_jsonb(NEW) - ARRAY['prepared_at','intent_artifact_id',
            'intent_artifact_revision_id','intent_sha256']) THEN
          RAISE EXCEPTION 'KAKAO_CONCEPT_TASK_IMMUTABLE';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER protect_kakao_concept_task BEFORE INSERT OR UPDATE OR DELETE
        ON kakao_concept_tasks
        FOR EACH ROW EXECUTE FUNCTION protect_kakao_concept_task();
      CREATE FUNCTION protect_kakao_concept_phase() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'KAKAO_CONCEPT_PHASE_IMMUTABLE'; END IF;
        IF TG_OP = 'INSERT' THEN
          IF NEW.workflow_id IS NOT NULL OR NOT EXISTS (
            SELECT 1 FROM kakao_concept_tasks t WHERE t.task_id = NEW.task_id
              AND t.intent_artifact_id IS NOT NULL
              AND t.source_binding_id = NEW.work_input->>'source_binding_id'
              AND t.question_revision_id = NEW.work_input->>'question_revision_id') THEN
            RAISE EXCEPTION 'KAKAO_CONCEPT_PHASE_INITIAL_INVALID';
          END IF;
          RETURN NEW;
        END IF;
        IF OLD.workflow_id IS NOT NULL OR NEW.workflow_id IS NULL OR
          (to_jsonb(OLD) - 'workflow_id') IS DISTINCT FROM (to_jsonb(NEW) - 'workflow_id') THEN
          RAISE EXCEPTION 'KAKAO_CONCEPT_PHASE_IMMUTABLE';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER protect_kakao_concept_phase BEFORE INSERT OR UPDATE OR DELETE
        ON kakao_concept_phases
        FOR EACH ROW EXECUTE FUNCTION protect_kakao_concept_phase();
    """)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM kakao_concept_tasks) THEN
      RAISE EXCEPTION 'KAKAO_CONCEPT_HISTORY_REQUIRES_REVIEW'; END IF; END $$;""")
    op.drop_table("kakao_concept_phases")
    op.drop_table("kakao_concept_tasks")
    op.execute(
        "DROP FUNCTION protect_kakao_concept_phase(); DROP FUNCTION protect_kakao_concept_task();"
    )
