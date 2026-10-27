"""Creative Workflow replay/concurrency in the guarded disposable owner DB.

The source authorizer is explicitly synthetic. These tests prove persistence,
not production source permission, page Artifact validity, or worker admission.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_engine
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.repository import create_workflow_instance
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.unit.test_external_item_learning_workflow_admission import (
    OPERATOR,
    OTHER_OPERATOR,
    _definition,
    _owner,
    _request,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def creative_engine():
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh external-item-tests; never production")
    state = validate_state_directory(Path(os.environ["EOM_EXTERNAL_ITEM_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
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


def _unique_request() -> WorkflowRequest:
    value = _request().model_dump(mode="json")
    work = value["external_item_learning_work"]
    work["request_id"] = "extlearnreq_" + uuid4().hex
    work["page_artifact"]["artifact_revision_id"] = "rev_" + uuid4().hex
    work["request_sha256"] = content_sha256(
        {key: item for key, item in work.items() if key != "request_sha256"}
    )
    return WorkflowRequest.model_validate(value)


def _seed(session: Session) -> WorkflowDefinitionRecord:
    candidate = _definition()
    existing = session.get(WorkflowDefinitionRecord, candidate.definition_id)
    if existing is None:
        session.add(candidate)
        session.flush()
        return candidate
    assert existing.canonical_definition == candidate.canonical_definition
    assert existing.definition_hash == candidate.definition_hash
    return existing


def _submit(session: Session, request: WorkflowRequest, key: str, actor: str = OPERATOR):
    return create_workflow_instance(
        session,
        definition=_seed(session),
        request=request,
        idempotency_key=key,
        actor_type="human",
        actor_id=actor,
        external_item_learning_authorizer=_owner(request),
    )


def test_creative_storage_replays_exact_input_and_separates_owners(creative_engine: Engine):
    with creative_engine.connect() as connection, connection.begin() as outer:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            request = _unique_request()
            key = "synthetic-creative-" + uuid4().hex
            first, created = _submit(session, request, key)
            assert created and first.stage == "KNOWLEDGE_ANALYSIS"
            same, created = _submit(session, request, key)
            assert not created and same.workflow_id == first.workflow_id
            active, created = _submit(session, request, key + "-other-key")
            assert not created and active.workflow_id == first.workflow_id
            other, created = _submit(session, request, key + "-other-owner", OTHER_OPERATOR)
            assert created and other.request_hash != first.request_hash
            assert other.created_actor_id == OTHER_OPERATOR
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowEventRecord)
                    .where(WorkflowEventRecord.workflow_id == first.workflow_id)
                )
                == 1
            )
            session.expire_all()
            assert session.get(WorkflowInstanceRecord, first.workflow_id).initial_request == (
                request.model_dump(mode="json", exclude_none=True)
            )
        outer.rollback()


def test_creative_late_authorization_rejection_discards_workflow(creative_engine: Engine):
    request = _unique_request()
    key = "synthetic-creative-revoked-" + uuid4().hex
    with Session(creative_engine) as session:
        owner = _owner(request)
        owner.reauthorize.side_effect = [request.external_item_learning_work.source, ValueError()]
        with pytest.raises(WorkflowError):
            create_workflow_instance(
                session,
                definition=_seed(session),
                request=request,
                idempotency_key=key,
                actor_type="human",
                actor_id=OPERATOR,
                external_item_learning_authorizer=owner,
            )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == key)
            )
            is None
        )


@pytest.mark.parametrize("different_keys", [False, True])
def test_concurrent_creative_submits_preserve_one_workflow_and_event(
    creative_engine: Engine, different_keys: bool
):
    request = _unique_request()
    key = "synthetic-creative-concurrent-" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        _seed(session)
    barrier = Barrier(2)

    def submit(index):
        with Session(creative_engine) as session, session.begin():
            barrier.wait(timeout=10)
            workflow, created = _submit(
                session, request, key + str(index) if different_keys else key
            )
            return workflow.workflow_id, created

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(submit, range(2)))
    assert len({identity for identity, _created in results}) == 1
    assert sum(created for _identity, created in results) == 1
    with Session(creative_engine) as session:
        stored = session.get(WorkflowInstanceRecord, results[0][0])
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.request_hash == stored.request_hash)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == results[0][0])
            )
            == 1
        )
