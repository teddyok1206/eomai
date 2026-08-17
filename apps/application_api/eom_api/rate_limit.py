"""Bounded process-local sliding-window rate limiter."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int


class BoundedRateLimiter:
    def __init__(self, maximum_buckets: int = 10_000) -> None:
        if maximum_buckets < 1:
            raise ValueError("maximum_buckets must be positive")
        self._maximum = maximum_buckets
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def bucket_count(self) -> int:
        return len(self._buckets)

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        now: float | None = None,
    ) -> RateLimitResult:
        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - window_seconds
        with self._lock:
            bucket = self._buckets.pop(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                self._buckets[key] = bucket
                retry = max(1, math.ceil(bucket[0] + window_seconds - timestamp))
                return RateLimitResult(False, retry)
            bucket.append(timestamp)
            self._buckets[key] = bucket
            while len(self._buckets) > self._maximum:
                self._buckets.popitem(last=False)
            return RateLimitResult(True, 0)
