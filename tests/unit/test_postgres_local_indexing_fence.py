"""Synthetic Session/SQL responses and runtime fixture, NOT real principal acceptance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_identity_service import local_indexing_fence_sql as sql
from eom_identity_service import local_indexing_runtime as runtime
from eom_identity_service.postgres_local_indexing_fence import PostgresLocalIndexingServiceFence
from eom_operator_identity import local_indexing_runtime_bytes, local_indexing_service_reference
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from tests.unit.test_local_indexing_fence_sql import FIELDS, OWNER, Result
from tests.unit.test_local_indexing_runtime_admission import digest
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_local_indexing_service_contracts import identity, status_document


class Root:
    is_active = True


class Connection:
    def __init__(self, value: object) -> None:
        self.dialect = SimpleNamespace(name="postgresql", driver="psycopg")
        self.connection = SimpleNamespace(driver_connection=SimpleNamespace(autocommit=False))
        self.invalidated, self.active, self.nested = False, True, False
        self.isolation = "READ COMMITTED"
        self.context = {
            "principal": sql.LOCAL_INDEXING_FENCE_EXECUTE_ROLE,
            "role_name": sql.LOCAL_INDEXING_FENCE_EXECUTE_ROLE,
            "isolation": "read committed",
            "read_only": "off",
            "schemas": ["app", "pg_catalog"],
            "temp_schema": 0,
            "backend_pid": 12345,
            "transaction_id": 23456,
        }
        self.limits = [
            {"name": "lock_timeout", "milliseconds": 100, "previous": "100ms"},
            {"name": "statement_timeout", "milliseconds": 0, "previous": "0"},
        ]
        self.installation = {field: True for field in FIELDS}
        self.value = value
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_on = ""

    def get_isolation_level(self) -> str:
        return self.isolation

    def in_transaction(self) -> bool:
        return self.active

    def in_nested_transaction(self) -> bool:
        return self.nested

    def execute(self, statement: object, values: dict[str, object] | None = None) -> Result:
        query = str(statement)
        self.calls.append((query, values or {}))
        if self.fail_on and self.fail_on in query:
            raise SQLAlchemyError("SECRET_MARKER")
        if "owner_ok" in query:
            return Result([self.installation])
        if "pg_settings" in query:
            return Result(self.limits)
        if "transaction_isolation" in query:
            return Result([self.context])
        return Result([], self.value)


class SyntheticSession:
    def __init__(self, value: object) -> None:
        self.root: Root | None = Root()
        self.nested: object | None = None
        self.new: set[object] = set()
        self.dirty: set[object] = set()
        self.deleted: set[object] = set()
        self.db = Connection(value)

    def get_transaction(self) -> Root | None:
        return self.root

    def get_nested_transaction(self) -> object | None:
        return self.nested

    def connection(self) -> Connection:
        return self.db


@pytest.fixture
def case(installed: dict[str, Any]) -> tuple[PostgresLocalIndexingServiceFence, SyntheticSession]:
    item = identity(
        database_role=sql.LOCAL_INDEXING_FENCE_EXECUTE_ROLE, runtime_source_commit="4" * 40
    )
    service = local_indexing_service_reference(item)
    config = installed["config"].model_copy(update={"service": service})
    raw = local_indexing_runtime_bytes(config)
    installed["path"].write_bytes(raw)
    pin = runtime.LocalIndexingRuntimePin(service, config.runtime_source_commit, digest(raw))
    actual = runtime.capture_local_indexing_runtime(pin)
    adapter = PostgresLocalIndexingServiceFence(OWNER, pin, actual)
    values = {
        "identity": item.model_dump(mode="json"),
        "status": status_document(current=service.model_dump(mode="json")),
    }
    return adapter, SyntheticSession(values)


def invoke(case: tuple[PostgresLocalIndexingServiceFence, SyntheticSession]):
    adapter, session = case
    return adapter.fence_current_service(cast(Session, session))


def test_exact_pins_retained_root_and_smaller_timeout_restored(case) -> None:
    adapter, session = case
    checked = invoke(case)
    assert local_indexing_service_reference(checked) == adapter.pin.service
    calls = session.db.calls
    assert calls[1][1] == {"name": "lock_timeout", "value": "100ms"}
    assert calls[2][1] == {"name": "statement_timeout", "value": "10000ms"}
    assert calls[-2][1] == {"name": "lock_timeout", "value": "100ms"}
    assert calls[-1][1] == {"name": "statement_timeout", "value": "0"}
    query, bound = next((q, p) for q, p in calls if q == sql.LOCAL_INDEXING_FENCE_CALL_SQL)
    assert adapter.pin.service.service_id not in query
    assert bound == {
        "service_id": adapter.pin.service.service_id,
        "revision_id": adapter.pin.service.service_revision_id,
        "identity_sha256": adapter.pin.service.service_identity_sha256,
        "source_commit": adapter.pin.runtime_source_commit,
    }
    session.nested, session.db.nested = object(), True
    assert invoke(case) == checked
    assert len(adapter._witnesses) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "no_root",
        "inactive",
        "savepoint",
        "dirty",
        "dialect",
        "driver",
        "autocommit",
        "invalidated",
        "no_transaction",
        "isolation",
    ],
)
def test_cannot_start_fence_in_implicit_or_wrong_database_root(case, fault: str) -> None:
    _adapter, session = case
    if fault == "no_root":
        session.root = None
    elif fault == "inactive":
        session.root.is_active = False
    elif fault == "savepoint":
        session.nested, session.db.nested = object(), True
    elif fault == "dirty":
        session.dirty.add(object())
    elif fault in {"dialect", "driver"}:
        setattr(session.db.dialect, "name" if fault == "dialect" else "driver", "sqlite")
    elif fault == "autocommit":
        session.db.connection.driver_connection.autocommit = True
    elif fault == "invalidated":
        session.db.invalidated = True
    elif fault == "no_transaction":
        session.db.active = False
    else:
        session.db.isolation = "REPEATABLE READ"
    with pytest.raises(sql.LocalIndexingFenceError, match="CONTEXT_INVALID"):
        invoke(case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal", "synthetic_owner"),
        ("role_name", "synthetic_owner"),
        ("read_only", "on"),
        ("schemas", ["public", "app"]),
        ("temp_schema", 1),
        ("temp_schema", False),
        ("backend_pid", True),
        ("transaction_id", 0),
    ],
)
def test_actual_principal_and_unshadowed_context_required_on_reuse(case, field, value) -> None:
    invoke(case)
    case[1].db.context[field] = value
    with pytest.raises(sql.LocalIndexingFenceError, match="CONTEXT_INVALID"):
        invoke(case)


@pytest.mark.parametrize(
    "fault", ["shape", "disabled", "stale", "hash", "source", "extra_identity", "missing_status"]
)
def test_returned_metadata_is_revalidated_and_never_becomes_a_grant(case, fault: str) -> None:
    values = deepcopy(case[1].db.value)
    if fault == "shape":
        values["grant"] = "ADMIN"
    elif fault == "disabled":
        values["status"]["state"] = "DISABLED"
    elif fault == "stale":
        values["status"]["current"]["service_revision_id"] = "localindexservicerev_" + "f" * 32
    elif fault == "hash":
        values["identity"]["content_sha256"] = "sha256:" + "f" * 64
    elif fault == "source":
        values["identity"]["runtime_source_commit"] = "f" * 40
    elif fault == "extra_identity":
        values["identity"]["permissions"] = ["ADMIN"]
    else:
        del values["status"]
    case[1].db.value = values
    with pytest.raises(sql.LocalIndexingFenceError):
        invoke(case)
    assert not case[0]._witnesses


def test_runtime_revocation_denies_before_any_database_access(case) -> None:
    case[0].runtime.close()
    with pytest.raises(sql.LocalIndexingFenceError, match="UNAVAILABLE"):
        invoke(case)
    assert not case[1].db.calls


@pytest.mark.parametrize(
    "phase", ["pg_settings", "owner_ok", "eom_fence_local_indexing_service_v1"]
)
def test_db_failure_redacted_no_restore_retry_commit_or_witness(case, phase: str) -> None:
    case[1].db.fail_on = phase
    with pytest.raises(sql.LocalIndexingFenceError) as caught:
        invoke(case)
    assert str(caught.value) == "LOCAL_INDEXING_FENCE_UNAVAILABLE"
    assert caught.value.__cause__ is None and not case[0]._witnesses
    assert not any(values.get("value") == "0" for _query, values in case[1].db.calls)


def test_root_replacement_and_wrong_thread_cannot_reuse_witness(case) -> None:
    invoke(case)
    before = len(case[1].db.calls)
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        pytest.raises(sql.LocalIndexingFenceError, match="CONTEXT_INVALID"),
    ):
        pool.submit(invoke, case).result()
    assert len(case[1].db.calls) == before
    case[1].root, case[1].nested = Root(), object()
    with pytest.raises(sql.LocalIndexingFenceError, match="CONTEXT_INVALID"):
        invoke(case)
