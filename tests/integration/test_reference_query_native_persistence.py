"""Opt-in disposable PostgreSQL QUERY Job/Artifact transactions, never live authority.

Current IAM/Workflow SQL and numerical observations remain explicit synthetic
seams. The existing marker/owner/schema/head guard is mandatory for all writes.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.settings import Settings
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.reference_query_execution import ReferenceQueryStepOutput
from sqlalchemy import Engine, func, select

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_reference_query_consumer_read import make_completed_read_case, read
from tests.unit.test_reference_query_native_executor import ExecutorCase, make_executor_case

pytestmark = pytest.mark.integration


@pytest.fixture
def query(guarded_engine: Engine, tmp_path: Path, monkeypatch) -> ExecutorCase:
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    artifacts, workspace = tmp_path / "artifacts", tmp_path / "workspace"
    artifacts.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging", nas_artifact_root=artifacts, workspace_root=workspace
        ),
    )
    value = make_executor_case(tmp_path, monkeypatch, publisher=publisher)
    # The shared disposable DB retains prior tests; every context is a new identity.
    value.workflow.workflow_id, value.step.step_run_id = (
        "workflow_" + uuid4().hex,
        "steprun_" + uuid4().hex,
    )
    return value


def assert_exact_completed_producers(value: ExecutorCase) -> None:
    history = value.history()
    assert history.state == "SUCCEEDED" and len(history.records) == 4
    allocation = history.records[0].payload
    assert isinstance(allocation, NativeQueryAllocation)
    ids = (
        history.launch.native_launch_job_id,
        allocation.query_producer.job_id,
        allocation.receipt_producer.job_id,
    )
    with value.publisher.sessions.begin() as session:
        jobs = tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.in_(ids))))
        assert len(jobs) == 3 and all(job.status == "SUCCEEDED" for job in jobs)
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.job_id.in_(ids))
            )
            == 2
        )


def test_postgres_query_checkpoint_commit_receipt_and_exact_replay(query):
    output = query.execute()
    assert isinstance(output, ReferenceQueryStepOutput)
    history = query.history()
    assert query.execute(generation=2) == output
    assert query.history() == history and len(query.runs) == 1
    assert_exact_completed_producers(query)


def test_postgres_completed_query_read_uses_original_job_and_canonical_members(query, monkeypatch):
    current = make_completed_read_case(query, monkeypatch)
    first = read(current)
    assert read(current) == first and len(query.runs) == 1
    assert first.request.job_id == query.history().launch.native_launch_job_id
    assert_exact_completed_producers(query)


@pytest.mark.parametrize(
    "boundary", ("query_before", "query_after", "receipt_before", "receipt_after")
)
def test_postgres_crash_recovery_never_reencodes_or_reallocates(query, monkeypatch, boundary):
    owner_type = (
        EmbeddingArtifactStore
        if boundary.startswith("query")
        else NativeEmbeddingCompletionPublisher
    )
    method = owner_type.publish_reference_query

    def crash(self, *args, **kwargs):
        if boundary.endswith("after"):
            method(self, *args, **kwargs)
        raise KeyboardInterrupt("synthetic owner death; not a new inference grant")

    with monkeypatch.context() as patch:
        patch.setattr(owner_type, "publish_reference_query", crash)
        with pytest.raises(KeyboardInterrupt):
            query.execute()
    original = query.history()
    assert len(original.records) == (2 if boundary.startswith("query") else 3)
    assert isinstance(query.execute(generation=2), ReferenceQueryStepOutput)
    assert query.history().records[: len(original.records)] == original.records
    assert len(query.runs) == 1
    assert_exact_completed_producers(query)
