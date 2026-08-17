from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from eom_orchestrator.database import build_engine
from sqlalchemy import event
from sqlalchemy.orm import Session


@pytest.fixture
def db_session() -> Iterator[Session]:
    if os.environ.get("EOM_RUN_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_INTEGRATION=1 to run PostgreSQL integration tests")
    engine = build_engine()
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(current: Session, transaction: object) -> None:
        if not current.in_nested_transaction() and current.in_transaction():
            current.begin_nested()

    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()
        engine.dispose()
