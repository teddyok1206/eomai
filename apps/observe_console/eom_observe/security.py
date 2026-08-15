"""Token KDF and signed, stateless session primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def generate_access_token() -> str:
    return secrets.token_urlsafe(32)


def hash_access_token(token: str, *, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        token.encode("utf-8"),
        salt=actual_salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64encode(actual_salt)}${_b64encode(digest)}"


def verify_access_token(token: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            token.encode("utf-8"),
            salt=_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_b64decode(expected)),
        )
        return hmac.compare_digest(actual, _b64decode(expected))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class SessionClaims:
    issued_at: int
    expires_at: int
    nonce: str


class SessionSigner:
    def __init__(self, secret: str, ttl_seconds: int) -> None:
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def create(self, *, now: datetime | None = None) -> str:
        current = int((now or datetime.now(UTC)).timestamp())
        payload = {
            "iat": current,
            "exp": current + self._ttl_seconds,
            "nonce": secrets.token_urlsafe(12),
        }
        encoded = _b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _b64encode(
            hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{encoded}.{signature}"

    def verify(self, value: str, *, now: datetime | None = None) -> SessionClaims | None:
        try:
            encoded, supplied = value.split(".", 1)
            expected = _b64encode(
                hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied, expected):
                return None
            payload = json.loads(_b64decode(encoded))
            current = int((now or datetime.now(UTC)).timestamp())
            issued_at = int(payload["iat"])
            expires_at = int(payload["exp"])
            nonce = str(payload["nonce"])
            if expires_at <= current or issued_at > current + 30 or expires_at <= issued_at:
                return None
            return SessionClaims(issued_at=issued_at, expires_at=expires_at, nonce=nonce)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
