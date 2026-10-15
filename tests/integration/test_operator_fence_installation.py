"""Opt-in, rolled-back owner DDL/ACL tests in a marker-guarded disposable DB only."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from eom_identity_service import (
    OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256,
    OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL,
    OPERATOR_AUTHORIZATION_FENCE_SIGNATURE,
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    install_operator_authorization_fence,
    require_operator_authorization_fence_installation,
)
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
_IAM = (
    "operators",
    "roles",
    "permissions",
    "role_permissions",
    "operator_role_assignments",
    "operator_credentials",
    "api_sessions",
    "api_tokens",
    "operator_events",
)


@pytest.fixture
def installation_root(guarded_engine: Engine):
    if os.environ.get("EOM_RUN_OPERATOR_FENCE_INSTALLATION_TESTS") != "1":
        pytest.skip("explicit disposable owner-installation opt-in required")
    with Session(guarded_engine) as session, session.begin():
        assert (
            session.scalar(
                text("SELECT pg_catalog.to_regprocedure(:signature)"),
                {
                    "signature": OPERATOR_AUTHORIZATION_FENCE_SIGNATURE,
                },
            )
            is None
        ), "never replace an installed interface"
        name, oid = session.execute(
            text("SELECT SESSION_USER,oid FROM pg_catalog.pg_roles WHERE rolname=SESSION_USER")
        ).one()
        assert (
            session.scalar(
                text(
                    "SELECT oid FROM pg_catalog.pg_roles "
                    "WHERE rolname='eom_catalog_manager_runtime'"
                )
            )
            is not None
        ), "fixed role is an existing cluster prerequisite, not created by tests"
        # Only this marked test DB; all grants and DDL roll back with this root.
        # Do not change cluster roles, other databases or actual runtime credentials.
        session.execute(text("GRANT USAGE ON SCHEMA app,public TO eom_catalog_manager_runtime"))
        for table in _IAM:
            session.execute(
                text(f"REVOKE ALL ON TABLE app.{table} FROM eom_catalog_manager_runtime")
            )
        for table in _IAM[:5]:
            session.execute(
                text(f"GRANT SELECT ON TABLE app.{table} TO eom_catalog_manager_runtime")
            )
        try:
            yield session, OperatorAuthorizationFenceOwnerPin(name, oid)
        finally:
            session.rollback()


def inventory(session):
    return session.execute(
        text(
            "SELECT p.oid,p.prosrc,p.proacl::pg_catalog.text FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname='eom_fence_operator_authorization_v1' "
            "ORDER BY p.oid LIMIT 2"
        )
    ).all()


def test_exact_creation_and_replay_perform_no_replacement_or_acl_repair(installation_root):
    session, owner = installation_root
    created = install_operator_authorization_fence(session, owner)
    assert created.disposition == "CREATED" and created.owner == owner
    assert created.body_sha256 == OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256
    before, ddl = inventory(session), []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(("CREATE", "GRANT", "REVOKE", "ALTER", "DROP")):
            ddl.append(statement)

    event.listen(session.connection(), "before_cursor_execute", capture)
    try:
        assert install_operator_authorization_fence(session, owner).disposition == "REPLAYED"
    finally:
        event.remove(session.connection(), "before_cursor_execute", capture)
    assert not ddl and inventory(session) == before
    require_operator_authorization_fence_installation(session.connection(), owner)
    assert session.in_transaction()


@pytest.mark.parametrize("fault", ["name", "oid", "role", "readonly", "nested"])
def test_wrong_owner_or_context_creates_nothing(installation_root, fault):
    session, owner = installation_root
    if fault == "name":
        owner = OperatorAuthorizationFenceOwnerPin("not_the_owner", owner.role_oid)
    elif fault == "oid":
        owner = OperatorAuthorizationFenceOwnerPin(owner.role_name, owner.role_oid + 1)
    elif fault == "role":
        session.execute(text("SELECT pg_catalog.set_config('role',SESSION_USER,true)"))
    elif fault == "readonly":
        # The fixture made local grants already; setting the root read-only is legal.
        session.execute(text("SET TRANSACTION READ ONLY"))
    elif fault == "nested":
        with session.begin_nested(), pytest.raises(OperatorAuthorizationFenceError):
            install_operator_authorization_fence(session, owner)
        assert not inventory(session)
        return
    with pytest.raises(OperatorAuthorizationFenceError):
        install_operator_authorization_fence(session, owner)
    assert not inventory(session)


@pytest.mark.parametrize("fault", ["public_acl", "body", "overload"])
def test_existing_drift_is_preserved_not_repaired(installation_root, fault):
    session, owner = installation_root
    if fault == "public_acl":
        install_operator_authorization_fence(session, owner)
        session.execute(
            text(
                "GRANT EXECUTE ON FUNCTION public.eom_fence_operator_authorization_v1(text) "
                "TO PUBLIC"
            )
        )
    elif fault == "body":
        session.execute(
            text(
                OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL.replace(
                    "BEGIN\n", "BEGIN\n    PERFORM 1;\n", 1
                )
            )
        )
    else:
        session.execute(
            text(
                "CREATE FUNCTION public.eom_fence_operator_authorization_v1(pg_catalog.int4) "
                "RETURNS void LANGUAGE SQL AS 'SELECT NULL::pg_catalog.void'"
            )
        )
    before = inventory(session)
    with pytest.raises(OperatorAuthorizationFenceError):
        install_operator_authorization_fence(session, owner)
    assert inventory(session) == before


def test_late_inspection_failure_removes_new_ddl_and_acl(installation_root):
    session, owner = installation_root
    session.execute(text("GRANT UPDATE ON app.operators TO eom_catalog_manager_runtime"))
    with pytest.raises(OperatorAuthorizationFenceError):
        install_operator_authorization_fence(session, owner)
    assert not inventory(session)
    assert session.scalar(text("SELECT 1")) == 1


def test_nonblocking_lock_serializes_installation_without_parallel_ddl(installation_root):
    session, owner = installation_root
    assert install_operator_authorization_fence(session, owner).disposition == "CREATED"

    def second_install():
        with Session(session.bind) as second, second.begin():
            with pytest.raises(OperatorAuthorizationFenceError, match="UNAVAILABLE"):
                install_operator_authorization_fence(second, owner)
            return not inventory(second)

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(second_install).result(timeout=10)


def test_stricter_wait_limits_are_restored_exactly(installation_root):
    session, owner = installation_root
    session.execute(text("SET LOCAL lock_timeout='123ms'"))
    session.execute(text("SET LOCAL statement_timeout='456ms'"))
    assert install_operator_authorization_fence(session, owner).disposition == "CREATED"
    assert session.execute(
        text("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')")
    ).one() == ("123ms", "456ms")


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_non_read_committed_owner_is_rejected_before_ddl(guarded_engine, isolation):
    if os.environ.get("EOM_RUN_OPERATOR_FENCE_INSTALLATION_TESTS") != "1":
        pytest.skip("explicit disposable owner-installation opt-in required")
    with Session(guarded_engine) as session, session.begin():
        session.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation}"))
        name, oid = session.execute(
            text("SELECT SESSION_USER,oid FROM pg_catalog.pg_roles WHERE rolname=SESSION_USER")
        ).one()
        with pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"):
            install_operator_authorization_fence(
                session, OperatorAuthorizationFenceOwnerPin(name, oid)
            )
        assert not inventory(session)
