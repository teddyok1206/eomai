"""Real PG controls/Jobs/Artifact/receipt bytes; authority, Workflow views and math are fake.

Separate lease and source suites cover those boundaries. This is not live
private2 admission, physical-unit execution or a real-model acceptance.
"""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.compiler import compile_definition
from eom_workflow.private_chat_query_workflow_v2 import PrivateChatQueryStepOutputV2
from eom_workflow_runner.private_chat_query_source_read import (
    read_pinned_private_chat_query_controls,
)
from sqlalchemy import select

from tests.integration import test_private_chat_query_native_persistence as legacy_cases
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_query_source_owner import make_owned_private_source
from tests.unit import test_private_chat_public_query_native_executor as cases
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_public_query_source_owner import (
    make_private_public_source_from_legacy,
)
from tests.unit.test_private_chat_query_basis import TEXT

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def query(registered, guarded_engine, tmp_path, monkeypatch):
    current = make_owned_common_private_source(registered, guarded_engine, monkeypatch)
    old = current.old
    source = SimpleNamespace(
        owner=current.owner,
        publisher=old.publisher,
        request=current.request,
        policy=current.policy,
        bundle=old.bundle,
        projection=old.projection,
        fault=old.fault,
        events=old.events,
    )
    value = cases.make_public_private_executor_case(tmp_path, monkeypatch, source=source)
    value.workflow.workflow_id = "workflow_" + uuid4().hex
    value.step.workflow_id = value.workflow.workflow_id
    value.step.step_run_id = "steprun_" + uuid4().hex
    return value


def make_owned_common_private_source(registered, guarded_engine, monkeypatch):
    """Reuse real PostgreSQL control ownership for execution and completed-reader suites."""
    resources = reference_prepared().workflow_request.resource_profile
    previous = make_owned_private_source(registered, guarded_engine, resource_profile=resources)
    with previous.publisher.sessions.begin() as session:
        _policy, bundle = read_pinned_private_chat_query_controls(
            PinnedArtifactReadContext(session, previous.owner.settings),
            previous.owner.configuration,
        )
    old = SimpleNamespace(
        **vars(previous),
        bundle=bundle,
        controls=LocalEmbeddingControlArtifactPublisher(previous.publisher, source_commit="a" * 40),
        events=[],
    )
    old.fault.public_revoked = False
    compiled = compile_definition(
        Path(__file__).resolve().parents[2]
        / "config/workflows/local-embedding-private-chat-query.v2.yaml",
        set(),
    )
    current = make_private_public_source_from_legacy(
        old, monkeypatch, definition_sha256=compiled.sha256, resource_profile=resources
    )
    return current


def test_postgres_common_private_executor_commits_original_text_free_result_and_receipt(query):
    output = query.execute()
    assert type(output) is PrivateChatQueryStepOutputV2
    launch, history = query.history()
    assert history.state == "SUCCEEDED" and len(history.records) == 4
    allocation = history.records[0].payload.allocation
    ids = (
        launch.native_launch_job_id,
        allocation.query_producer.job_id,
        allocation.receipt_producer.job_id,
    )
    with query.publisher.sessions() as session:
        jobs = tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.in_(ids))))
        assert len(jobs) == 3 and all(job.status == "SUCCEEDED" for job in jobs)
        revisions = tuple(
            session.scalars(
                select(ArtifactRevisionRecord).where(ArtifactRevisionRecord.job_id.in_(ids))
            )
        )
        assert len(revisions) == 2
        for job in jobs:
            assert TEXT.encode() not in canonical_json_bytes(job.request)
        for revision in revisions:
            assert TEXT.encode() not in canonical_json_bytes(revision.result)
            assert TEXT.encode() not in canonical_json_bytes(revision.manifest)
            assert not (Path(revision.nas_path) / "input.json").exists()
    query.launcher.assert_current_runtime.side_effect = OSError("retired original physical runtime")
    assert query.execute(generation=2) == output and query.encodes == 1


@pytest.mark.parametrize(
    "boundary", ["query_before", "query_after", "receipt_before", "receipt_after"]
)
def test_postgres_common_private_publication_crash_reuses_original_numeric_output(
    query, monkeypatch, boundary
):
    cases.test_common_private_each_publication_interruption_resumes_original_numeric_work(
        query, monkeypatch, boundary
    )


def test_postgres_common_private_source_loss_cannot_publish_after_numerical_work(query):
    cases.test_common_private_source_revocation_after_numeric_work_cannot_publish(query)


def test_postgres_common_private_concurrent_exact_history_replay_has_one_prefix(query):
    legacy_cases.test_postgres_private_history_concurrent_exact_replay_has_one_prefix(query)


def test_postgres_common_private_allocation_rollback_leaves_no_launch(query):
    legacy_cases.test_postgres_private_allocated_root_rollback_preserves_no_launch(query)
