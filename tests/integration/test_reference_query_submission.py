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
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
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


@pytest.fixture
def prepared_query(guarded_engine, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
    from eom_operator_identity import PermissionKey
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
    from eom_orchestrator.settings import Settings
    from eom_workflow_runner import reference_query_preparation

    from tests.unit.test_reference_query_owner_admission import make_source_case

    (tmp_path / "artifacts").mkdir(mode=0o700)
    (tmp_path / "workspace").mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging",
            nas_artifact_root=tmp_path / "artifacts",
            workspace_root=tmp_path / "workspace",
        ),
    )
    value = make_source_case(tmp_path, monkeypatch, publisher=publisher, control_seed=uuid4().hex)
    compiled = compile_definition_data(definition_body(), "synthetic/query-preparation", set())
    with Session(guarded_engine) as session, session.begin():
        import_workflow_definition(session, compiled)
    monkeypatch.setattr(
        reference_query_preparation,
        "effective_permissions",
        lambda *_: frozenset({PermissionKey.WORKFLOW_START}),
    )
    return SimpleNamespace(
        source=value,
        engine=guarded_engine,
        caller=EmbeddingRegistryCaller(value.request.operator_audit.operator_id),
        context=value.request.context_request,
        executor=Mock(spec=ReferenceQueryNativeExecutor),
        key="synthetic-prepared-query:" + uuid4().hex,
    )


def prepare_query(value, session):
    from eom_workflow_runner.reference_query_preparation import (
        prepare_and_start_reference_query_in_session,
    )

    return prepare_and_start_reference_query_in_session(
        session,
        caller=value.caller,
        context=value.context,
        idempotency_key=value.key,
        owner=value.source.owner,
        executor=value.executor,
    )


def test_postgres_preparation_uses_canonical_controls_and_original_workflow_start(
    prepared_query, monkeypatch
):
    from eom_workflow_runner import reference_query_preparation as preparation

    value = prepared_query
    with Session(value.engine, expire_on_commit=False) as session, session.begin():
        submitted = prepare_query(value, session)
        identity = submitted.workflow.workflow_id, submitted.command.command_id
        original = submitted.workflow.initial_request
        assert submitted.workflow_created and submitted.command_created
        assert original["context_request"] == value.context.model_dump(mode="json")
    for name in ("effective_permissions", "read_pinned_reference_query_controls"):
        monkeypatch.setattr(
            preparation, name, Mock(side_effect=AssertionError("rebuilding original request"))
        )
    with Session(value.engine) as session, session.begin():
        replay = prepare_query(value, session)
        assert (replay.workflow.workflow_id, replay.command.command_id) == identity
        assert replay.workflow.initial_request == original
        assert not replay.workflow_created and not replay.command_created
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


@pytest.mark.parametrize("when", (1, 4))
def test_postgres_preparation_preserves_full_root_rollback_on_current_denial(
    prepared_query, monkeypatch, when
):
    value = prepared_query
    current = value.source.owner.resolve_submission
    observed = 0

    def revoke(session, request):
        nonlocal observed
        observed += 1
        if observed == when:
            value.source.deny = True
        return current(session, request)

    monkeypatch.setattr(value.source.owner, "resolve_submission", revoke)
    with Session(value.engine) as session, pytest.raises(ValueError), session.begin():
        prepare_query(value, session)
    with Session(value.engine) as session:
        assert not session.scalar(
            select(WorkflowInstanceRecord.workflow_id).where(
                WorkflowInstanceRecord.idempotency_key == value.key
            )
        )
    assert observed == when
    value.executor.execute.assert_not_called()


def test_postgres_preparation_rejects_changed_context_without_another_workflow(prepared_query):
    from eom_catalog_contracts.similarity_context import parse_similarity_context_request

    value = prepared_query
    with Session(value.engine, expire_on_commit=False) as session, session.begin():
        first = prepare_query(value, session)
        workflow_id = first.workflow.workflow_id
    value.context = parse_similarity_context_request(
        seal(
            value.context.model_dump(mode="json") | {"top_k": value.context.top_k + 1},
            "request_sha256",
        )
    )
    with (
        Session(value.engine) as session,
        session.begin(),
        pytest.raises(ValueError, match="REFERENCE_QUERY_PREPARATION_REPLAY_MISMATCH"),
    ):
        prepare_query(value, session)
    with Session(value.engine) as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord.workflow_id).where(
                    WorkflowInstanceRecord.idempotency_key == value.key
                )
            )
            == workflow_id
        )
        assert (
            len(
                tuple(
                    session.scalars(
                        select(WorkflowCommandRecord).where(
                            WorkflowCommandRecord.workflow_id == workflow_id
                        )
                    )
                )
            )
            == 1
        )


def test_postgres_concurrent_preparation_reuses_one_original_workflow_and_start(
    prepared_query, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from eom_workflow_runner import reference_query_preparation as preparation

    value = prepared_query
    both_first_reads = Barrier(2)
    read = preparation.read_pinned_reference_query_controls

    def concurrent_controls(*args):
        controls = read(*args)
        both_first_reads.wait(timeout=10)
        return controls

    monkeypatch.setattr(preparation, "read_pinned_reference_query_controls", concurrent_controls)

    def submit():
        with Session(value.engine, expire_on_commit=False) as session, session.begin():
            result = prepare_query(value, session)
            return (
                result.workflow.workflow_id,
                result.command.command_id,
                result.workflow_created,
                result.command_created,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(pool.submit(submit) for _ in range(2))
        outcomes = tuple(future.result(timeout=30) for future in futures)
    assert outcomes[0][:2] == outcomes[1][:2]
    assert sorted(outcome[2:] for outcome in outcomes) == [(False, False), (True, True)]
    with Session(value.engine) as session:
        workflows = tuple(
            session.scalars(
                select(WorkflowInstanceRecord).where(
                    WorkflowInstanceRecord.idempotency_key == value.key
                )
            )
        )
        commands = tuple(
            session.scalars(
                select(WorkflowCommandRecord).where(
                    WorkflowCommandRecord.workflow_id == outcomes[0][0]
                )
            )
        )
        assert len(workflows) == len(commands) == 1
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


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
        # Retain the actual Catalog root-only guard; do not mock away transaction depth.
        CatalogEmbeddingRegistryVerifier._require_similarity_root(session)
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


@pytest.mark.parametrize("when", (2, 3, 4))
def test_postgres_caught_owner_denial_still_discards_entire_submission_root(atomic, when):
    count = 0
    roots = []

    def current(session, request):
        nonlocal count
        CatalogEmbeddingRegistryVerifier._require_similarity_root(session)
        assert request == atomic.scope.request
        roots.append(session.get_transaction())
        count += 1
        if count == when:
            raise ValueError("SYNTHETIC_CAUGHT_OWNER_DENIAL")
        return atomic.scope

    atomic.owner.resolve_submission.side_effect = current
    with Session(atomic.engine) as session, session.begin():
        with pytest.raises(ValueError, match="CAUGHT_OWNER_DENIAL"):
            atomic.submit(session)
        assert not session.in_transaction()
    assert count == when and all(root is roots[0] for root in roots)
    assert_absent(atomic)


def test_postgres_caught_queue_failure_discards_released_workflow_savepoint(atomic, monkeypatch):
    monkeypatch.setattr(
        native_start_command,
        "enqueue_command",
        Mock(side_effect=ValueError("SYNTHETIC_CAUGHT_QUEUE_FAILURE")),
    )
    with Session(atomic.engine) as session, session.begin():
        with pytest.raises(ValueError, match="CAUGHT_QUEUE_FAILURE"):
            atomic.submit(session)
        assert not session.in_transaction()
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
        CatalogEmbeddingRegistryVerifier._require_similarity_root(_session)
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
