"""Serialize existing file publication owners; no queue, lease or authority is created."""

import hashlib
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

from sqlalchemy import Engine, text


@contextmanager
def artifact_publication_lock(
    engine: Engine,
    *,
    namespace: str,
    idempotency_key: str,
    local_lock: AbstractContextManager[object],
) -> Iterator[None]:
    if engine.dialect.name != "postgresql":
        with local_lock:
            yield
        return
    key = int.from_bytes(
        hashlib.sha256(f"{namespace}:{idempotency_key}".encode()).digest()[:8], "big", signed=True
    )
    with engine.connect() as connection:
        try:
            connection.execute(text("SELECT pg_advisory_lock(:lock_key)"), {"lock_key": key})
        except Exception:
            connection.invalidate()
            raise
        try:
            yield
        finally:
            # Session advisory ownership survives rollback; discard an aborted SQL root first.
            try:
                connection.rollback()
                released = connection.scalar(
                    text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": key}
                )
                if released is not True:
                    raise RuntimeError("ARTIFACT_PUBLICATION_LOCK_LOST")
            except Exception:
                connection.invalidate()
                raise
