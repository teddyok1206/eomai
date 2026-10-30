"""Guarded PostgreSQL QUERY2 continuation; source/model/unit evidence is synthetic.

The original Job, ordered event journal, canonical Artifact bytes and receipt
publisher are real. These tests grant no live source, Workflow or GPU authority.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_public_solution_query_completion,
    resolve_native_reference_query_completion,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetIdentity,
    ControlFileSetPublisher,
)
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import (
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
    ProtocolVersionRecord,
)
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    NativeReferenceQueryHistoryError,
    create_native_reference_query_launch,
    read_native_reference_query_launch,
)
from eom_orchestrator.settings import Settings
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryCompletedV2,
    NativeQueryPublishedV2,
    native_reference_query_continuation_checkpoint,
    reference_query_checkpoint_receipt,
)
from eom_workflow.schemas import (
    NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE,
    REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_public_solution_query_artifacts import (
    public_artifact_case,
    publication_arguments,
)
from tests.unit.test_public_solution_query_continuation import VERSION, public_query_records
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case

pytestmark = pytest.mark.integration


@pytest.fixture
def publisher(guarded_engine, tmp_path):
    assert guarded_engine.dialect.name == "postgresql"
    assert not tmp_path.is_relative_to(Path("/mnt/nas"))
    artifacts, workspace = tmp_path / "artifacts", tmp_path / "workspace"
    artifacts.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    return ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging", nas_artifact_root=artifacts, workspace_root=workspace
        ),
    )


def original(publisher, value):
    with publisher.sessions.begin() as session:
        launch = create_native_reference_query_launch(
            session, request=value.request, launch=value.launch
        )
    return NativeReferenceQueryCoordinator(value.request, launch)


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_query2_concurrent_original_launch_reuses_one_job_after_conflict(publisher, device):
    value = public_workflow_case(identity=uuid4().hex, device=device)
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=30)
        try:
            with publisher.sessions.begin() as session:
                return create_native_reference_query_launch(
                    session, request=value.request, launch=value.launch
                )
        except (IntegrityError, NativeReferenceQueryHistoryError) as error:
            if isinstance(error, NativeReferenceQueryHistoryError):
                assert str(error) == "REFERENCE_QUERY_LAUNCH_RACE_UNRECONCILED"
            # Observe the original key after rollback; never allocate another
            # identity or infer that a commit conflict means no work happened.
            with publisher.sessions.begin() as session:
                result = read_native_reference_query_launch(
                    session,
                    request=value.request,
                    workflow_id=value.launch.workflow_id,
                    step_run_id=value.launch.step_run_id,
                )
                assert result is not None
                return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = tuple(executor.map(lambda _: submit(), range(2)))
    assert first == second == value.launch
    with publisher.sessions.begin() as session:
        job = session.get(JobRecord, first.native_launch_job_id)
        assert job.protocol_version == "reference-query/2.0" and job.status == "CLAIMED"
        assert (
            session.get(ProtocolVersionRecord, job.protocol_version).schema_sha256
            == (REFERENCE_QUERY_PUBLIC_EXECUTION_SCHEMA_RESOURCE[2])
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == job.job_id,
                    JobEventRecord.event == "REFERENCE_QUERY_NATIVE_LAUNCH",
                )
            )
            == 1
        )


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_query2_every_committed_prefix_resumes_and_concurrent_replay_keeps_four_events(
    publisher, device
):
    value = public_workflow_case(identity=uuid4().hex, device=device)
    records = public_query_records(value, device=device)
    owner = original(publisher, value)
    for index, record in enumerate(records):
        with publisher.sessions.begin() as session:
            assert owner.read(session).records == records[:index]
            owner.append(session, record)
        # New adapter/process view, same persisted launch and prefix.
        owner = NativeReferenceQueryCoordinator(value.request, value.launch)

    def replay():
        with publisher.sessions.begin() as session:
            for record in records:
                owner.append(session, record)
            return owner.read(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = tuple(executor.map(lambda _: replay(), range(2)))
    assert first == second and first.state == "SUCCEEDED" and first.records == records
    with publisher.sessions.begin() as session:
        events = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(
                    JobEventRecord.job_id == value.launch.native_launch_job_id,
                    JobEventRecord.event.in_(
                        tuple("REFERENCE_QUERY_NATIVE_" + row.record_type for row in records)
                    ),
                )
                .order_by(JobEventRecord.sequence)
            )
        )
        assert len(events) == 4
        assert all(len(canonical_json_bytes(event.data)) < 16 * 1024 for event in events)
        assert (
            session.get(ProtocolVersionRecord, "native-query-coordinator/2.0").schema_sha256
            == (NATIVE_REFERENCE_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE[2])
        )


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_query2_known_failure_is_preserved_and_cannot_be_replayed_as_success(publisher, device):
    value = public_workflow_case(identity=uuid4().hex, device=device)
    records = public_query_records(value, device=device)
    owner = original(publisher, value)
    with publisher.sessions.begin() as session:
        owner.append(session, records[0])
        failed = owner.record_known_failure(session)
    with publisher.sessions.begin() as session:
        assert owner.record_known_failure(session) == failed
        with pytest.raises(NativeReferenceQueryHistoryError, match="TERMINAL_OR_FOREIGN"):
            owner.append(session, records[1])
        assert owner.read(session) == failed
        job = session.get(JobRecord, value.launch.native_launch_job_id)
        assert job.status == "FAILED" and job.error_code == "NATIVE_QUERY_KNOWN_FAILED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id == job.job_id,
                    JobEventRecord.event == "REFERENCE_QUERY_NATIVE_EXECUTION_FAILED",
                )
            )
            == 1
        )


@pytest.mark.parametrize("response_loss", ["before", "after"])
def test_query2_original_receipt_publication_recovery_uses_exact_producers_and_bytes(
    publisher,
    tmp_path,
    response_loss,
):
    value = public_artifact_case(tmp_path, publisher)
    c = value.case
    records = public_query_records(c)
    owner = original(publisher, c)
    for record in records[:2]:
        with publisher.sessions.begin() as session:
            owner.append(session, record)
    allocation = records[0].payload
    published = value.store.publish_public_solution_reference_query(
        **publication_arguments(value),
        identity=ControlFileSetIdentity(
            allocation.query_producer.job_id,
            allocation.query_producer.artifact_id,
            allocation.query_producer.artifact_revision_id,
        ),
    )
    publication = NativeQueryPublishedV2(
        query_owner_job_id=published.owner_job_id,
        input=published.input,
        result=published.result,
        shard=published.shard,
        binary=published.binary,
        manifest_sha256=published.manifest_sha256,
        published_observed_at=c.receipt.published_at,
    )
    checkpoint = native_reference_query_continuation_checkpoint(
        c.launch,
        "PUBLISHED",
        publication,
        previous=records[:2],
        initial_version=VERSION,
    )
    with publisher.sessions.begin() as session:
        history = owner.append(session, checkpoint)
    receipt = reference_query_checkpoint_receipt(
        c.request, c.launch, allocation, records[1].payload, publication
    )
    identity = ControlFileSetIdentity(
        allocation.receipt_producer.job_id,
        allocation.receipt_producer.artifact_id,
        allocation.receipt_producer.artifact_revision_id,
    )
    completion = NativeEmbeddingCompletionPublisher(publisher, source_commit="a" * 40)
    if response_loss == "after":
        lost = completion.publish_public_solution_reference_query(receipt, identity=identity)
    # Simulate process replacement at the publication/response boundary. The
    # numerical workspace/result is unchanged; no encoder is called again.
    completion = NativeEmbeddingCompletionPublisher(publisher, source_commit="a" * 40)
    output = completion.publish_public_solution_reference_query(receipt, identity=identity)
    if response_loss == "after":
        assert output == lost
    completed = native_reference_query_continuation_checkpoint(
        c.launch,
        "COMPLETED",
        NativeQueryCompletedV2(output=output),
        previous=history.records,
        initial_version=VERSION,
    )
    with publisher.sessions.begin() as session:
        assert owner.append(session, completed).state == "SUCCEEDED"
    with publisher.sessions.begin() as session:
        settings = CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        assert resolve_native_public_solution_query_completion(session, settings, output) == receipt
        with pytest.raises(ValueError):
            resolve_native_reference_query_completion(session, settings, output)
        ids = (c.launch.native_launch_job_id, published.owner_job_id, identity.job_id)
        jobs = tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.in_(ids))))
        assert len(jobs) == 3 and all(job.status == "SUCCEEDED" for job in jobs)
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(
                    ArtifactRevisionRecord.job_id.in_(ids),
                )
            )
            == 2
        )
    with pytest.raises(ValueError, match="PRODUCER_MISMATCH"):
        completion.publish_public_solution_reference_query(
            receipt, identity=replace(identity, job_id="job_" + uuid4().hex)
        )
