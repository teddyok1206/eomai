"""Opt-in actual PostgreSQL errors/rollback in an independently marker-guarded DB."""

from uuid import uuid4

import pytest
from eom_orchestrator.database import recoverable_database_error_code
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "state,expected",
    [
        ("53100", "BACKGROUND_DATABASE_STORAGE_EXHAUSTED"),
        ("40P01", "BACKGROUND_DATABASE_RETRY_REQUIRED"),
        ("42501", None),
    ],
)
def test_real_postgresql_resource_error_rolls_back_then_original_identity_can_be_reused(
    guarded_engine: Engine, state: str, expected: str | None
) -> None:
    table = "background_recovery_probe_" + uuid4().hex
    with guarded_engine.connect() as connection:
        connection.execute(text(f"CREATE TEMP TABLE {table} (key text PRIMARY KEY)"))
        connection.commit()
        with pytest.raises(DBAPIError) as caught, connection.begin():
            connection.execute(text(f"INSERT INTO {table} VALUES ('same-original-key')"))
            # Actual server exception; no host disk filling or runtime fault injection.
            connection.execute(
                text(
                    "DO $$ BEGIN RAISE EXCEPTION 'synthetic protected resource fault' "
                    f"USING ERRCODE = '{state}'; END $$"
                )
            )
        assert recoverable_database_error_code(caught.value) == expected
        assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        connection.rollback()
        with connection.begin():
            connection.execute(text(f"INSERT INTO {table} VALUES ('same-original-key')"))
        assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 1
