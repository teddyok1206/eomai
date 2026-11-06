"""Keep one existing claim during slow Graph publication, without holding a DB row lock.

Only the original run/owner/token is renewed by indexed lookup. No claim is acquired,
revived, transferred or turned into model/source authority here. The caller must leave
the run non-terminal until this scope has stopped and revalidated its ownership.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from math import isfinite
from threading import Event, Thread

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from eom_catalog_service.material_learning_store import (
    MaterialLearningStorageError,
    MaterialRunClaim,
    lock_material_run,
    renew_material_claim,
)


@contextmanager
def maintain_material_claim(
    sessions: sessionmaker[Session],
    claim: MaterialRunClaim,
    *,
    lease_duration: timedelta,
    heartbeat_seconds: float = 30.0,
) -> Iterator[None]:
    if (
        isinstance(heartbeat_seconds, bool)
        or not isfinite(heartbeat_seconds)
        or not 0 < heartbeat_seconds <= lease_duration.total_seconds() / 3
        or not timedelta(seconds=10) <= lease_duration <= timedelta(hours=1)
    ):
        raise ValueError("MATERIAL_LEARNING_HEARTBEAT_INTERVAL_INVALID")
    stopped = Event()
    failures: list[Exception] = []

    def renew() -> None:
        with sessions.begin() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("SET LOCAL statement_timeout = '10s'"))
            renew_material_claim(
                session, claim, now=datetime.now(UTC), lease_duration=lease_duration
            )

    def heartbeat() -> None:
        while not stopped.wait(heartbeat_seconds):
            try:
                renew()
            except Exception as error:
                failures.append(error)
                return

    renew()
    thread = Thread(target=heartbeat, name="material-claim-renewal", daemon=True)
    thread.start()
    body_failed = False
    try:
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        stopped.set()
        thread.join(timeout=12)
        if not body_failed:
            if thread.is_alive():
                raise MaterialLearningStorageError("MATERIAL_LEARNING_HEARTBEAT_STOP_UNCERTAIN")
            if failures:
                raise failures[0]
            with sessions.begin() as session:
                lock_material_run(session, claim, now=datetime.now(UTC))
