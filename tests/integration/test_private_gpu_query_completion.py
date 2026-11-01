"""Real PG/Artifact/parent completion; command/Workflow/IAM and GPU math are synthetic."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_query_job_allocation import create_native_query_launch
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    native_private_chat_gpu_query_checkpoint,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.private_chat_query_workflow_v2 import private_chat_query_result_schema
from eom_workflow_runner import private_chat_query_batch_material as batch_material
from eom_workflow_runner.local_embedding_publications import (
    native_embedding_publications,
    new_native_artifact_producer,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_completion import NativePrivateChatQueryCompletion
from eom_workflow_runner.private_chat_query_publication_read import (
    resolve_supported_private_chat_query_publication,
)
from eom_workflow_runner.repository import CommandLeaseIdentity
from sqlalchemy import func, select

from tests.integration.test_private_query_batch_execution_read import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_query_batch_execution_read import (
    private_batch as private_batch,
)
from tests.unit.test_private_chat_query_basis import TEXT

pytestmark = pytest.mark.integration


@pytest.fixture
def completion(private_batch, tmp_path, monkeypatch, request):
    phase_limit = 1 if getattr(request, "param", None) == "ALLOCATION_ONLY" else 2
    value = private_batch
    from eom_catalog_service import embedding_work_batch_execution

    def forbidden(*_args, **_kwargs):
        raise AssertionError("completion/read must not launch another numerical execution")

    monkeypatch.setattr(embedding_work_batch_execution, "execute_embedding_work_batch", forbidden)
    child, launch = value.child, value.launch
    coordinator = NativePrivateChatQueryCoordinator(child, launch)
    allocation = NativePrivateQueryAllocation(
        allocation=NativeQueryAllocation(
            query_producer=new_native_artifact_producer(),
            receipt_producer=new_native_artifact_producer(),
            created_at=launch.launched_at,
            source_commit="a" * 40,
        ),
        origin=value.sources.projection.origin,
    )
    with value.publisher.sessions.begin() as session:
        create_native_query_launch(session, request=child, launch=launch)
        for phase, payload in (("ALLOCATION", allocation), ("EXECUTED", value.executed))[
            :phase_limit
        ]:
            coordinator.append(
                session, native_private_chat_gpu_query_checkpoint(launch, phase, payload)
            )
    publication_root = tmp_path / "private-child-output"
    publication_root.mkdir(mode=0o700)
    monkeypatch.setattr(batch_material, "PRIVATE_QUERY_PUBLICATION_ROOT", publication_root)
    monkeypatch.setattr(
        batch_material, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    batch_material.stage_private_batch_query_publication(
        value.material, value.numeric.result.children[0].result, memoryview(value.numeric.vectors)
    )
    workspace = value.material.workspace
    workflow = NS(
        workflow_id=launch.workflow_id,
        state="RUNNING",
        current_step_key="encode_private_chat_query",
        runtime_context=value.origin_context.model_dump(mode="json"),
    )
    step = NS(
        workflow_id=launch.workflow_id,
        step_run_id=launch.step_run_id,
        step_key=launch.step_key,
        attempt=1,
        state="RUNNING",
        step_type="application",
        worker_role=None,
        result_schema=private_chat_query_result_schema(child),
        input_pointer_manifest={"workflow_request_sha256": child.request_sha256},
        platform_job_id=None,
    )
    calls = []
    lease = CommandLeaseIdentity(launch.original_command_id, "synthetic-private-runner", "test", 1)

    def sources(session, received, current_lease, **identity):
        assert received == child and current_lease == lease
        assert identity == dict(workflow_id=workflow.workflow_id, step_run_id=step.step_run_id)
        calls.append("current")
        return value.owner.cuda.resolve_submission(session, received, value.origin_context)

    def fence(_session, received, current_lease):
        assert received == child and current_lease == lease
        calls.append("late")

    owner = NS(
        settings=value.owner.cuda.settings, resolve_execution_sources=sources, fence_mutation=fence
    )
    application = NativePrivateChatQueryCompletion(owner)
    publications = native_embedding_publications(value.publisher, source_commit="a" * 40)
    prepared = value.material

    @contextmanager
    def root():
        with value.publisher.sessions.begin() as session:
            original_get = session.get

            def get(model, *args, **kwargs):
                if model is WorkflowInstanceRecord:
                    assert args[0] == workflow.workflow_id
                    return workflow
                if model is WorkflowStepRunRecord:
                    assert args[0] == step.step_run_id
                    return step
                return original_get(model, *args, **kwargs)

            # Only Workflow/command authority is synthetic; actual parent/Job,
            # canonical source/control/receipt and publication use guarded PG.
            monkeypatch.setattr(session, "get", get)
            yield session

    def publish():
        return application.publish(
            workflow=workflow,
            step=step,
            request=child,
            command_lease=lease,
            prepared=prepared,
            coordinator=coordinator,
            allocation=allocation,
            publications=publications,
            fenced_transaction=root,
        )

    def read(output):
        with root() as session:
            current = sources(
                session,
                child,
                lease,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
            return resolve_supported_private_chat_query_publication(
                owner.settings,
                session=session,
                workflow=workflow,
                step=step,
                sources=current,
                output=output,
            )

    return NS(
        value=value,
        request=child,
        launch=launch,
        coordinator=coordinator,
        allocation=allocation,
        publications=publications,
        publish=publish,
        read=read,
        calls=calls,
        workspace=workspace,
        workflow=workflow,
        step=step,
    )


def assert_original(completion, output):
    value = completion.value
    with value.publisher.sessions.begin() as session:
        history = completion.coordinator.read(session)
        assert history.state == "SUCCEEDED" and len(history.records) == 4
        assert history.records[1].payload == value.executed
        assert {row.schema_version for row in history.records} == {
            "native-private-chat-query-coordinator/2.1"
        }
        assert value.store.read(session) == value.history
        producers = completion.allocation.allocation
        for identity in (producers.query_producer, producers.receipt_producer):
            job = session.get(JobRecord, identity.job_id)
            assert job.status == "SUCCEEDED"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ArtifactRevisionRecord)
                    .where(ArtifactRevisionRecord.job_id == identity.job_id)
                )
                == 1
            )
            assert TEXT.encode() not in canonical_json_bytes(job.request)
        revision = session.get(
            ArtifactRevisionRecord, producers.query_producer.artifact_revision_id
        )
        assert not (Path(revision.nas_path) / "input.json").exists()
        for member in (
            revision.manifest,
            revision.result,
            *(record.model_dump(mode="json") for record in history.records),
        ):
            assert TEXT.encode() not in canonical_json_bytes(member)
    resolved, read_history = completion.read(output)
    assert read_history == history and resolved.request == value.native
    assert resolved.binary == value.numeric.vectors
    assert resolved.result == value.numeric.result.children[0].result
    return history


@pytest.mark.parametrize(
    "interruption", ("NONE", "QUERY_COMMITTED", "RECEIPT_BEFORE", "RECEIPT_COMMITTED")
)
def test_private_gpu_completion_resumes_original_producers_without_reencoding(
    completion, monkeypatch, interruption
):
    value = completion.value
    if interruption != "NONE":
        leaf, name = (
            (completion.publications.artifacts, "publish_private_chat_query")
            if interruption == "QUERY_COMMITTED"
            else (completion.publications.completions, "publish_supported_private_chat_query")
        )
        original = getattr(leaf, name)

        def interrupt(*args, **kwargs):
            if interruption != "RECEIPT_BEFORE":
                original(*args, **kwargs)
            raise RuntimeError("synthetic interruption at original private publication boundary")

        monkeypatch.setattr(leaf, name, interrupt)
        with pytest.raises(RuntimeError):
            completion.publish()
        monkeypatch.setattr(leaf, name, original)
    output = completion.publish()
    history = assert_original(completion, output)
    for member in completion.workspace.iterdir():
        member.unlink()
    assert completion.publish() == output
    assert assert_original(completion, output) == history
    assert "current" in completion.calls and "late" in completion.calls
    with value.publisher.sessions() as session:
        assert (
            session.get(JobRecord, completion.launch.native_launch_job_id).protocol_version
            == "private-chat-query/2.0"
        )


def test_private_gpu_completed_checkpoint_concurrent_replay_is_one_history(completion):
    output = completion.publish()
    history = assert_original(completion, output)

    def replay(_ordinal):
        with completion.value.publisher.sessions.begin() as session:
            for record in history.records:
                completion.coordinator.append(session, record)
            return completion.coordinator.read(session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(replay, range(2))) == [history, history]


@pytest.mark.parametrize("fault", ("chat", "public", "identity"))
def test_private_gpu_completion_reauthorizes_current_sources_before_replay(completion, fault):
    output = completion.publish()
    assert_original(completion, output)
    if fault == "chat":
        completion.value.chat.repository.revoked = True
    else:
        completion.value.fault.value = fault
    with pytest.raises(ValueError):
        completion.publish()


def test_private_gpu_completed_read_requires_the_original_batch_receipt(completion):
    output = completion.publish()
    assert_original(completion, output)
    value = completion.value
    with value.publisher.sessions() as session:
        original = session.get(ArtifactRevisionRecord, value.saved.member.artifact_revision_id)
        pointer = Path(original.nas_path) / "receipt.json"
    pointer.write_bytes(pointer.read_bytes() + b" ")
    with pytest.raises((ValueError, PinnedArtifactResolutionError)):
        completion.read(output)
    with pytest.raises((ValueError, PinnedArtifactResolutionError)):
        completion.publish()


def test_private_gpu_missing_original_proof_cannot_publish_any_child_result(completion):
    value = completion.value
    with value.publisher.sessions() as session:
        revision = session.get(ArtifactRevisionRecord, value.saved.member.artifact_revision_id)
        pointer = Path(revision.nas_path) / "receipt.json"
    pointer.unlink()
    with pytest.raises((ValueError, PinnedArtifactResolutionError)):
        completion.publish()
    with value.publisher.sessions() as session:
        assert (
            session.get(JobRecord, completion.allocation.allocation.query_producer.job_id) is None
        )
        assert (
            session.get(JobRecord, completion.allocation.allocation.receipt_producer.job_id) is None
        )


@pytest.mark.parametrize("completion", ("ALLOCATION_ONLY",), indirect=True)
def test_private_gpu_failed_original_is_not_restarted_or_published(completion):
    value = completion.value
    with value.publisher.sessions.begin() as session:
        failed = completion.coordinator.record_known_failure(session)
        assert failed.state == "FAILED"
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_EXECUTION_NOT_OBSERVED"):
        completion.publish()
    with value.publisher.sessions.begin() as session:
        assert completion.coordinator.read(session) == failed
        assert (
            session.get(JobRecord, completion.allocation.allocation.query_producer.job_id) is None
        )
        assert (
            session.get(JobRecord, completion.allocation.allocation.receipt_producer.job_id) is None
        )


def test_private_gpu_canonical_binary_corruption_is_not_a_reencoding_request(completion):
    output = completion.publish()
    assert_original(completion, output)
    value = completion.value
    with value.publisher.sessions() as session:
        producer = completion.allocation.allocation.query_producer
        row = session.get(ArtifactRevisionRecord, producer.artifact_revision_id)
        path = Path(row.nas_path) / "vectors.f32"
    changed = path.read_bytes() + b"\x00"
    path.write_bytes(changed)
    with pytest.raises(ValueError):
        completion.read(output)
    assert path.read_bytes() == changed


def test_private_gpu_proof_is_rechecked_between_result_and_completion_commits(
    completion, monkeypatch
):
    leaf = completion.publications.artifacts
    original = leaf.publish_private_chat_query

    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic interruption after original private query commit")

    with monkeypatch.context() as patch:
        patch.setattr(leaf, "publish_private_chat_query", interrupt)
        with pytest.raises(RuntimeError):
            completion.publish()
    value = completion.value
    with value.publisher.sessions() as session:
        row = session.get(ArtifactRevisionRecord, value.saved.member.artifact_revision_id)
        path = Path(row.nas_path) / "receipt.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        completion.publish()
    with value.publisher.sessions.begin() as session:
        assert len(completion.coordinator.read(session).records) == 2
        assert (
            session.get(JobRecord, completion.allocation.allocation.receipt_producer.job_id) is None
        )
