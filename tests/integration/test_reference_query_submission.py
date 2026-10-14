"""Actual guarded PostgreSQL and exact admission; IAM/physical executor are synthetic.

No model, NAS, production data or real QUERY activation. Committed synthetic
Workflow/command evidence remains in this disposable DB, never deleted on retry.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier, local
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition_data
from eom_workflow.reference_query_execution import parse_reference_query_workflow_request
from eom_workflow_runner import native_start_command
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.reference_query_admission import (
    ReferenceQueryOwnerAdmission,
    ResolvedReferenceQueryAdmission,
)
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from eom_workflow_runner.reference_query_submission import (
    ReferenceQueryWorkflowSubmitted,
    start_reference_query_in_session,
)
from eom_workflow_runner.repository import (
    CommandType,
    create_workflow_instance,
    enqueue_command,
    import_workflow_definition,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_reference_query_workflow_contracts import definition_body

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@dataclass
class AtomicCase:
    engine: Engine
    definition: WorkflowDefinitionRecord
    scope: ResolvedReferenceQueryAdmission
    owner: Mock
    executor: Mock
    key: str

    def submit(self, session: Session) -> ReferenceQueryWorkflowSubmitted:
        return start_reference_query_in_session(
            session,
            definition=self.definition,
            request=self.scope.request,
            idempotency_key=self.key,
            actor_type="human",
            actor_id=self.scope.request.operator_audit.operator_id,
            owner=self.owner,
            executor=self.executor,
        )

    def workflow(self, session: Session) -> WorkflowInstanceRecord | None:
        return session.scalar(
            select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == self.key)
        )


@pytest.fixture
def atomic(guarded_engine):
    assert guarded_engine.dialect.name == "postgresql"
    assert workflow_definition_is_admitted("local-embedding-reference-query", "1.0.0")
    assert not workflow_definition_is_admitted("local-embedding-reference-query", "1.0.1")
    compiled = compile_definition_data(definition_body(), "synthetic/guarded-query-start", set())
    base = case(definition_sha256=compiled.sha256)
    request = parse_reference_query_workflow_request(
        seal(
            base.request.model_dump(mode="json")
            | {
                "operator_audit": base.request.operator_audit.model_dump(mode="json")
                | {"operator_id": "operator_" + uuid4().hex}
            },
            "request_sha256",
        )
    )
    scope = ResolvedReferenceQueryAdmission(request, base.policy, base.bundle)
    with Session(guarded_engine, expire_on_commit=False) as session, session.begin():
        definition, _created = import_workflow_definition(session, compiled)
    owner = Mock(spec=ReferenceQueryOwnerAdmission)
    executor = Mock(spec=ReferenceQueryNativeExecutor)

    def current(session, request):
        assert session.get_transaction() is not None and request == scope.request
        return scope

    owner.resolve_submission.side_effect = current
    return AtomicCase(
        guarded_engine, definition, scope, owner, executor, "synthetic-atomic-query:" + uuid4().hex
    )


def assert_absent(value):
    with Session(value.engine) as session:
        assert value.workflow(session) is None
    value.executor.execute.assert_not_called()


def test_postgres_atomic_query_replay_keeps_one_workflow_and_start(atomic):
    with Session(atomic.engine, expire_on_commit=False) as session, session.begin():
        first = atomic.submit(session)
        identity = first.workflow.workflow_id, first.command.command_id
        assert first.workflow_created and first.command_created
    with Session(atomic.engine) as session, session.begin():
        repeated = atomic.submit(session)
        assert (repeated.workflow.workflow_id, repeated.command.command_id) == identity
        assert not repeated.workflow_created and not repeated.command_created
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == identity[0])
            )
            == 1
        )
    atomic.executor.execute.assert_not_called()


def test_postgres_late_owner_denial_rolls_back_workflow_and_command(atomic):
    count = 0

    def current(_session, _request):
        nonlocal count
        count += 1
        if count == 4:
            raise ValueError("SYNTHETIC_LATE_OWNER_REVOKED")
        return atomic.scope

    atomic.owner.resolve_submission.side_effect = current
    with (
        pytest.raises(ValueError, match="LATE_OWNER_REVOKED"),
        Session(atomic.engine) as session,
        session.begin(),
    ):
        atomic.submit(session)
    assert count == 4
    assert_absent(atomic)


def test_postgres_queue_failure_rolls_back_the_new_workflow(atomic, monkeypatch):
    monkeypatch.setattr(
        native_start_command,
        "enqueue_command",
        Mock(side_effect=ValueError("SYNTHETIC_QUEUE_FAILED")),
    )
    with (
        pytest.raises(ValueError, match="QUEUE_FAILED"),
        Session(atomic.engine) as session,
        session.begin(),
    ):
        atomic.submit(session)
    assert_absent(atomic)


def test_postgres_concurrent_exact_query_start_returns_original_ids_once(atomic):
    barrier, thread = Barrier(2), local()

    def current(_session, _request):
        if not getattr(thread, "started", False):
            thread.started = True
            barrier.wait(timeout=10)
        return atomic.scope

    atomic.owner.resolve_submission.side_effect = current

    def submit(_ordinal):
        with Session(atomic.engine) as session, session.begin():
            session.connection().exec_driver_sql("SET LOCAL lock_timeout='10s'")
            result = atomic.submit(session)
            return result.workflow.workflow_id, result.command.command_id, result.workflow_created

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(submit, (0, 1)))
    assert first[:2] == second[:2] and sum((first[2], second[2])) == 1
    with Session(atomic.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == first[0])
            )
            == 1
        )
    atomic.executor.execute.assert_not_called()


@pytest.mark.parametrize("command", (False, True))
def test_postgres_incomplete_or_wrong_source_history_is_not_repaired(atomic, command):
    # Supported repository creation deliberately preserves this incomplete synthetic history.
    with Session(atomic.engine, expire_on_commit=False) as session, session.begin():
        workflow, created = create_workflow_instance(
            session,
            definition=atomic.definition,
            request=atomic.scope.request,
            idempotency_key=atomic.key,
            actor_type="human",
            actor_id=atomic.scope.request.operator_audit.operator_id,
            reference_query_owner=atomic.owner,
            reference_query_executor=atomic.executor,
        )
        assert created
        if command:
            enqueue_command(
                session,
                workflow_id=workflow.workflow_id,
                command_type=CommandType.START_WORKFLOW,
                payload={},
                actor_type="human",
                actor_id=workflow.created_actor_id,
                source="synthetic-wrong-source",
                idempotency_key=f"start:{workflow.workflow_id}",
            )
    with (
        pytest.raises(ValueError, match="REFERENCE_QUERY_SUBMISSION_REPLAY_INVALID"),
        Session(atomic.engine) as session,
        session.begin(),
    ):
        atomic.submit(session)
    with Session(atomic.engine) as session:
        assert atomic.workflow(session).workflow_id == workflow.workflow_id
        commands = tuple(
            session.scalars(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == workflow.workflow_id
                )
            )
        )
        assert len(commands) == int(command)
        assert not commands or commands[0].source == "synthetic-wrong-source"
