"""Guarded PostgreSQL scheduling metadata only; all state injection is disposable fixture data."""

from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_workflow.local_embedding_request import local_embedding_request_actor
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.local_embedding_submission import start_local_embedding_in_session
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.native_cpu_scheduling_read import (
    active_reference_query_command_exists,
    should_defer_background_cpu_claim,
)
from eom_workflow_runner.repository import import_workflow_definition
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from tests.integration.test_local_embedding_runner import SyntheticOwner
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_reference_query_submission import (
    prepare_query,
)
from tests.integration.test_reference_query_submission import (
    prepared_query as prepared_query,
)
from tests.unit.test_local_embedding_runner_admission import scope_fixture

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def leased_query(prepared_query, request):
    value = prepared_query
    assert not should_defer_background_cpu_claim(value.engine), "run first in a fresh guarded DB"
    with Session(value.engine) as session, session.begin():
        if (
            getattr(request.node, "callspec", None) is not None
            and request.node.callspec.params.get("fault") == "other_family"
        ):
            scope, compiled = scope_fixture()
            definition, _ = import_workflow_definition(session, compiled)
            actor_type, actor_id = local_embedding_request_actor(scope.request)
            submitted = start_local_embedding_in_session(
                session,
                definition=definition,
                request=scope.request,
                idempotency_key="priority-index-fixture:" + uuid4().hex,
                actor_type=actor_type,
                actor_id=actor_id,
                owner=SyntheticOwner(scope),
                executor=Mock(spec=LocalEmbeddingNativeExecutor),
            )
        else:
            submitted = prepare_query(value, session)
        workflow, command = submitted.workflow, submitted.command
        workflow.state = "RUNNING"
        workflow.stage = "LOCAL_EMBEDDING"
        command.state = "PROCESSING"
        command.attempts = command.lease_generation = 1
        command.lease_owner = "synthetic-priority-owner"
        command.lease_token = "lease_" + uuid4().hex
        command.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        identity = workflow.workflow_id, command.command_id
    try:
        yield value, identity
    finally:
        # Fixture teardown in this marker-guarded disposable DB only, never runtime repair.
        with Session(value.engine) as session, session.begin():
            session.get(WorkflowCommandRecord, identity[1]).state = "CANCELLED"
            session.get(WorkflowInstanceRecord, identity[0]).state = "CANCELLED"


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "leased",
        "pending",
        "succeeded",
        "failed",
        "cancelled",
        "expired",
        "missing_token",
        "missing_owner",
        "zero_generation",
        "zero_attempts",
        "actor_mismatch",
        "terminal_workflow",
        "other_family",
        "other_stage",
        "service_actor",
    ],
)
def test_actual_read_only_exists_distinguishes_current_work_from_history(leased_query, fault):
    value, (wid, cid) = leased_query
    with Session(value.engine) as session, session.begin():
        command = session.get(WorkflowCommandRecord, cid)
        workflow = session.get(WorkflowInstanceRecord, wid)
        if fault in {"leased", "pending", "succeeded", "failed", "cancelled"}:
            command.state = fault.upper()
        elif fault == "expired":
            command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif fault == "missing_token":
            command.lease_token = None
        elif fault == "missing_owner":
            command.lease_owner = None
        elif fault == "zero_generation":
            command.lease_generation = 0
        elif fault == "zero_attempts":
            command.attempts = 0
        elif fault == "actor_mismatch":
            command.actor_id = "operator_" + "f" * 32
        elif fault == "terminal_workflow":
            workflow.state = "COMPLETED"
        elif fault == "other_stage":
            workflow.stage = "AUTHORING"
        elif fault == "service_actor":
            command.actor_type = workflow.created_actor_type = "local_indexing_service"
    expected = fault in {"none", "leased"}
    assert should_defer_background_cpu_claim(value.engine) is expected
    with Session(value.engine) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert active_reference_query_command_exists(session) is expected


def test_uncommitted_completion_does_not_block_read_and_next_snapshot_sees_commit(leased_query):
    value, (_wid, cid) = leased_query
    changed, release = Event(), Event()

    def writer():
        with Session(value.engine) as session, session.begin():
            session.get(WorkflowCommandRecord, cid).state = "SUCCEEDED"
            session.flush()
            changed.set()
            assert release.wait(10)

    thread = Thread(target=writer)
    thread.start()
    try:
        assert changed.wait(10)
        assert should_defer_background_cpu_claim(value.engine) is True
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert should_defer_background_cpu_claim(value.engine) is False


def test_synthetic_terminal_history_uses_existing_claimable_index(leased_query):
    value, (wid, _cid) = leased_query
    with Session(value.engine) as session, session.begin():
        original = session.get(WorkflowInstanceRecord, wid)
        session.execute(
            insert(WorkflowCommandRecord),
            [
                {
                    "command_id": "wfcmd_" + uuid4().hex,
                    "workflow_id": wid,
                    "command_type": "ADVANCE_WORKFLOW",
                    "payload": {},
                    "actor_type": "human",
                    "actor_id": original.created_actor_id,
                    "source": "synthetic-priority-plan",
                    "idempotency_key": "priority-plan:" + uuid4().hex,
                    "request_hash": "sha256:" + "1" * 64,
                    "state": "SUCCEEDED",
                    "attempts": 1,
                }
                for _ in range(10000)
            ],
        )
        session.execute(text("ANALYZE app.workflow_commands"))
        statements = []

        class Capture:
            def scalar(self, statement):
                statements.append(statement)
                return True

        assert active_reference_query_command_exists(Capture())
        sql = str(
            statements[0].compile(
                dialect=value.engine.dialect, compile_kwargs={"literal_binds": True}
            )
        )
        document = session.execute(text("EXPLAIN (ANALYZE, FORMAT JSON) " + sql)).scalar_one()
        nodes = [document[0]["Plan"]]
        indexes = set()
        while nodes:
            node = nodes.pop()
            indexes.add(node.get("Index Name"))
            nodes.extend(node.get("Plans", ()))
        assert "ix_workflow_commands_claimable" in indexes
        assert should_defer_background_cpu_claim(value.engine) is True
