from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def integration_engine() -> Iterator[Engine]:
    if os.environ.get("EOM_RUN_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_INTEGRATION=1 to run PostgreSQL integration tests")
    engine = build_engine()
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(integration_engine: Engine) -> Iterator[Session]:
    with integration_engine.connect() as connection:
        outer = connection.begin()
        with Session(bind=connection, expire_on_commit=False) as session:
            yield session
            session.close()
        outer.rollback()
