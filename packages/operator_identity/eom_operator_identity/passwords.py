"""Argon2id password policy and verification."""

from __future__ import annotations

import secrets
import string
import unicodedata
from dataclasses import dataclass

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from eom_operator_identity.errors import IdentityError, IdentityErrorCode

COMMON_PASSWORDS = frozenset(
    {
        "123456789012345",
        "adminadminadmin",
        "changemechangeme",
        "letmeinletmein123",
        "passwordpassword",
        "qwertyqwerty12345",
    }
)


@dataclass(frozen=True)
class PasswordPolicy:
    maximum_characters: int = 128
    maximum_encoded_bytes: int = 256


class PasswordService:
    def __init__(self, policy: PasswordPolicy | None = None) -> None:
        self.policy = policy or PasswordPolicy()
        self._hasher = PasswordHash.recommended()
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def validate(self, password: str, *, username: str, display_name: str) -> None:
        normalized = self._validate_non_identity(password)
        identities = {
            unicodedata.normalize("NFKC", username).casefold(),
            unicodedata.normalize("NFKC", display_name).casefold(),
        }
        if normalized in identities:
            raise IdentityError(
                IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED,
                "password does not satisfy policy",
            )

    def _validate_non_identity(self, password: str) -> str:
        encoded = password.encode("utf-8")
        normalized = unicodedata.normalize("NFKC", password).casefold()
        invalid = (
            not password
            or "\x00" in password
            or len(password) > self.policy.maximum_characters
            or len(encoded) > self.policy.maximum_encoded_bytes
            or normalized in COMMON_PASSWORDS
        )
        if invalid:
            raise IdentityError(
                IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED,
                "password does not satisfy policy",
            )
        return normalized

    def hash_password(self, password: str, *, username: str, display_name: str) -> str:
        self.validate(password, username=username, display_name=display_name)
        return self._hasher.hash(password)

    def hash_temporary_login_id_password(self, *, username: str) -> str:
        """Hash a canonical login ID only after the scoped recovery use case authorizes it.

        The caller owns exact-target authorization and forced-change lifecycle. Ordinary
        creation and credential updates must continue to use ``hash_password``.
        """

        self._validate_non_identity(username)
        return self._hasher.hash(username)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password, password_hash)
        except (UnknownHashError, ValueError):
            return False

    def verify_dummy(self, password: str) -> None:
        self._hasher.verify(password, self._dummy_hash)

    @staticmethod
    def generate_temporary_password() -> str:
        alphabet = string.ascii_letters + string.digits + "-_.!@#%"
        return "".join(secrets.choice(alphabet) for _ in range(28))
