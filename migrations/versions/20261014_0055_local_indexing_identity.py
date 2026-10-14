"""Identity-owned local indexing metadata only; no runtime or source grants.

Revision ID: 20261014_0055
Revises: 20261013_0054
Create Date: 2026-10-14 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261014_0055"
down_revision: str | None = "20261013_0054"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen DDL: current models are never imported by an installed migration.
_DDL: tuple[str, ...] = (
    """
    CREATE TABLE local_indexing_services (
    service_id VARCHAR(50) NOT NULL,
    latest_revision_id VARCHAR(53) NOT NULL,
    current_revision_id VARCHAR(53),
    state VARCHAR(8) NOT NULL,
    resource_version INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (service_id),
    CONSTRAINT ck_lis_id CHECK (service_id ~ '^localindexservice_[0-9a-f]{32}$'),
    CONSTRAINT ck_lis_state CHECK (state IN ('ACTIVE','DISABLED') AND (state <> 'ACTIVE' OR
    current_revision_id IS NOT NULL)),
    CONSTRAINT ck_lis_version CHECK (resource_version >= 1 AND updated_at >= created_at)
    )
    """,
    """
    CREATE TABLE local_indexing_service_revisions (
    service_revision_id VARCHAR(53) NOT NULL,
    service_id VARCHAR(50) NOT NULL,
    schema_version VARCHAR(64) NOT NULL,
    previous_service_revision_id VARCHAR(53),
    revision_number INTEGER NOT NULL,
    purpose VARCHAR(32) NOT NULL,
    runtime_user VARCHAR(64) NOT NULL,
    database_role VARCHAR(63) NOT NULL,
    runtime_source_commit VARCHAR(40) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    content_sha256 VARCHAR(71) NOT NULL,
    PRIMARY KEY (service_revision_id),
    CONSTRAINT ck_lis_revision_identity CHECK (schema_version =
    'local-indexing-service-identity/1.0' AND service_revision_id ~
    '^localindexservicerev_[0-9a-f]{32}$' AND content_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT ck_lis_revision_chain CHECK ((revision_number = 1 AND
    previous_service_revision_id IS NULL) OR (revision_number > 1 AND
    previous_service_revision_id IS NOT NULL AND previous_service_revision_id <>
    service_revision_id)),
    CONSTRAINT ck_lis_revision_runtime CHECK (purpose = 'LOCAL_EMBEDDING_INDEX' AND runtime_user
    = 'eom-workflow-runner' AND database_role ~ '^[a-z][a-z0-9_]{0,62}$' AND database_role !~
    '[[:space:]]' AND runtime_source_commit ~ '^[0-9a-f]{40}$'),
    CONSTRAINT uq_lis_revision_identity UNIQUE (service_id, service_revision_id),
    CONSTRAINT uq_lis_revision_number UNIQUE (service_id, revision_number),
    CONSTRAINT uq_lis_successor UNIQUE (service_id, previous_service_revision_id),
    CONSTRAINT fk_lis_predecessor FOREIGN KEY(service_id, previous_service_revision_id)
    REFERENCES local_indexing_service_revisions (service_id, service_revision_id) ON DELETE
    RESTRICT,
    FOREIGN KEY(service_id) REFERENCES local_indexing_services (service_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE local_indexing_service_events (
    service_id VARCHAR(50) NOT NULL,
    sequence INTEGER NOT NULL,
    operation_key VARCHAR(128) NOT NULL,
    request_sha256 VARCHAR(71) NOT NULL,
    event_type VARCHAR(8) NOT NULL,
    actor_database_principal VARCHAR(63) NOT NULL,
    target_revision_id VARCHAR(53),
    expected_resource_version INTEGER,
    previous_state VARCHAR(8),
    previous_latest_revision_id VARCHAR(53),
    previous_current_revision_id VARCHAR(53),
    state_after VARCHAR(8) NOT NULL,
    latest_revision_id VARCHAR(53) NOT NULL,
    current_revision_id VARCHAR(53),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (service_id, sequence),
    CONSTRAINT uq_lis_operation_key UNIQUE (operation_key),
    CONSTRAINT ck_lis_event_sequence CHECK (sequence >= 1),
    CONSTRAINT ck_lis_event_shape CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND event_type
    IN ('REGISTER','ACTIVATE','DISABLE') AND state_after IN ('ACTIVE','DISABLED') AND
    (previous_state IS NULL OR previous_state IN ('ACTIVE','DISABLED')) AND (state_after <>
    'ACTIVE' OR current_revision_id IS NOT NULL)),
    CONSTRAINT ck_lis_event_operation CHECK ((event_type = 'REGISTER' AND target_revision_id IS
    NOT NULL AND expected_resource_version IS NULL) OR (event_type = 'ACTIVATE' AND
    target_revision_id IS NOT NULL AND expected_resource_version IS NOT NULL AND
    expected_resource_version = sequence - 1 AND expected_resource_version >= 1) OR (event_type
    = 'DISABLE' AND target_revision_id IS NULL AND expected_resource_version IS NOT NULL AND
    expected_resource_version = sequence - 1 AND expected_resource_version >= 1)),
    CONSTRAINT fk_lis_event_target FOREIGN KEY(service_id, target_revision_id) REFERENCES
    local_indexing_service_revisions (service_id, service_revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_lis_event_latest FOREIGN KEY(service_id, latest_revision_id) REFERENCES
    local_indexing_service_revisions (service_id, service_revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_lis_event_current FOREIGN KEY(service_id, current_revision_id) REFERENCES
    local_indexing_service_revisions (service_id, service_revision_id) ON DELETE RESTRICT,
    CONSTRAINT fk_lis_event_previous_latest FOREIGN KEY(service_id, previous_latest_revision_id)
    REFERENCES local_indexing_service_revisions (service_id, service_revision_id) ON DELETE
    RESTRICT,
    CONSTRAINT fk_lis_event_previous_current FOREIGN KEY(service_id,
    previous_current_revision_id) REFERENCES local_indexing_service_revisions (service_id,
    service_revision_id) ON DELETE RESTRICT,
    FOREIGN KEY(service_id) REFERENCES local_indexing_services (service_id) ON DELETE RESTRICT
    )
    """,
    """
    ALTER TABLE local_indexing_services ADD CONSTRAINT fk_lis_current FOREIGN KEY(service_id,
    current_revision_id) REFERENCES local_indexing_service_revisions (service_id,
    service_revision_id) DEFERRABLE INITIALLY DEFERRED
    """,
    """
    ALTER TABLE local_indexing_services ADD CONSTRAINT fk_lis_latest FOREIGN KEY(service_id,
    latest_revision_id) REFERENCES local_indexing_service_revisions (service_id,
    service_revision_id) DEFERRABLE INITIALLY DEFERRED
    """,
)

_IMMUTABLE = """
CREATE FUNCTION app.reject_local_indexing_history_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, app AS $$
BEGIN
    RAISE EXCEPTION 'local indexing identity history is immutable' USING ERRCODE = '23514';
END
$$
"""

_HEAD_GUARD = """
CREATE FUNCTION app.protect_local_indexing_head_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, app AS $$
BEGIN
    IF NEW.service_id IS DISTINCT FROM OLD.service_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.resource_version::bigint <> OLD.resource_version::bigint + 1
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'local indexing identity head transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.latest_revision_id IS DISTINCT FROM OLD.latest_revision_id AND NOT EXISTS (
        SELECT 1 FROM app.local_indexing_service_revisions next
        JOIN app.local_indexing_service_revisions previous
          ON previous.service_id = next.service_id
         AND previous.service_revision_id = next.previous_service_revision_id
        WHERE next.service_id = NEW.service_id
          AND next.service_revision_id = NEW.latest_revision_id
          AND previous.service_revision_id = OLD.latest_revision_id
          AND next.revision_number::bigint = previous.revision_number::bigint + 1
          AND next.created_at >= previous.created_at
    ) THEN
        RAISE EXCEPTION 'local indexing identity head requires the exact successor'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$
"""

_REFUSE_HISTORY = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM local_indexing_services)
       OR EXISTS (SELECT 1 FROM local_indexing_service_revisions)
       OR EXISTS (SELECT 1 FROM local_indexing_service_events) THEN
        RAISE EXCEPTION 'local indexing identity downgrade requires absent history'
            USING ERRCODE = '23514';
    END IF;
END
$$
"""


def upgrade() -> None:
    for statement in _DDL:
        op.execute(statement)
    op.execute(_IMMUTABLE)
    op.execute(_HEAD_GUARD)
    for table in ("local_indexing_service_revisions", "local_indexing_service_events"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.reject_local_indexing_history_mutation()"
        )
    for table in (
        "local_indexing_services",
        "local_indexing_service_revisions",
        "local_indexing_service_events",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON app.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION app.reject_local_indexing_history_mutation()"
        )
    op.execute(
        "CREATE TRIGGER local_indexing_services_no_delete BEFORE DELETE ON "
        "app.local_indexing_services FOR EACH ROW "
        "EXECUTE FUNCTION app.reject_local_indexing_history_mutation()"
    )
    op.execute(
        "CREATE TRIGGER local_indexing_services_protect_update BEFORE UPDATE ON "
        "app.local_indexing_services FOR EACH ROW "
        "EXECUTE FUNCTION app.protect_local_indexing_head_update()"
    )


def downgrade() -> None:
    op.execute(_REFUSE_HISTORY)
    op.drop_constraint("fk_lis_current", "local_indexing_services", type_="foreignkey")
    op.drop_constraint("fk_lis_latest", "local_indexing_services", type_="foreignkey")
    op.drop_table("local_indexing_service_events")
    op.drop_table("local_indexing_service_revisions")
    op.drop_table("local_indexing_services")
    op.execute("DROP FUNCTION app.protect_local_indexing_head_update()")
    op.execute("DROP FUNCTION app.reject_local_indexing_history_mutation()")
