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
    LOCAL_INDEXING_FENCE_BODY_SHA256,
    LOCAL_INDEXING_FENCE_CALL_SQL,
    LOCAL_INDEXING_FENCE_CREATE_SQL,
    LOCAL_INDEXING_FENCE_EXECUTE_ROLE,
    LOCAL_INDEXING_FENCE_REVOKE_PUBLIC_SQL,
    LOCAL_INDEXING_FENCE_SIGNATURE,
    LocalIndexingFenceError,
    LocalIndexingFenceOwnerPin,
    activate_local_indexing_service,
    disable_local_indexing_service,
    install_local_indexing_service_fence,
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


@pytest.fixture
def installation_root(guarded_engine: Engine):
    """Real DDL/ACL, not a Catalog login. All DB-scoped grants roll back.

    The fixed Catalog role must already exist. Never create/modify a cluster role,
    read its credentials, or reuse a production DB for this opt-in acceptance.
    """
    with Session(guarded_engine) as session:
        root = session.begin()
        try:
            assert (
                session.scalar(
                    text("SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:role"),
                    {"role": LOCAL_INDEXING_FENCE_EXECUTE_ROLE},
                )
                is not None
            ), "the existing fixed Catalog role is a required integration resource"
            assert (
                session.scalar(
                    text("SELECT pg_catalog.to_regprocedure(:signature)"),
                    {"signature": LOCAL_INDEXING_FENCE_SIGNATURE},
                )
                is None
            ), "never reinterpret or replace an installed interface"
            owner = session.execute(
                text("SELECT SESSION_USER, oid FROM pg_catalog.pg_roles WHERE rolname=SESSION_USER")
            ).one()
            # Use only the known fixed role; these privileges are local to the
            # marked disposable DB and disappear with this root's rollback.
            session.execute(text("GRANT USAGE ON SCHEMA app TO eom_catalog_manager_runtime"))
            yield session, LocalIndexingFenceOwnerPin(owner[0], owner[1])
        finally:
            if root.is_active:
                root.rollback()


def test_supported_installation_is_atomic_and_exact_replay_does_no_ddl(installation_root):
    session, owner = installation_root
    created = install_local_indexing_service_fence(session, owner)
    assert created.disposition == "CREATED" and created.owner == owner
    assert created.body_sha256 == LOCAL_INDEXING_FENCE_BODY_SHA256
    oid = session.scalar(
        text("SELECT pg_catalog.to_regprocedure(:signature)::pg_catalog.oid"),
        {"signature": LOCAL_INDEXING_FENCE_SIGNATURE},
    )
    assert install_local_indexing_service_fence(session, owner).disposition == "REPLAYED"
    assert (
        session.scalar(
            text("SELECT pg_catalog.to_regprocedure(:signature)::pg_catalog.oid"),
            {"signature": LOCAL_INDEXING_FENCE_SIGNATURE},
        )
        == oid
    )
    assert session.in_transaction()


@pytest.mark.parametrize("fault", ["owner_name", "owner_oid", "set_role"])
def test_installation_rejects_false_owner_without_creating_function(installation_root, fault):
    session, owner = installation_root
    if fault == "owner_name":
        owner = LocalIndexingFenceOwnerPin("not_the_owner", owner.role_oid)
    elif fault == "owner_oid":
        owner = LocalIndexingFenceOwnerPin(owner.role_name, owner.role_oid + 1)
    else:
        session.execute(text("SELECT pg_catalog.set_config('role',SESSION_USER,true)"))
    with pytest.raises(LocalIndexingFenceError, match="FORBIDDEN"):
        install_local_indexing_service_fence(session, owner)
    assert (
        session.scalar(
            text("SELECT pg_catalog.to_regprocedure(:signature)"),
            {"signature": LOCAL_INDEXING_FENCE_SIGNATURE},
        )
        is None
    )


@pytest.mark.parametrize("fault", ["public_acl", "overload", "body"])
def test_existing_drift_is_not_replaced_or_acl_repaired(installation_root, fault):
    session, owner = installation_root
    if fault == "public_acl":
        install_local_indexing_service_fence(session, owner)
        session.execute(
            text("GRANT EXECUTE ON FUNCTION " + LOCAL_INDEXING_FENCE_SIGNATURE + " TO PUBLIC")
        )
    elif fault == "overload":
        session.execute(
            text(
                "CREATE FUNCTION public.eom_fence_local_indexing_service_v1(pg_catalog.text) "
                "RETURNS pg_catalog.jsonb LANGUAGE SQL AS 'SELECT NULL::pg_catalog.jsonb'"
            )
        )
    else:
        session.execute(
            text(
                LOCAL_INDEXING_FENCE_CREATE_SQL.replace(
                    "DECLARE\n", "DECLARE\n    unexpected_value int;\n", 1
                )
            )
        )
    before = session.execute(
        text(
            "SELECT procedure.oid, procedure.prosrc, procedure.proacl::pg_catalog.text "
            "FROM pg_catalog.pg_proc procedure JOIN pg_catalog.pg_namespace namespace "
            "ON namespace.oid=procedure.pronamespace WHERE namespace.nspname='public' "
            "AND procedure.proname='eom_fence_local_indexing_service_v1' ORDER BY procedure.oid"
        )
    ).all()
    with pytest.raises(LocalIndexingFenceError, match="UNAVAILABLE"):
        install_local_indexing_service_fence(session, owner)
    after = session.execute(
        text(
            "SELECT procedure.oid, procedure.prosrc, procedure.proacl::pg_catalog.text "
            "FROM pg_catalog.pg_proc procedure JOIN pg_catalog.pg_namespace namespace "
            "ON namespace.oid=procedure.pronamespace WHERE namespace.nspname='public' "
            "AND procedure.proname='eom_fence_local_indexing_service_v1' ORDER BY procedure.oid"
        )
    ).all()
    assert after == before


def test_concurrent_installation_returns_busy_not_duplicate_ddl(installation_root, guarded_engine):
    session, owner = installation_root
    assert install_local_indexing_service_fence(session, owner).disposition == "CREATED"

    def competing():
        with Session(guarded_engine) as second, second.begin():
            return install_local_indexing_service_fence(second, owner)

    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        pytest.raises(LocalIndexingServiceError) as caught,
    ):
        pool.submit(competing).result(timeout=10)
    assert str(caught.value.code) == "LOCAL_INDEXING_SERVICE_BUSY"


def test_failed_final_inspection_rolls_back_partial_function_not_owner_root(installation_root):
    session, owner = installation_root
    # Deliberately invalid DB-local role privileges. No identity content is read,
    # no cluster-role mutation occurs, and this fixture rolls the grant back.
    session.execute(
        text("GRANT SELECT ON app.local_indexing_services TO eom_catalog_manager_runtime")
    )
    with pytest.raises(LocalIndexingFenceError, match="UNAVAILABLE"):
        install_local_indexing_service_fence(session, owner)
    assert session.in_transaction() and session.get_nested_transaction() is None
    assert (
        session.scalar(
            text("SELECT pg_catalog.to_regprocedure(:signature)"),
            {"signature": LOCAL_INDEXING_FENCE_SIGNATURE},
        )
        is None
    )


def test_owner_rollback_removes_ddl_and_allows_next_supported_installation(
    installation_root, guarded_engine
):
    session, owner = installation_root
    assert install_local_indexing_service_fence(session, owner).disposition == "CREATED"
    session.rollback()
    with Session(guarded_engine) as second:
        root = second.begin()
        try:
            assert (
                second.scalar(
                    text("SELECT pg_catalog.to_regprocedure(:signature)"),
                    {"signature": LOCAL_INDEXING_FENCE_SIGNATURE},
                )
                is None
            )
            second.execute(text("GRANT USAGE ON SCHEMA app TO eom_catalog_manager_runtime"))
            assert install_local_indexing_service_fence(second, owner).disposition == "CREATED"
        finally:
            root.rollback()


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
