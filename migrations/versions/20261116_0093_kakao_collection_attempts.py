"""Pinned first collection attempts and immutable command/result evidence."""

from alembic import op

revision = "20261116_0093"
down_revision = "20261116_0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical DDL is self-contained, never imported from mutable runtime models.
    op.execute("""
        CREATE TABLE kakao_collection_attempts (
            attempt_id VARCHAR(45) NOT NULL PRIMARY KEY,
            run_id VARCHAR(41) NOT NULL,
            task_id VARCHAR(42) NOT NULL,
            command_id VARCHAR(45) NOT NULL,
            attempt_number INTEGER NOT NULL,
            source_binding_id VARCHAR(45) NOT NULL,
            room_id VARCHAR(42) NOT NULL,
            profile_id VARCHAR(45) NOT NULL,
            browser_run_id VARCHAR(48) NOT NULL,
            fence INTEGER NOT NULL,
            snapshot_revision_id VARCHAR(49) NOT NULL,
            normalization_revision_id VARCHAR(54) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            resource_version INTEGER NOT NULL,
            state VARCHAR(16) NOT NULL,
            command_artifact_id VARCHAR(41), command_artifact_revision_id VARCHAR(36),
            command_sha256 VARCHAR(71), capability_sha256 VARCHAR(71),
            inventory_artifact_id VARCHAR(41), inventory_artifact_revision_id VARCHAR(36),
            inventory_sha256 VARCHAR(71),
            result_artifact_id VARCHAR(41), result_artifact_revision_id VARCHAR(36),
            result_sha256 VARCHAR(71), result_status VARCHAR(16),
            report_sha256 VARCHAR(71), error_code VARCHAR(32),
            CONSTRAINT uq_kakao_collection_first_attempt UNIQUE (task_id),
            CONSTRAINT uq_kakao_collection_command UNIQUE (command_id),
            CONSTRAINT fk_kakao_collection_attempt_task FOREIGN KEY(task_id)
                REFERENCES kakao_collection_tasks (task_id) ON DELETE RESTRICT,
            CONSTRAINT fk_kakao_collection_attempt_browser FOREIGN KEY(run_id, browser_run_id)
                REFERENCES kakao_collection_browsers (run_id, browser_run_id) ON DELETE RESTRICT,
            CONSTRAINT fk_kakao_collection_attempt_command
                FOREIGN KEY(command_artifact_id, command_artifact_revision_id)
                REFERENCES artifact_revisions (logical_artifact_id, revision_id) ON DELETE RESTRICT,
            CONSTRAINT fk_kakao_collection_attempt_result
                FOREIGN KEY(result_artifact_id, result_artifact_revision_id)
                REFERENCES artifact_revisions (logical_artifact_id, revision_id) ON DELETE RESTRICT,
            CONSTRAINT fk_kakao_collection_attempt_inventory
                FOREIGN KEY(inventory_artifact_id, inventory_artifact_revision_id)
                REFERENCES artifact_revisions (logical_artifact_id, revision_id) ON DELETE RESTRICT,
            CONSTRAINT ck_kakao_collection_attempt_values CHECK (
                attempt_id ~ '^kakaoattempt_[0-9a-f]{32}$' AND
                command_id ~ '^kakaocommand_[0-9a-f]{32}$' AND
                snapshot_revision_id ~ '^kakaosnapshotrev_[0-9a-f]{32}$' AND
                normalization_revision_id ~ '^kakaonormalizationrev_[0-9a-f]{32}$' AND
                attempt_number = 1 AND fence BETWEEN 1 AND 2147483647 AND
                resource_version BETWEEN 1 AND 2147483647 AND updated_at >= created_at),
            CONSTRAINT ck_kakao_collection_attempt_state CHECK (
                state IN ('RESERVED','COMMAND_READY','RESULT_ACCEPTED')),
            CONSTRAINT ck_kakao_collection_attempt_command CHECK (
                (state = 'RESERVED' AND command_artifact_id IS NULL AND
                command_artifact_revision_id IS NULL AND command_sha256 IS NULL AND
                capability_sha256 IS NULL AND inventory_artifact_id IS NULL AND
                inventory_artifact_revision_id IS NULL AND inventory_sha256 IS NULL) OR
                (state <> 'RESERVED' AND
                command_artifact_id IS NOT NULL AND command_artifact_revision_id IS NOT NULL AND
                command_sha256 IS NOT NULL AND command_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
                capability_sha256 IS NOT NULL AND capability_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
                inventory_artifact_id IS NOT NULL AND inventory_artifact_revision_id IS NOT NULL AND
                inventory_sha256 IS NOT NULL AND inventory_sha256 ~ '^sha256:[0-9a-f]{64}$')),
            CONSTRAINT ck_kakao_collection_attempt_result CHECK (
                (state <> 'RESULT_ACCEPTED' AND result_artifact_id IS NULL AND
                result_artifact_revision_id IS NULL AND result_sha256 IS NULL AND
                result_status IS NULL AND report_sha256 IS NULL AND error_code IS NULL) OR
                (state = 'RESULT_ACCEPTED' AND result_artifact_id IS NOT NULL AND
                result_artifact_revision_id IS NOT NULL AND result_sha256 IS NOT NULL AND
                result_sha256 ~ '^sha256:[0-9a-f]{64}$' AND result_status IS NOT NULL AND
                result_status IN ('COMPLETED','PARTIAL','FAILED','PAUSED','CANCELLED') AND
                ((result_status IN ('COMPLETED','PARTIAL') AND report_sha256 IS NOT NULL AND
                report_sha256 ~ '^sha256:[0-9a-f]{64}$') OR
                (result_status NOT IN ('COMPLETED','PARTIAL') AND report_sha256 IS NULL)) AND
                ((result_status = 'FAILED' AND error_code IS NOT NULL) OR
                (result_status <> 'FAILED' AND error_code IS NULL)))),
            CONSTRAINT ck_kakao_collection_attempt_error CHECK (
                error_code IS NULL OR error_code IN ('NETWORK_TRANSIENT','RATE_LIMITED',
                'AUTH_REQUIRED','ACCESS_DENIED','UI_CHANGED','ENUMERATION_STALLED','HASH_MISMATCH',
                'DISK_FULL','TIMEOUT','PUBLICATION_UNAVAILABLE','INVALID_INPUT'))
        );
        CREATE FUNCTION protect_kakao_collection_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_ATTEMPT_IMMUTABLE';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.state <> 'RESERVED' OR NEW.resource_version <> 1 OR
               NEW.created_at <> NEW.updated_at OR NOT EXISTS (
                  SELECT 1 FROM kakao_collection_tasks t
                  JOIN kakao_collection_browsers b ON b.run_id = t.run_id
                  WHERE t.task_id = NEW.task_id AND t.run_id = NEW.run_id
                    AND t.source_binding_id = NEW.source_binding_id AND t.room_id = NEW.room_id
                    AND b.browser_run_id = NEW.browser_run_id AND b.phase = 'RUNNING'
                    AND b.profile_id = NEW.profile_id AND b.fence_epoch = NEW.fence
                    AND NEW.created_at >= b.browser_observed_at) THEN
              RAISE EXCEPTION 'KAKAO_COLLECTION_ATTEMPT_INITIAL_STATE_INVALID';
            END IF;
            RETURN NEW;
          END IF;
          IF OLD.state = 'RESULT_ACCEPTED' OR
             NEW.resource_version <> OLD.resource_version + 1 OR NEW.updated_at < OLD.updated_at OR
             (OLD.state,NEW.state) NOT IN
                (('RESERVED','COMMAND_READY'),('COMMAND_READY','RESULT_ACCEPTED')) OR
             (to_jsonb(NEW) - ARRAY['state','resource_version','updated_at','command_artifact_id',
                'command_artifact_revision_id','command_sha256','capability_sha256',
                'inventory_artifact_id','inventory_artifact_revision_id','inventory_sha256',
                'result_artifact_id','result_artifact_revision_id','result_sha256',
                'result_status','report_sha256','error_code']) IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['state','resource_version','updated_at','command_artifact_id',
                'command_artifact_revision_id','command_sha256','capability_sha256',
                'inventory_artifact_id','inventory_artifact_revision_id','inventory_sha256',
                'result_artifact_id','result_artifact_revision_id','result_sha256',
                'result_status','report_sha256','error_code']) OR
             (OLD.state <> 'RESERVED' AND ROW(NEW.command_artifact_id,
                NEW.command_artifact_revision_id,NEW.command_sha256,NEW.capability_sha256,
                NEW.inventory_artifact_id,NEW.inventory_artifact_revision_id,NEW.inventory_sha256)
                IS DISTINCT FROM ROW(OLD.command_artifact_id,OLD.command_artifact_revision_id,
                OLD.command_sha256,OLD.capability_sha256,
                OLD.inventory_artifact_id,OLD.inventory_artifact_revision_id,
                OLD.inventory_sha256)) THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_ATTEMPT_IMMUTABLE';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER protect_kakao_collection_attempt BEFORE INSERT OR UPDATE OR DELETE
          ON kakao_collection_attempts FOR EACH ROW
          EXECUTE FUNCTION protect_kakao_collection_attempt();
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM kakao_collection_attempts) THEN
            RAISE EXCEPTION 'KAKAO_COLLECTION_ATTEMPT_HISTORY_REQUIRES_REVIEW';
          END IF;
        END $$;
    """)
    op.drop_table("kakao_collection_attempts")
    op.execute("DROP FUNCTION protect_kakao_collection_attempt()")
