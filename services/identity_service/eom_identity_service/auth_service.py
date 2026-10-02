"""Transactional authentication application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from eom_operator_identity.contracts import normalize_username, validate_username
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.passwords import PasswordService
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select

from eom_identity_service.models import ApiSessionRecord, OperatorCredentialRecord, OperatorRecord
from eom_identity_service.repository import (
    add_operator_event,
    lock_identity_invariants,
    operator_by_username,
    require_credential,
    revoke_operator_sessions,
)
from eom_identity_service.tokens import (
    AccessAuthentication,
    IssuedTokenPair,
    RefreshOutcome,
    SessionTokenService,
)


@dataclass(frozen=True)
class LoginPolicy:
    failure_limit: int = 5
    failure_window_seconds: int = 900
    lock_seconds: int = 900


@dataclass(frozen=True)
class LoginResult:
    pair: IssuedTokenPair
    operator_id: str


class AuthenticationFailure(IdentityError):
    def __init__(self, internal_reason: str) -> None:
        super().__init__(
            IdentityErrorCode.AUTH_INVALID_CREDENTIALS,
            "Invalid username or password.",
        )
        self.internal_reason = internal_reason


class AuthService:
    def __init__(
        self,
        engine: Engine,
        tokens: SessionTokenService,
        passwords: PasswordService | None = None,
        login_policy: LoginPolicy | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.tokens = tokens
        self.passwords = passwords or PasswordService()
        self.login_policy = login_policy or LoginPolicy()

    def login(
        self,
        *,
        username: str,
        password: str,
        client_name: str,
        now: datetime | None = None,
    ) -> LoginResult:
        timestamp = now or datetime.now(UTC)
        normalized = normalize_username(username)
        failure: str | None = None
        result: LoginResult | None = None
        with transaction(self.sessions) as session:
            operator = operator_by_username(session, normalized, for_update=True)
            if operator is None:
                self.passwords.verify_dummy(password)
                failure = "UNKNOWN_USERNAME"
            else:
                credential = require_credential(session, operator.operator_id, for_update=True)
                password_valid = self.passwords.verify(password, credential.password_hash)
                locked = credential.locked_until is not None and credential.locked_until > timestamp
                active = operator.status == "ACTIVE"
                if not password_valid:
                    self._register_failure(credential, timestamp)
                    failure = "PASSWORD_MISMATCH"
                elif locked:
                    failure = "ACCOUNT_LOCKED"
                elif not active:
                    failure = "OPERATOR_DISABLED"
                else:
                    self._register_success(operator, credential, timestamp)
                    pair = self.tokens.create_session(
                        session,
                        operator,
                        client_name=client_name,
                        password_change_required=credential.must_change_password,
                        now=timestamp,
                    )
                    result = LoginResult(pair=pair, operator_id=operator.operator_id)
                    add_operator_event(
                        session,
                        operator,
                        event_type="LOGIN_SUCCEEDED",
                        actor_id=operator.operator_id,
                        request_id="authentication",
                        payload={"actor_type": "OPERATOR", "source": "APPLICATION_API"},
                        now=timestamp,
                    )
        if failure is not None:
            raise AuthenticationFailure(failure)
        if result is None:
            raise RuntimeError("login completed without a result")
        return result

    def authenticate_access(
        self, raw_token: str, *, now: datetime | None = None
    ) -> AccessAuthentication:
        authentication: AccessAuthentication | None = None
        error: IdentityError | None = None
        with transaction(self.sessions) as session:
            try:
                authentication = self.tokens.authenticate_access(session, raw_token, now=now)
            except IdentityError as exc:
                error = exc
        if error is not None:
            raise error
        if authentication is None:
            raise RuntimeError("access authentication completed without a result")
        return authentication

    def refresh(self, raw_token: str, *, now: datetime | None = None) -> IssuedTokenPair:
        with transaction(self.sessions) as session:
            outcome = self.tokens.rotate_refresh(session, raw_token, now=now)
        self._raise_refresh(outcome)
        assert outcome.pair is not None
        return outcome.pair

    def logout(self, api_session_id: str, operator_id: str) -> None:
        timestamp = datetime.now(UTC)
        with transaction(self.sessions) as session:
            api_session = session.scalar(
                select(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == api_session_id)
                .with_for_update()
            )
            if api_session is None or api_session.operator_id != operator_id:
                raise IdentityError(IdentityErrorCode.AUTH_SESSION_REVOKED, "session is revoked")
            if api_session.revoked_at is None:
                api_session.revoked_at = timestamp
                api_session.revoked_by = operator_id
                api_session.revoke_reason = "LOGOUT"
                api_session.lock_version += 1

    def logout_all(self, operator_id: str) -> int:
        with transaction(self.sessions) as session:
            return revoke_operator_sessions(
                session,
                operator_id,
                actor_id=operator_id,
                reason="LOGOUT_ALL",
            )

    def change_password(
        self,
        authentication: AccessAuthentication,
        *,
        current_password: str,
        new_password: str,
    ) -> IssuedTokenPair:
        timestamp = datetime.now(UTC)
        failure = False
        pair: IssuedTokenPair | None = None
        with transaction(self.sessions) as session:
            operator = session.scalar(
                select(OperatorRecord)
                .where(OperatorRecord.operator_id == authentication.operator.operator_id)
                .with_for_update()
            )
            if operator is None or operator.status != "ACTIVE":
                raise IdentityError(IdentityErrorCode.AUTH_SESSION_REVOKED, "session is revoked")
            credential = require_credential(session, operator.operator_id, for_update=True)
            if not self.passwords.verify(current_password, credential.password_hash):
                failure = True
            else:
                credential.password_hash = self.passwords.hash_password(
                    new_password,
                    username=operator.username,
                    display_name=operator.display_name,
                )
                credential.password_algorithm = "argon2id"
                credential.password_version += 1
                credential.must_change_password = False
                credential.password_changed_at = timestamp
                credential.failed_login_count = 0
                credential.first_failed_at = None
                credential.last_failed_at = None
                credential.locked_until = None
                operator.must_change_password = False
                operator.lock_version += 1
                revoke_operator_sessions(
                    session,
                    operator.operator_id,
                    actor_id=operator.operator_id,
                    reason="PASSWORD_CHANGED",
                    except_session_id=authentication.session_id,
                    now=timestamp,
                )
                pair = self.tokens.rotate_current_session(
                    session,
                    authentication.session_id,
                    password_change_required=False,
                    now=timestamp,
                )
                add_operator_event(
                    session,
                    operator,
                    event_type="PASSWORD_CHANGED",
                    actor_id=operator.operator_id,
                    request_id="authentication",
                    payload={"actor_type": "OPERATOR", "source": "APPLICATION_API"},
                    now=timestamp,
                )
        if failure:
            raise AuthenticationFailure("CURRENT_PASSWORD_MISMATCH")
        if pair is None:
            raise RuntimeError("password change completed without a token pair")
        return pair

    def update_credentials(
        self,
        authentication: AccessAuthentication,
        *,
        current_password: str,
        new_username: str | None,
        new_password: str | None,
        expected_resource_version: int,
        request_id: str,
    ) -> IssuedTokenPair:
        """Atomically update this authenticated Operator's login credentials."""

        requested_username = validate_username(new_username) if new_username is not None else None
        timestamp = datetime.now(UTC)
        failure = False
        pair: IssuedTokenPair | None = None
        with transaction(self.sessions) as session:
            if requested_username is not None:
                lock_identity_invariants(session)
            operator = session.scalar(
                select(OperatorRecord)
                .where(OperatorRecord.operator_id == authentication.operator.operator_id)
                .with_for_update()
            )
            if operator is None or operator.status != "ACTIVE":
                raise IdentityError(IdentityErrorCode.AUTH_SESSION_REVOKED, "session is revoked")
            credential = require_credential(session, operator.operator_id, for_update=True)
            if not self.passwords.verify(current_password, credential.password_hash):
                failure = True
            elif operator.lock_version != expected_resource_version:
                raise IdentityError(
                    IdentityErrorCode.OPERATOR_VERSION_CONFLICT,
                    "operator resource version differs",
                )
            else:
                username_changed = (
                    requested_username is not None and requested_username != operator.username
                )
                password_changed = new_password is not None
                if not username_changed and not password_changed:
                    raise IdentityError(
                        IdentityErrorCode.OPERATOR_CREDENTIALS_UNCHANGED,
                        "credential update does not change the account",
                    )
                if requested_username is not None:
                    normalized = normalize_username(requested_username)
                    existing = operator_by_username(session, normalized)
                    if existing is not None and existing.operator_id != operator.operator_id:
                        raise IdentityError(
                            IdentityErrorCode.OPERATOR_USERNAME_CONFLICT,
                            "username already exists",
                        )
                    operator.username = requested_username
                    operator.normalized_username = normalized
                if new_password is not None:
                    credential.password_hash = self.passwords.hash_password(
                        new_password,
                        username=operator.username,
                        display_name=operator.display_name,
                    )
                    credential.password_algorithm = "argon2id"
                    credential.password_version += 1
                    credential.must_change_password = False
                    credential.password_changed_at = timestamp
                    credential.failed_login_count = 0
                    credential.first_failed_at = None
                    credential.last_failed_at = None
                    credential.locked_until = None
                    operator.must_change_password = False
                operator.lock_version += 1
                revoke_operator_sessions(
                    session,
                    operator.operator_id,
                    actor_id=operator.operator_id,
                    reason="CREDENTIALS_CHANGED",
                    except_session_id=authentication.session_id,
                    now=timestamp,
                )
                pair = self.tokens.rotate_current_session(
                    session,
                    authentication.session_id,
                    password_change_required=credential.must_change_password,
                    now=timestamp,
                )
                add_operator_event(
                    session,
                    operator,
                    event_type="CREDENTIALS_CHANGED",
                    actor_id=operator.operator_id,
                    request_id=request_id,
                    payload={
                        "actor_type": "OPERATOR",
                        "source": "APPLICATION_API",
                        "username_changed": username_changed,
                        "password_changed": password_changed,
                        "resource_version": operator.lock_version,
                    },
                    now=timestamp,
                )
        if failure:
            raise AuthenticationFailure("CURRENT_PASSWORD_MISMATCH")
        if pair is None:
            raise RuntimeError("credential update completed without a token pair")
        return pair

    def _register_failure(self, credential: OperatorCredentialRecord, timestamp: datetime) -> None:
        window = timedelta(seconds=self.login_policy.failure_window_seconds)
        if credential.first_failed_at is None or credential.first_failed_at + window <= timestamp:
            credential.failed_login_count = 1
            credential.first_failed_at = timestamp
        else:
            credential.failed_login_count += 1
        credential.last_failed_at = timestamp
        if credential.failed_login_count >= self.login_policy.failure_limit:
            credential.locked_until = timestamp + timedelta(seconds=self.login_policy.lock_seconds)

    @staticmethod
    def _register_success(
        operator: OperatorRecord,
        credential: OperatorCredentialRecord,
        timestamp: datetime,
    ) -> None:
        credential.failed_login_count = 0
        credential.first_failed_at = None
        credential.last_failed_at = None
        credential.locked_until = None
        credential.last_success_at = timestamp
        operator.last_login_at = timestamp

    @staticmethod
    def _raise_refresh(outcome: RefreshOutcome) -> None:
        if outcome.error is not None:
            raise IdentityError(outcome.error, "refresh token is invalid")
