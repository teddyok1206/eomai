"""Durable mixed-material learning pointers and source-local sequential tasks.

Revision ID: 20261105_0074
Revises: 20261105_0073
Create Date: 2026-11-05 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261105_0074"
down_revision = "20261105_0073"
branch_labels = None
depends_on = None

_CAPACITY_PREDECESSOR = (
    "(max_configured_slots BETWEEN 1 AND 6 AND max_active_codex BETWEEN 1 AND 3 "
    "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
    "AND max_active_gpu = 1 AND (max_active_knowledge_analysis BETWEEN 1 AND 2 "
    "OR (schema_version = 'worker-capacity-policy/1.4' "
    "AND max_active_knowledge_analysis = 3))) OR "
    "(schema_version = 'worker-capacity-policy/1.5' AND max_configured_slots = 6 "
    "AND max_active_codex = 4 AND max_active_per_slot = 1 AND max_active_gpu = 1 "
    "AND max_active_knowledge_analysis = 4)"
)
_CAPACITY_SUCCESSOR = (
    "(" + _CAPACITY_PREDECESSOR + ") OR "
    "(schema_version = 'worker-capacity-policy/1.6' AND max_configured_slots = 6 "
    "AND max_active_codex = 4 AND max_active_per_slot = 1 AND max_active_gpu = 1 "
    "AND max_active_knowledge_analysis = 4)"
)

# Frozen DDL: this migration never imports a future application model.
_DDL = (
    """CREATE TABLE learning_materials (
    material_id VARCHAR(41) NOT NULL,
    current_revision_id VARCHAR(44),
    lifecycle_state VARCHAR(16) NOT NULL,
    created_by VARCHAR(41) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (material_id),
    CONSTRAINT ck_learning_material_lifecycle CHECK (lifecycle_state IN ('ACTIVE',
        'RETIRED')),
    FOREIGN KEY(created_by) REFERENCES operators (operator_id) ON DELETE RESTRICT
)""",
    """CREATE TABLE learning_material_revisions (
    material_revision_id VARCHAR(44) NOT NULL,
    material_id VARCHAR(41) NOT NULL,
    revision_number INTEGER NOT NULL,
    previous_revision_id VARCHAR(44),
    title VARCHAR(200) NOT NULL,
    material_kind VARCHAR(32) NOT NULL,
    request_sha256 VARCHAR(71) NOT NULL,
    manifest_artifact_id VARCHAR(41) NOT NULL,
    manifest_artifact_revision_id VARCHAR(36) NOT NULL,
    manifest_member_path VARCHAR(512) NOT NULL,
    manifest_sha256 VARCHAR(71) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    created_by VARCHAR(41) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (material_revision_id),
    CONSTRAINT uq_learning_material_revision_number UNIQUE (material_id, revision_number),

    CONSTRAINT uq_learning_material_revision_owner UNIQUE (material_id, material_revision_id),

    CONSTRAINT uq_learning_material_revision_replay UNIQUE (created_by, idempotency_key),

    CONSTRAINT ck_learning_material_revision_number CHECK (revision_number > 0),
    CONSTRAINT ck_learning_material_kind CHECK (material_kind IN ('TEXTBOOK','REFERENCE_BOOK',
        'WORKBOOK','MOCK_EXAM','OTHER')),
    CONSTRAINT ck_learning_material_revision_hashes CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$'
        AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT fk_learning_material_revision_manifest FOREIGN KEY(manifest_artifact_id,
         manifest_artifact_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
         revision_id) ON DELETE RESTRICT,
    FOREIGN KEY(material_id) REFERENCES learning_materials (material_id) ON DELETE
        RESTRICT,
    FOREIGN KEY(previous_revision_id) REFERENCES learning_material_revisions (material_revision_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(created_by) REFERENCES operators (operator_id) ON DELETE RESTRICT
)""",
    """CREATE TABLE material_learning_runs (
    run_id VARCHAR(44) NOT NULL,
    material_revision_id VARCHAR(44) NOT NULL,
    attempt INTEGER NOT NULL,
    predecessor_run_id VARCHAR(44),
    state VARCHAR(32) NOT NULL,
    phase_before_wait VARCHAR(32),
    next_event_sequence INTEGER DEFAULT 1 NOT NULL,
    lease_owner VARCHAR(128),
    lease_token VARCHAR(32),
    lease_expires_at TIMESTAMP WITH TIME ZONE,
    prepared_artifact_id VARCHAR(41),
    prepared_artifact_revision_id VARCHAR(36),
    prepared_sha256 VARCHAR(71),
    error_code VARCHAR(128),
    created_by VARCHAR(41) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (run_id),
    CONSTRAINT uq_material_learning_run_attempt UNIQUE (material_revision_id, attempt),

    CONSTRAINT ck_material_learning_run_counters CHECK (attempt > 0 AND next_event_sequence
        > 0),
    CONSTRAINT ck_material_learning_run_state CHECK (state IN ('RECEIVED','PREPARING',
        'DISCOVERING','PROCESSING','WAITING_FOR_CAPACITY','PAUSED','COMPLETED','COMPLETED_WITH_EXCEPTIONS',
        'FAILED','CANCELLED')),
    CONSTRAINT ck_material_learning_run_lease CHECK ((lease_owner IS NULL AND lease_token
        IS NULL AND lease_expires_at IS NULL) OR (lease_owner IS NOT NULL AND lease_token
        IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CONSTRAINT ck_material_learning_prepared_pointer CHECK ((prepared_artifact_id
        IS NULL AND prepared_artifact_revision_id IS NULL AND prepared_sha256 IS NULL)
        OR (prepared_artifact_id IS NOT NULL AND prepared_artifact_revision_id IS
        NOT NULL AND prepared_sha256 IS NOT NULL AND prepared_sha256 ~ '^sha256:[0-9a-f]{64}$')),

    CONSTRAINT fk_material_learning_run_prepared FOREIGN KEY(prepared_artifact_id,
         prepared_artifact_revision_id) REFERENCES artifact_revisions (logical_artifact_id,
         revision_id) ON DELETE RESTRICT,
    FOREIGN KEY(material_revision_id) REFERENCES learning_material_revisions (material_revision_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(predecessor_run_id) REFERENCES material_learning_runs (run_id) ON
        DELETE RESTRICT,
    FOREIGN KEY(created_by) REFERENCES operators (operator_id) ON DELETE RESTRICT
)""",
    """CREATE TABLE material_learning_tasks (
    task_id VARCHAR(45) NOT NULL,
    run_id VARCHAR(44) NOT NULL,
    task_kind VARCHAR(16) NOT NULL,
    unit_key VARCHAR(128) NOT NULL,
    ordinal INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    predecessor_task_id VARCHAR(45),
    state VARCHAR(24) NOT NULL,
    execution_lane VARCHAR(32) DEFAULT 'MATERIAL_LEARNING' NOT NULL,
    input_artifact_id VARCHAR(41),
    input_artifact_revision_id VARCHAR(36),
    input_sha256 VARCHAR(71),
    workflow_id VARCHAR(41),
    output_artifact_id VARCHAR(41),
    output_artifact_revision_id VARCHAR(36),
    output_sha256 VARCHAR(71),
    item_revision_id VARCHAR(40),
    analysis_run_id VARCHAR(44),
    solution_analysis_run_id VARCHAR(44),
    graph_snapshot_revision_id VARCHAR(41),
    error_code VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (task_id),
    CONSTRAINT uq_material_learning_task_attempt UNIQUE (run_id, unit_key, attempt),

        CONSTRAINT uq_material_learning_task_owner UNIQUE (run_id, task_id),
        CONSTRAINT uq_material_learning_task_ordinal UNIQUE (run_id, ordinal),
    CONSTRAINT ck_material_learning_task_counters CHECK (ordinal > 0 AND attempt >
        0),
    CONSTRAINT ck_material_learning_task_kind CHECK (task_kind IN
        ('PREPARE','DISCOVER','EXPLANATION','QUESTION')),
    CONSTRAINT ck_material_learning_task_state CHECK (state IN ('PENDING','PREPARING',
        'READY','RUNNING','RESULT_READY','REGISTERED','ANALYZING','PUBLISHING','GRAPH_READY',
        'COMPLETED','EXCEPTION','FAILED','CANCELLED')),
    CONSTRAINT ck_material_learning_task_lane CHECK (execution_lane = 'MATERIAL_LEARNING'),

    CONSTRAINT ck_material_learning_task_input CHECK ((input_artifact_id IS NULL AND
        input_artifact_revision_id IS NULL AND input_sha256 IS NULL) OR (input_artifact_id
        IS NOT NULL AND input_artifact_revision_id IS NOT NULL AND input_sha256 IS
        NOT NULL AND input_sha256 ~ '^sha256:[0-9a-f]{64}$')),
    CONSTRAINT ck_material_learning_task_output CHECK ((output_artifact_id IS NULL
        AND output_artifact_revision_id IS NULL AND output_sha256 IS NULL) OR (output_artifact_id
        IS NOT NULL AND output_artifact_revision_id IS NOT NULL AND output_sha256
        IS NOT NULL AND output_sha256 ~ '^sha256:[0-9a-f]{64}$')),
    CONSTRAINT fk_material_learning_task_input FOREIGN KEY(input_artifact_id,
        input_artifact_revision_id)
        REFERENCES artifact_revisions (logical_artifact_id, revision_id) ON DELETE
        RESTRICT,
    CONSTRAINT fk_material_learning_task_output FOREIGN KEY(output_artifact_id,
        output_artifact_revision_id)
        REFERENCES artifact_revisions (logical_artifact_id, revision_id) ON DELETE
        RESTRICT,
    FOREIGN KEY(run_id) REFERENCES material_learning_runs (run_id) ON DELETE RESTRICT,

    FOREIGN KEY(predecessor_task_id) REFERENCES material_learning_tasks (task_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(workflow_id) REFERENCES workflow_instances (workflow_id) ON DELETE
        RESTRICT,
    FOREIGN KEY(item_revision_id) REFERENCES item_revisions (item_revision_id) ON
        DELETE RESTRICT,
    FOREIGN KEY(analysis_run_id) REFERENCES knowledge_analysis_runs (analysis_run_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(solution_analysis_run_id) REFERENCES knowledge_analysis_runs (analysis_run_id)
        ON DELETE RESTRICT,
    FOREIGN KEY(graph_snapshot_revision_id) REFERENCES knowledge_graph_snapshots
        (graph_snapshot_revision_id)
        ON DELETE RESTRICT
)""",
    """CREATE TABLE material_learning_events (
    event_id BIGINT GENERATED BY DEFAULT AS IDENTITY,
    run_id VARCHAR(44) NOT NULL,
    task_id VARCHAR(45),
    sequence INTEGER NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    prior_state VARCHAR(32),
    new_state VARCHAR(32) NOT NULL,
    error_code VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (event_id),
    CONSTRAINT uq_material_learning_event_sequence UNIQUE (run_id, sequence),
    CONSTRAINT ck_material_learning_event_sequence CHECK (sequence > 0),
    CONSTRAINT fk_material_learning_event_task FOREIGN KEY(run_id, task_id) REFERENCES
        material_learning_tasks (run_id, task_id) ON DELETE RESTRICT,
    FOREIGN KEY(run_id) REFERENCES material_learning_runs (run_id) ON DELETE RESTRICT
)""",
    """ALTER TABLE learning_materials ADD CONSTRAINT fk_learning_material_current_revision
        FOREIGN KEY(material_id, current_revision_id) REFERENCES learning_material_revisions
        (material_id, material_revision_id) ON DELETE RESTRICT""",
    """CREATE INDEX ix_learning_material_owner_recent ON learning_materials (created_by,
        created_at DESC, material_id)""",
    """CREATE INDEX ix_material_learning_next_run ON material_learning_runs
        (state, lease_expires_at,
         created_at, run_id)""",
    """CREATE UNIQUE INDEX uq_material_learning_live_revision ON material_learning_runs
        (material_revision_id)
        WHERE state NOT IN ('COMPLETED','COMPLETED_WITH_EXCEPTIONS','FAILED','CANCELLED')""",
    """CREATE INDEX ix_material_learning_next_task ON material_learning_tasks (run_id, state,
         ordinal, attempt)""",
    """CREATE UNIQUE INDEX uq_material_learning_child_workflow ON material_learning_tasks
       (workflow_id) WHERE workflow_id IS NOT NULL""",
    """CREATE UNIQUE INDEX uq_material_learning_child_analysis ON material_learning_tasks
       (analysis_run_id) WHERE analysis_run_id IS NOT NULL""",
    """CREATE UNIQUE INDEX uq_material_learning_child_solution ON material_learning_tasks
       (solution_analysis_run_id) WHERE solution_analysis_run_id IS NOT NULL""",
    """CREATE INDEX ix_material_learning_registered_item ON material_learning_tasks
        (item_revision_id)""",
    """CREATE UNIQUE INDEX uq_material_learning_one_ai ON material_learning_tasks (execution_lane)
        WHERE state IN ('RUNNING','ANALYZING')""",
)

_HISTORY = """
CREATE FUNCTION protect_material_learning_history() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE previous jsonb; following jsonb; pinned text;
BEGIN
IF TG_OP = 'DELETE' OR TG_ARGV[0] = 'FROZEN' THEN
    RAISE EXCEPTION 'MATERIAL_LEARNING_HISTORY_IMMUTABLE' USING ERRCODE='23514';
END IF;
previous := to_jsonb(OLD); following := to_jsonb(NEW);
IF TG_ARGV[0] = 'MATERIAL' THEN
    IF (following - ARRAY['current_revision_id','lifecycle_state']) IS DISTINCT FROM
       (previous - ARRAY['current_revision_id','lifecycle_state']) OR
       (OLD.lifecycle_state = 'RETIRED' AND NEW IS DISTINCT FROM OLD) THEN
        RAISE EXCEPTION 'MATERIAL_LEARNING_IDENTITY_IMMUTABLE' USING ERRCODE='23514';
    END IF;
ELSIF TG_ARGV[0] = 'RUN' THEN
    IF (following - ARRAY['state','phase_before_wait','next_event_sequence','lease_owner',
       'lease_token','lease_expires_at','prepared_artifact_id',
       'prepared_artifact_revision_id','prepared_sha256','error_code','updated_at'])
       IS DISTINCT FROM
       (previous - ARRAY['state','phase_before_wait','next_event_sequence','lease_owner',
       'lease_token','lease_expires_at','prepared_artifact_id',
       'prepared_artifact_revision_id','prepared_sha256','error_code','updated_at'])
       OR (OLD.state IN ('COMPLETED','COMPLETED_WITH_EXCEPTIONS','FAILED','CANCELLED')
           AND NEW IS DISTINCT FROM OLD) THEN
        RAISE EXCEPTION 'MATERIAL_LEARNING_RUN_HISTORY_IMMUTABLE' USING ERRCODE='23514';
    END IF;
    FOREACH pinned IN ARRAY ARRAY['prepared_artifact_id','prepared_artifact_revision_id',
                                 'prepared_sha256'] LOOP
        IF previous->pinned <> 'null'::jsonb AND
           following->pinned IS DISTINCT FROM previous->pinned THEN
            RAISE EXCEPTION 'MATERIAL_LEARNING_PREPARED_PIN_IMMUTABLE' USING ERRCODE='23514';
        END IF;
    END LOOP;
ELSIF TG_ARGV[0] = 'TASK' THEN
    IF (following - ARRAY['state','input_artifact_id','input_artifact_revision_id',
       'input_sha256','workflow_id','output_artifact_id','output_artifact_revision_id',
       'output_sha256','item_revision_id','analysis_run_id','solution_analysis_run_id',
       'graph_snapshot_revision_id',
       'error_code','updated_at']) IS DISTINCT FROM
       (previous - ARRAY['state','input_artifact_id','input_artifact_revision_id',
       'input_sha256','workflow_id','output_artifact_id','output_artifact_revision_id',
       'output_sha256','item_revision_id','analysis_run_id','solution_analysis_run_id',
       'graph_snapshot_revision_id',
       'error_code','updated_at'])
       OR (OLD.state IN ('COMPLETED','EXCEPTION','FAILED','CANCELLED')
           AND NEW IS DISTINCT FROM OLD) THEN
        RAISE EXCEPTION 'MATERIAL_LEARNING_TASK_HISTORY_IMMUTABLE' USING ERRCODE='23514';
    END IF;
    FOREACH pinned IN ARRAY ARRAY['input_artifact_id','input_artifact_revision_id',
        'input_sha256','workflow_id','output_artifact_id','output_artifact_revision_id',
        'output_sha256','item_revision_id','analysis_run_id','solution_analysis_run_id',
        'graph_snapshot_revision_id'] LOOP
        IF previous->pinned <> 'null'::jsonb AND
           following->pinned IS DISTINCT FROM previous->pinned THEN
            RAISE EXCEPTION 'MATERIAL_LEARNING_TASK_PIN_IMMUTABLE' USING ERRCODE='23514';
        END IF;
    END LOOP;
END IF;
RETURN NEW;
END;
$$
"""

_TABLES = (
    ("learning_materials", "MATERIAL"),
    ("learning_material_revisions", "FROZEN"),
    ("material_learning_runs", "RUN"),
    ("material_learning_tasks", "TASK"),
    ("material_learning_events", "FROZEN"),
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_capacity_policy_host_limits", "worker_capacity_policy_revisions", type_="check"
    )
    op.create_check_constraint(
        "ck_capacity_policy_host_limits", "worker_capacity_policy_revisions", _CAPACITY_SUCCESSOR
    )
    for statement in _DDL:
        op.execute(statement)
    op.execute(_HISTORY)
    for table, protection in _TABLES:
        op.execute(
            f"CREATE TRIGGER protect_{table}_history BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION protect_material_learning_history('{protection}')"
        )


def downgrade() -> None:
    # Reverting code never authorizes throwing away uploaded source lineage/history.
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM worker_capacity_policy_revisions "
            "WHERE schema_version='worker-capacity-policy/1.6')"
        )
    ):
        raise RuntimeError("MATERIAL_LEARNING_CAPACITY_HISTORY_EXISTS")
    for table, _ in _TABLES:
        if op.get_bind().scalar(text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("MATERIAL_LEARNING_HISTORY_EXISTS")
    op.execute(
        "ALTER TABLE learning_materials DROP CONSTRAINT fk_learning_material_current_revision"
    )
    for table, _ in reversed(_TABLES):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION protect_material_learning_history()")
    op.drop_constraint(
        "ck_capacity_policy_host_limits", "worker_capacity_policy_revisions", type_="check"
    )
    op.create_check_constraint(
        "ck_capacity_policy_host_limits", "worker_capacity_policy_revisions", _CAPACITY_PREDECESSOR
    )
