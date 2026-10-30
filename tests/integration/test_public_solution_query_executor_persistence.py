"""Opt-in guarded PostgreSQL QUERY2 recovery; IAM and model observations are synthetic.

Uses the same canonical Job/event/Artifact owners and marker guard as legacy
QUERY tests. No production database, real model, GPU or authenticated user grant.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.native_embedding_query_systemd import NativeQueryLaunchError
from eom_orchestrator.native_reference_query_coordinator import NativeReferenceQueryCoordinator
from eom_orchestrator.settings import Settings
from eom_workflow.reference_query_execution import ReferenceQueryStepOutputV2
from sqlalchemy import Engine

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_reference_query_native_persistence import (
    assert_exact_completed_producers,
)
from tests.unit.test_public_solution_query_native_executor import make_public_executor_case

pytestmark = pytest.mark.integration


@pytest.fixture
def query(guarded_engine: Engine, tmp_path: Path, monkeypatch):
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
    return make_public_executor_case(
        tmp_path, monkeypatch, publisher=publisher, identity=uuid4().hex
    )


def test_public_query_postgres_exact_result_receipt_and_replay(query):
    output = query.execute()
    assert isinstance(output, ReferenceQueryStepOutputV2)
    before = query.history()
    assert before.state == "SUCCEEDED" and len(before.records) == 4
    assert {row.schema_version for row in before.records} == {
        "native-reference-query-coordinator/2.0"
    }
    assert query.execute(generation=2) == output and query.history() == before
    assert len(query.runs) == 1
    assert_exact_completed_producers(query)


def test_public_query_postgres_concurrent_checkpoint_replay_keeps_original_identity(query):
    assert isinstance(query.execute(), ReferenceQueryStepOutputV2)
    before = query.history()
    barrier = Barrier(2)

    def replay():
        barrier.wait(timeout=10)
        with query.publisher.sessions.begin() as session:
            owner = NativeReferenceQueryCoordinator(query.request, before.launch)
            for record in before.records:
                owner.append(session, record)
            return owner.read(session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(replay), pool.submit(replay))
        assert all(future.result(timeout=30) == before for future in futures)
    assert query.history() == before and len(query.runs) == 1
    assert_exact_completed_producers(query)


@pytest.mark.parametrize(
    "boundary", ("query_before", "query_after", "receipt_before", "receipt_after")
)
def test_public_query_postgres_recovers_publication_without_another_encode(
    query, monkeypatch, boundary
):
    owner = (
        EmbeddingArtifactStore
        if boundary.startswith("query")
        else NativeEmbeddingCompletionPublisher
    )
    original = owner.publish_supported_reference_query

    def interrupt(self, *args, **kwargs):
        if boundary.endswith("after"):
            original(self, *args, **kwargs)
        raise KeyboardInterrupt("synthetic original owner interruption")

    with monkeypatch.context() as patch:
        patch.setattr(owner, "publish_supported_reference_query", interrupt)
        with pytest.raises(KeyboardInterrupt):
            query.execute()
    before = query.history()
    assert len(before.records) == (2 if boundary.startswith("query") else 3)
    assert isinstance(query.execute(generation=2), ReferenceQueryStepOutputV2)
    after = query.history()
    assert after.launch == before.launch and after.records[: len(before.records)] == before.records
    assert len(query.runs) == 1
    assert_exact_completed_producers(query)


def test_public_query_postgres_never_reinterprets_failed_history_as_success(query):
    query.failure = "NATIVE_QUERY_KNOWN_FAILED"
    with pytest.raises(NativeQueryLaunchError):
        query.execute()
    before = query.history()
    assert before.state == "FAILED"
    query.failure = None
    with pytest.raises(ValueError, match="TERMINAL_HISTORY"):
        query.execute(generation=2)
    assert query.history() == before and len(query.runs) == 1
