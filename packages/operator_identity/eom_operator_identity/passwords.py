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
    minimum_characters: int = 15
    maximum_characters: int = 128
    maximum_encoded_bytes: int = 256


class PasswordService:
    def __init__(self, policy: PasswordPolicy | None = None) -> None:
        self.policy = policy or PasswordPolicy()
        self._hasher = PasswordHash.recommended()
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def validate(self, password: str, *, username: str, display_name: str) -> None:
        encoded = password.encode("utf-8")
        normalized = unicodedata.normalize("NFKC", password).casefold()
        identities = {
            unicodedata.normalize("NFKC", username).casefold(),
            unicodedata.normalize("NFKC", display_name).casefold(),
        }
        invalid = (
            not password
            or "\x00" in password
            or len(password) < self.policy.minimum_characters
            or len(password) > self.policy.maximum_characters
            or len(encoded) > self.policy.maximum_encoded_bytes
            or normalized in identities
            or normalized in COMMON_PASSWORDS
        )
        if invalid:
            raise IdentityError(
                IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED,
                "password does not satisfy policy",
            )

    def hash_password(self, password: str, *, username: str, display_name: str) -> str:
        self.validate(password, username=username, display_name=display_name)
        return self._hasher.hash(password)

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
