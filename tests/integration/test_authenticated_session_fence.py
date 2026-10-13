"""Opt-in official disposable DB only; source phase collects but never executes.

Real independent writers and HMAC verification use synthetic keys/identities, not
production authentication/provider admission. Rows remain until guarded DB cleanup.
No role/routine/grant, production DB, NAS, model or GPU is touched by these tests.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event, current_thread
from typing import Any
from uuid import uuid4

import pytest
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    AuthenticatedSessionFenceError,
    AuthenticatedSessionFenceOwnerPin,
    CapturedOperatorAuthorizationFence,
    OperatorAuthorizationFenceError,
)
from eom_identity_service.auth_service import AuthService
from eom_identity_service.models import (
    ApiSessionRecord,
    ApiTokenRecord,
    OperatorCredentialRecord,
    OperatorEventRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from eom_identity_service.repository import require_role
from eom_identity_service.service import OperatorService
from eom_identity_service.tokens import (
    AccessAuthentication,
    IssuedTokenPair,
    SessionTokenService,
    TokenCodec,
)
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey, RoleKey
from eom_operator_identity.identifiers import (
    new_credential_id,
    new_operator_event_id,
    new_role_assignment_id,
)
from eom_operator_identity.passwords import PasswordService
from sqlalchemy import Connection, Engine, create_engine, event, func, select, text
from sqlalchemy.engine import ExecutionContext
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
_SYNTHETIC_KEY = b"synthetic-disposable-session-fence-key-not-production" * 2


@dataclass(frozen=True)
class PreparedSessionFence:
    engine: Engine
    auth: AuthService
    pin: AuthenticatedSessionFenceOwnerPin
    capture: AuthenticatedOperatorSession
    authentication: AccessAuthentication
    pair: IssuedTokenPair = field(repr=False)
    target_id: str
    admin: ActorContext
    password: str = field(repr=False)

    def check(self, session: Session, adapter: AuthenticatedSessionFence | None = None) -> None:
        (adapter or AuthenticatedSessionFence(self.pin)).assert_current(
            session, self.capture, required_permission=PermissionKey.WORKFLOW_START
        )


@pytest.fixture
def owner_engine(guarded_engine: Engine) -> Iterator[Engine]:
    if os.environ.get("EOM_RUN_AUTHENTICATED_SESSION_INTEGRATION") != "1":
        pytest.skip("explicit disposable session-fence owner invocation required")
    # The existing marker guard admits the test DB with its ordinary app,public
    # search path. Owner fencing has a narrower independently configured context;
    # do not weaken that source check or mutate the shared integration engine.
    engine = create_engine(
        guarded_engine.url,
        connect_args={"options": "-c search_path=app,pg_catalog"},
        isolation_level="READ COMMITTED",
        pool_size=2,
        max_overflow=0,
        pool_timeout=10,
    )
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT current_schemas(false)")) == ["app", "pg_catalog"]
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def prepared(owner_engine: Engine) -> PreparedSessionFence:
    with owner_engine.connect() as connection:
        actual = (
            connection.execute(
                text(
                    "SELECT CURRENT_USER AS name, role.oid AS oid, role.rolsuper AS superuser, "
                    "role.rolbypassrls AS bypassrls FROM pg_catalog.pg_roles role "
                    "WHERE role.rolname=CURRENT_USER"
                )
            )
            .mappings()
            .one()
        )
        assert actual["superuser"] is False and actual["bypassrls"] is False
        pin = AuthenticatedSessionFenceOwnerPin(actual["name"], actual["oid"], 900)
    now = datetime.now(UTC)
    password = "Synthetic-Session-" + uuid4().hex + "!9"
    identities = [
        ("operator_" + uuid4().hex, "session_admin_" + uuid4().hex[:12], RoleKey.ADMIN),
        ("operator_" + uuid4().hex, "session_author_" + uuid4().hex[:12], RoleKey.AUTHOR),
    ]
    with Session(owner_engine) as session, session.begin():
        for operator_id, username, role_key in identities:
            session.add(
                OperatorRecord(
                    operator_id=operator_id,
                    username=username,
                    normalized_username=username,
                    display_name="Synthetic session fence",
                    status="ACTIVE",
                    must_change_password=False,
                    role_version=1,
                    lock_version=1,
                    created_by="synthetic-session-fence",
                )
            )
            session.flush()
            session.add(
                OperatorCredentialRecord(
                    operator_credential_id=new_credential_id(),
                    operator_id=operator_id,
                    password_hash=PasswordService().hash_password(
                        password, username=username, display_name="Synthetic session fence"
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
                    assigned_by="synthetic-session-fence",
                    assigned_at=now,
                )
            )
    auth = AuthService(owner_engine, SessionTokenService(TokenCodec(_SYNTHETIC_KEY)))
    admin_pair = auth.login(
        username=identities[0][1], password=password, client_name="Synthetic session fence admin"
    ).pair
    admin_auth = auth.authenticate_access(admin_pair.access_token)
    admin = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=identities[0][0],
        session_id=admin_auth.session_id,
        request_id="synthetic-session-fence",
        authentication_time=admin_auth.authenticated_at,
        permissions=admin_auth.permissions,
        source=ActorSource.APPLICATION_API,
    )
    pair = auth.login(
        username=identities[1][1], password=password, client_name="Synthetic session fence target"
    ).pair
    authentication = auth.authenticate_access(pair.access_token)
    capture = auth.capture_access(pair.access_token)
    result = PreparedSessionFence(
        owner_engine, auth, pin, capture, authentication, pair, identities[1][0], admin, password
    )
    # Every negative/race case starts from an actual accepted owner root, not an
    # unrelated connection-context denial that happens to raise the same type.
    with Session(owner_engine) as session, session.begin():
        result.check(session)
    return result


def test_actual_capture_and_same_root_fence_do_not_touch_activity(
    prepared: PreparedSessionFence,
) -> None:
    with Session(prepared.engine) as session, session.begin():
        row = session.get(ApiSessionRecord, prepared.authentication.session_id)
        assert row is not None
        before = (row.last_seen_at, row.idle_expires_at, row.refresh_generation)
        tokens = tuple(
            session.scalars(
                select(ApiTokenRecord).where(ApiTokenRecord.api_session_id == row.api_session_id)
            )
        )
        token_times = tuple((token.api_token_id, token.last_used_at) for token in tokens)
        adapter = AuthenticatedSessionFence(prepared.pin)
        prepared.check(session, adapter)
        with session.begin_nested():
            prepared.check(session, adapter)
        session.refresh(row)
        assert (row.last_seen_at, row.idle_expires_at, row.refresh_generation) == before
        assert tuple((token.api_token_id, token.last_used_at) for token in tokens) == token_times


@pytest.mark.parametrize(
    "action", ["logout", "logout_all", "refresh", "password", "role", "disable", "delete", "access"]
)
@pytest.mark.parametrize("through_catalog_bridge", [False, True])
def test_actual_independent_supported_writer_blocks_then_old_capture_rechecks(
    prepared: PreparedSessionFence, action: str, through_catalog_bridge: bool
) -> None:
    started = Event()
    backend: list[int] = []
    bridge = CapturedOperatorAuthorizationFence(
        prepared.capture, AuthenticatedSessionFence(prepared.pin), PermissionKey.WORKFLOW_START
    )

    def check(session: Session) -> None:
        if through_catalog_bridge:
            bridge.fence_current_operator(session, prepared.target_id)
        else:
            prepared.check(session)

    def before_cursor(
        connection: Connection,
        _cursor: Any,
        _statement: str,
        _parameters: Any,
        _context: ExecutionContext,
        _many: bool,
    ) -> None:
        if current_thread().name.startswith("session-fence-writer") and not backend:
            driver = connection.connection.driver_connection
            assert driver is not None
            backend.append(driver.info.backend_pid)
            started.set()

    def writer() -> object:
        if action == "logout":
            prepared.auth.logout(prepared.authentication.session_id, prepared.target_id)
            return None
        if action == "logout_all":
            return prepared.auth.logout_all(prepared.target_id)
        if action == "refresh":
            return prepared.auth.refresh(prepared.pair.refresh_token)
        if action == "password":
            return prepared.auth.change_password(
                prepared.authentication,
                current_password=prepared.password,
                new_password="Synthetic-New-" + uuid4().hex + "!9",
            )
        if action == "access":
            return prepared.auth.authenticate_access(prepared.pair.access_token)
        operators = OperatorService(prepared.engine)
        if action == "role":
            return operators.revoke_role(
                prepared.target_id,
                RoleKey.AUTHOR,
                prepared.admin,
                reason="synthetic disposable race",
            )
        if action == "disable":
            return operators.disable(
                prepared.target_id, prepared.admin, reason="synthetic disposable race"
            )
        return operators.delete(
            prepared.target_id, prepared.admin, reason="synthetic disposable race"
        )

    event.listen(prepared.engine, "before_cursor_execute", before_cursor)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-fence-writer") as pool:
            with Session(prepared.engine) as session, session.begin():
                check(session)
                holder = session.scalar(text("SELECT pg_catalog.pg_backend_pid()"))
                future = pool.submit(writer)
                assert started.wait(5)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    blockers = session.scalar(
                        text("SELECT pg_catalog.pg_blocking_pids(:pid)"), {"pid": backend[0]}
                    )
                    if holder in blockers:
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("independent writer did not wait on this retained root")
                assert not future.done()
            future.result(timeout=10)
    finally:
        event.remove(prepared.engine, "before_cursor_execute", before_cursor)
    with Session(prepared.engine) as session, session.begin():
        if action == "access":
            check(session)
        else:
            error_type = (
                OperatorAuthorizationFenceError
                if through_catalog_bridge
                else AuthenticatedSessionFenceError
            )
            with pytest.raises(error_type):
                check(session)


def test_actual_late_expiry_rolls_back_caller_mutation(prepared: PreparedSessionFence) -> None:
    with Session(prepared.engine) as session, session.begin():
        token = session.scalar(
            select(ApiTokenRecord).where(
                ApiTokenRecord.api_session_id == prepared.authentication.session_id,
                ApiTokenRecord.token_type == "ACCESS",
                ApiTokenRecord.revoked_at.is_(None),
            )
        )
        assert token is not None
        token.expires_at = datetime.now(UTC) + timedelta(seconds=2)
    capture = prepared.auth.capture_access(prepared.pair.access_token)
    event_id = new_operator_event_id()
    with (
        pytest.raises(AuthenticatedSessionFenceError),
        Session(prepared.engine) as session,
        session.begin(),
    ):
        adapter = AuthenticatedSessionFence(prepared.pin)
        adapter.assert_current(session, capture, required_permission=PermissionKey.WORKFLOW_START)
        sequence = session.scalar(
            select(func.coalesce(func.max(OperatorEventRecord.sequence), 0)).where(
                OperatorEventRecord.operator_id == prepared.target_id
            )
        )
        assert type(sequence) is int
        session.add(
            OperatorEventRecord(
                operator_event_id=event_id,
                operator_id=prepared.target_id,
                sequence=sequence + 1,
                event_type="SYNTHETIC_SESSION_FENCE_ROLLBACK",
                actor_id=prepared.target_id,
                request_id="synthetic-session-fence",
                payload={"synthetic": True},
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
        time.sleep(2.1)
        adapter.assert_current(session, capture, required_permission=PermissionKey.WORKFLOW_START)
    with Session(prepared.engine) as session:
        assert session.get(OperatorEventRecord, event_id) is None


def test_actual_wrong_role_oid_and_nested_first_are_unavailable(
    prepared: PreparedSessionFence,
) -> None:
    with Session(prepared.engine) as session, session.begin():
        prepared.check(session)
    with (
        pytest.raises(
            AuthenticatedSessionFenceError, match=r"^AUTHENTICATED_SESSION_CONTEXT_INVALID$"
        ),
        Session(prepared.engine) as session,
        session.begin(),
    ):
        wrong = AuthenticatedSessionFenceOwnerPin(
            prepared.pin.role_name, prepared.pin.role_oid + 1, 900
        )
        prepared.check(session, AuthenticatedSessionFence(wrong))
    with (
        pytest.raises(
            AuthenticatedSessionFenceError, match=r"^AUTHENTICATED_SESSION_CONTEXT_INVALID$"
        ),
        Session(prepared.engine) as session,
        session.begin(),
        session.begin_nested(),
    ):
        prepared.check(session)
