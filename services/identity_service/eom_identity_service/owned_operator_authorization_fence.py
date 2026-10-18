"""Bound Identity target-row fence for an already-pinned database owner, not a login."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_identity_service.models import OperatorRecord
from eom_identity_service.operator_authorization_fence_sql import (
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
)

_CONTEXT_SQL = """
SELECT CURRENT_USER AS role_name, SESSION_USER AS session_role_name,
 role.oid::pg_catalog.int8 AS role_oid,
 role.rolsuper AS superuser, role.rolbypassrls AS bypassrls,
 pg_catalog.current_setting('transaction_isolation') AS isolation,
 pg_catalog.current_setting('transaction_read_only') AS read_only,
 pg_catalog.current_schemas(false) AS schemas,
 pg_catalog.pg_my_temp_schema() AS temp_schema,
 target.relowner::pg_catalog.int8 AS table_owner_oid,
 namespace.nspowner::pg_catalog.int8 AS schema_owner_oid
FROM pg_catalog.pg_roles role
JOIN pg_catalog.pg_namespace namespace ON namespace.nspname='app'
JOIN pg_catalog.pg_class target ON target.relnamespace=namespace.oid
 AND target.relname='operators' AND target.relkind='r'
WHERE role.rolname=CURRENT_USER
"""
_WAIT_SQL = """
SELECT pg_catalog.current_setting('lock_timeout') AS lock_timeout,
 pg_catalog.current_setting('statement_timeout') AS statement_timeout,
 (SELECT setting::pg_catalog.int8 FROM pg_catalog.pg_settings
  WHERE name='lock_timeout' AND unit='ms') AS lock_timeout_ms,
 (SELECT setting::pg_catalog.int8 FROM pg_catalog.pg_settings
  WHERE name='statement_timeout' AND unit='ms') AS statement_timeout_ms
"""
_SET_WAIT_SQL = (
    "SELECT pg_catalog.set_config('lock_timeout', :lock_timeout, true), "
    "pg_catalog.set_config('statement_timeout', :statement_timeout, true)"
)


@dataclass(frozen=True, slots=True)
class OwnedOperatorAuthorizationFence:
    """Recheck one actor in every clean root; source owners separately authenticate it.

    No session/capture is manufactured. The selected actor and DB pin are small
    trusted composition values, not transferable authority. Only a real table/
    schema owner may use the direct FOR SHARE path; Catalog's restricted adapter
    and its security-definer installation remain unchanged.
    """

    owner: OperatorAuthorizationFenceOwnerPin
    operator_id: str

    def __post_init__(self) -> None:
        if type(self.owner) is not OperatorAuthorizationFenceOwnerPin or (
            type(self.operator_id) is not str
            or re.fullmatch(r"operator_[0-9a-f]{32}", self.operator_id) is None
        ):
            raise OperatorAuthorizationFenceError(
                "OPERATOR_AUTHORIZATION_FENCE_CONFIGURATION_INVALID"
            )
        self.owner.__post_init__()

    def fence_current_operator(self, session: Session, operator_id: str) -> None:
        self.__post_init__()
        root = session.get_transaction()
        if (
            operator_id != self.operator_id
            or not session.is_active
            or root is None
            or not root.is_active
            or session.in_nested_transaction()
            or session.new
            or session.dirty
            or session.deleted
        ):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
        try:
            connection = session.connection()
            if (
                connection.dialect.name != "postgresql"
                or connection.invalidated
                or not connection.in_transaction()
                or connection.get_execution_options().get("isolation_level") == "AUTOCOMMIT"
                or connection.engine.get_execution_options().get("isolation_level") == "AUTOCOMMIT"
                or getattr(connection.connection.driver_connection, "autocommit", None) is not False
                or connection.get_isolation_level() != "READ COMMITTED"
            ):
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            limits = connection.execute(text(_WAIT_SQL)).mappings().one()
            prior, capped = {}, {}
            for name, cap in (("lock_timeout", 5000), ("statement_timeout", 10000)):
                previous, actual = limits[name], limits[name + "_ms"]
                if (
                    type(previous) is not str
                    or not 0 < len(previous) <= 32
                    or type(actual) is not int
                    or not 0 <= actual <= 2147483647
                ):
                    raise OperatorAuthorizationFenceError(
                        "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                    )
                prior[name] = previous
                capped[name] = str(min(actual, cap) if actual else cap) + "ms"
            connection.execute(text(_SET_WAIT_SQL), capped)
            current = connection.execute(text(_CONTEXT_SQL)).mappings().one()
            if (
                current["role_name"] != self.owner.role_name
                or current["session_role_name"] != self.owner.role_name
                or type(current["role_oid"]) is not int
                or current["role_oid"] != self.owner.role_oid
                or type(current["table_owner_oid"]) is not int
                or current["table_owner_oid"] != self.owner.role_oid
                or type(current["schema_owner_oid"]) is not int
                or current["schema_owner_oid"] != self.owner.role_oid
                or current["superuser"] is not False
                or current["bypassrls"] is not False
                or current["isolation"] != "read committed"
                or current["read_only"] != "off"
                or current["schemas"] != ["app", "pg_catalog"]
                or type(current["temp_schema"]) is not int
                or current["temp_schema"] != 0
            ):
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            with session.no_autoflush:
                operator = session.scalar(
                    select(OperatorRecord)
                    .where(OperatorRecord.operator_id == self.operator_id)
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True, schema_translate_map={None: "app"})
                )
            if (
                operator is None
                or operator.operator_id != self.operator_id
                or operator.status != "ACTIVE"
                or operator.deleted_at is not None
                or operator.must_change_password is not False
            ):
                raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
            if (
                session.get_transaction() is not root
                or not root.is_active
                or session.in_nested_transaction()
            ):
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            connection.execute(text(_SET_WAIT_SQL), prior)
        except OperatorAuthorizationFenceError:
            raise
        except (SQLAlchemyError, KeyError, TypeError):
            # Never include SQL, a DB URL or record/input representations.
            raise OperatorAuthorizationFenceError(
                "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
            ) from None
