"""Operation-local verified access capture and direct caller-root Identity fencing.

No production provider/key/transport is composed here. Captures are private adapter
provenance, not cryptographic Python capabilities or serialized authority grants.
"""

from __future__ import annotations

import re
from _thread import LockType
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock, Thread, current_thread
from typing import TYPE_CHECKING
from weakref import ReferenceType, WeakKeyDictionary, ref

from eom_operator_identity.contracts import PermissionKey
from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransaction

from eom_identity_service.models import (
    ApiSessionRecord,
    ApiTokenRecord,
    OperatorCredentialRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RolePermissionRecord,
    RoleRecord,
)
from eom_identity_service.repository import effective_permissions

if TYPE_CHECKING:
    from eom_identity_service.tokens import AccessAuthentication

_CONTEXT_SQL = """
SELECT pg_catalog.current_setting('transaction_isolation') AS isolation,
 pg_catalog.current_setting('transaction_read_only') AS read_only,
 CURRENT_USER AS role_name, SESSION_USER AS session_role_name,
 role.oid AS role_oid, role.rolsuper AS superuser, role.rolbypassrls AS bypassrls,
 pg_catalog.pg_backend_pid() AS backend_pid, pg_catalog.txid_current() AS transaction_id,
 pg_catalog.current_schemas(false) AS schemas, pg_catalog.pg_my_temp_schema() AS temp_schema,
 (SELECT pg_catalog.bool_and(
   pg_catalog.has_table_privilege(CURRENT_USER, 'app.' || name, 'SELECT') AND
   pg_catalog.has_table_privilege(CURRENT_USER, 'app.' || name, 'UPDATE'))
  FROM (VALUES ('operators'),('api_sessions'),('api_tokens')) AS target(name)) AS targets_lockable
FROM pg_catalog.pg_roles AS role WHERE role.rolname = CURRENT_USER
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
_IAM_RECORDS = (
    OperatorRecord,
    ApiSessionRecord,
    ApiTokenRecord,
    OperatorCredentialRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RoleRecord,
    RolePermissionRecord,
)


class AuthenticatedSessionFenceError(ValueError):
    """Content-free local failure; no credential, SQL or source values escape."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AuthenticatedSessionFenceError("AUTHENTICATED_SESSION_" + code)


def _utc(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(None)
    )


@dataclass(frozen=True, slots=True)
class _CapturedValues:
    operator_id: str
    session_id: str
    token_id: str
    verifier_hash: str = field(repr=False)
    issued_at: datetime
    access_expires_at: datetime
    authenticated_at: datetime
    absolute_expires_at: datetime
    idle_expires_at: datetime
    refresh_generation: int

    def pin(self) -> tuple[object, ...]:
        return (
            self.operator_id,
            self.session_id,
            self.token_id,
            self.verifier_hash,
            self.issued_at,
            self.access_expires_at,
            self.authenticated_at,
            self.absolute_expires_at,
            self.idle_expires_at,
            self.refresh_generation,
        )

    def __post_init__(self) -> None:
        for value, prefix in (
            (self.operator_id, "operator"),
            (self.session_id, "apisession"),
            (self.token_id, "apitoken"),
        ):
            _require(
                type(value) is str and re.fullmatch(prefix + r"_[0-9a-f]{32}", value) is not None,
                "CAPTURE_INVALID",
            )
        _require(
            type(self.verifier_hash) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", self.verifier_hash) is not None
            and all(
                _utc(value)
                for value in (
                    self.issued_at,
                    self.access_expires_at,
                    self.authenticated_at,
                    self.absolute_expires_at,
                    self.idle_expires_at,
                )
            )
            and self.authenticated_at <= self.issued_at < self.access_expires_at
            and self.access_expires_at <= self.absolute_expires_at
            and self.authenticated_at < self.idle_expires_at <= self.absolute_expires_at
            and type(self.refresh_generation) is int
            and self.refresh_generation >= 1,
            "CAPTURE_INVALID",
        )


@dataclass(frozen=True, slots=True)
class _CaptureOrigin:
    capture: ReferenceType[AuthenticatedOperatorSession]
    values: _CapturedValues
    pin: tuple[object, ...]


class AuthenticatedOperatorSession:
    """Opaque Identity-created capture; no credential, DTO constructor or serializer."""

    __slots__ = ("__weakref__", "_origin", "_values")
    _values: _CapturedValues
    _origin: _CaptureOrigin

    def __new__(cls) -> AuthenticatedOperatorSession:
        raise AuthenticatedSessionFenceError("AUTHENTICATED_SESSION_CAPTURE_UNAVAILABLE")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("authenticated session capture is immutable")

    def __repr__(self) -> str:
        return "<AuthenticatedOperatorSession>"

    @property
    def operator_id(self) -> str:
        return _capture_values(self).operator_id


def _capture_values(capture: AuthenticatedOperatorSession) -> _CapturedValues:
    _require(type(capture) is AuthenticatedOperatorSession, "CAPTURE_INVALID")
    values = getattr(capture, "_values", None)
    origin = getattr(capture, "_origin", None)
    _require(type(values) is _CapturedValues and type(origin) is _CaptureOrigin, "CAPTURE_INVALID")
    assert isinstance(values, _CapturedValues) and isinstance(origin, _CaptureOrigin)
    values.__post_init__()
    _require(
        origin.capture() is capture and origin.values is values and origin.pin == values.pin(),
        "CAPTURE_INVALID",
    )
    return values


def _capture_verified_access(
    authentication: AccessAuthentication,
    api_session: ApiSessionRecord,
    token: ApiTokenRecord,
) -> AuthenticatedOperatorSession:
    """Called only after the one authoritative TokenService HMAC validation path."""
    _require(
        authentication.operator.status == "ACTIVE"
        and authentication.operator.must_change_password is False
        and authentication.password_change_required is False
        and authentication.operator.operator_id == api_session.operator_id
        and authentication.session_id == api_session.api_session_id == token.api_session_id
        and token.token_type == "ACCESS"
        and token.revoked_at is None
        and api_session.revoked_at is None,
        "CAPTURE_INVALID",
    )
    values = _CapturedValues(
        api_session.operator_id,
        api_session.api_session_id,
        token.api_token_id,
        token.verifier_hash,
        token.issued_at,
        token.expires_at,
        api_session.authenticated_at,
        api_session.absolute_expires_at,
        api_session.idle_expires_at,
        api_session.refresh_generation,
    )
    return _new_authenticated_capture(values)


def _new_authenticated_capture(values: _CapturedValues) -> AuthenticatedOperatorSession:
    """Identity-private shared creation after genuine verification or admitted transport."""
    values.__post_init__()
    capture = object.__new__(AuthenticatedOperatorSession)
    object.__setattr__(capture, "_values", values)
    object.__setattr__(capture, "_origin", _CaptureOrigin(ref(capture), values, values.pin()))
    return capture


@dataclass(frozen=True, slots=True)
class AuthenticatedSessionFenceOwnerPin:
    """Independently configured caller identity/fresh-auth context, never a grant."""

    role_name: str
    role_oid: int
    fresh_auth_seconds: int

    def __post_init__(self) -> None:
        _require(
            type(self.role_name) is str
            and re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", self.role_name) is not None
            and type(self.role_oid) is int
            and 0 < self.role_oid <= 2**32 - 1
            and type(self.fresh_auth_seconds) is int
            and 0 < self.fresh_auth_seconds <= 3600,
            "CONFIGURATION_INVALID",
        )


@dataclass(frozen=True, slots=True)
class _RootFence:
    root: ReferenceType[SessionTransaction]
    connection: ReferenceType[Connection]
    thread: ReferenceType[Thread]
    capture: ReferenceType[AuthenticatedOperatorSession]
    backend_pid: int
    transaction_id: int


@dataclass(frozen=True, slots=True)
class AuthenticatedSessionFence:
    """Fresh direct operator→session→ACCESS locks on an actual admitted caller root."""

    owner: AuthenticatedSessionFenceOwnerPin
    _roots: WeakKeyDictionary[Session, _RootFence] = field(
        default_factory=WeakKeyDictionary, init=False, repr=False, compare=False
    )
    _lock: LockType = field(default_factory=Lock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require(type(self.owner) is AuthenticatedSessionFenceOwnerPin, "CONFIGURATION_INVALID")
        self.owner.__post_init__()

    def assert_current(
        self,
        session: Session,
        capture: AuthenticatedOperatorSession,
        *,
        required_permission: PermissionKey,
    ) -> None:
        values = _capture_values(capture)
        _require(type(required_permission) is PermissionKey, "CONTEXT_INVALID")
        self.owner.__post_init__()
        root, nested = session.get_transaction(), session.get_nested_transaction()
        _require(session.is_active and root is not None and root.is_active, "CONTEXT_INVALID")
        assert root is not None
        with self._lock:
            witness = self._roots.get(session)
            if witness is not None and witness.root() is not root:
                self._roots.pop(session, None)
                witness = None
        _require(nested is None or witness is not None, "CONTEXT_INVALID")
        if witness is not None:
            _require(
                witness.thread() is current_thread() and witness.capture() is capture,
                "CONTEXT_INVALID",
            )
        _require(
            not any(
                isinstance(row, _IAM_RECORDS)
                for rows in (session.new, session.dirty, session.deleted)
                for row in rows
            ),
            "CONTEXT_INVALID",
        )
        try:
            connection = session.connection()
            _require(
                connection.dialect.name == "postgresql"
                and not connection.invalidated
                and connection.in_transaction()
                and connection.get_execution_options().get("isolation_level") != "AUTOCOMMIT"
                and connection.engine.get_execution_options().get("isolation_level") != "AUTOCOMMIT"
                and getattr(connection.connection.driver_connection, "autocommit", None) is False,
                "CONTEXT_INVALID",
            )
            limits = connection.execute(text(_WAIT_SQL)).mappings().one()
            prior: dict[str, str] = {}
            capped: dict[str, str] = {}
            for name, cap in (("lock_timeout", 5000), ("statement_timeout", 10000)):
                previous, actual = limits[name], limits[name + "_ms"]
                _require(
                    type(previous) is str
                    and 0 < len(previous) <= 32
                    and type(actual) is int
                    and 0 <= actual <= 2147483647,
                    "CONTEXT_INVALID",
                )
                prior[name] = previous
                capped[name] = str(min(actual, cap) if actual else cap) + "ms"
            connection.execute(text(_SET_WAIT_SQL), capped)
            context = connection.execute(text(_CONTEXT_SQL)).mappings().one()
            _require(
                connection.get_isolation_level() == "READ COMMITTED"
                and context["isolation"] == "read committed"
                and context["read_only"] == "off"
                and context["role_name"] == context["session_role_name"] == self.owner.role_name
                and type(context["role_oid"]) is int
                and context["role_oid"] == self.owner.role_oid
                and context["superuser"] is False
                and context["bypassrls"] is False
                and context["targets_lockable"] is True
                and context["schemas"] == ["app", "pg_catalog"]
                and type(context["temp_schema"]) is int
                and context["temp_schema"] == 0
                and type(context["backend_pid"]) is int
                and context["backend_pid"] > 0
                and type(context["transaction_id"]) is int
                and context["transaction_id"] > 0,
                "CONTEXT_INVALID",
            )
            if witness is not None:
                _require(
                    witness.connection() is connection
                    and witness.backend_pid == context["backend_pid"]
                    and witness.transaction_id == context["transaction_id"],
                    "CONTEXT_INVALID",
                )
            with session.no_autoflush:
                operator = session.scalar(
                    select(OperatorRecord)
                    .where(OperatorRecord.operator_id == values.operator_id)
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True, schema_translate_map={None: "app"})
                )
                api_session = session.scalar(
                    select(ApiSessionRecord)
                    .where(ApiSessionRecord.api_session_id == values.session_id)
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True, schema_translate_map={None: "app"})
                )
                token = session.scalar(
                    select(ApiTokenRecord)
                    .where(
                        ApiTokenRecord.api_token_id == values.token_id,
                        ApiTokenRecord.token_type == "ACCESS",
                    )
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True, schema_translate_map={None: "app"})
                )
                _require(
                    operator is not None
                    and operator.operator_id == values.operator_id
                    and operator.status == "ACTIVE"
                    and operator.deleted_at is None
                    and operator.must_change_password is False
                    and api_session is not None
                    and api_session.api_session_id == values.session_id
                    and api_session.operator_id == values.operator_id
                    and api_session.revoked_at is None
                    and api_session.authenticated_at == values.authenticated_at
                    and api_session.absolute_expires_at == values.absolute_expires_at
                    and type(api_session.refresh_generation) is int
                    and api_session.refresh_generation == values.refresh_generation
                    and token is not None
                    and token.api_token_id == values.token_id
                    and token.api_session_id == values.session_id
                    and token.token_type == "ACCESS"
                    and token.verifier_hash == values.verifier_hash
                    and token.issued_at == values.issued_at
                    and token.expires_at == values.access_expires_at
                    and token.revoked_at is None,
                    "FORBIDDEN",
                )
                assert api_session is not None
                _require(
                    required_permission in effective_permissions(session, values.operator_id),
                    "FORBIDDEN",
                )
                now = datetime.now(UTC)
                _require(
                    _utc(api_session.idle_expires_at)
                    and values.authenticated_at
                    <= now
                    < min(
                        values.access_expires_at,
                        values.absolute_expires_at,
                        values.idle_expires_at,
                        api_session.idle_expires_at,
                    )
                    and (now - values.authenticated_at).total_seconds()
                    <= self.owner.fresh_auth_seconds,
                    "FORBIDDEN",
                )
            _require(
                session.get_transaction() is root
                and root.is_active
                and session.get_nested_transaction() is nested,
                "CONTEXT_INVALID",
            )
            _capture_values(capture)
            connection.execute(text(_SET_WAIT_SQL), prior)
            # Restoring owner SQL settings can itself consume time. Temporal
            # acceptance is last; locks retain the checked row/permission state.
            now = datetime.now(UTC)
            _require(
                values.authenticated_at
                <= now
                < min(
                    values.access_expires_at,
                    values.absolute_expires_at,
                    values.idle_expires_at,
                    api_session.idle_expires_at,
                )
                and (now - values.authenticated_at).total_seconds()
                <= self.owner.fresh_auth_seconds,
                "FORBIDDEN",
            )
            if witness is None:
                with self._lock:
                    self._roots[session] = _RootFence(
                        ref(root),
                        ref(connection),
                        ref(current_thread()),
                        ref(capture),
                        context["backend_pid"],
                        context["transaction_id"],
                    )
        except AuthenticatedSessionFenceError:
            raise
        except (SQLAlchemyError, ValueError, TypeError, KeyError):
            raise AuthenticatedSessionFenceError("AUTHENTICATED_SESSION_UNAVAILABLE") from None
