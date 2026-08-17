from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from eom_identity_service.auth_service import (
    AuthenticationFailure,
    AuthService,
    LoginPolicy,
)
from eom_identity_service.models import (
    ApiAuditEventRecord,
    ApiIdempotencyRecord,
    ApiSessionRecord,
    ApiTokenRecord,
    OperatorCredentialRecord,
    OperatorEventRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RolePermissionRecord,
    RoleRecord,
)
from eom_identity_service.repository import effective_permissions, seed_builtin_rbac
from eom_identity_service.service import CreateOperatorCommand, OperatorService
from eom_identity_service.tokens import SessionTokenService, TokenCodec
from eom_operator_identity.contracts import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.identifiers import new_api_audit_event_id
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]
TOKEN_HASH_KEY = "TEST_ONLY_TOKEN_HASH_KEY_0123456789ABCDEF"
ADMIN_REPLACEMENT_PASSWORD = "TEST_ONLY replacement password 84"
REVIEWER_PASSWORD = "TEST_ONLY reviewer password 42"
VIEWER_PASSWORD = "TEST_ONLY viewer password 42"


def _enabled() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_API_INTEGRATION=1 with an isolated PostgreSQL database")


def _actor(authentication: object) -> ActorContext:
    from eom_identity_service.tokens import AccessAuthentication

    assert isinstance(authentication, AccessAuthentication)
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=authentication.operator.operator_id,
        session_id=authentication.session_id,
        request_id="req_identity_integration",
        authentication_time=authentication.authenticated_at,
        permissions=authentication.permissions,
        source=ActorSource.APPLICATION_API,
    )


def _cleanup(engine: object) -> None:
    from sqlalchemy import Engine

    assert isinstance(engine, Engine)
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        operator_ids = list(
            session.scalars(
                select(OperatorRecord.operator_id).where(
                    OperatorRecord.username.in_(("admin", "review01", "viewer01"))
                )
            )
        )
        if not operator_ids:
            return
        session.execute(
            delete(ApiTokenRecord).where(
                ApiTokenRecord.api_session_id.in_(
                    select(ApiSessionRecord.api_session_id).where(
                        ApiSessionRecord.operator_id.in_(operator_ids)
                    )
                )
            )
        )
        session.execute(
            delete(ApiIdempotencyRecord).where(ApiIdempotencyRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(ApiSessionRecord).where(ApiSessionRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(OperatorEventRecord).where(OperatorEventRecord.operator_id.in_(operator_ids))
        )
        session.execute(
            delete(OperatorRoleAssignmentRecord).where(
                OperatorRoleAssignmentRecord.operator_id.in_(operator_ids)
            )
        )
        session.execute(
            delete(OperatorCredentialRecord).where(
                OperatorCredentialRecord.operator_id.in_(operator_ids)
            )
        )
        session.execute(delete(OperatorRecord).where(OperatorRecord.operator_id.in_(operator_ids)))


def test_identity_rbac_session_and_refresh_concurrency() -> None:
    _enabled()
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        if int(session.scalar(select(func.count(OperatorRecord.operator_id))) or 0):
            pytest.skip("identity integration requires a database without existing Operators")
    _cleanup(engine)
    try:
        barrier = Barrier(2)

        def bootstrap() -> object:
            barrier.wait(timeout=5)
            try:
                return OperatorService(engine).bootstrap_admin(
                    username="admin", display_name="통합 관리자"
                )
            except IdentityError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: bootstrap(), range(2)))
        successes = [result for result in results if not isinstance(result, IdentityError)]
        failures = [result for result in results if isinstance(result, IdentityError)]
        assert len(successes) == 1
        assert len(failures) == 1
        bootstrap_result = successes[0]
        assert hasattr(bootstrap_result, "temporary_password")
        temporary_password = bootstrap_result.temporary_password

        tokens = SessionTokenService(TokenCodec(TOKEN_HASH_KEY))
        auth = AuthService(engine, tokens)
        restricted = auth.login(
            username="admin",
            password=temporary_password,
            client_name="identity-integration",
        )
        restricted_authentication = auth.authenticate_access(restricted.pair.access_token)
        assert restricted_authentication.password_change_required
        normal_pair = auth.change_password(
            restricted_authentication,
            current_password=temporary_password,
            new_password=ADMIN_REPLACEMENT_PASSWORD,
        )
        with pytest.raises(IdentityError):
            auth.authenticate_access(restricted.pair.access_token)
        admin_authentication = auth.authenticate_access(normal_pair.access_token)
        assert not admin_authentication.password_change_required
        admin_actor = _actor(admin_authentication)

        operators = OperatorService(engine)
        reviewer = operators.create_operator(
            CreateOperatorCommand(
                username="review01",
                display_name="검토자",
                temporary_password=REVIEWER_PASSWORD,
                initial_roles=(RoleKey.REVIEWER,),
            ),
            admin_actor,
        )
        viewer = operators.create_operator(
            CreateOperatorCommand(
                username="viewer01",
                display_name="조회자",
                temporary_password=VIEWER_PASSWORD,
                initial_roles=(RoleKey.VIEWER,),
            ),
            admin_actor,
        )
        with pytest.raises(IdentityError) as duplicate:
            operators.create_operator(
                CreateOperatorCommand(
                    username="viewer01",
                    display_name="중복 조회자",
                    temporary_password="TEST_ONLY duplicate password 42",
                    initial_roles=(RoleKey.VIEWER,),
                ),
                admin_actor,
            )
        assert duplicate.value.code is IdentityErrorCode.OPERATOR_USERNAME_CONFLICT
        with pytest.raises(IdentityError) as last_admin:
            operators.revoke_role(
                admin_authentication.operator.operator_id,
                RoleKey.ADMIN,
                admin_actor,
                reason="TEST_ONLY last admin guard",
            )
        assert last_admin.value.code is IdentityErrorCode.OPERATOR_LAST_ADMIN

        viewer_login = auth.login(
            username="viewer01",
            password=VIEWER_PASSWORD,
            client_name="identity-integration",
        )
        before = auth.authenticate_access(viewer_login.pair.access_token)
        assert PermissionKey.WORKFLOW_START not in before.permissions
        operators.assign_role(viewer.operator_id, RoleKey.AUTHOR, admin_actor)
        after = auth.authenticate_access(viewer_login.pair.access_token)
        assert PermissionKey.WORKFLOW_START in after.permissions
        operators.disable(viewer.operator_id, admin_actor, reason="TEST_ONLY disable")
        with pytest.raises(IdentityError) as disabled:
            auth.authenticate_access(viewer_login.pair.access_token)
        assert disabled.value.code is IdentityErrorCode.AUTH_SESSION_REVOKED

        reviewer_login = auth.login(
            username="review01",
            password=REVIEWER_PASSWORD,
            client_name="identity-integration",
        )
        refresh_token = reviewer_login.pair.refresh_token
        refresh_barrier = Barrier(2)

        def refresh() -> object:
            refresh_barrier.wait(timeout=5)
            try:
                return auth.refresh(refresh_token)
            except IdentityError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            refresh_results = list(executor.map(lambda _: refresh(), range(2)))
        rotated = [result for result in refresh_results if not isinstance(result, IdentityError)]
        rejected = [result for result in refresh_results if isinstance(result, IdentityError)]
        assert len(rotated) == 1
        assert len(rejected) == 1
        assert rejected[0].code is IdentityErrorCode.AUTH_REFRESH_TOKEN_REUSED
        with pytest.raises(IdentityError) as family_revoked:
            auth.authenticate_access(rotated[0].access_token)
        assert family_revoked.value.code is IdentityErrorCode.AUTH_SESSION_REVOKED

        operators.assign_role(reviewer.operator_id, RoleKey.ADMIN, admin_actor)
        operators.disable(
            admin_authentication.operator.operator_id,
            admin_actor,
            reason="TEST_ONLY second admin permits disable",
        )
        with sessions() as session:
            assert PermissionKey.SYSTEM_DOCTOR in effective_permissions(
                session, reviewer.operator_id
            )
    finally:
        _cleanup(engine)
        engine.dispose()


def test_account_lock_persists_failed_attempts() -> None:
    _enabled()
    engine = build_engine()
    with build_session_factory(engine)() as session:
        if int(session.scalar(select(func.count(OperatorRecord.operator_id))) or 0):
            pytest.skip("identity integration requires a database without existing Operators")
    try:
        bootstrap = OperatorService(engine).bootstrap_admin(
            username="admin", display_name="통합 관리자"
        )
        auth = AuthService(
            engine,
            SessionTokenService(TokenCodec(TOKEN_HASH_KEY)),
            login_policy=LoginPolicy(failure_limit=2, failure_window_seconds=900, lock_seconds=900),
        )
        start = datetime.now(UTC)
        for offset in (0, 1):
            with pytest.raises(AuthenticationFailure):
                auth.login(
                    username="admin",
                    password="TEST_ONLY wrong password 42",
                    client_name="identity-integration",
                    now=start + timedelta(seconds=offset),
                )
        with pytest.raises(AuthenticationFailure) as locked:
            auth.login(
                username="admin",
                password=bootstrap.temporary_password,
                client_name="identity-integration",
                now=start + timedelta(seconds=2),
            )
        assert locked.value.internal_reason == "ACCOUNT_LOCKED"
        result = auth.login(
            username="admin",
            password=bootstrap.temporary_password,
            client_name="identity-integration",
            now=start + timedelta(seconds=902),
        )
        assert result.operator_id == bootstrap.operator.operator_id
    finally:
        _cleanup(engine)
        engine.dispose()


def test_builtin_seed_idempotency_and_append_only_audit() -> None:
    _enabled()
    engine = build_engine()
    sessions = build_session_factory(engine)
    with transaction(sessions) as session:
        seed_builtin_rbac(session)
        seed_builtin_rbac(session)
    with sessions() as session:
        assert len(list(session.scalars(select(RoleRecord)))) == 5
        assert len(list(session.scalars(select(PermissionRecord)))) == len(PermissionKey)
        assert len(list(session.scalars(select(RolePermissionRecord)))) == sum(
            len(permissions)
            for permissions in __import__(
                "eom_operator_identity.contracts", fromlist=["ROLE_PERMISSIONS"]
            ).ROLE_PERMISSIONS.values()
        )

    with engine.connect() as connection:
        outer = connection.begin()
        session = Session(bind=connection, expire_on_commit=False)
        audit_id = new_api_audit_event_id()
        session.add(
            ApiAuditEventRecord(
                api_audit_event_id=audit_id,
                request_id="req_audit_test",
                operator_id=None,
                api_session_id=None,
                event_type="LOGIN_FAILED",
                operation_id="auth_login",
                http_method="POST",
                route_template="/api/v1/auth/login",
                outcome="DENIED",
                http_status=401,
                created_at=datetime.now(UTC),
            )
        )
        session.flush()
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                update(ApiAuditEventRecord)
                .where(ApiAuditEventRecord.api_audit_event_id == audit_id)
                .values(outcome="MUTATED")
            )
        session.close()
        outer.rollback()
    engine.dispose()
