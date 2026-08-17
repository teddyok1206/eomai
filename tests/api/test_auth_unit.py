from __future__ import annotations

import pytest
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.passwords import PasswordService

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
    service.validate(" " * 15, username="author01", display_name="작성자")


@pytest.mark.parametrize(
    "password",
    [
        "",
        "short password",
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
