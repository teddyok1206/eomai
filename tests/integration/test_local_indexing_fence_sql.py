"""Real disposable PostgreSQL SQL semantics under its owner, NOT service admission.

No runtime/Catalog login or live grant is claimed. The function exists only inside
each rolled-back root; committed synthetic Identity history is retained normally.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from eom_identity_service import (
    LOCAL_INDEXING_FENCE_CALL_SQL,
    LOCAL_INDEXING_FENCE_CREATE_SQL,
    LOCAL_INDEXING_FENCE_REVOKE_PUBLIC_SQL,
    LOCAL_INDEXING_FENCE_SIGNATURE,
    activate_local_indexing_service,
    disable_local_indexing_service,
    register_local_indexing_service,
)
from eom_operator_identity import (
    LocalIndexingServiceError,
    LocalIndexingServiceIdentity,
    LocalIndexingServiceStatus,
    local_indexing_service_reference,
    validate_local_indexing_service_current,
)
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_local_indexing_service_registry import identity
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(autouse=True)
def exact_opt_in() -> None:
    if os.environ.get("EOM_RUN_LOCAL_INDEXING_SERVICE_INTEGRATION") != "1":
        pytest.skip("use guarded local-indexing-service-tests; never production")


@dataclass(frozen=True)
class Target:
    engine: Engine
    identity: LocalIndexingServiceIdentity
    key: str

    @property
    def parameters(self) -> dict[str, Any]:
        item = self.identity
        return {
            "service_id": item.service_id,
            "revision_id": item.service_revision_id,
            "identity_sha256": item.content_sha256,
            "source_commit": item.runtime_source_commit,
        }


@pytest.fixture
def target(guarded_engine: Engine, request: pytest.FixtureRequest) -> Target:
    # These cases authenticate as the actual isolated owner. This deliberately
    # does not masquerade as the production Catalog DB login/runtime.
    item = identity(database_role=getattr(request, "param", guarded_engine.url.username))
    key = "synthetic-lif-sql:" + uuid4().hex
    with Session(guarded_engine) as session, session.begin():
        register_local_indexing_service(session, item, operation_key=key + ":register")
        activate_local_indexing_service(
            session,
            local_indexing_service_reference(item),
            expected_resource_version=1,
            operation_key=key + ":activate",
        )
    return Target(guarded_engine, item, key)


@pytest.fixture
def routine(target: Target):
    with target.engine.connect() as connection:
        root = connection.begin()
        try:
            assert (
                connection.scalar(
                    text("SELECT pg_catalog.to_regprocedure(:signature)"),
                    {"signature": LOCAL_INDEXING_FENCE_SIGNATURE},
                )
                is None
            ), "never replace or reinterpret an existing installed routine"
            connection.execute(text(LOCAL_INDEXING_FENCE_CREATE_SQL))
            connection.execute(text(LOCAL_INDEXING_FENCE_REVOKE_PUBLIC_SQL))
            yield connection
        finally:
            if root.is_active:
                root.rollback()


def read(connection: Connection, target: Target, **changes: object) -> dict[str, Any]:
    values = {**target.parameters, **changes}
    return connection.scalar(text(LOCAL_INDEXING_FENCE_CALL_SQL), values)


def test_actual_exact_function_returns_only_current_closed_metadata(
    routine, target: Target
) -> None:
    result = read(routine, target)
    assert set(result) == {"identity", "status"}
    item = LocalIndexingServiceIdentity.model_validate(result["identity"])
    status = LocalIndexingServiceStatus.model_validate(result["status"])
    assert item == target.identity
    assert status.resource_version == 2
    assert validate_local_indexing_service_current(status, item) == target.identity
    assert read(routine, target) == result
    assert routine.scalar(text("SELECT current_setting('role')")) == "none"


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_id", None),
        ("revision_id", None),
        ("identity_sha256", None),
        ("source_commit", None),
        ("service_id", "localindexservice_" + "f" * 32),
        ("revision_id", "localindexservicerev_" + "f" * 32),
        ("identity_sha256", "sha256:" + "f" * 64),
        ("source_commit", "f" * 40),
        ("source_commit", "3" * 40 + "\n"),
    ],
)
def test_actual_function_denies_missing_stale_or_malformed_pins(
    routine, target, field, value
) -> None:
    with pytest.raises(DBAPIError) as caught:
        read(routine, target, **{field: value})
    assert caught.value.orig.sqlstate == "P0001"
    assert caught.value.orig.diag.message_primary == "LOCAL_INDEXING_FENCE_FORBIDDEN"


def test_actual_set_role_even_to_same_owner_is_not_authenticated_session(routine, target) -> None:
    routine.execute(text("SELECT pg_catalog.set_config('role',SESSION_USER,true)"))
    with pytest.raises(DBAPIError) as caught:
        read(routine, target)
    assert caught.value.orig.sqlstate == "P0001"


def test_actual_shared_head_lock_blocks_control_writer_until_root_rollback(routine, target) -> None:
    read(routine, target)

    def disable() -> None:
        with Session(target.engine) as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout = '80ms'"))
            disable_local_indexing_service(
                session,
                target.identity.service_id,
                expected_resource_version=2,
                operation_key=target.key + ":disable",
            )

    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        pytest.raises(LocalIndexingServiceError) as caught,
    ):
        pool.submit(disable).result(timeout=10)
    assert str(caught.value.code) == "LOCAL_INDEXING_SERVICE_BUSY"
    routine.rollback()
    disable()
    with target.engine.connect() as connection, connection.begin():
        assert (
            connection.scalar(
                text("SELECT pg_catalog.to_regprocedure(:signature)"),
                {"signature": LOCAL_INDEXING_FENCE_SIGNATURE},
            )
            is None
        )
        connection.execute(text(LOCAL_INDEXING_FENCE_CREATE_SQL))
        connection.execute(text(LOCAL_INDEXING_FENCE_REVOKE_PUBLIC_SQL))
        with pytest.raises(DBAPIError) as denied:
            read(connection, target)
        assert denied.value.orig.sqlstate == "P0001"
        connection.rollback()


@pytest.mark.parametrize("target", ["different_indexing_principal"], indirect=True)
def test_actual_database_session_cannot_impersonate_registered_principal(routine, target) -> None:
    with pytest.raises(DBAPIError) as caught:
        read(routine, target)
    assert caught.value.orig.sqlstate == "P0001"
    assert caught.value.orig.diag.message_primary == "LOCAL_INDEXING_FENCE_FORBIDDEN"
