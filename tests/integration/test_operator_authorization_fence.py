"""Prepared process races; requires an explicitly prepared disposable limited profile.

Never executed in the source-only stage. Does not install the routine or grant /
repair prerequisite privileges. Only the guard's unique disposable runtime role
is substituted in tests; production role literals are pinned by source tests.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from eom_identity_service import (
    OPERATOR_AUTHORIZATION_FENCE_SIGNATURE,
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    PostgresOperatorAuthorizationFence,
    require_operator_authorization_fence_installation,
)
from eom_identity_service import operator_authorization_fence_sql as routine
from eom_identity_service import postgres_operator_authorization_fence as adapter_module
from eom_identity_service.auth_service import AuthService
from eom_identity_service.models import (
    OperatorCredentialRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from eom_identity_service.repository import effective_permissions, require_role
from eom_identity_service.service import OperatorService
from eom_identity_service.tokens import SessionTokenService, TokenCodec
from eom_operator_identity.contracts import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from eom_operator_identity.errors import IdentityError
from eom_operator_identity.identifiers import new_credential_id, new_role_assignment_id
from eom_operator_identity.passwords import PasswordService
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker
from sqlalchemy.sql import ClauseElement

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
_SYNTHETIC_KEY = b"synthetic-disposable-fence-key-not-production" * 2


def _test_role(role: str) -> None:
    # No public runtime role argument or environment switch exists in the adapter.
    patcher = pytest.MonkeyPatch()
    patcher.setattr(routine, "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE", role)
    patcher.setattr(adapter_module, "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE", role)


def _auth(engine: Engine) -> AuthService:
    return AuthService(engine, SessionTokenService(TokenCodec(_SYNTHETIC_KEY)))


@dataclass(frozen=True)
class PreparedFence:
    owner_url: str = field(repr=False)
    runtime_url: str = field(repr=False)
    state: str
    owner_pin: OperatorAuthorizationFenceOwnerPin
    runtime_role: str
    admin_id: str
    admin_username: str
    target_id: str
    target_username: str
    password: str = field(repr=False)


def _guard_process(value: PreparedFence, *, runtime: bool) -> Engine:
    state = validate_state_directory(Path(value.state))
    manifest = DisposableManifest.load(state / "manifest.json")
    url = value.runtime_url if runtime else value.owner_url
    parsed = urlsplit(url)
    assert parsed.path.removeprefix("/") == manifest.database
    assert parsed.username == (manifest.runtime_role if runtime else manifest.owner_role)
    assert value.runtime_role == manifest.runtime_role
    assert value.owner_pin.role_name == manifest.owner_role
    _test_role(manifest.runtime_role)
    engine = build_engine(url)
    try:
        with engine.connect() as connection:
            actual = connection.execute(
                text(
                    "SELECT pg_catalog.current_database(), CURRENT_USER, owner.rolname, "
                    "pg_catalog.obj_description(namespace.oid,'pg_namespace') "
                    "FROM pg_catalog.pg_namespace AS namespace "
                    "JOIN pg_catalog.pg_roles AS owner ON owner.oid=namespace.nspowner "
                    "WHERE namespace.nspname='app'"
                )
            ).one()
        assert actual == (
            manifest.database,
            manifest.runtime_role if runtime else manifest.owner_role,
            manifest.owner_role,
            manifest.marker,
        )
    except BaseException:
        engine.dispose()
        raise
    return engine


@pytest.fixture
def prepared(guarded_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> PreparedFence:
    if os.environ.get("EOM_RUN_OPERATOR_FENCE_INTEGRATION") != "1":
        pytest.skip("prepared opt-in disposable fence profile required; never production")
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    runtime_url = values["EOM_API_DATABASE_URL"]
    assert urlsplit(runtime_url).username == manifest.runtime_role
    owner_url = guarded_engine.url.render_as_string(hide_password=False)
    monkeypatch.setattr(routine, "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE", manifest.runtime_role)
    monkeypatch.setattr(
        adapter_module, "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE", manifest.runtime_role
    )
    with guarded_engine.connect() as connection:
        oid = connection.scalar(
            text("SELECT oid FROM pg_catalog.pg_roles WHERE rolname=:role"),
            {"role": manifest.owner_role},
        )
    assert type(oid) is int
    owner_pin = OperatorAuthorizationFenceOwnerPin(manifest.owner_role, oid)
    runtime_engine = build_engine(runtime_url)
    try:
        with runtime_engine.connect() as connection:
            # The default API test profile has IAM writes: it must NOT pass.
            # Preparation must admit exact body/owner/ACL plus limited IAM SELECT.
            require_operator_authorization_fence_installation(connection, owner_pin)
    finally:
        runtime_engine.dispose()
    seed, now = uuid4().hex, datetime.now(UTC)
    password = "Synthetic-Only-" + uuid4().hex + "!9"
    ids = ("operator_" + uuid4().hex, "operator_" + uuid4().hex)
    names = ("fence_admin_" + seed[:12], "fence_reader_" + seed[:12])
    with Session(guarded_engine) as session, session.begin():
        for operator_id, username, role_key in zip(
            ids, names, (RoleKey.ADMIN, RoleKey.REVIEWER), strict=True
        ):
            session.add(
                OperatorRecord(
                    operator_id=operator_id,
                    username=username,
                    normalized_username=username,
                    display_name="Synthetic disposable fence",
                    status="ACTIVE",
                    must_change_password=False,
                    role_version=1,
                    created_by="synthetic-fence",
                    lock_version=1,
                )
            )
            session.flush()
            session.add(
                OperatorCredentialRecord(
                    operator_credential_id=new_credential_id(),
                    operator_id=operator_id,
                    password_hash=PasswordService().hash_password(
                        password, username=username, display_name="Synthetic disposable fence"
                    ),
                    password_algorithm="argon2id",
                    password_version=1,
                    must_change_password=False,
                    password_changed_at=now,
                    failed_login_count=0,
                )
            )
            role = require_role(session, role_key)
            session.add(
                OperatorRoleAssignmentRecord(
                    operator_role_assignment_id=new_role_assignment_id(),
                    operator_id=operator_id,
                    role_id=role.role_id,
                    assigned_by="synthetic-fence",
                    assigned_at=now,
                )
            )
    return PreparedFence(
        owner_url,
        runtime_url,
        str(state),
        owner_pin,
        manifest.runtime_role,
        ids[0],
        names[0],
        ids[1],
        names[1],
        password,
    )


def _actor(auth: AuthService, value: PreparedFence) -> ActorContext:
    login = auth.login(
        username=value.admin_username, password=value.password, client_name="synthetic-fence"
    )
    authentication = auth.authenticate_access(login.pair.access_token)
    assert authentication.operator.operator_id == value.admin_id
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=value.admin_id,
        session_id=authentication.session_id,
        request_id="synthetic-fence-revoke",
        authentication_time=authentication.authenticated_at,
        permissions=authentication.permissions,
        source=ActorSource.APPLICATION_API,
    )


def _writer(
    value: PreparedFence, operation: str, events: Any, release: Any, pause_after_lock: bool
) -> None:
    engine = _guard_process(value, runtime=False)
    auth, actor = _auth(engine), None
    actor = _actor(auth, value)
    password_authentication = None
    if operation == "password":
        login = auth.login(
            username=value.target_username,
            password=value.password,
            client_name="synthetic-password-writer",
        )
        password_authentication = auth.authenticate_access(login.pair.access_token)

    class ObservedSession(Session):
        pass

    def observe(state: ORMExecuteState) -> Any:
        statement = str(state.statement)
        is_target = (
            "FROM operators" in statement
            and "FOR UPDATE" in statement
            and value.target_id in cast(ClauseElement, state.statement).compile().params.values()
        )
        if is_target:
            pid = state.session.connection().scalar(text("SELECT pg_catalog.pg_backend_pid()"))
            events.put(("WRITER_TRY", pid))
        result = state.invoke_statement()
        if is_target:
            events.put(("WRITER_LOCKED", pid))
            if pause_after_lock and not release.wait(10):
                raise AssertionError("bounded writer controller expired")
        return result

    event.listen(ObservedSession, "do_orm_execute", observe, retval=True)
    factory = sessionmaker(
        bind=engine, class_=cast(type[Session], ObservedSession), expire_on_commit=False
    )
    try:
        if operation == "password":
            assert password_authentication is not None
            auth.sessions = factory
            auth.change_password(
                password_authentication,
                current_password=value.password,
                new_password="Synthetic-Changed-" + uuid4().hex + "!9",
            )
        else:
            service = OperatorService(engine)
            service.sessions = factory
            if operation == "revoke":
                service.revoke_role(
                    value.target_id, RoleKey.REVIEWER, actor, reason="synthetic disposable denial"
                )
            elif operation == "disable":
                service.disable(value.target_id, actor, reason="synthetic disposable denial")
            else:
                raise AssertionError("unsupported fixed test writer")
        events.put(("WRITER_COMMITTED", 0))
    finally:
        engine.dispose()


def _reader(value: PreparedFence, events: Any) -> str:
    engine = _guard_process(value, runtime=True)
    try:
        adapter = PostgresOperatorAuthorizationFence(value.owner_pin)
        with Session(engine, expire_on_commit=False) as session, session.begin():
            operator = session.get(OperatorRecord, value.target_id)
            assert operator is not None and operator.status == "ACTIVE"
            pid = session.connection().scalar(text("SELECT pg_catalog.pg_backend_pid()"))
            events.put(("READER_TRY", pid))
            try:
                adapter.fence_current_operator(session, value.target_id)
            except OperatorAuthorizationFenceError as error:
                return error.code
            assert session.get(OperatorRecord, value.target_id) is operator
            return "FENCED_ACTIVE_NOT_SESSION_AUTHORITY"
    finally:
        engine.dispose()


def _blocked(owner: Engine, waiting_pid: int, holding_pid: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with owner.connect() as connection:
            blockers = connection.scalar(
                text("SELECT pg_catalog.pg_blocking_pids(:pid)"), {"pid": waiting_pid}
            )
        if holding_pid in blockers:
            return
        multiprocessing.Event().wait(0.02)
    raise AssertionError("expected bounded real PostgreSQL row-lock contention")


def test_actual_limited_role_executes_fixed_routine_and_denies_iam_writes(
    prepared: PreparedFence,
) -> None:
    engine = _guard_process(prepared, runtime=True)
    try:
        with Session(engine) as session, session.begin():
            PostgresOperatorAuthorizationFence(prepared.owner_pin).fence_current_operator(
                session, prepared.target_id
            )
            assert PermissionKey.WORKFLOW_APPROVE in effective_permissions(
                session, prepared.target_id
            )
        for statement in (
            "SELECT operator_id FROM app.operators FOR SHARE",
            "UPDATE app.operators SET status=status WHERE false",
            "SELECT password_hash FROM app.operator_credentials WHERE false",
            "SELECT * FROM app.api_sessions WHERE false",
            "ALTER FUNCTION public.eom_fence_operator_authorization_v1(text) SECURITY INVOKER",
        ):
            with engine.begin() as connection, pytest.raises(DBAPIError) as error:
                connection.execute(text(statement))
            assert getattr(error.value.orig, "sqlstate", None) == "42501"
    finally:
        engine.dispose()


def test_nested_rollback_retains_outer_fence_against_actual_role_revoke(
    prepared: PreparedFence,
) -> None:
    runtime, owner = _guard_process(prepared, runtime=True), _guard_process(prepared, runtime=False)
    context = multiprocessing.get_context("spawn")
    try:
        with context.Manager() as manager, ProcessPoolExecutor(1, mp_context=context) as pool:
            events, release = manager.Queue(), manager.Event()
            with Session(runtime) as session:
                root = session.begin()
                adapter = PostgresOperatorAuthorizationFence(prepared.owner_pin)
                adapter.fence_current_operator(session, prepared.target_id)
                pid = session.connection().scalar(text("SELECT pg_catalog.pg_backend_pid()"))
                nested = session.begin_nested()
                adapter.fence_current_operator(session, prepared.target_id)
                nested.rollback()
                adapter.fence_current_operator(session, prepared.target_id)
                writer = pool.submit(_writer, prepared, "revoke", events, release, False)
                label, writer_pid = events.get(timeout=10)
                assert label == "WRITER_TRY"
                _blocked(owner, writer_pid, pid)
                root.rollback()
                writer.result(timeout=15)
            with Session(runtime) as session:
                assert PermissionKey.WORKFLOW_APPROVE not in effective_permissions(
                    session, prepared.target_id
                )
    finally:
        runtime.dispose()
        owner.dispose()


@pytest.mark.parametrize("operation", ["disable", "password"])
def test_writer_first_wait_refresh_and_session_distinction(
    prepared: PreparedFence, operation: str
) -> None:
    owner = _guard_process(prepared, runtime=False)
    auth = _auth(owner)
    login = auth.login(
        username=prepared.target_username,
        password=prepared.password,
        client_name="synthetic-retired-session",
    )
    context = multiprocessing.get_context("spawn")
    try:
        with context.Manager() as manager, ProcessPoolExecutor(2, mp_context=context) as pool:
            events, release = manager.Queue(), manager.Event()
            writer = pool.submit(_writer, prepared, operation, events, release, True)
            label, writer_pid = events.get(timeout=10)
            assert label == "WRITER_TRY"
            assert events.get(timeout=10)[0] == "WRITER_LOCKED"
            reader = pool.submit(_reader, prepared, events)
            label, reader_pid = events.get(timeout=10)
            assert label == "READER_TRY"
            _blocked(owner, reader_pid, writer_pid)
            release.set()
            writer.result(timeout=15)
            result = reader.result(timeout=15)
            assert result == (
                "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                if operation == "disable"
                else "FENCED_ACTIVE_NOT_SESSION_AUTHORITY"
            )
        with pytest.raises(IdentityError):
            auth.authenticate_access(login.pair.access_token)
    finally:
        owner.dispose()


def test_acl_drift_cannot_reuse_root_witness_as_a_grant(prepared: PreparedFence) -> None:
    owner, runtime = _guard_process(prepared, runtime=False), _guard_process(prepared, runtime=True)
    try:
        with Session(runtime) as session, session.begin():
            adapter = PostgresOperatorAuthorizationFence(prepared.owner_pin)
            adapter.fence_current_operator(session, prepared.target_id)
            with owner.begin() as connection:
                connection.execute(
                    text(
                        "GRANT EXECUTE ON FUNCTION "
                        + OPERATOR_AUTHORIZATION_FENCE_SIGNATURE
                        + " TO PUBLIC"
                    )
                )
            try:
                with pytest.raises(
                    OperatorAuthorizationFenceError,
                    match="OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE",
                ):
                    adapter.fence_current_operator(session, prepared.target_id)
            finally:
                with owner.begin() as connection:
                    connection.execute(text(routine.OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL))
    finally:
        owner.dispose()
        runtime.dispose()


def test_actual_temp_shadow_is_denied_without_reading_or_deleting_its_contents(
    prepared: PreparedFence,
) -> None:
    runtime = _guard_process(prepared, runtime=True)
    try:
        with Session(runtime) as session, session.begin():
            adapter = PostgresOperatorAuthorizationFence(prepared.owner_pin)
            adapter.fence_current_operator(session, prepared.target_id)
            session.connection().execute(
                text("CREATE TEMP TABLE operators (operator_id text, status text)")
            )
            with pytest.raises(
                OperatorAuthorizationFenceError,
                match="OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID",
            ):
                adapter.fence_current_operator(session, prepared.target_id)
        # No broad temp cleanup: dispose this guarded synthetic connection pool.
    finally:
        runtime.dispose()
