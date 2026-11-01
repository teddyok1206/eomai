"""Permit exact private lifecycle1/2 tuples without changing original turn ownership.

Revision ID: 20261101_0067
Revises: 20261031_0066
Create Date: 2026-11-01 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "20261101_0067"
down_revision: str | None = "20261031_0066"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen SQL snapshots; never import mutable contracts/models in a migration.
_CONTEXT_CHECK = "ck_workflow_instances_private_query_context"
_STEP_CHECK = "ck_workflow_step_runs_local_embedding"
_PREVIOUS_CONTEXT_PREDICATE = r"""CASE WHEN (
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
_PREVIOUS_STEP_PREDICATE = (
    "(step_type = 'application') = (result_schema IS NOT DISTINCT FROM "
    "'incremental-embedding-result@1.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-reference-query-result@1.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-private-chat-query-result@1.0') AND (step_type <> 'application' OR "
    "(worker_role IS NULL AND ((result_schema = 'incremental-embedding-result@1.0' AND "
    "step_key = 'encode_batch') OR (result_schema = 'embedding-reference-query-result@1.0' "
    "AND step_key = 'encode_reference_query' AND attempt = 1) OR (result_schema = "
    "'embedding-private-chat-query-result@1.0' AND step_key = 'encode_private_chat_query' "
    "AND attempt = 1))))"
)
_CONTEXT_PREDICATE = r"""CASE WHEN (
    definition_key = 'local-embedding-private-chat-query'
    OR role_schema_version IN ('private-chat-query/1.0','private-chat-query/2.0')
    OR initial_request ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR request_payload ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR initial_request ->> 'request_name' = 'PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST'
    OR runtime_context ->> 'purpose' = 'PRIVATE_CHAT_QUERY'
    OR runtime_context ->> 'schema_version' = 'private-chat-query-submission-context/1.0'
) THEN (
    definition_key = 'local-embedding-private-chat-query'
    AND (
        (definition_version = '1.0.0'
         AND role_schema_version = 'private-chat-query/1.0'
         AND initial_request ->> 'schema_version' = 'private-chat-query-workflow-request/1.0')
        OR
        (definition_version = '2.0.0'
         AND role_schema_version = 'private-chat-query/2.0'
         AND initial_request ->> 'schema_version' = 'private-chat-query-workflow-request/2.0'
         AND initial_request ->> 'workflow_definition_key' = definition_key
         AND initial_request ->> 'workflow_definition_version' = definition_version
         AND initial_request ->> 'workflow_definition_sha256' = definition_hash
         AND initial_request #>> '{operator_audit,operator_id}' = created_actor_id
         AND initial_request #>> '{context_request,schema_version}'
             = 'system-rag-private-chat-similarity-request/2.0')
    )
    AND created_actor_type = 'human'
    AND created_actor_id ~ '^operator_[0-9a-f]{32}$'
    AND state IN ('REQUESTED','RUNNING','COMPLETED','FAILED','CANCELLED')
    AND stage IN ('LOCAL_EMBEDDING','COMPLETED','FAILED','CANCELLED')
    AND current_step_key IN ('encode_private_chat_query','complete')
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
_STEP_PREDICATE = (
    "(step_type = 'application') = (result_schema IS NOT DISTINCT FROM "
    "'incremental-embedding-result@1.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-reference-query-result@1.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-reference-query-result@2.0' OR result_schema IS NOT DISTINCT FROM "
    "'embedding-private-chat-query-result@1.0') AND (step_type <> 'application' OR "
    "(worker_role IS NULL AND ((result_schema = 'incremental-embedding-result@1.0' AND "
    "step_key = 'encode_batch') OR (result_schema = 'embedding-reference-query-result@1.0' "
    "AND step_key = 'encode_reference_query' AND attempt = 1) OR (result_schema = "
    "'embedding-private-chat-query-result@1.0' AND step_key = 'encode_private_chat_query' "
    "AND attempt = 1) OR (result_schema = 'embedding-reference-query-result@2.0' AND "
    "step_key = 'encode_private_chat_query' AND attempt = 1))))"
)
_REFUSE_NEW_HISTORY = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM workflow_instances
        WHERE (definition_key = 'local-embedding-private-chat-query'
               AND definition_version = '2.0.0')
           OR role_schema_version = 'private-chat-query/2.0'
           OR initial_request ->> 'schema_version' = 'private-chat-query-workflow-request/2.0'
    ) OR EXISTS (
        SELECT 1 FROM workflow_step_runs
        WHERE result_schema = 'embedding-reference-query-result@2.0'
           OR output_pointer_manifest ->> 'schema_version' = 'private-chat-query-step-output/2.0'
    ) THEN
        RAISE EXCEPTION 'private query2 downgrade requires absent successor history'
            USING ERRCODE = '23514';
    END IF;
END
$$
"""


def upgrade() -> None:
    # The existing cross-version unique turn index and immutable-origin triggers
    # remain installed. No row, key, source, vector or historical identity changes.
    op.drop_constraint(_CONTEXT_CHECK, "workflow_instances", type_="check")
    op.create_check_constraint(_CONTEXT_CHECK, "workflow_instances", _CONTEXT_PREDICATE)
    op.drop_constraint(_STEP_CHECK, "workflow_step_runs", type_="check")
    op.create_check_constraint(_STEP_CHECK, "workflow_step_runs", _STEP_PREDICATE)


def downgrade() -> None:
    op.execute(_REFUSE_NEW_HISTORY)
    op.drop_constraint(_STEP_CHECK, "workflow_step_runs", type_="check")
    op.create_check_constraint(_STEP_CHECK, "workflow_step_runs", _PREVIOUS_STEP_PREDICATE)
    op.drop_constraint(_CONTEXT_CHECK, "workflow_instances", type_="check")
    op.create_check_constraint(_CONTEXT_CHECK, "workflow_instances", _PREVIOUS_CONTEXT_PREDICATE)
