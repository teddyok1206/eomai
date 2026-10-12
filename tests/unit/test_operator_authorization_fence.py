"""Synthetic active-Session/routine/freshness/lifetime tests; no live database."""

from __future__ import annotations

import gc
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast
from weakref import ref

import pytest
from eom_identity_service import (
    OPERATOR_AUTHORIZATION_FENCE_CALL_SQL,
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    PostgresOperatorAuthorizationFence,
)
from eom_identity_service.models import OperatorRecord
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from tests.unit.test_operator_authorization_fence_sql import FIELDS, SyntheticResult

OPERATOR_ID = "operator_" + "a" * 32
OWNER = OperatorAuthorizationFenceOwnerPin("synthetic_owner", 12345)


class SyntheticRoot:
    is_active = True
    session: object | None = None


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
            "role_name": "eom_catalog_manager_runtime",
            "backend_pid": 3456,
            "transaction_id": 4567,
            "schemas": ["app", "pg_catalog"],
            "temp_schema": 0,
        }
        self.limits: dict[str, object] = {
            "lock_timeout": "0",
            "statement_timeout": "0",
            "lock_timeout_ms": 0,
            "statement_timeout_ms": 0,
        }
        self.installation: dict[str, object] = {field: True for field in FIELDS}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_on: str | None = None
        self.error: SQLAlchemyError = SQLAlchemyError("synthetic-secret-marker")

    def get_execution_options(self) -> dict[str, object]:
        return self.options

    def get_isolation_level(self) -> str:
        return self.isolation

    def in_transaction(self) -> bool:
        return self.active

    def execute(
        self, statement: object, parameters: dict[str, object] | None = None
    ) -> SyntheticResult:
        sql = str(statement)
        self.calls.append((sql, parameters or {}))
        if self.fail_on and self.fail_on in sql:
            raise self.error
        if "transaction_isolation" in sql:
            return SyntheticResult([self.context.copy()])
        if "pg_settings" in sql:
            return SyntheticResult([self.limits.copy()])
        if "owner_ok" in sql:
            return SyntheticResult([self.installation.copy()])
        return SyntheticResult([])


class SyntheticSession:
    def __init__(self) -> None:
        self.root: SyntheticRoot | None = SyntheticRoot()
        self.root.session = self
        self.nested: object | None = None
        self.connection_value = SyntheticConnection()
        self.no_autoflush = nullcontext()
        self.new: set[object] = set()
        self.dirty: set[object] = set()
        self.deleted: set[object] = set()
        self.operator: OperatorRecord | None = OperatorRecord(
            operator_id=OPERATOR_ID, status="ACTIVE", must_change_password=False, deleted_at=None
        )
        self.current: dict[str, object] = {
            "status": "ACTIVE",
            "must_change_password": False,
            "deleted_at": None,
        }
        self.refreshes = 0
        self.lose_root_on_refresh = False

    def get_transaction(self) -> SyntheticRoot | None:
        return self.root

    def get_nested_transaction(self) -> object | None:
        return self.nested

    def connection(self) -> SyntheticConnection:
        return self.connection_value

    def scalar(self, statement: Any) -> OperatorRecord | None:
        assert statement.get_execution_options()["populate_existing"] is True
        assert statement.get_execution_options()["schema_translate_map"] == {None: "app"}
        assert "FROM app.operators" in str(
            statement.compile(schema_translate_map={None: "app"}, render_schema_translate=True)
        )
        assert statement.compile().params == {"operator_id_1": OPERATOR_ID}
        self.refreshes += 1
        if self.operator is not None:
            for name, value in self.current.items():
                setattr(self.operator, name, value)
        if self.lose_root_on_refresh:
            self.root = None
        return self.operator


def fence(
    session: SyntheticSession,
    adapter: PostgresOperatorAuthorizationFence | None = None,
    operator_id: str = OPERATOR_ID,
) -> None:
    (adapter or PostgresOperatorAuthorizationFence(OWNER)).fence_current_operator(
        cast(Session, session), operator_id
    )


def lock_calls(session: SyntheticSession) -> int:
    return sum(
        sql == OPERATOR_AUTHORIZATION_FENCE_CALL_SQL for sql, _ in session.connection_value.calls
    )


def test_fixed_bound_call_timeouts_and_fresh_operator_without_grant() -> None:
    session = SyntheticSession()
    fence(session)
    calls = session.connection_value.calls
    assert len(calls) == 6 and session.refreshes == 1
    assert calls[1][1] == {"lock_timeout": "5000ms", "statement_timeout": "10000ms"}
    assert "txid_current()" in calls[2][0]
    assert calls[-2] == (OPERATOR_AUTHORIZATION_FENCE_CALL_SQL, {"operator_id": OPERATOR_ID})
    assert calls[-1][1] == {"lock_timeout": "0", "statement_timeout": "0"}
    assert OPERATOR_ID not in calls[-2][0]


@pytest.mark.parametrize(
    "operator_id",
    ["ADMIN", "operator_not-canonical", "operator_" + "a" * 32 + "'", "", "operator_" + "A" * 32],
)
def test_invalid_identity_fails_before_any_database_call(operator_id: str) -> None:
    session = SyntheticSession()
    with pytest.raises(
        OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_OPERATOR_INVALID"
    ):
        fence(session, operator_id=operator_id)
    assert not session.connection_value.calls


@pytest.mark.parametrize("value,expected", [(0, 5000), (1000, 1000), (5000, 5000), (6000, 5000)])
def test_wait_caps_preserve_stricter_owner_values_and_restore_success(
    value: int, expected: int
) -> None:
    session = SyntheticSession()
    session.connection_value.limits.update(
        lock_timeout_ms=value,
        lock_timeout=str(value) + "ms",
        statement_timeout_ms=1000,
        statement_timeout="1s",
    )
    fence(session)
    assert session.connection_value.calls[1][1] == {
        "lock_timeout": str(expected) + "ms",
        "statement_timeout": "1000ms",
    }
    assert session.connection_value.calls[-1][1] == {
        "lock_timeout": str(value) + "ms",
        "statement_timeout": "1s",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("lock_timeout_ms", True),
        ("statement_timeout_ms", -1),
        ("lock_timeout", ""),
        ("statement_timeout", "x" * 33),
    ],
)
def test_invalid_wait_metadata_cannot_open_unbounded_fence(field: str, value: object) -> None:
    session = SyntheticSession()
    session.connection_value.limits[field] = value
    with pytest.raises(
        OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
    ):
        fence(session)
    assert lock_calls(session) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("schemas", ["pg_catalog", "app"]),
        ("schemas", ["app", "public"]),
        ("schemas", ["app", "pg_catalog", "pg_temp"]),
        ("temp_schema", 1234),
        ("temp_schema", False),
    ],
)
def test_native_context_denies_schema_or_temp_shadow_on_first_and_reuse(
    field: str, value: object
) -> None:
    for reused in (False, True):
        session, adapter = SyntheticSession(), PostgresOperatorAuthorizationFence(OWNER)
        if reused:
            fence(session, adapter)
            session.nested = object()
        before = lock_calls(session)
        session.connection_value.context[field] = value
        with pytest.raises(
            OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
        ):
            fence(session, adapter)
        assert lock_calls(session) == before


@pytest.mark.parametrize(
    "mode",
    [
        "no_root",
        "inactive",
        "first_nested",
        "dialect",
        "connection_autocommit",
        "engine_autocommit",
        "driver_autocommit",
        "driver_unknown",
        "repeatable",
        "invalidated",
        "no_db_transaction",
        "readonly",
        "wrong_role",
        "bad_pid",
        "bad_xid",
        "identity_dirty",
    ],
)
def test_root_readcommitted_context_is_mandatory(mode: str) -> None:
    session = SyntheticSession()
    connection = session.connection_value
    if mode == "no_root":
        session.root = None
    elif mode == "inactive":
        assert session.root is not None
        session.root.is_active = False
    elif mode == "first_nested":
        session.nested = object()
    elif mode == "dialect":
        connection.dialect.name = "sqlite"
    elif mode == "connection_autocommit":
        connection.options["isolation_level"] = "AUTOCOMMIT"
    elif mode == "engine_autocommit":
        connection.engine.get_execution_options = lambda: {"isolation_level": "AUTOCOMMIT"}
    elif mode == "driver_autocommit":
        connection.connection.driver_connection.autocommit = True
    elif mode == "driver_unknown":
        del connection.connection.driver_connection.autocommit
    elif mode == "repeatable":
        connection.isolation = "REPEATABLE READ"
    elif mode == "invalidated":
        connection.invalidated = True
    elif mode == "no_db_transaction":
        connection.active = False
    elif mode == "readonly":
        connection.context["read_only"] = "on"
    elif mode == "wrong_role":
        connection.context["role_name"] = "synthetic_owner"
    elif mode == "bad_pid":
        connection.context["backend_pid"] = True
    elif mode == "bad_xid":
        connection.context["transaction_id"] = 0
    elif mode == "identity_dirty":
        session.dirty.add(OperatorRecord(operator_id=OPERATOR_ID))
    with pytest.raises(
        OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
    ):
        fence(session)
    assert lock_calls(session) == 0


@pytest.mark.parametrize(
    "field,value",
    [("status", "DISABLED"), ("must_change_password", True), ("deleted_at", "synthetic-deleted")],
)
def test_stale_identity_map_state_is_refreshed_before_denial(field: str, value: object) -> None:
    session = SyntheticSession()
    assert session.operator is not None and session.operator.status == "ACTIVE"
    session.current[field] = value
    with pytest.raises(
        OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
    ):
        fence(session)
    assert session.refreshes == 1 and lock_calls(session) == 1


def test_missing_operator_or_lost_root_never_records_retained_witness() -> None:
    for missing in (True, False):
        session, adapter = SyntheticSession(), PostgresOperatorAuthorizationFence(OWNER)
        if missing:
            session.operator = None
        else:
            session.lose_root_on_refresh = True
        with pytest.raises(OperatorAuthorizationFenceError):
            fence(session, adapter)
        assert not adapter._witnesses


def test_true_root_witness_allows_nested_fresh_checks_without_new_lock() -> None:
    session, adapter = SyntheticSession(), PostgresOperatorAuthorizationFence(OWNER)
    fence(session, adapter)
    session.nested = object()
    fence(session, adapter)
    assert lock_calls(session) == 1 and session.refreshes == 2
    assert len(session.connection_value.calls) == 11
    session.current["status"] = "DISABLED"
    with pytest.raises(
        OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
    ):
        fence(session, adapter)
    assert lock_calls(session) == 1 and session.refreshes == 3


@pytest.mark.parametrize(
    "change", ["root", "rollback", "connection", "pid", "xid", "operator", "adapter"]
)
def test_nested_without_exact_retained_root_identity_cannot_reacquire(change: str) -> None:
    session, adapter = SyntheticSession(), PostgresOperatorAuthorizationFence(OWNER)
    fence(session, adapter)
    session.nested = object()
    operator_id = OPERATOR_ID
    if change == "root":
        session.root = SyntheticRoot()
    elif change == "rollback":
        session.root = None
    elif change == "connection":
        session.connection_value = SyntheticConnection()
    elif change == "pid":
        session.connection_value.context["backend_pid"] = 1234
    elif change == "xid":
        session.connection_value.context["transaction_id"] = 1234
    elif change == "operator":
        operator_id = "operator_" + "b" * 32
    elif change == "adapter":
        adapter = PostgresOperatorAuthorizationFence(OWNER)
    before = lock_calls(session)
    with pytest.raises(
        OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
    ):
        fence(session, adapter, operator_id)
    assert lock_calls(session) == before


def test_wrong_thread_witness_is_denied_before_session_database_use() -> None:
    session, adapter = SyntheticSession(), PostgresOperatorAuthorizationFence(OWNER)
    fence(session, adapter)
    session.nested = object()
    before = len(session.connection_value.calls)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fence, session, adapter)
        with pytest.raises(
            OperatorAuthorizationFenceError, match="OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
        ):
            future.result()
    assert len(session.connection_value.calls) == before


def test_weak_witness_does_not_retain_session_or_root_gc_cycles() -> None:
    session, adapter = SyntheticSession(), PostgresOperatorAuthorizationFence(OWNER)
    fence(session, adapter)
    assert session.root is not None
    session_ref, root_ref = ref(session), ref(session.root)
    assert len(adapter._witnesses) == 1
    del session
    gc.collect()
    assert session_ref() is None and root_ref() is None and not adapter._witnesses


def test_root_replacement_requires_new_real_root_acquisition() -> None:
    session, adapter = SyntheticSession(), PostgresOperatorAuthorizationFence(OWNER)
    fence(session, adapter)
    session.root = SyntheticRoot()
    session.connection_value.context["transaction_id"] = 5678
    fence(session, adapter)
    assert lock_calls(session) == 2 and len(adapter._witnesses) == 1


@pytest.mark.parametrize(
    "phase", ["set_config", "transaction_isolation", "owner_ok", "eom_fence_operator"]
)
def test_database_failures_are_content_free_without_commit_or_fallback(phase: str) -> None:
    session, adapter = SyntheticSession(), PostgresOperatorAuthorizationFence(OWNER)
    session.connection_value.fail_on = phase
    with pytest.raises(OperatorAuthorizationFenceError) as caught:
        fence(session, adapter)
    assert str(caught.value) == "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
    assert "synthetic-secret-marker" not in str(caught.value)
    assert not adapter._witnesses


def test_fixed_database_missing_row_code_is_denied_without_raw_diagnostics() -> None:
    class MissingRow(Exception):
        sqlstate = "P0001"
        diag = SimpleNamespace(message_primary="OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")

    session = SyntheticSession()
    session.connection_value.fail_on = OPERATOR_AUTHORIZATION_FENCE_CALL_SQL
    session.connection_value.error = DBAPIError(
        "synthetic-sensitive-sql", None, MissingRow("synthetic-sensitive-body")
    )
    with pytest.raises(OperatorAuthorizationFenceError) as caught:
        fence(session)
    assert str(caught.value) == "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
