from eom_api.rate_limit import BoundedRateLimiter


def test_rate_limit_expiry_retry_and_bound() -> None:
    limiter = BoundedRateLimiter(maximum_buckets=2)
    assert limiter.check("first", limit=1, window_seconds=60, now=0).allowed
    blocked = limiter.check("first", limit=1, window_seconds=60, now=1)
    assert not blocked.allowed
    assert blocked.retry_after == 59
    assert limiter.check("second", limit=1, window_seconds=60, now=1).allowed
    assert limiter.check("third", limit=1, window_seconds=60, now=1).allowed
    assert limiter.bucket_count == 2
    assert limiter.check("first", limit=1, window_seconds=60, now=61).allowed


def test_discard_is_scoped_idempotent_and_does_not_reset_global_budget() -> None:
    limiter = BoundedRateLimiter()
    for key in ("login:global", "login:username:one", "login:username:two"):
        assert limiter.check(key, limit=1, window_seconds=900, now=0).allowed
    limiter.discard("login:username:one")
    limiter.discard("missing")
    assert limiter.check("login:username:one", limit=1, window_seconds=900, now=1).allowed
    assert not limiter.check("login:username:two", limit=1, window_seconds=900, now=1).allowed
    assert not limiter.check("login:global", limit=1, window_seconds=900, now=1).allowed
