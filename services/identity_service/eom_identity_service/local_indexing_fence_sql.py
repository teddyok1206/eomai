"""Narrow Identity SQL interface; constants/inspection never install or grant it."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

LOCAL_INDEXING_FENCE_FUNCTION: Final = "public.eom_fence_local_indexing_service_v1"
LOCAL_INDEXING_FENCE_SIGNATURE: Final = LOCAL_INDEXING_FENCE_FUNCTION + "(text,text,text,text)"
LOCAL_INDEXING_FENCE_EXECUTE_ROLE: Final = "eom_catalog_manager_runtime"
LOCAL_INDEXING_FENCE_BODY: Final = """
DECLARE
    locked_head app.local_indexing_services%ROWTYPE;
    pinned_identity app.local_indexing_service_revisions%ROWTYPE;
BEGIN
    IF pg_catalog.current_setting('role') <> 'none' THEN
        RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LOCAL_INDEXING_FENCE_FORBIDDEN';
    END IF;
    IF requested_service_id IS NULL OR requested_revision_id IS NULL
       OR requested_identity_sha256 IS NULL OR requested_source_commit IS NULL
       OR requested_service_id !~ '^localindexservice_[0-9a-f]{32}$'
       OR pg_catalog.octet_length(requested_service_id) <> 50
       OR requested_revision_id !~ '^localindexservicerev_[0-9a-f]{32}$'
       OR pg_catalog.octet_length(requested_revision_id) <> 53
       OR requested_identity_sha256 !~ '^sha256:[0-9a-f]{64}$'
       OR pg_catalog.octet_length(requested_identity_sha256) <> 71
       OR requested_source_commit !~ '^[0-9a-f]{40}$'
       OR pg_catalog.octet_length(requested_source_commit) <> 40 THEN
        RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LOCAL_INDEXING_FENCE_FORBIDDEN';
    END IF;
    SELECT head.* INTO locked_head FROM app.local_indexing_services AS head
        WHERE head.service_id = requested_service_id FOR SHARE;
    IF NOT FOUND OR locked_head.state <> 'ACTIVE'
       OR locked_head.current_revision_id IS DISTINCT FROM requested_revision_id THEN
        RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LOCAL_INDEXING_FENCE_FORBIDDEN';
    END IF;
    SELECT identity.* INTO pinned_identity FROM app.local_indexing_service_revisions AS identity
        WHERE identity.service_id = requested_service_id
          AND identity.service_revision_id = requested_revision_id;
    IF NOT FOUND OR pinned_identity.content_sha256 <> requested_identity_sha256
       OR pinned_identity.runtime_source_commit <> requested_source_commit
       OR pinned_identity.database_role <> SESSION_USER::pg_catalog.text
       OR pinned_identity.runtime_user <> 'eom-workflow-runner'
       OR pinned_identity.purpose <> 'LOCAL_EMBEDDING_INDEX' THEN
        RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'LOCAL_INDEXING_FENCE_FORBIDDEN';
    END IF;
    RETURN pg_catalog.jsonb_build_object(
        'identity', pg_catalog.jsonb_build_object(
            'schema_version', pinned_identity.schema_version,
            'service_id', pinned_identity.service_id,
            'service_revision_id', pinned_identity.service_revision_id,
            'previous_service_revision_id', pinned_identity.previous_service_revision_id,
            'revision_number', pinned_identity.revision_number,
            'purpose', pinned_identity.purpose,
            'runtime_user', pinned_identity.runtime_user,
            'database_role', pinned_identity.database_role,
            'runtime_source_commit', pinned_identity.runtime_source_commit,
            'created_at', pg_catalog.to_char(pinned_identity.created_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            'content_sha256', pinned_identity.content_sha256),
        'status', pg_catalog.jsonb_build_object(
            'schema_version', 'local-indexing-service-status/1.0',
            'service_id', locked_head.service_id,
            'state', locked_head.state,
            'current', pg_catalog.jsonb_build_object(
                'service_id', pinned_identity.service_id,
                'service_revision_id', pinned_identity.service_revision_id,
                'service_identity_sha256', pinned_identity.content_sha256),
            'resource_version', locked_head.resource_version,
            'updated_at', pg_catalog.to_char(locked_head.updated_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')));
END;
"""
LOCAL_INDEXING_FENCE_BODY_SHA256: Final = (
    "sha256:" + hashlib.sha256(LOCAL_INDEXING_FENCE_BODY.encode()).hexdigest()
)
LOCAL_INDEXING_FENCE_CREATE_SQL: Final = (
    "CREATE FUNCTION " + LOCAL_INDEXING_FENCE_FUNCTION + "("
    "requested_service_id pg_catalog.text, requested_revision_id pg_catalog.text, "
    "requested_identity_sha256 pg_catalog.text, requested_source_commit pg_catalog.text) "
    "RETURNS pg_catalog.jsonb LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE SECURITY DEFINER "
    "CALLED ON NULL INPUT SET search_path TO pg_catalog, pg_temp "
    "AS $eom_indexing_fence$" + LOCAL_INDEXING_FENCE_BODY + "$eom_indexing_fence$"
)
LOCAL_INDEXING_FENCE_REVOKE_PUBLIC_SQL: Final = (
    "REVOKE ALL ON FUNCTION " + LOCAL_INDEXING_FENCE_SIGNATURE + " FROM PUBLIC"
)
LOCAL_INDEXING_FENCE_GRANT_SQL: Final = (
    "GRANT EXECUTE ON FUNCTION "
    + LOCAL_INDEXING_FENCE_SIGNATURE
    + " TO "
    + LOCAL_INDEXING_FENCE_EXECUTE_ROLE
)
LOCAL_INDEXING_FENCE_CALL_SQL: Final = (
    "SELECT " + LOCAL_INDEXING_FENCE_FUNCTION + "("
    "CAST(:service_id AS pg_catalog.text),CAST(:revision_id AS pg_catalog.text),"
    "CAST(:identity_sha256 AS pg_catalog.text),CAST(:source_commit AS pg_catalog.text))"
)

type LocalIndexingFenceErrorCode = Literal[
    "LOCAL_INDEXING_FENCE_CONFIGURATION_INVALID",
    "LOCAL_INDEXING_FENCE_CONTEXT_INVALID",
    "LOCAL_INDEXING_FENCE_FORBIDDEN",
    "LOCAL_INDEXING_FENCE_UNAVAILABLE",
]


class LocalIndexingFenceError(ValueError):
    def __init__(self, code: LocalIndexingFenceErrorCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LocalIndexingFenceOwnerPin:
    role_name: str
    role_oid: int

    def __post_init__(self) -> None:
        if (
            type(self.role_name) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.role_name) is None
            or self.role_name == LOCAL_INDEXING_FENCE_EXECUTE_ROLE
            or type(self.role_oid) is not int
            or not 1 <= self.role_oid <= 4294967295
        ):
            raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_CONFIGURATION_INVALID")


# Compare only bounded booleans server-side, never return raw function/ACL payloads.
_INSPECTION_SQL: Final = """
SELECT
    (procedure.proowner = :owner_oid AND function_owner.rolname = :owner_name
     AND application.nspowner = :owner_oid) AS owner_ok,
    (procedure.prokind = 'f' AND procedure.pronargs = 4
     AND procedure.proargtypes = '25 25 25 25'::pg_catalog.oidvector
     AND procedure.prorettype = 'pg_catalog.jsonb'::pg_catalog.regtype
     AND procedure.proargnames = ARRAY['requested_service_id','requested_revision_id',
         'requested_identity_sha256','requested_source_commit']::pg_catalog.text[]
     AND procedure.proallargtypes IS NULL AND procedure.proargmodes IS NULL
     AND procedure.pronargdefaults = 0 AND procedure.provariadic = 0
     AND NOT procedure.proretset AND NOT procedure.proisstrict
     AND NOT procedure.proleakproof AND procedure.prosupport = 0
     AND language.lanname = 'plpgsql' AND procedure.prosecdef
     AND procedure.provolatile = 'v' AND procedure.proparallel = 'u'
     AND procedure.proconfig = ARRAY['search_path=pg_catalog, pg_temp']::pg_catalog.text[])
        AS definition_ok,
    (procedure.prosrc = :expected_body) AS body_ok,
    (SELECT pg_catalog.count(*) = 2 AND pg_catalog.count(DISTINCT acl.grantee) = 2
        AND pg_catalog.bool_and(acl.grantor = :owner_oid
            AND acl.grantee IN (:owner_oid, runtime.oid)
            AND acl.privilege_type = 'EXECUTE' AND NOT acl.is_grantable)
     FROM pg_catalog.aclexplode(COALESCE(procedure.proacl,
        pg_catalog.acldefault('f', procedure.proowner))) AS acl) AS acl_ok,
    (runtime.rolcanlogin AND NOT runtime.rolsuper AND NOT runtime.rolcreatedb
     AND NOT runtime.rolcreaterole AND NOT runtime.rolinherit
     AND NOT runtime.rolreplication AND NOT runtime.rolbypassrls
     AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members WHERE member = runtime.oid))
        AS runtime_role_ok,
    (pg_catalog.has_schema_privilege(runtime.oid, namespace.oid, 'USAGE')
     AND NOT pg_catalog.has_schema_privilege(runtime.oid, namespace.oid, 'CREATE')
     AND pg_catalog.has_schema_privilege(runtime.oid, application.oid, 'USAGE')
     AND NOT pg_catalog.has_schema_privilege(runtime.oid, application.oid, 'CREATE')
     AND NOT EXISTS (SELECT 1 FROM pg_catalog.aclexplode(COALESCE(namespace.nspacl,
         pg_catalog.acldefault('n', namespace.nspowner))) AS schema_acl
         WHERE schema_acl.privilege_type = 'CREATE'
           AND schema_acl.grantee NOT IN (namespace.nspowner, :owner_oid, database.datdba)))
        AS schema_ok,
    pg_catalog.has_function_privilege(runtime.oid, procedure.oid, 'EXECUTE') AS execute_ok,
    (SELECT pg_catalog.count(object.oid) = 3 AND pg_catalog.bool_and(
         object.relowner = :owner_oid AND object.relkind = 'r'
         AND NOT object.relrowsecurity AND NOT object.relforcerowsecurity
         AND NOT pg_catalog.has_table_privilege(runtime.oid, object.oid,
             'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
         AND NOT pg_catalog.has_any_column_privilege(runtime.oid, object.oid,
             'SELECT,INSERT,UPDATE,REFERENCES'))
     FROM (VALUES ('local_indexing_services'),('local_indexing_service_revisions'),
         ('local_indexing_service_events')) AS identity(table_name)
     LEFT JOIN pg_catalog.pg_class AS object
         ON object.relnamespace = application.oid AND object.relname = identity.table_name)
        AS identity_privileges_ok
FROM pg_catalog.pg_proc AS procedure
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
JOIN pg_catalog.pg_roles AS function_owner ON function_owner.oid = procedure.proowner
JOIN pg_catalog.pg_language AS language ON language.oid = procedure.prolang
JOIN pg_catalog.pg_namespace AS application ON application.nspname = 'app'
JOIN pg_catalog.pg_database AS database ON database.datname = pg_catalog.current_database()
JOIN pg_catalog.pg_roles AS runtime ON runtime.rolname = :execute_role
WHERE namespace.nspname = 'public' AND procedure.proname = 'eom_fence_local_indexing_service_v1'
ORDER BY procedure.oid
LIMIT 2
"""
_INSPECTION_FIELDS: Final = (
    "owner_ok",
    "definition_ok",
    "body_ok",
    "acl_ok",
    "runtime_role_ok",
    "schema_ok",
    "execute_ok",
    "identity_privileges_ok",
)


def require_local_indexing_fence_installation(
    connection: Connection,
    owner: LocalIndexingFenceOwnerPin,
) -> None:
    owner = LocalIndexingFenceOwnerPin(owner.role_name, owner.role_oid)
    if connection.dialect.name != "postgresql":
        raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_UNAVAILABLE")
    try:
        rows = (
            connection.execute(
                text(_INSPECTION_SQL),
                {
                    "owner_oid": owner.role_oid,
                    "owner_name": owner.role_name,
                    "execute_role": LOCAL_INDEXING_FENCE_EXECUTE_ROLE,
                    "expected_body": LOCAL_INDEXING_FENCE_BODY,
                },
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError:
        raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_UNAVAILABLE") from None
    if (
        len(rows) != 1
        or set(rows[0]) != set(_INSPECTION_FIELDS)
        or any(rows[0][field] is not True for field in _INSPECTION_FIELDS)
    ):
        raise LocalIndexingFenceError("LOCAL_INDEXING_FENCE_UNAVAILABLE")
