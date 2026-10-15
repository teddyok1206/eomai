"""Owner-only installation of the fixed operator row fence; never runtime admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from eom_identity_service.operator_authorization_fence_sql import (
    OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256,
    OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL,
    OPERATOR_AUTHORIZATION_FENCE_GRANT_SQL,
    OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL,
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    require_operator_authorization_fence_installation,
)


@dataclass(frozen=True, slots=True)
class OperatorAuthorizationFenceInstallationResult:
    disposition: Literal["CREATED", "REPLAYED"]
    owner: OperatorAuthorizationFenceOwnerPin
    body_sha256: str


def install_operator_authorization_fence(
    session: Session, owner: OperatorAuthorizationFenceOwnerPin
) -> OperatorAuthorizationFenceInstallationResult:
    """Atomic fixed DDL/ACL in a caller-owned root; existing drift is not repaired."""
    if type(owner) is not OperatorAuthorizationFenceOwnerPin:
        raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONFIGURATION_INVALID")
    owner = OperatorAuthorizationFenceOwnerPin(owner.role_name, owner.role_oid)
    root = session.get_transaction()
    if (
        root is None
        or not root.is_active
        or root.origin is not SessionTransactionOrigin.BEGIN
        or session.get_nested_transaction() is not None
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
    try:
        connection = session.connection()
        if (
            connection.dialect.name != "postgresql"
            or connection.dialect.driver != "psycopg"
            or connection.invalidated
            or not connection.in_transaction()
            or connection.in_nested_transaction()
            or getattr(connection.connection.driver_connection, "autocommit", None) is not False
        ):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
        context = (
            connection.execute(
                text(
                    "SELECT SESSION_USER AS principal, CURRENT_USER AS selected_principal, "
                    "principal.oid AS owner_oid, application.nspowner AS schema_owner, "
                    "operator_table.relowner AS table_owner, operator_table.relkind AS table_kind, "
                    "pg_catalog.current_setting('role') AS selected_role, "
                    "pg_catalog.current_setting('transaction_isolation') AS isolation, "
                    "pg_catalog.current_setting('transaction_read_only') AS read_only "
                    "FROM pg_catalog.pg_roles principal "
                    "JOIN pg_catalog.pg_namespace application ON application.nspname='app' "
                    "JOIN pg_catalog.pg_class operator_table ON "
                    "operator_table.relnamespace=application.oid "
                    "AND operator_table.relname='operators' "
                    "WHERE principal.rolname=SESSION_USER"
                )
            )
            .mappings()
            .one_or_none()
        )
        if context is None or (
            context["principal"] != owner.role_name
            or context["selected_principal"] != owner.role_name
            or context["owner_oid"] != owner.role_oid
            or context["schema_owner"] != owner.role_oid
            or context["table_owner"] != owner.role_oid
            or context["table_kind"] != "r"
            or context["selected_role"] != "none"
        ):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
        if context["isolation"] != "read committed" or context["read_only"] != "off":
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
        limits = (
            connection.execute(
                text(
                    "SELECT name, setting::pg_catalog.int8 AS milliseconds, "
                    "pg_catalog.current_setting(name) AS previous FROM pg_catalog.pg_settings "
                    "WHERE name IN ('lock_timeout','statement_timeout') AND unit='ms'"
                )
            )
            .mappings()
            .all()
        )
        previous: dict[str, str] = {}
        for limit in limits:
            name, actual, prior = limit["name"], limit["milliseconds"], limit["previous"]
            if (
                name not in {"lock_timeout", "statement_timeout"}
                or type(actual) is not int
                or actual < 0
                or type(prior) is not str
                or not 0 < len(prior) <= 32
            ):
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            previous[name] = prior
        if set(previous) != {"lock_timeout", "statement_timeout"}:
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
        with session.begin_nested():
            # Session savepoints are lazy. Enlist this connection in the nested
            # transaction before DDL, or a failed inspection could retain it.
            connection = session.connection()
            for limit in limits:
                cap = 5000 if limit["name"] == "lock_timeout" else 10000
                actual = limit["milliseconds"]
                connection.execute(
                    text("SELECT pg_catalog.set_config(:name,:value,true)"),
                    {"name": limit["name"], "value": f"{min(actual, cap) if actual else cap}ms"},
                )
            if (
                connection.scalar(
                    text("SELECT pg_catalog.pg_try_advisory_xact_lock(1162825554,1330660946)")
                )
                is not True
            ):
                raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE")
            existing = connection.execute(
                text(
                    "SELECT procedure.oid FROM pg_catalog.pg_proc procedure "
                    "JOIN pg_catalog.pg_namespace namespace "
                    "ON namespace.oid=procedure.pronamespace "
                    "WHERE namespace.nspname='public' "
                    "AND procedure.proname='eom_fence_operator_authorization_v1' "
                    "ORDER BY procedure.oid LIMIT 2"
                )
            ).all()
            if not existing:
                connection.execute(text(OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL))
                connection.execute(text(OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL))
                connection.execute(text(OPERATOR_AUTHORIZATION_FENCE_GRANT_SQL))
            require_operator_authorization_fence_installation(connection, owner)
            for name, value in previous.items():
                connection.execute(
                    text("SELECT pg_catalog.set_config(:name,:value,true)"),
                    {"name": name, "value": value},
                )
        return OperatorAuthorizationFenceInstallationResult(
            "REPLAYED" if existing else "CREATED", owner, OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256
        )
    except SQLAlchemyError:
        raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE") from None
