"""Opt-in exact claims in the official guarded disposable DB, never production.

Synthetic owner/executor callbacks below are NOT actual authority or runtime admission.
Committed synthetic claim rows remain in this disposable database until the root's
guarded whole-database cleanup, so independent-process locking is real and no history
is deleted or marked successful for convenience. No Job, NAS, model or GPU is used.
"""

from __future__ import annotations

import multiprocessing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_orchestrator.database import build_engine, build_session_factory
from eom_workflow.compiler import compile_definition
from eom_workflow.local_embedding_request import LocalEmbeddingWorkflowRequestV11
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.local_embedding_submission import (
    LocalEmbeddingWorkflowSubmitted,
    start_local_embedding_in_session,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandCandidate,
    CommandExecutionFamily,
    CommandLeaseIdentity,
    claim_command_candidate,
    claim_next_command,
    claimable_command_exists,
    import_workflow_definition,
    peek_command_candidate,
    workflow_requires_local_embedding,
)
from sqlalchemy import Connection, Engine, event, select
from sqlalchemy.engine import ExecutionContext
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_local_embedding_runner_admission import scope_fixture

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@dataclass
class SyntheticOwner:
    """Source callback spy; DB concurrency is actual but permission is not evaluated."""

    scope: ResolvedLocalEmbeddingAdmission
    late_denied: bool = False

    def resolve_submission(
        self, session: Session, request: LocalEmbeddingWorkflowRequestV11
    ) -> ResolvedLocalEmbeddingAdmission:
        assert session.get_transaction() is not None and request == self.scope.request
        return self.scope

    def resolve_claim(
        self,
        session: Session,
        *,
        command: WorkflowCommandRecord,
        workflow: WorkflowInstanceRecord,
        request: LocalEmbeddingWorkflowRequestV11,
    ) -> ResolvedLocalEmbeddingAdmission:
        assert session.get_transaction() is not None and request == self.scope.request
        assert command.workflow_id == workflow.workflow_id
        if command.state != "PENDING":
            raise WorkflowError(
                WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
                "synthetic owner has no linked recovery admission",
            )
        return self.scope

    def fence_mutation(
        self,
        session: Session,
        request: LocalEmbeddingWorkflowRequestV11,
        lease: CommandLeaseIdentity,
    ) -> None:
        assert session.get_transaction() is not None and request == self.scope.request
        assert lease.lease_generation >= 1
        if self.late_denied:
            raise WorkflowError(
                WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE, "synthetic late owner revoked"
            )


@dataclass(frozen=True)
class ClaimFixture:
    engine: Engine
    sessions: sessionmaker[Session]
    owner: SyntheticOwner
    executor: LocalEmbeddingNativeExecutor
    workflow_id: str
    command_id: str

    def peek(self) -> CommandCandidate:
        with self.sessions() as session:
            candidate = peek_command_candidate(
                session,
                family=CommandExecutionFamily.LOCAL_EMBEDDING,
                workflow_id=self.workflow_id,
            )
        assert candidate is not None
        return candidate

    def claim(self, session: Session, candidate: CommandCandidate) -> WorkflowCommandRecord | None:
        return claim_command_candidate(
            session,
            candidate,
            runner_id="synthetic-guarded-native",
            lease_seconds=60,
            local_embedding_owner=self.owner,
            local_embedding_executor=self.executor,
        )


@pytest.fixture
def claim_fixture(stage_owner_connection: Connection) -> ClaimFixture:
    engine = stage_owner_connection.engine
    sessions = build_session_factory(engine)
    scope, compiled = scope_fixture()
    actor_id = "operator_" + uuid4().hex
    body = scope.request.model_dump(mode="json")
    body["actor_context"]["operator_id"] = actor_id
    request = LocalEmbeddingWorkflowRequestV11.model_validate(seal(body, "request_sha256"))
    scope = ResolvedLocalEmbeddingAdmission(request, scope.plan, scope.policy)
    owner = SyntheticOwner(scope)
    executor = cast(LocalEmbeddingNativeExecutor, Mock(spec=LocalEmbeddingNativeExecutor))
    with sessions.begin() as session:
        definition, _created = import_workflow_definition(session, compiled)
        submitted = start_local_embedding_in_session(
            session,
            definition=definition,
            request=request,
            idempotency_key="synthetic-guarded-native:" + uuid4().hex,
            actor_type="human",
            actor_id=actor_id,
            owner=owner,
            executor=executor,
        )
        assert isinstance(submitted, LocalEmbeddingWorkflowSubmitted)
        workflow_id, command_id = submitted.workflow.workflow_id, submitted.command.command_id
    return ClaimFixture(engine, sessions, owner, executor, workflow_id, command_id)


def test_actual_native_exact_claim_refresh_and_generation(claim_fixture: ClaimFixture) -> None:
    candidate = claim_fixture.peek()
    with claim_fixture.sessions.begin() as session:
        command = claim_fixture.claim(session, candidate)
        assert command is not None and command.command_id == candidate.command_id
        assert command.state == "LEASED" and command.lease_generation == command.attempts == 1
    with claim_fixture.sessions.begin() as session:
        assert claim_fixture.claim(session, candidate) is None


def test_actual_legacy_claim_cannot_bypass_native_owner(claim_fixture: ClaimFixture) -> None:
    with claim_fixture.sessions.begin() as session:
        assert not claimable_command_exists(session, workflow_id=claim_fixture.workflow_id)
        assert (
            claim_next_command(
                session,
                runner_id="legacy-cannot-bypass",
                lease_seconds=60,
                workflow_id=claim_fixture.workflow_id,
            )
            is None
        )
    assert claim_fixture.peek().lease_generation == 0


def test_actual_late_revocation_rolls_back_new_generation(claim_fixture: ClaimFixture) -> None:
    candidate = claim_fixture.peek()
    claim_fixture.owner.late_denied = True
    with pytest.raises(WorkflowError), claim_fixture.sessions.begin() as session:
        claim_fixture.claim(session, candidate)
    after = claim_fixture.peek()
    assert after == candidate and after.lease_generation == after.attempts == 0


def test_actual_identity_map_stale_candidate_is_refreshed(claim_fixture: ClaimFixture) -> None:
    candidate = claim_fixture.peek()
    with claim_fixture.sessions.begin() as stale:
        old = stale.get(WorkflowInstanceRecord, claim_fixture.workflow_id)
        assert old is not None
        with claim_fixture.sessions.begin() as mutation:
            current = mutation.get(WorkflowInstanceRecord, claim_fixture.workflow_id)
            assert current is not None
            current.lock_version += 1
        assert old.lock_version == candidate.workflow_lock_version
        assert claim_fixture.claim(stale, candidate) is None
        assert old.lock_version == candidate.workflow_lock_version + 1
    assert claim_fixture.peek().lease_generation == 0


def test_actual_held_workflow_lock_does_not_claim_other_command(
    claim_fixture: ClaimFixture,
) -> None:
    candidate = claim_fixture.peek()
    with claim_fixture.sessions.begin() as locker:
        locker.scalar(
            select(WorkflowInstanceRecord)
            .where(WorkflowInstanceRecord.workflow_id == claim_fixture.workflow_id)
            .with_for_update()
        )
        with claim_fixture.sessions.begin() as contender:
            assert claim_fixture.claim(contender, candidate) is None
    assert claim_fixture.peek().lease_generation == 0


def _claim_child(
    url: str,
    candidate: CommandCandidate,
    scope: ResolvedLocalEmbeddingAdmission,
    queue: Any,
    barrier: Any,
) -> None:
    engine = build_engine(url)
    sessions = build_session_factory(engine)
    try:
        barrier.wait(timeout=20)
        with sessions.begin() as session:
            command = claim_command_candidate(
                session,
                candidate,
                runner_id="synthetic-native-child-" + uuid4().hex,
                lease_seconds=60,
                local_embedding_owner=SyntheticOwner(scope),
                local_embedding_executor=cast(
                    LocalEmbeddingNativeExecutor, Mock(spec=LocalEmbeddingNativeExecutor)
                ),
            )
            queue.put(command.command_id if command is not None else None)
    finally:
        engine.dispose()


def test_actual_independent_processes_claim_once(claim_fixture: ClaimFixture) -> None:
    candidate = claim_fixture.peek()
    context = multiprocessing.get_context("spawn")
    queue, barrier = context.Queue(), context.Barrier(2)
    children = [
        context.Process(
            target=_claim_child,
            args=(
                claim_fixture.engine.url.render_as_string(hide_password=False),
                candidate,
                claim_fixture.owner.scope,
                queue,
                barrier,
            ),
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            child.start()
        results = [queue.get(timeout=40) for _ in children]
        for child in children:
            child.join(timeout=10)
            assert child.exitcode == 0
        assert results.count(candidate.command_id) == results.count(None) == 1
        with claim_fixture.sessions() as session:
            command = session.get(WorkflowCommandRecord, candidate.command_id)
            assert command is not None and command.lease_generation == command.attempts == 1
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        queue.close()


def test_actual_expired_native_command_cannot_restart_without_recovery(
    claim_fixture: ClaimFixture,
) -> None:
    candidate = claim_fixture.peek()
    with claim_fixture.sessions.begin() as session:
        command = claim_fixture.claim(session, candidate)
        assert command is not None
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    expired = claim_fixture.peek()
    with pytest.raises(WorkflowError), claim_fixture.sessions.begin() as session:
        claim_fixture.claim(session, expired)
    assert claim_fixture.peek() == expired


def test_actual_peek_one_statement_per_family_and_query_plan(claim_fixture: ClaimFixture) -> None:
    statements: list[tuple[str, Any]] = []

    def capture(
        _connection: Connection,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: ExecutionContext,
        _many: bool,
    ) -> None:
        statements.append((statement, parameters))

    event.listen(claim_fixture.engine, "before_cursor_execute", capture)
    try:
        with claim_fixture.sessions() as session:
            for family in CommandExecutionFamily:
                before = len(statements)
                peek_command_candidate(
                    session, family=family, workflow_id=claim_fixture.workflow_id
                )
                assert len(statements) == before + 1
    finally:
        event.remove(claim_fixture.engine, "before_cursor_execute", capture)
    assert len(statements) == len(CommandExecutionFamily)
    with claim_fixture.engine.connect() as connection:
        for statement, parameters in statements:
            plan = connection.exec_driver_sql(
                "EXPLAIN (FORMAT JSON) " + statement, parameters
            ).scalar_one()
            assert plan[0]["Plan"]["Node Type"] == "Limit"
            assert "workflow_events" not in statement and "LIMIT" in statement
        names = set(
            connection.exec_driver_sql(
                "SELECT indexname FROM pg_indexes WHERE schemaname='app' "
                "AND tablename IN ('workflow_commands','workflow_step_runs')"
            ).scalars()
        )
        assert {"ix_workflow_commands_claimable", "ix_workflow_step_runs_workflow_id"} <= names


@pytest.mark.parametrize("marker", ["related_definition", "related_step"])
def test_actual_malformed_native_relation_blocks_unleased_legacy_reconcile(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    sessions = build_session_factory(stage_owner_connection.engine)
    roles = {"authoring", "review", "image", "item_management", "support"}
    compiled = compile_definition(
        Path("config/workflows/generic-item-development.v1.2.yaml"), roles
    )
    identity = uuid4().hex
    definition_id, workflow_id = "wfdef_" + identity, "workflow_" + identity
    with sessions.begin() as session:
        session.add(
            WorkflowDefinitionRecord(
                definition_id=definition_id,
                definition_key="local-embedding-index"
                if marker == "related_definition"
                else "synthetic-malformed-parent-" + identity[:8],
                definition_version="synthetic-" + identity[:8],
                schema_version=compiled.definition.schema_version,
                canonical_definition=compiled.as_dict(),
                definition_hash=compiled.sha256,
                active=False,
                source_path=compiled.source_path,
            )
        )
        session.flush()
        session.add(
            WorkflowInstanceRecord(
                workflow_id=workflow_id,
                definition_id=definition_id,
                definition_key=compiled.definition.definition_key,
                definition_version=compiled.definition.definition_version,
                definition_hash=compiled.sha256,
                protocol_version="1.0.1",
                role_schema_version="1.0",
                state="RUNNING",
                stage="AUTHORING",
                current_step_key=compiled.definition.start_step,
                request_payload={"schema_version": "1.0"},
                initial_request={"schema_version": "1.0"},
                runtime_context={},
                idempotency_key="synthetic-malformed-native-relation:" + identity,
                request_hash="sha256:" + identity * 2,
                lock_version=1,
                rework_cycle_count=0,
                created_actor_type="human",
                created_actor_id="synthetic-malformed-native-relation",
            )
        )
        session.flush()
        if marker == "related_step":
            session.add(
                WorkflowStepRunRecord(
                    step_run_id="steprun_" + identity,
                    workflow_id=workflow_id,
                    step_key="encode_batch",
                    attempt=1,
                    step_type="application",
                    worker_role=None,
                    result_schema="incremental-embedding-result@1.0",
                    state="RUNNING",
                    input_pointer_manifest={},
                )
            )
    with sessions() as session:
        assert workflow_requires_local_embedding(session, workflow_id=workflow_id) is True
    runner = object.__new__(WorkflowRunner)
    runner.sessions = sessions
    runner.available_roles = frozenset(roles)
    monkeypatch.setattr(
        runner, "_require_runtime_ready", lambda: pytest.fail("legacy readiness called")
    )
    monkeypatch.setattr(
        runner, "_advance", lambda *_args: pytest.fail("unleased legacy advance called")
    )
    with pytest.raises(WorkflowError) as failure:
        runner.reconcile(workflow_id)
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
