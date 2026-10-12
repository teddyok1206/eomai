"""Fixed Identity-owned SQL routine and read-only installed security inspection.

The CREATE text is for a later reviewed migration, never executed by this module.
Inspection returns no operator/session authority and installs no privilege.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

OPERATOR_AUTHORIZATION_FENCE_FUNCTION: Final = "public.eom_fence_operator_authorization_v1"
OPERATOR_AUTHORIZATION_FENCE_SIGNATURE: Final = OPERATOR_AUTHORIZATION_FENCE_FUNCTION + "(text)"
OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE: Final = "eom_catalog_manager_runtime"
OPERATOR_AUTHORIZATION_FENCE_BODY: Final = """
BEGIN
    IF requested_operator_id IS NULL
       OR requested_operator_id !~ '^operator_[0-9a-f]{32}$'
       OR pg_catalog.octet_length(requested_operator_id) <> 41 THEN
        RAISE EXCEPTION USING ERRCODE = 'P0001',
            MESSAGE = 'OPERATOR_AUTHORIZATION_FENCE_OPERATOR_INVALID';
    END IF;
    PERFORM 1 FROM app.operators AS locked_operator
        WHERE locked_operator.operator_id = requested_operator_id
        FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0001',
            MESSAGE = 'OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN';
    END IF;
    RETURN;
END;
"""
OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256: Final = (
    "sha256:" + hashlib.sha256(OPERATOR_AUTHORIZATION_FENCE_BODY.encode("utf-8")).hexdigest()
)
OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL: Final = (
    "CREATE FUNCTION public.eom_fence_operator_authorization_v1("
    "requested_operator_id pg_catalog.text) RETURNS pg_catalog.void "
    "LANGUAGE plpgsql VOLATILE PARALLEL UNSAFE SECURITY DEFINER "
    "CALLED ON NULL INPUT SET search_path TO pg_catalog, pg_temp "
    "AS $eom_operator_fence$" + OPERATOR_AUTHORIZATION_FENCE_BODY + "$eom_operator_fence$"
)
OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL: Final = (
    "REVOKE ALL ON FUNCTION public.eom_fence_operator_authorization_v1(text) FROM PUBLIC"
)
OPERATOR_AUTHORIZATION_FENCE_GRANT_SQL: Final = (
    "GRANT EXECUTE ON FUNCTION public.eom_fence_operator_authorization_v1(text) "
    "TO eom_catalog_manager_runtime"
)
OPERATOR_AUTHORIZATION_FENCE_CALL_SQL: Final = (
    "SELECT public.eom_fence_operator_authorization_v1(CAST(:operator_id AS pg_catalog.text))"
)

type OperatorAuthorizationFenceErrorCode = Literal[
    "OPERATOR_AUTHORIZATION_FENCE_CONFIGURATION_INVALID",
    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID",
    "OPERATOR_AUTHORIZATION_FENCE_OPERATOR_INVALID",
    "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN",
    "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE",
]


class OperatorAuthorizationFenceError(ValueError):
    """Stable content-free failure, not a transferable denial/permission DTO."""

    def __init__(self, code: OperatorAuthorizationFenceErrorCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OperatorAuthorizationFenceOwnerPin:
    """Trusted installed owner identity, supplied by release composition, never a worker."""

    role_name: str
    role_oid: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.role_name, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.role_name) is None
            or self.role_name == OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE
            or type(self.role_oid) is not int
            or not 1 <= self.role_oid <= 4294967295
        ):
            raise OperatorAuthorizationFenceError(
                "OPERATOR_AUTHORIZATION_FENCE_CONFIGURATION_INVALID"
            )


# Never return prosrc/ACL payloads: malicious catalog metadata remains a bounded
# server-side comparison and at most two fixed-shape result rows.
_INSPECTION_SQL: Final = """
SELECT
    (procedure.proowner = :owner_oid AND function_owner.rolname = :owner_name
     AND application.nspowner = :owner_oid AND operator_table.relowner = :owner_oid
     AND operator_table.relkind = 'r' AND NOT operator_table.relrowsecurity
     AND NOT operator_table.relforcerowsecurity)
        AS owner_ok,
    (procedure.prokind = 'f' AND procedure.pronargs = 1
     AND procedure.proargtypes = '25'::pg_catalog.oidvector
     AND procedure.prorettype = 'pg_catalog.void'::pg_catalog.regtype
     AND procedure.proargnames = ARRAY['requested_operator_id']::pg_catalog.text[]
     AND procedure.proallargtypes IS NULL AND procedure.proargmodes IS NULL
     AND procedure.pronargdefaults = 0 AND procedure.provariadic = 0
     AND NOT procedure.proretset AND NOT procedure.proisstrict
     AND NOT procedure.proleakproof AND procedure.prosupport = 0
     AND language.lanname = 'plpgsql' AND procedure.prosecdef
     AND procedure.provolatile = 'v' AND procedure.proparallel = 'u'
     AND procedure.proconfig = ARRAY['search_path=pg_catalog, pg_temp']::pg_catalog.text[])
        AS definition_ok,
    (procedure.prosrc = :expected_body) AS body_ok,
    (SELECT pg_catalog.count(*) = 2
            AND pg_catalog.count(DISTINCT acl.grantee) = 2
            AND pg_catalog.bool_and(acl.grantor = :owner_oid
                AND acl.grantee IN (:owner_oid, runtime.oid)
                AND acl.privilege_type = 'EXECUTE' AND NOT acl.is_grantable)
       FROM pg_catalog.aclexplode(COALESCE(procedure.proacl,
            pg_catalog.acldefault('f', procedure.proowner))) AS acl) AS acl_ok,
    (runtime.rolcanlogin AND NOT runtime.rolsuper AND NOT runtime.rolcreatedb
     AND NOT runtime.rolcreaterole AND NOT runtime.rolinherit
     AND NOT runtime.rolreplication AND NOT runtime.rolbypassrls
     AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members
         WHERE member = runtime.oid)) AS runtime_role_ok,
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
    (SELECT pg_catalog.bool_and(
         object.oid IS NOT NULL
         AND pg_catalog.has_table_privilege(runtime.oid, object.oid, 'SELECT') = iam.readable
         AND (iam.readable OR NOT pg_catalog.has_any_column_privilege(
                 runtime.oid, object.oid, 'SELECT'))
         AND NOT pg_catalog.has_table_privilege(runtime.oid, object.oid,
                 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
         AND NOT pg_catalog.has_any_column_privilege(runtime.oid, object.oid,
                 'INSERT,UPDATE,REFERENCES'))
       FROM (VALUES ('operators', true), ('roles', true), ('permissions', true),
           ('role_permissions', true), ('operator_role_assignments', true),
           ('operator_credentials', false), ('api_sessions', false),
           ('api_tokens', false), ('operator_events', false)) AS iam(table_name, readable)
       LEFT JOIN pg_catalog.pg_class AS object
         ON object.relnamespace = application.oid AND object.relname = iam.table_name)
        AS iam_privileges_ok
FROM pg_catalog.pg_proc AS procedure
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
JOIN pg_catalog.pg_roles AS function_owner ON function_owner.oid = procedure.proowner
JOIN pg_catalog.pg_language AS language ON language.oid = procedure.prolang
JOIN pg_catalog.pg_namespace AS application ON application.nspname = 'app'
JOIN pg_catalog.pg_class AS operator_table
  ON operator_table.relnamespace = application.oid AND operator_table.relname = 'operators'
JOIN pg_catalog.pg_database AS database ON database.datname = pg_catalog.current_database()
JOIN pg_catalog.pg_roles AS runtime ON runtime.rolname = :execute_role
WHERE namespace.nspname = 'public' AND procedure.proname = 'eom_fence_operator_authorization_v1'
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
    "iam_privileges_ok",
)


def require_operator_authorization_fence_installation(
    connection: Connection, owner: OperatorAuthorizationFenceOwnerPin
) -> None:
    """Read-only exact installed security check, not an install or operator grant."""
    owner = OperatorAuthorizationFenceOwnerPin(owner.role_name, owner.role_oid)
    if connection.dialect.name != "postgresql":
        raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE")
    try:
        rows = (
            connection.execute(
                text(_INSPECTION_SQL),
                {
                    "owner_oid": owner.role_oid,
                    "owner_name": owner.role_name,
                    "execute_role": OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE,
                    "expected_body": OPERATOR_AUTHORIZATION_FENCE_BODY,
                },
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError:
        raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE") from None
    if (
        len(rows) != 1
        or set(rows[0]) != set(_INSPECTION_FIELDS)
        or any(rows[0][name] is not True for name in _INSPECTION_FIELDS)
    ):
        raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE")
