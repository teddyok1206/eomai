from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast
from unittest.mock import Mock

import pytest
from eom_identity_service import AuthenticatedSessionFence, AuthenticatedSessionFenceError
from eom_identity_service import auth_service as auth_module
from eom_identity_service.auth_service import AuthService
from eom_identity_service.tokens import SessionTokenService
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.passwords import PasswordService
from sqlalchemy.orm import Session, sessionmaker

from tests.api.test_token_unit import TokenMutationSession
from tests.unit.test_authenticated_session_fence import PIN, assert_current, verified_capture

VALID_PASSWORD = "TEST_ONLY long password 42"


def test_argon2id_hash_and_verify() -> None:
    service = PasswordService()
    password_hash = service.hash_password(
        VALID_PASSWORD, username="author01", display_name="작성자"
    )
    assert password_hash.startswith("$argon2id$")
    assert service.verify(VALID_PASSWORD, password_hash)
    assert not service.verify("TEST_ONLY wrong password 42", password_hash)


def test_password_policy_accepts_unicode_and_whitespace() -> None:
    service = PasswordService()
    unicode_password = "통합과학 안전한 암호 2026"
    service.validate(unicode_password, username="author01", display_name="작성자")
    service.validate("x", username="author01", display_name="작성자")
    service.validate(" ", username="author01", display_name="작성자")


@pytest.mark.parametrize(
    "password",
    [
        "",
        "author01",
        "작성자",
        "passwordpassword",
        "TEST_ONLY valid\x00but nul",
        "x" * 129,
        "가" * 86,
    ],
)
def test_password_policy_rejects_invalid_values(password: str) -> None:
    with pytest.raises(IdentityError) as raised:
        PasswordService().validate(password, username="author01", display_name="작성자")
    assert raised.value.code is IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED


def test_dummy_verification_runs_for_arbitrary_password() -> None:
    PasswordService().verify_dummy("TEST_ONLY unknown operator password")


def test_password_hash_has_no_silent_truncation() -> None:
    service = PasswordService()
    first = "a" * 127 + "x"
    second = "a" * 127 + "y"
    first_hash = service.hash_password(first, username="author01", display_name="작성자")
    assert service.verify(first, first_hash)
    assert not service.verify(second, first_hash)


def source_auth(
    monkeypatch: pytest.MonkeyPatch, source: TokenMutationSession
) -> tuple[AuthService, list[str]]:
    roots: list[str] = []

    @contextmanager
    def transaction(_factory: object) -> Iterator[Session]:
        roots.append("begin")
        try:
            yield cast(Session, source)
        finally:
            roots.append("end")

    monkeypatch.setattr(auth_module, "transaction", transaction)
    service = object.__new__(AuthService)
    service.sessions = cast(sessionmaker[Session], object())
    service.tokens = SessionTokenService(source.codec)
    return service, roots


def test_capture_wrapper_closes_authentication_root_without_retaining_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TokenMutationSession()
    verified_capture(monkeypatch, source)
    service, roots = source_auth(monkeypatch, source)
    capture = service.capture_access(source.raw_token)
    assert roots == ["begin", "end"] and capture.operator_id == source.operator.operator_id
    assert source.raw_token not in repr(capture)
    assert_current(source, capture, AuthenticatedSessionFence(PIN))


@pytest.mark.parametrize("all_sessions", [False, True])
def test_supported_logout_paths_revoke_capture_without_changing_token_identity(
    monkeypatch: pytest.MonkeyPatch, all_sessions: bool
) -> None:
    source = TokenMutationSession()
    _, capture = verified_capture(monkeypatch, source)
    service, _roots = source_auth(monkeypatch, source)
    token_id = source.token.api_token_id
    if all_sessions:
        service.logout_all(source.operator.operator_id)
    else:
        service.logout(source.api_session.api_session_id, source.operator.operator_id)
    assert source.api_session.revoked_at is not None and source.token.api_token_id == token_id
    with pytest.raises(AuthenticatedSessionFenceError):
        assert_current(source, capture)


def test_supported_password_change_locks_operator_credential_then_session_and_rotates_old_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TokenMutationSession()
    _, capture = verified_capture(monkeypatch, source)
    service, _roots = source_auth(monkeypatch, source)
    passwords = Mock(spec=PasswordService)
    passwords.verify.return_value = True
    passwords.hash_password.return_value = "synthetic-new-password-hash"
    service.passwords = cast(PasswordService, passwords)
    authentication = service.tokens.authenticate_access(cast(Session, source), source.raw_token)
    source.order.clear()
    pair = service.change_password(
        authentication, current_password="synthetic-only", new_password="synthetic-new-only"
    )
    assert source.order[:3] == ["OperatorRecord", "OperatorCredentialRecord", "UPDATE_api_sessions"]
    assert source.order[3:5] == ["ApiSessionRecord", "UPDATE_api_tokens"]
    assert (
        pair.session_id == source.api_session.api_session_id
        and source.api_session.refresh_generation == 2
    )
    assert (
        source.credential.password_hash == "synthetic-new-password-hash"
        and source.credential.password_version == 2
    )
    assert source.token.revoked_at is not None and source.api_session.revoked_at is None
    with pytest.raises(AuthenticatedSessionFenceError):
        assert_current(source, capture)


def test_capture_wrapper_preserves_authentication_denial_and_no_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TokenMutationSession()
    verified_capture(monkeypatch, source)
    service, roots = source_auth(monkeypatch, source)
    source.token.expires_at = datetime.now(UTC)
    with pytest.raises(IdentityError):
        service.capture_access(source.raw_token)
    assert roots == ["begin", "end"]
