"""Actual restricted PostgreSQL reads; no real content, NAS, inference or role widening."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_service.creative_proposal_read_set import capture_creative_proposal_read_set
from eom_catalog_service.models import ItemComponentRecord
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.database import build_engine
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from sqlalchemy import false, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_creative_proposal_resolution_v2 import _case

pytestmark = pytest.mark.integration
IMMUTABLE = (ItemComponentRecord, ResolvedExecutionPlanRecord, ArtifactRevisionRecord)


@pytest.fixture
def restricted(guarded_engine):
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    url = make_url(values["EOM_API_DATABASE_URL"])
    assert (url.username, url.database) == (manifest.runtime_role, manifest.database)
    engine = build_engine(str(url.render_as_string(hide_password=False)))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("model", IMMUTABLE)
def test_actual_limited_role_reads_immutable_metadata_without_an_update_grant(restricted, model):
    table = model.__tablename__
    with restricted.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT has_table_privilege(current_user, :table, 'SELECT') "
                "AND NOT has_table_privilege(current_user, :table, 'UPDATE')"
            ),
            {"table": "app." + table},
        )
        assert connection.execute(select(model).where(false())).all() == []


@pytest.mark.parametrize("model", IMMUTABLE)
@pytest.mark.parametrize("mutation", (False, True))
def test_actual_limited_role_still_cannot_lock_or_mutate_immutable_metadata(
    restricted, model, mutation
):
    statement = (
        model.__table__.update()
        .where(false())
        .values({model.__table__.primary_key.columns.values()[0]: "unused"})
        if mutation
        else select(model).where(false()).with_for_update(read=True)
    )
    with restricted.connect() as connection, pytest.raises(ProgrammingError) as error:
        connection.execute(statement)
    assert error.value.orig.sqlstate == "42501"


def test_existing_database_triggers_protect_the_pinned_immutable_records(guarded_engine):
    expected = {model.__tablename__ + "_immutable" for model in IMMUTABLE}
    with guarded_engine.connect() as connection:
        found = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger JOIN pg_class ON pg_class.oid=tgrelid "
                    "JOIN pg_namespace ON pg_namespace.oid=relnamespace "
                    "WHERE nspname='app' AND tgname=ANY(:names) AND tgenabled='O'"
                ),
                {"names": sorted(expected)},
            )
        )
    assert found == expected


def test_source_completion_select_locks_need_a_normal_root_not_postgres_read_only(guarded_engine):
    statement = select(JobRecord.job_id).where(false()).with_for_update(read=True)
    with guarded_engine.begin() as connection, pytest.raises(DBAPIError) as error:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(statement)
    assert error.value.orig.sqlstate == "25006"
    with guarded_engine.begin() as connection:
        assert connection.execute(statement).all() == []


def test_actual_savepoint_read_scope_cannot_escape_commit_or_rollback(guarded_engine, monkeypatch):
    # Only the selection carrier is synthetic; transactions and SELECTs are real.
    original = _case(monkeypatch).selection
    selection = type(original).model_validate(
        original.model_dump(mode="json")
        | dict(
            workflow_id="workflow_" + uuid4().hex,
            step_run_id="steprun_" + uuid4().hex,
            plan_id="execplan_" + uuid4().hex,
        )
    )
    with Session(guarded_engine) as session, session.begin():
        outside = capture_creative_proposal_read_set(session, (selection,))
        with session.begin_nested():
            with pytest.raises(ValueError, match="READ_SET_INVALID"):
                outside.for_selection(session, selection)
            inside = capture_creative_proposal_read_set(session, (selection,))
            assert inside.for_selection(session, selection).workflow is None
        with pytest.raises(ValueError, match="READ_SET_INVALID"):
            inside.for_selection(session, selection)
        assert outside.for_selection(session, selection).workflow is None
        savepoint = session.begin_nested()
        rolled_back = capture_creative_proposal_read_set(session, (selection,))
        savepoint.rollback()
        with pytest.raises(ValueError, match="READ_SET_INVALID"):
            rolled_back.for_selection(session, selection)
    with pytest.raises(ValueError, match="READ_SET_INVALID"):
        outside.for_selection(session, selection)
