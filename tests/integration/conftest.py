from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.integration.general_chat_fixtures import chat  # noqa: F401


@pytest.fixture
def creative_engine() -> Iterator[Engine]:
    """External source/control tests may use only the guarded disposable owner DB."""

    from scripts.api.testdb_guard import TestDatabaseManifest, validate_state_directory

    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh external-item-tests; never production")
    state = validate_state_directory(Path(os.environ["EOM_EXTERNAL_ITEM_TEST_STATE"]))
    manifest = TestDatabaseManifest.load(state / "manifest.json")
    parsed = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert parsed.username == manifest.owner_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT current_database()")) == manifest.database
            assert connection.scalar(text("SELECT current_user")) == manifest.owner_role
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def integration_engine() -> Iterator[Engine]:
    if os.environ.get("EOM_RUN_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_INTEGRATION=1 to run PostgreSQL integration tests")
    explicit_url = os.environ.get("EOM_DATABASE_URL")
    if not explicit_url:
        pytest.fail(
            "integration tests require an explicit isolated EOM_DATABASE_URL; "
            "runtime secret-file fallback is forbidden"
        )
    # Pass the already-resolved test URL so ``build_engine`` can never fall back to the installed
    # production secret file. Never include the credential-bearing URL in test output.
    engine = build_engine(explicit_url)
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
