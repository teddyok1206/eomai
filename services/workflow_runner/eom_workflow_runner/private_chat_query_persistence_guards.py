"""Private-only Workflow metadata shape, not complete schema or source authorization."""

PRIVATE_CHAT_QUERY_CONTEXT_CHECK = "ck_workflow_instances_private_query_context"
PRIVATE_CHAT_QUERY_TURN_INDEX = "uq_workflow_private_chat_query_turn"
PRIVATE_CHAT_QUERY_CONTEXT_PREDICATE = r"""CASE WHEN (
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
