"""Authentication service and bounded in-memory login failure limiter."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from eom_observe.security import SessionClaims, SessionSigner, verify_access_token


class LoginRateLimiter:
    def __init__(self, *, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window = timedelta(seconds=window_seconds)
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)

    def _prune(self, key: str, now: datetime) -> deque[datetime]:
        values = self._failures[key]
        cutoff = now - self.window
        while values and values[0] <= cutoff:
            values.popleft()
        return values

    def allowed(self, key: str, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return len(self._prune(key, current)) < self.max_failures

    def record_failure(self, key: str, *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        self._prune(key, current).append(current)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


class AuthService:
    def __init__(self, token_hash: str, session_secret: str, ttl_seconds: int) -> None:
        self._token_hash = token_hash
        self.signer = SessionSigner(session_secret, ttl_seconds)
        self.rate_limiter = LoginRateLimiter()

    def authenticate(self, token: str, client_key: str) -> bool:
        if not self.rate_limiter.allowed(client_key):
            return False
        if verify_access_token(token, self._token_hash):
            self.rate_limiter.reset(client_key)
            return True
        self.rate_limiter.record_failure(client_key)
        return False

    def session(self, cookie: str | None) -> SessionClaims | None:
        if not cookie:
            return None
        return self.signer.verify(cookie)
