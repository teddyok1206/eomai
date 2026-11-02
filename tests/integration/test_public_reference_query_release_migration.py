"""Guarded real66→68 migration/replay; privileged file/Identity ports remain synthetic."""

import pytest
from alembic import command
from sqlalchemy import text

from scripts.api import release_operator_runtime as operator
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_registered_public_release_migration import head
from tests.integration.test_registered_public_release_migration import release_case as release_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.mark.parametrize("release_case", ["20261102_0068"], indirect=True)
@pytest.mark.parametrize("response_lost", (False, True))
def test_public_step68_exact66_upgrade_and_post_commit_replay(
    release_case, monkeypatch, response_lost
):
    stage, context, config, engine = release_case
    command.downgrade(config, "20261031_0066")
    upgrade = command.upgrade
    calls = []

    def once(configuration, revision):
        calls.append(revision)
        upgrade(configuration, revision)
        if response_lost:
            raise OSError("synthetic response lost after committed DDL")

    monkeypatch.setattr(command, "upgrade", once)
    if response_lost:
        with pytest.raises(OSError, match="response lost"):
            operator.run_callback(
                stage, context, operator.Callback.MIGRATION_UPGRADE_0068_FROM_0066
            )
    else:
        operator.run_callback(stage, context, operator.Callback.MIGRATION_UPGRADE_0068_FROM_0066)
    assert head(engine) == "20261102_0068"
    operator.run_callback(stage, context, operator.Callback.MIGRATION_UPGRADE_0068_FROM_0066)
    assert calls == ["20261102_0068"]
    monkeypatch.setattr(command, "upgrade", upgrade)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE "
                    "tgrelid='app.workflow_step_runs'::regclass "
                    "AND tgname='trg_reference_query2_step_family'"
                )
            )
            == 1
        )
