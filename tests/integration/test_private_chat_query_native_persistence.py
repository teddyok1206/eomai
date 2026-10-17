"""Guarded PostgreSQL private execution composition; not production source/claim authority.

Published controls, registered index, Jobs/events/Artifacts and canonical bytes
are real. Chat/IAM/public population/Workflow views/units/numerics are synthetic.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_private_chat_query_systemd import NativePrivateQueryLaunchError
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from sqlalchemy import func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_query_source_owner import make_owned_private_source
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_native_executor import make_private_executor_case

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def query(registered, guarded_engine, tmp_path, monkeypatch):
    source = make_owned_private_source(
        registered,
        guarded_engine,
        resource_profile=reference_prepared().workflow_request.resource_profile,
    )
    value = make_private_executor_case(tmp_path, monkeypatch, source=source)
    value.workflow.workflow_id = "workflow_" + uuid4().hex
    value.step.workflow_id = value.workflow.workflow_id
    value.step.step_run_id = "steprun_" + uuid4().hex
    return value


def assert_original_producers(value):
    launch, history = value.history()
    assert history.state == "SUCCEEDED" and len(history.records) == 4
    allocation = history.records[0].payload.allocation
    identities = (
        launch.native_launch_job_id,
        allocation.query_producer.job_id,
        allocation.receipt_producer.job_id,
    )
    assert len(set(identities)) == 3
    with value.publisher.sessions.begin() as session:
        jobs = tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.in_(identities))))
        assert len(jobs) == 3 and all(job.status == "SUCCEEDED" for job in jobs)
        revisions = tuple(
            session.scalars(
                select(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id.in_(identities))
            )
        )
        assert len(revisions) == 2
        for job in jobs:
            assert TEXT.encode() not in canonical_json_bytes(job.request)
        for revision in revisions:
            assert TEXT.encode() not in canonical_json_bytes(revision.result)
            assert TEXT.encode() not in canonical_json_bytes(revision.manifest)
    return launch, history


def test_postgres_private_executor_original_history_publication_and_replay(query):
    context = query.workflow.runtime_context.copy()
    output = query.execute()
    assert isinstance(output, PrivateChatQueryStepOutput)
    launch, history = assert_original_producers(query)
    assert query.execute(generation=2) == output
    assert query.history() == (launch, history)
    assert query.encodes == 1 and len(query.runs) == 1
    assert query.workflow.runtime_context == context


@pytest.mark.parametrize(
    "boundary", ["query_before", "query_after", "receipt_before", "receipt_after"]
)
def test_postgres_private_commit_boundary_crash_reuses_original_producers(
    query, monkeypatch, boundary
):
    owner_type = (
        EmbeddingArtifactStore
        if boundary.startswith("query")
        else NativeEmbeddingCompletionPublisher
    )
    method = owner_type.publish_private_chat_query

    def crash(self, *args, **kwargs):
        if boundary.endswith("after"):
            method(self, *args, **kwargs)
        raise KeyboardInterrupt("synthetic owner death; never a new encoding grant")

    with monkeypatch.context() as patch:
        patch.setattr(owner_type, "publish_private_chat_query", crash)
        with pytest.raises(KeyboardInterrupt):
            query.execute()
    launch, before = query.history()
    assert len(before.records) == (2 if boundary.startswith("query") else 3)
    assert isinstance(query.execute(generation=2), PrivateChatQueryStepOutput)
    current_launch, after = assert_original_producers(query)
    assert current_launch == launch and after.records[: len(before.records)] == before.records
    assert query.encodes == 1 and len(query.runs) == 1


def test_postgres_private_history_concurrent_exact_replay_has_one_prefix(query):
    query.execute()
    launch, original = assert_original_producers(query)
    barrier = Barrier(2)

    def replay():
        barrier.wait(timeout=10)
        with query.publisher.sessions.begin() as session:
            coordinator = NativePrivateChatQueryCoordinator(query.request, launch)
            for row in original.records:
                coordinator.append(session, row)
            return coordinator.read(session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(replay), pool.submit(replay))
        assert all(future.result(timeout=30) == original for future in futures)
    assert query.history() == (launch, original) and query.encodes == 1
    assert_original_producers(query)


def test_postgres_private_allocated_root_rollback_preserves_no_launch(query):
    with query.publisher.sessions.begin() as session:
        before = session.scalar(select(func.count()).select_from(JobRecord))
    with pytest.raises(RuntimeError, match="synthetic rollback"), query.root() as session:
        query.service.allocate_execution(
            session=session,
            workflow=query.workflow,
            step=query.step,
            request=query.request,
            command_lease=query.lease(),
        )
        raise RuntimeError("synthetic rollback")
    with query.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == before
    assert not query.runs


def test_postgres_completed_private_query_cannot_outrun_late_public_withdrawal(query):
    query.execute()
    original = assert_original_producers(query)
    query.source.fault.value = "public_during_private_auth"
    with pytest.raises(ValueError, match="SOURCE_REVOKED"):
        query.execute(generation=2)
    assert query.encodes == 1
    assert query.history() == original


def test_postgres_between_requests_withdrawal_has_empty_current_scope_not_a_retained_grant(
    query, registered
):
    output = query.execute()
    registered.fault.value = "source"
    # A query embedding contains only this user's question, not public document
    # content. It may be reused with an empty newly authorized candidate scope.
    assert query.execute(generation=2) == output
    with query.root() as session:
        current = query.owner.resolve_execution_sources(
            session,
            query.request,
            query.lease(2),
            workflow_id=query.workflow.workflow_id,
            step_run_id=query.step.step_run_id,
        )
        assert current.documents.sources == ()
    assert query.encodes == 1


def test_postgres_private_known_failure_stays_failed_and_cannot_reallocate(query):
    query.failure = NativePrivateQueryLaunchError("NATIVE_PRIVATE_QUERY_KNOWN_FAILED")
    with pytest.raises(NativePrivateQueryLaunchError):
        query.execute()
    launch, history = query.history()
    assert history.state == "FAILED" and len(history.records) == 1
    query.failure = None
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_EXECUTOR_TERMINAL_HISTORY"):
        query.execute(generation=2)
    assert query.history() == (launch, history) and query.encodes == 0


def test_postgres_completed_private_read_does_not_need_retired_original_units(query):
    output = query.execute()
    query.launcher.assert_current_runtime.side_effect = OSError("retired original units")
    assert query.execute(generation=2) == output
    assert query.encodes == 1
    assert_original_producers(query)
