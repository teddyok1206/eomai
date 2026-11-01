"""Disposable PG source/lease/concurrency checks; Chat/IAM/public documents are fake ports.

Real current command and original Job/launch rows are used, not physical GPU proof.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
    PrivateChatQueryBatchSource,
)
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.private_chat_query_source_read import (
    build_private_chat_public_query_native_input,
)
from sqlalchemy import func, select

from tests.integration.test_private_chat_public_query_owner_admission import (
    declared as declared,
)
from tests.integration.test_private_chat_public_query_owner_admission import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_public_query_owner_admission import (
    live_lease,
)
from tests.unit.test_private_chat_public_query_owner_admission import declare_original_allocation
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_batch_source import private_batch_for, private_binding
from tests.unit.test_private_chat_query_workflow import completed as completed

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def authorized(declared, public_completed, monkeypatch):
    launch = declare_original_allocation(declared, public_completed)
    lease = live_lease(declared)
    publisher = declared.source.publisher
    state = SimpleNamespace(deny_operator=False, expire_late=False, identity_calls=0)

    def identity(session, actor):
        assert session.get_bind() is publisher.engine and session.get_transaction().is_active
        assert actor == declared.request.operator_audit.operator_id
        state.identity_calls += 1
        if state.deny_operator:
            raise PermissionError("SYNTHETIC_CURRENT_OPERATOR_REVOKED")
        if state.expire_late:
            command = session.get(WorkflowCommandRecord, lease.command_id)
            command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.flush()

    monkeypatch.setattr(
        declared.owner.sources,
        "identity",
        SimpleNamespace(fence_current_operator=identity),
        raising=False,
    )

    @contextmanager
    def transaction():
        with publisher.sessions.begin() as session:
            yield session

    with transaction() as session:
        resolved = declared.owner.resolve_execution_sources(
            session,
            declared.request,
            lease,
            workflow_id=launch.workflow_id,
            step_run_id=launch.step_run_id,
        )
        history = NativePrivateChatQueryCoordinator(declared.request, launch).read(session)
    native = build_private_chat_public_query_native_input(
        resolved, job_id=launch.native_launch_job_id, query_request_id=launch.query_request_id
    )
    batch = private_batch_for(native, declared.request)
    source = PrivateChatQueryBatchSource(
        declared.owner, declared.request, launch, lease, transaction
    )
    fence = CatalogEmbeddingBatchSourceAuthorization(batch, (source,))
    return SimpleNamespace(
        declared=declared,
        publisher=publisher,
        state=state,
        lease=lease,
        request=declared.request,
        launch=launch,
        native=native,
        batch=batch,
        source=source,
        fence=fence,
        history=history,
    )


def assert_original(authorized):
    with authorized.publisher.sessions.begin() as session:
        assert (
            NativePrivateChatQueryCoordinator(authorized.request, authorized.launch).read(session)
            == authorized.history
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.job_id == authorized.launch.native_launch_job_id)
            )
            == 1
        )
        command = session.get(WorkflowCommandRecord, authorized.lease.command_id)
        assert (
            command.state == "PROCESSING"
            and command.lease_generation == authorized.lease.lease_generation
        )
        return command.lease_expires_at


def test_postgres_concurrent_private_batch_fences_preserve_original_launch_and_history(authorized):
    barrier = Barrier(2)

    def authorize():
        barrier.wait(timeout=15)
        authorized.fence.authorize_batch()
        authorized.fence.authorize_binding(private_binding(authorized))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(authorize) for _ in range(2)]
        for future in futures:
            future.result(timeout=45)
    assert authorized.state.identity_calls == 4
    assert_original(authorized)


@pytest.mark.parametrize("fault", ("source", "operator", "late_lease"))
def test_postgres_private_batch_current_revocation_never_creates_work_or_repairs_history(
    authorized, fault
):
    authorized.fence.authorize_batch()
    deadline = assert_original(authorized)
    if fault == "source":
        authorized.declared.source.fault.value = "deny"
    elif fault == "operator":
        authorized.state.deny_operator = True
    else:
        authorized.state.expire_late = True
    with pytest.raises((ValueError, RuntimeError, PermissionError)):
        authorized.fence.authorize_batch()
    assert assert_original(authorized) == deadline


def test_postgres_private_batch_expired_lease_stays_expired_without_retry_or_success_rewrite(
    authorized,
):
    with authorized.publisher.sessions.begin() as session:
        command = session.get(WorkflowCommandRecord, authorized.lease.command_id)
        command.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    before = assert_original(authorized)
    with pytest.raises(RuntimeError):
        authorized.fence.authorize_batch()
    assert assert_original(authorized) == before and before < datetime.now(UTC)


def test_postgres_failed_private_native_history_is_preserved_not_retried(authorized):
    with authorized.publisher.sessions.begin() as session:
        coordinator = NativePrivateChatQueryCoordinator(authorized.request, authorized.launch)
        authorized.history = coordinator.record_known_failure(session)
        assert authorized.history.state == "FAILED"
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_SOURCE_AUTHORIZATION_INVALID"):
        authorized.fence.authorize_batch()
    assert_original(authorized)
