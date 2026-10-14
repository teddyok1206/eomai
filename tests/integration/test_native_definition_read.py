"""Actual disposable immutable metadata and restricted reads, not source/IAM admission."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_orchestrator.database import build_engine
from eom_workflow.compiler import compile_definition
from eom_workflow_runner.local_embedding_admission import (
    LocalEmbeddingOwnerAdmission,
    resolve_local_embedding_submission_controls,
)
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_local_embedding_runner_admission import scope_fixture

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(autouse=True)
def exact_opt_in():
    if os.environ.get("EOM_RUN_LOCAL_INDEXING_SERVICE_INTEGRATION") != "1":
        pytest.skip("use guarded local-indexing-service-tests; never production")


@pytest.fixture(params=["INDEX", "QUERY"])
def definition(guarded_engine, request):
    name = {
        "INDEX": "local-embedding-index.v1.yaml",
        "QUERY": "local-embedding-reference-query.v1.yaml",
    }[request.param]
    compiled = compile_definition(Path("config/workflows") / name, set())
    with Session(guarded_engine) as session, session.begin():
        record, _created = import_workflow_definition(session, compiled)
        assert record.active is True
        identity = record.definition_id
    return guarded_engine, identity, compiled


@pytest.fixture
def limited(definition):
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    values = dict(line.split("=", 1) for line in (state / "runtime.env").read_text().splitlines())
    url = make_url(values["EOM_API_DATABASE_URL"])
    assert url.username == manifest.runtime_role and url.database == manifest.database
    assert url.drivername == "postgresql+psycopg" and url.host == "127.0.0.1"
    runtime = build_engine(
        url.set(query={"options": "-csearch_path=app,pg_catalog"}).render_as_string(
            hide_password=False
        )
    )
    try:
        yield runtime
    finally:
        runtime.dispose()


def test_actual_restricted_select_succeeds_without_update_or_row_lock(definition, limited):
    _owner, identity, compiled = definition
    with Session(limited) as session, session.begin():
        assert (
            session.scalar(
                text(
                    "SELECT NOT has_table_privilege(SESSION_USER,"
                    "'app.workflow_definitions','UPDATE,DELETE,TRUNCATE')"
                )
            )
            is True
        )
        record = session.scalar(
            select(WorkflowDefinitionRecord)
            .where(WorkflowDefinitionRecord.definition_id == identity)
            .execution_options(populate_existing=True)
        )
        assert record is not None and record.definition_hash == compiled.sha256
        with pytest.raises(DBAPIError) as caught, session.begin_nested():
            session.execute(
                text(
                    "SELECT definition_id FROM app.workflow_definitions "
                    "WHERE definition_id=:id FOR SHARE"
                ),
                {"id": identity},
            )
        assert caught.value.orig.sqlstate == "42501"
        if compiled.definition.definition_key == "local-embedding-index":
            # Only current owner/source IO is synthetic; the native definition
            # application performs its real SQL/compile/hash checks below.
            scope, expected = scope_fixture()
            assert expected.sha256 == compiled.sha256
            owner = Mock(spec=LocalEmbeddingOwnerAdmission)
            owner.resolve_submission.return_value = scope
            actual = resolve_local_embedding_submission_controls(
                session,
                definition=record,
                request=scope.request,
                actor_type="human",
                actor_id=scope.request.actor_context.operator_id,
                owner=owner,
                executor=Mock(spec=LocalEmbeddingNativeExecutor),
            )
            assert actual == scope


@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_actual_even_owner_cannot_mutate_definition_or_active(definition, verb):
    engine, identity, _compiled = definition
    command = (
        "UPDATE app.workflow_definitions SET active=false WHERE definition_id=:id"
        if verb == "UPDATE"
        else "DELETE FROM app.workflow_definitions WHERE definition_id=:id"
    )
    with Session(engine) as session:
        root = session.begin()
        try:
            with pytest.raises(DBAPIError) as caught, session.begin_nested():
                session.execute(text(command), {"id": identity})
            assert caught.value.orig.sqlstate == "P0001"
            assert caught.value.orig.diag.message_primary == "workflow definitions are immutable"
        finally:
            root.rollback()


def test_actual_concurrent_owner_change_fails_while_limited_reader_stays_valid(definition, limited):
    engine, identity, compiled = definition

    def reject_change():
        with Session(engine) as session:
            root = session.begin()
            try:
                session.execute(text("SET LOCAL lock_timeout='250ms'"))
                session.execute(
                    text(
                        "UPDATE app.workflow_definitions SET active=false WHERE definition_id=:id"
                    ),
                    {"id": identity},
                )
            finally:
                root.rollback()

    with Session(limited) as session, session.begin():
        record = session.get(WorkflowDefinitionRecord, identity)
        assert record is not None and record.active is True
        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(DBAPIError) as caught:
            pool.submit(reject_change).result(timeout=5)
        assert caught.value.orig.sqlstate == "P0001"  # immutable, not a lock timeout
        session.refresh(record)
        assert record.active is True and record.definition_hash == compiled.sha256
