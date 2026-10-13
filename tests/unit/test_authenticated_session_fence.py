"""Synthetic HMAC/row/root tests only; no production provider, role or DB admission."""

from __future__ import annotations

import copy
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    AuthenticatedSessionFenceError,
    AuthenticatedSessionFenceOwnerPin,
)
from eom_identity_service import authenticated_session_fence as fence_module
from eom_identity_service import tokens as tokens_module
from eom_identity_service.models import ApiSessionRecord, ApiTokenRecord, OperatorRecord
from eom_identity_service.tokens import SessionTokenService, TokenCodec, TokenType
from eom_operator_identity.contracts import (
    OperatorProjection,
    OperatorStatus,
    PermissionKey,
    RoleKey,
)
from eom_operator_identity.errors import IdentityError
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

PIN = AuthenticatedSessionFenceOwnerPin("synthetic_owner", 12345, 900)
TEST_KEY = b"synthetic-session-capture-key-not-production" * 2
SQL_DIALECT = cast(type[Dialect], postgresql.dialect)()


class _Result:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def mappings(self) -> _Result:
        return self

    def one(self) -> dict[str, object]:
        return self.values


class SyntheticRoot:
    is_active = True


class SyntheticConnection:
    def __init__(self) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.options: dict[str, object] = {}
        self.engine = SimpleNamespace(get_execution_options=lambda: {})
        self.connection = SimpleNamespace(driver_connection=SimpleNamespace(autocommit=False))
        self.invalidated = False
        self.active = True
        self.isolation = "READ COMMITTED"
        self.context: dict[str, object] = {
            "isolation": "read committed",
            "read_only": "off",
            "role_name": PIN.role_name,
            "session_role_name": PIN.role_name,
            "role_oid": PIN.role_oid,
            "superuser": False,
            "bypassrls": False,
            "targets_lockable": True,
            "schemas": ["app", "pg_catalog"],
            "temp_schema": 0,
            "backend_pid": 11,
            "transaction_id": 22,
        }
        self.limits: dict[str, object] = {
            "lock_timeout": "0",
            "statement_timeout": "0",
            "lock_timeout_ms": 0,
            "statement_timeout_ms": 0,
        }
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.on_restore: Callable[[], None] = lambda: None
        self.fail = False

    def get_execution_options(self) -> dict[str, object]:
        return self.options

    def get_isolation_level(self) -> str:
        return self.isolation

    def in_transaction(self) -> bool:
        return self.active

    def execute(self, query: object, parameters: dict[str, object] | None = None) -> _Result:
        if self.fail:
            raise SQLAlchemyError("synthetic credential must not escape")
        sql = str(query)
        self.calls.append((sql, parameters or {}))
        if "pg_settings" in sql:
            return _Result(self.limits.copy())
        if "transaction_isolation" in sql:
            return _Result(self.context.copy())
        if parameters == {"lock_timeout": "0", "statement_timeout": "0"}:
            self.on_restore()
        return _Result({})


class SyntheticSession:
    is_active = True

    def __init__(self) -> None:
        now = datetime.now(UTC) - timedelta(seconds=1)
        self.root: SyntheticRoot | None = SyntheticRoot()
        self.nested: object | None = None
        self.connection_value = SyntheticConnection()
        self.no_autoflush = nullcontext()
        self.new: set[object] = set()
        self.dirty: set[object] = set()
        self.deleted: set[object] = set()
        self.operator = OperatorRecord(
            operator_id="operator_" + "a" * 32,
            status="ACTIVE",
            must_change_password=False,
            deleted_at=None,
            lock_version=1,
            username="synthetic",
            display_name="Synthetic",
        )
        self.api_session = ApiSessionRecord(
            api_session_id="apisession_" + "b" * 32,
            operator_id=self.operator.operator_id,
            authenticated_at=now,
            absolute_expires_at=now + timedelta(days=1),
            idle_expires_at=now + timedelta(hours=1),
            last_seen_at=now,
            refresh_generation=1,
            revoked_at=None,
            lock_version=1,
        )
        self.codec = TokenCodec(TEST_KEY)
        encoded = self.codec.issue(TokenType.ACCESS)
        self.raw_token = encoded.raw
        self.token = ApiTokenRecord(
            api_token_id="apitoken_" + "c" * 32,
            api_session_id=self.api_session.api_session_id,
            token_type="ACCESS",
            selector=encoded.selector,
            verifier_hash=encoded.verifier_hash,
            issued_at=now,
            expires_at=now + timedelta(minutes=30),
            revoked_at=None,
            consumed_at=None,
            last_used_at=None,
        )
        self.order: list[str] = []
        self.queries: list[Any] = []
        self.permissions = frozenset({PermissionKey.WORKFLOW_START})

    def get_transaction(self) -> SyntheticRoot | None:
        return self.root

    def get_nested_transaction(self) -> object | None:
        return self.nested

    def connection(self) -> SyntheticConnection:
        return self.connection_value

    def scalar(self, query: Any) -> Any:
        model = query.column_descriptions[0]["entity"]
        self.order.append(model.__name__)
        self.queries.append(query)
        return {
            OperatorRecord: self.operator,
            ApiSessionRecord: self.api_session,
            ApiTokenRecord: self.token,
        }[model]

    def get(self, model: object, _identity: str) -> OperatorRecord:
        assert model is OperatorRecord
        return self.operator

    def scalars(self, _query: object) -> tuple[str, ...]:
        return tuple(value.value for value in self.permissions)


def verified_capture(
    monkeypatch: pytest.MonkeyPatch, session: SyntheticSession | None = None
) -> tuple[SyntheticSession, AuthenticatedOperatorSession]:
    source = session or SyntheticSession()
    now = source.api_session.authenticated_at
    projection = OperatorProjection(
        operator_id=source.operator.operator_id,
        username="synthetic",
        display_name="Synthetic",
        status=OperatorStatus.ACTIVE,
        must_change_password=False,
        roles=(RoleKey.AUTHOR,),
        effective_permissions=(PermissionKey.WORKFLOW_START,),
        resource_version=1,
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(tokens_module, "operator_projection", lambda *_args: projection)
    capture = SessionTokenService(source.codec).capture_access(
        cast(Session, source), source.raw_token
    )
    source.order.clear()
    source.queries.clear()
    return source, capture


def assert_current(
    source: SyntheticSession,
    capture: AuthenticatedOperatorSession,
    adapter: AuthenticatedSessionFence | None = None,
) -> None:
    (adapter or AuthenticatedSessionFence(PIN)).assert_current(
        cast(Session, source), capture, required_permission=PermissionKey.WORKFLOW_START
    )


def test_actual_hmac_capture_is_opaque_and_fences_exact_share_order_without_activity_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, capture = verified_capture(monkeypatch)
    before = (
        source.api_session.last_seen_at,
        source.api_session.idle_expires_at,
        source.api_session.refresh_generation,
        source.token.last_used_at,
    )
    assert capture.operator_id == source.operator.operator_id
    assert source.raw_token not in repr(capture) and source.token.verifier_hash not in repr(capture)
    assert not hasattr(capture, "model_dump") and not hasattr(capture, "raw_token")
    assert_current(source, capture)
    assert source.order == ["OperatorRecord", "ApiSessionRecord", "ApiTokenRecord"]
    for query in source.queries:
        sql = str(query.compile(dialect=SQL_DIALECT))
        assert "FOR SHARE" in sql and "REFRESH" not in sql
        assert query.get_execution_options()["populate_existing"] is True
    assert (
        source.api_session.last_seen_at,
        source.api_session.idle_expires_at,
        source.api_session.refresh_generation,
        source.token.last_used_at,
    ) == before


def test_bad_hmac_never_creates_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    source, _capture = verified_capture(monkeypatch)
    bad = TokenCodec(b"a different synthetic HMAC key value").issue(TokenType.ACCESS)
    source.token.selector = bad.selector
    source.token.verifier_hash = bad.verifier_hash
    with pytest.raises(IdentityError):
        SessionTokenService(source.codec).capture_access(cast(Session, source), bad.raw)


@pytest.mark.parametrize("fault", ["new", "bare", "copy", "deepcopy", "changed", "nested_bool"])
def test_forged_copied_mutated_capture_is_not_an_authority_dto(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    source, capture = verified_capture(monkeypatch)
    if fault == "new":
        with pytest.raises(AuthenticatedSessionFenceError):
            AuthenticatedOperatorSession()
        return
    if fault == "bare":
        capture = object.__new__(AuthenticatedOperatorSession)
    elif fault in {"copy", "deepcopy"}:
        try:
            capture = copy.copy(capture) if fault == "copy" else copy.deepcopy(capture)
        except (TypeError, AuthenticatedSessionFenceError):
            return
    elif fault == "changed":
        object.__setattr__(
            capture, "_values", replace(capture._values, token_id="apitoken_" + "d" * 32)
        )
    else:
        object.__setattr__(capture._values, "refresh_generation", True)
    with pytest.raises(AuthenticatedSessionFenceError, match="CAPTURE_INVALID"):
        assert_current(source, capture)
    assert not source.order


@pytest.mark.parametrize(
    "record,field,value",
    [
        ("operator", "status", "DISABLED"),
        ("operator", "deleted_at", datetime.now(UTC)),
        ("operator", "must_change_password", True),
        ("operator", "operator_id", "operator_" + "d" * 32),
        ("api_session", "operator_id", "operator_" + "d" * 32),
        ("api_session", "api_session_id", "apisession_" + "d" * 32),
        ("api_session", "revoked_at", datetime.now(UTC)),
        ("api_session", "refresh_generation", 2),
        ("api_session", "refresh_generation", True),
        ("api_session", "idle_expires_at", datetime.now(UTC) - timedelta(days=1)),
        ("api_session", "idle_expires_at", None),
        ("api_session", "absolute_expires_at", datetime.now(UTC)),
        ("token", "revoked_at", datetime.now(UTC)),
        ("token", "token_type", "REFRESH"),
        ("token", "api_session_id", "apisession_" + "d" * 32),
        ("token", "api_token_id", "apitoken_" + "d" * 32),
        ("token", "verifier_hash", "sha256:" + "d" * 64),
        ("token", "expires_at", datetime.now(UTC)),
    ],
)
def test_current_rows_not_old_capture_deny_revocation_identity_rotation_and_expiry(
    monkeypatch: pytest.MonkeyPatch, record: str, field: str, value: Any
) -> None:
    source, capture = verified_capture(monkeypatch)
    setattr(getattr(source, record), field, value)
    with pytest.raises(AuthenticatedSessionFenceError, match="FORBIDDEN"):
        assert_current(source, capture)


def test_current_permission_revocation_denies_and_digest_is_not_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, capture = verified_capture(monkeypatch)
    source.permissions = frozenset()
    with pytest.raises(AuthenticatedSessionFenceError, match="FORBIDDEN"):
        assert_current(source, capture)


@pytest.mark.parametrize(
    "field,value",
    [
        ("role_name", "other"),
        ("session_role_name", "other"),
        ("role_oid", 1),
        ("role_oid", True),
        ("superuser", True),
        ("bypassrls", True),
        ("targets_lockable", False),
        ("schemas", ["public", "app", "pg_catalog"]),
        ("temp_schema", 1),
        ("temp_schema", False),
        ("isolation", "repeatable read"),
        ("read_only", "on"),
        ("backend_pid", True),
        ("transaction_id", False),
    ],
)
def test_actual_context_not_configured_claim_denies_before_target_locks(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    source, capture = verified_capture(monkeypatch)
    source.connection_value.context[field] = value
    with pytest.raises(AuthenticatedSessionFenceError, match="CONTEXT_INVALID"):
        assert_current(source, capture)
    assert not source.order


@pytest.mark.parametrize(
    "fault",
    [
        "no_root",
        "inactive",
        "nested",
        "autocommit",
        "dirty",
        "dialect",
        "lost_root",
        "connection",
        "thread",
    ],
)
def test_exact_root_connection_thread_lifetime_and_first_savepoint_guard(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    source, capture = verified_capture(monkeypatch)
    adapter = AuthenticatedSessionFence(PIN)
    if fault in {"connection", "thread"}:
        assert_current(source, capture, adapter)
    if fault == "no_root":
        source.root = None
    elif fault == "inactive":
        source.is_active = False
    elif fault == "nested":
        source.nested = object()
    elif fault == "autocommit":
        source.connection_value.connection.driver_connection.autocommit = True
    elif fault == "dirty":
        source.dirty.add(source.token)
    elif fault == "dialect":
        source.connection_value.dialect.name = "sqlite"
    elif fault == "lost_root":
        original = source.scalar

        def scalar(query: Any) -> Any:
            value = original(query)
            source.root = None
            return value

        source.scalar = scalar  # type: ignore[method-assign]
    elif fault == "connection":
        source.connection_value = SyntheticConnection()
    if fault == "thread":
        with (
            ThreadPoolExecutor(max_workers=1) as pool,
            pytest.raises(AuthenticatedSessionFenceError),
        ):
            pool.submit(assert_current, source, capture, adapter).result()
    else:
        with pytest.raises(AuthenticatedSessionFenceError):
            assert_current(source, capture, adapter)


def test_later_root_reacquires_and_same_root_savepoint_rechecks_retained_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, capture = verified_capture(monkeypatch)
    adapter = AuthenticatedSessionFence(PIN)
    assert_current(source, capture, adapter)
    source.nested = object()
    assert_current(source, capture, adapter)
    source.nested = None
    source.root = SyntheticRoot()
    source.connection_value.context["transaction_id"] = 23
    assert_current(source, capture, adapter)
    assert len(source.order) == 9


def test_late_clock_after_permission_sql_and_timeout_restore_is_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, capture = verified_capture(monkeypatch)
    late = source.token.expires_at + timedelta(seconds=1)

    class Clock(datetime):
        @classmethod
        def now(cls, _tz: object = None) -> Clock:
            return cls.fromtimestamp(late.timestamp(), UTC)

    source.connection_value.on_restore = lambda: monkeypatch.setattr(
        fence_module, "datetime", Clock
    )
    with pytest.raises(AuthenticatedSessionFenceError, match="FORBIDDEN"):
        assert_current(source, capture)


def test_fresh_auth_expiry_not_idle_refresh_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    source = SyntheticSession()
    source.api_session.authenticated_at -= timedelta(hours=1)
    source, capture = verified_capture(monkeypatch, source)
    with pytest.raises(AuthenticatedSessionFenceError, match="FORBIDDEN"):
        assert_current(source, capture)


def test_database_error_is_content_free_and_requires_root_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, capture = verified_capture(monkeypatch)
    source.connection_value.fail = True
    with pytest.raises(AuthenticatedSessionFenceError) as failure:
        assert_current(source, capture)
    assert str(failure.value) == "AUTHENTICATED_SESSION_UNAVAILABLE"
    assert failure.value.__cause__ is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("role_oid", True),
        ("role_oid", 0),
        ("fresh_auth_seconds", True),
        ("fresh_auth_seconds", 0),
        ("role_name", "postgres;bad"),
    ],
)
def test_configured_owner_values_are_required_strict_small_values(field: str, value: Any) -> None:
    body: dict[str, Any] = {
        "role_name": PIN.role_name,
        "role_oid": PIN.role_oid,
        "fresh_auth_seconds": 900,
    }
    body[field] = value
    with pytest.raises(AuthenticatedSessionFenceError):
        AuthenticatedSessionFenceOwnerPin(**body)
