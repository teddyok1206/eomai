from __future__ import annotations

import pytest
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.passwords import COMMON_PASSWORDS, PasswordService


def _fullwidth_ascii(value: str) -> str:
    return "".join(
        chr(0x3000) if character == " " else chr(ord(character) + 0xFEE0) for character in value
    )


@pytest.fixture(scope="module")
def passwords() -> PasswordService:
    return PasswordService()


@pytest.mark.parametrize(
    "password",
    [
        "test.operator",
        "TEST.OPERATOR",
        _fullwidth_ascii("TEST.OPERATOR"),
        "Fixture Name",
        "fixture name",
        _fullwidth_ascii("FIXTURE NAME"),
    ],
)
def test_ordinary_policy_still_rejects_normalized_identity_values(
    passwords: PasswordService, password: str
) -> None:
    for operation in (passwords.validate, passwords.hash_password):
        with pytest.raises(IdentityError) as raised:
            operation(password, username="test.operator", display_name="Fixture Name")
        assert raised.value.code is IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED


def test_temporary_login_id_hash_uses_exact_username_and_does_not_relax_normal_policy(
    passwords: PasswordService,
) -> None:
    username = "approved.fixture.01"

    password_hash = passwords.hash_temporary_login_id_password(username=username)

    assert password_hash.startswith("$argon2id$")
    assert passwords.verify(username, password_hash)
    assert not passwords.verify("different.fixture.01", password_hash)
    with pytest.raises(IdentityError) as raised:
        passwords.hash_password(username, username=username, display_name="Fixture Name")
    assert raised.value.code is IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED


@pytest.mark.parametrize(
    "username",
    [
        "",
        "test\x00operator",
        "x" * 129,
        "가" * 86,
        *sorted(COMMON_PASSWORDS),
        "PASSWORDPASSWORD",
        _fullwidth_ascii("PASSWORDPASSWORD"),
    ],
)
def test_temporary_login_id_hash_preserves_non_identity_policy(
    passwords: PasswordService, username: str
) -> None:
    with pytest.raises(IdentityError) as raised:
        passwords.hash_temporary_login_id_password(username=username)
    assert raised.value.code is IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED


def test_ordinary_non_identity_password_remains_valid(passwords: PasswordService) -> None:
    password = "Fixture independent password 42"

    password_hash = passwords.hash_password(
        password, username="test.operator", display_name="Fixture Name"
    )

    assert password_hash.startswith("$argon2id$")
    assert passwords.verify(password, password_hash)
