"""Freeze original private QUERY context; do not admit/execute a private Workflow.

Revision ID: 20261017_0056
Revises: 20261014_0055
Create Date: 2026-10-17 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261017_0056"
down_revision: str | None = "20261014_0055"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen migration values: never import current contracts/models.
_CHECK = "ck_workflow_instances_private_query_context"
_INDEX = "uq_workflow_private_chat_query_turn"
_PREDICATE = r"""CASE WHEN (
    definition_key = 'local-embedding-private-chat-query'
    OR role_schema_version = 'private-chat-query/1.0'
    OR initial_request ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR request_payload ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR initial_request ->> 'request_name' = 'PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST'
    OR runtime_context ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR runtime_context ->> 'schema_version' = 'private-chat-query-submission-context/1.0'
) THEN (
    definition_key = 'local-embedding-private-chat-query'
    AND definition_version = '1.0.0'
    AND role_schema_version = 'private-chat-query/1.0'
    AND created_actor_type = 'human'
    AND created_actor_id ~ '^operator_[0-9a-f]{32}$'
    AND state IN ('REQUESTED','RUNNING','COMPLETED','FAILED','CANCELLED')
    AND stage IN ('LOCAL_EMBEDDING','COMPLETED','FAILED','CANCELLED')
    AND current_step_key IN ('encode_private_chat_query','complete')
    AND initial_request ->> 'schema_version' = 'private-chat-query-workflow-request/1.0'
    AND initial_request ->> 'request_name' = 'PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST'
    AND initial_request ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    AND request_payload = initial_request
    AND octet_length(initial_request::text) <= 65536
    AND jsonb_typeof(runtime_context) = 'object'
    AND octet_length(runtime_context::text) <= 65536
    AND runtime_context ?& ARRAY[
        'schema_version','purpose','workflow_request_sha256','origin',
        'artifact_pointers','context_sha256'
    ]
    AND runtime_context - ARRAY[
        'schema_version','purpose','workflow_request_sha256','origin',
        'artifact_pointers','context_sha256'
    ] = '{}'::jsonb
    AND runtime_context ->> 'schema_version' = 'private-chat-query-submission-context/1.0'
    AND runtime_context ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    AND runtime_context -> 'artifact_pointers' = '[]'::jsonb
    AND runtime_context ->> 'context_sha256' ~ '^sha256:[0-9a-f]{64}$'
    AND runtime_context ->> 'workflow_request_sha256' ~ '^sha256:[0-9a-f]{64}$'
    AND runtime_context ->> 'workflow_request_sha256' = initial_request ->> 'request_sha256'
    AND jsonb_typeof(runtime_context -> 'origin') = 'object'
    AND runtime_context #>> '{origin,schema_version}' = 'general-chat-private-query-origin/1.0'
    AND runtime_context #>> '{origin,actor_id}' = created_actor_id
    AND runtime_context #>> '{origin,origin_sha256}' ~ '^sha256:[0-9a-f]{64}$'
    AND runtime_context #>> '{origin,basis,conversation_id}' ~ '^chat_[0-9a-f]{32}$'
    AND runtime_context #>> '{origin,basis,turn_id}' ~ '^chatturn_[0-9a-f]{32}$'
    AND runtime_context #> '{origin,basis}' = initial_request #> '{context_request,query_basis}'
    AND runtime_context #>> '{origin,ticket,conversation_id}'
        = runtime_context #>> '{origin,basis,conversation_id}'
    AND runtime_context #>> '{origin,ticket,turn_id}' = runtime_context #>> '{origin,basis,turn_id}'
    AND runtime_context #>> '{origin,request_member,sha256}'
        = runtime_context #>> '{origin,ticket,request_sha256}'
) IS TRUE ELSE TRUE END"""
_DISCRIMINATOR = r"""(
    definition_key = 'local-embedding-private-chat-query'
    OR role_schema_version = 'private-chat-query/1.0'
    OR initial_request ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR request_payload ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR initial_request ->> 'request_name' = 'PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST'
    OR runtime_context ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR runtime_context ->> 'schema_version' = 'private-chat-query-submission-context/1.0'
)"""
_MUTATION_FUNCTION = """
CREATE FUNCTION reject_private_chat_query_origin_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.definition_key = 'local-embedding-private-chat-query'
           OR OLD.initial_request ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
           OR OLD.runtime_context ->> 'purpose' = 'PRIVATE_CHAT_QUERY' THEN
            RAISE EXCEPTION 'PRIVATE_CHAT_QUERY_ORIGIN_IMMUTABLE' USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;
    IF (OLD.definition_key = 'local-embedding-private-chat-query'
        OR NEW.definition_key = 'local-embedding-private-chat-query'
        OR OLD.initial_request ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
        OR NEW.initial_request ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
        OR OLD.runtime_context ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
        OR NEW.runtime_context ->> 'purpose' = 'PRIVATE_CHAT_QUERY')
       AND (OLD.runtime_context IS DISTINCT FROM NEW.runtime_context
            OR OLD.created_actor_type IS DISTINCT FROM NEW.created_actor_type
            OR OLD.created_actor_id IS DISTINCT FROM NEW.created_actor_id
            OR OLD.request_payload IS DISTINCT FROM NEW.request_payload) THEN
        RAISE EXCEPTION 'PRIVATE_CHAT_QUERY_ORIGIN_IMMUTABLE' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.create_check_constraint(_CHECK, "workflow_instances", _PREDICATE)
    op.execute(
        "CREATE UNIQUE INDEX " + _INDEX + " ON workflow_instances "
        "(created_actor_id, (runtime_context #>> '{origin,basis,conversation_id}'), "
        "(runtime_context #>> '{origin,basis,turn_id}')) "
        "WHERE definition_key = 'local-embedding-private-chat-query'"
    )
    op.execute(_MUTATION_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION reject_private_chat_query_origin_mutation() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER workflow_instance_private_query_origin_immutable "
        "BEFORE UPDATE OR DELETE ON workflow_instances FOR EACH ROW "
        "EXECUTE FUNCTION reject_private_chat_query_origin_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM workflow_instances WHERE "
        + _DISCRIMINATOR
        + ") THEN RAISE EXCEPTION 'private query downgrade requires absent original history' "
        "USING ERRCODE = '23514'; END IF; END $$"
    )
    op.execute(
        "DROP TRIGGER workflow_instance_private_query_origin_immutable ON workflow_instances"
    )
    op.execute("DROP FUNCTION reject_private_chat_query_origin_mutation()")
    op.drop_index(_INDEX, table_name="workflow_instances")
    op.drop_constraint(_CHECK, "workflow_instances", type_="check")
