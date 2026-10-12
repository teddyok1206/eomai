"""Concrete official Identity target-row fence; no session freshness or grant."""

from __future__ import annotations

import re
from _thread import LockType
from dataclasses import dataclass, field
from threading import Lock, Thread, current_thread
from typing import Final
from weakref import ReferenceType, WeakKeyDictionary, ref

from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransaction

from eom_identity_service.models import OperatorRecord
from eom_identity_service.operator_authorization_fence_sql import (
    OPERATOR_AUTHORIZATION_FENCE_CALL_SQL,
    OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE,
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    require_operator_authorization_fence_installation,
)

OPERATOR_AUTHORIZATION_FENCE_LOCK_TIMEOUT_MS: Final = 5000
OPERATOR_AUTHORIZATION_FENCE_STATEMENT_TIMEOUT_MS: Final = 10000
_WAIT_LIMITS_SQL: Final = (
    "SELECT pg_catalog.current_setting('lock_timeout') AS lock_timeout, "
    "pg_catalog.current_setting('statement_timeout') AS statement_timeout, "
    "(SELECT setting::pg_catalog.int8 FROM pg_catalog.pg_settings "
    "WHERE name='lock_timeout' AND unit='ms') AS lock_timeout_ms, "
    "(SELECT setting::pg_catalog.int8 FROM pg_catalog.pg_settings "
    "WHERE name='statement_timeout' AND unit='ms') AS statement_timeout_ms"
)
_TIMEOUT_SQL: Final = (
    "SELECT pg_catalog.set_config('lock_timeout', :lock_timeout, true), "
    "pg_catalog.set_config('statement_timeout', :statement_timeout, true)"
)
_CONTEXT_SQL: Final = (
    "SELECT pg_catalog.current_setting('transaction_isolation') AS isolation, "
    "pg_catalog.current_setting('transaction_read_only') AS read_only, "
    "CURRENT_USER AS role_name, pg_catalog.pg_backend_pid() AS backend_pid, "
    "pg_catalog.txid_current() AS transaction_id, "
    "pg_catalog.current_schemas(false) AS schemas, "
    "pg_catalog.pg_my_temp_schema() AS temp_schema"
)


@dataclass(frozen=True, slots=True)
class _RootOperatorFenceWitness:
    root: ReferenceType[SessionTransaction]
    connection: ReferenceType[Connection]
    operator_id: str
    acquisition_thread: ReferenceType[Thread]
    backend_pid: int
    transaction_id: int


@dataclass(frozen=True, slots=True)
class PostgresOperatorAuthorizationFence:
    """Bind only in an authenticated owner operation on its exact active root Session.

    Existing instance state is refreshed, but actual roles/source policy remain
    caller checks. The routine must already be independently installed/admitted;
    this adapter cannot install it or grant itself permission. No cached success
    substitutes for the retained root row lock, and no session grant is returned.
    """

    owner: OperatorAuthorizationFenceOwnerPin
    _witnesses: WeakKeyDictionary[Session, _RootOperatorFenceWitness] = field(
        default_factory=WeakKeyDictionary, init=False, repr=False, compare=False
    )
    _witness_lock: LockType = field(default_factory=Lock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        OperatorAuthorizationFenceOwnerPin(self.owner.role_name, self.owner.role_oid)

    def fence_current_operator(self, session: Session, operator_id: str) -> None:
        if (
            not isinstance(operator_id, str)
            or re.fullmatch(r"operator_[0-9a-f]{32}", operator_id) is None
        ):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_OPERATOR_INVALID")
        root = session.get_transaction()
        nested = session.get_nested_transaction()
        with self._witness_lock:
            witness = self._witnesses.get(session)
            if witness is not None and (
                witness.root() is not root or root is None or not root.is_active
            ):
                del self._witnesses[session]
                witness = None
        if root is None or not root.is_active:
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
        if witness is not None and (
            witness.operator_id != operator_id
            or witness.acquisition_thread() is not current_thread()
        ):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
        if nested is not None and witness is None:
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
        if any(
            isinstance(value, OperatorRecord)
            for values in (session.new, session.dirty, session.deleted)
            for value in values
        ):
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID")
        try:
            connection = session.connection()
            if (
                connection.dialect.name != "postgresql"
                or connection.get_execution_options().get("isolation_level") == "AUTOCOMMIT"
                or connection.engine.get_execution_options().get("isolation_level") == "AUTOCOMMIT"
                or getattr(connection.connection.driver_connection, "autocommit", None) is not False
                or connection.invalidated
                or not connection.in_transaction()
            ):
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            limits = connection.execute(text(_WAIT_LIMITS_SQL)).mappings().one()
            capped: dict[str, str] = {}
            prior: dict[str, str] = {}
            for name, cap in (
                ("lock_timeout", OPERATOR_AUTHORIZATION_FENCE_LOCK_TIMEOUT_MS),
                ("statement_timeout", OPERATOR_AUTHORIZATION_FENCE_STATEMENT_TIMEOUT_MS),
            ):
                actual = limits[name + "_ms"]
                previous = limits[name]
                if (
                    type(actual) is not int
                    or not 0 <= actual <= 2147483647
                    or not isinstance(previous, str)
                    or not 0 < len(previous) <= 32
                ):
                    raise OperatorAuthorizationFenceError(
                        "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                    )
                capped[name] = str(min(actual, cap) if actual else cap) + "ms"
                prior[name] = previous
            connection.execute(text(_TIMEOUT_SQL), capped)
            if connection.get_isolation_level() != "READ COMMITTED":
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            context = connection.execute(text(_CONTEXT_SQL)).mappings().one()
            if (
                context["isolation"] != "read committed"
                or context["read_only"] != "off"
                or context["role_name"] != OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE
                or context["schemas"] != ["app", "pg_catalog"]
                or type(context["temp_schema"]) is not int
                or context["temp_schema"] != 0
                or type(context["backend_pid"]) is not int
                or context["backend_pid"] < 1
                or type(context["transaction_id"]) is not int
                or context["transaction_id"] < 1
            ):
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            if witness is not None and (
                witness.connection() is not connection
                or witness.backend_pid != context["backend_pid"]
                or witness.transaction_id != context["transaction_id"]
            ):
                with self._witness_lock:
                    self._witnesses.pop(session, None)
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            require_operator_authorization_fence_installation(connection, self.owner)
            if witness is None:
                # First target-row lock is acquired only before any savepoint.
                connection.execute(
                    text(OPERATOR_AUTHORIZATION_FENCE_CALL_SQL), {"operator_id": operator_id}
                )
            with session.no_autoflush:
                operator = session.scalar(
                    select(OperatorRecord)
                    .where(OperatorRecord.operator_id == operator_id)
                    .execution_options(populate_existing=True, schema_translate_map={None: "app"})
                )
            if (
                operator is None
                or operator.status != "ACTIVE"
                or operator.deleted_at is not None
                or operator.must_change_password is not False
            ):
                raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
            if (
                session.get_transaction() is not root
                or not root.is_active
                or session.get_nested_transaction() is not nested
            ):
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                )
            # Success restores the prior owner settings exactly. Failure requires
            # root rollback and never weakens the capped error/abort path.
            connection.execute(text(_TIMEOUT_SQL), prior)
            if witness is None:
                with self._witness_lock:
                    self._witnesses[session] = _RootOperatorFenceWitness(
                        ref(root),
                        ref(connection),
                        operator_id,
                        ref(current_thread()),
                        context["backend_pid"],
                        context["transaction_id"],
                    )
        except OperatorAuthorizationFenceError:
            raise
        except DBAPIError as exc:
            original = exc.orig
            diagnostic = getattr(original, "diag", None)
            if (
                getattr(original, "sqlstate", None) == "P0001"
                and getattr(diagnostic, "message_primary", None)
                == "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
            ):
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                ) from None
            raise OperatorAuthorizationFenceError(
                "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
            ) from None
        except SQLAlchemyError:
            raise OperatorAuthorizationFenceError(
                "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
            ) from None
