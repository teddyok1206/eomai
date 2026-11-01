"""Real local parent/launch/Artifact continuation; GPU, IAM and command authority are synthetic."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.local_embedding_control_artifacts import (
    batch_execution_receipt_publication_key,
)
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_query_job_allocation import read_native_query_launch
from eom_orchestrator.settings import Settings
from eom_workflow.private_chat_query_submission_context import private_chat_query_origin_key
from eom_workflow.private_chat_query_workflow_v2 import (
    PrivateChatQueryStepOutputV2,
    private_chat_query_result_schema,
)
from eom_workflow_runner import private_chat_query_batch_executor as executor
from eom_workflow_runner import private_chat_query_batch_material as material
from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    CatalogEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
    PublishedEmbeddingBatchExecution,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_execution_port import (
    PrivateChatQueryNativeExecutor,
    PrivateChatQueryStepPending,
)
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.embedding_batch_publication_fixtures import replace_receipt_parent
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.private_query_batch_execution_fixtures import private_query_batch_case

pytestmark = pytest.mark.integration


def make_executor_case(tmp_path, monkeypatch, *, publisher=None):
    value = private_query_batch_case(
        tmp_path, monkeypatch, publisher=publisher, key=uuid4().hex, bind=False
    )
    owner = value.owner.cuda
    operation = CatalogEmbeddingBatchExecution(
        value.owner, value.publisher, source_commit="a" * 40, controller_release="a" * 40
    )
    calls, physical = [], []
    channel = NS(require_direct_peer=lambda: calls.append("peer"))
    active = ActiveEmbeddingBatchExecution(
        operation, value.request, value.history, channel, value.numeric.frames.ready
    )
    service = executor.CatalogBatchPrivateChatQueryExecutor(operation, value.request, active, owner)
    workflow = NS(
        workflow_id=value.launch.workflow_id,
        state="RUNNING",
        current_step_key="encode_private_chat_query",
        idempotency_key=private_chat_query_origin_key(value.selection.origin),
        runtime_context=value.origin_context.model_dump(mode="json"),
    )
    step = NS(
        workflow_id=workflow.workflow_id,
        step_run_id=value.launch.step_run_id,
        step_key="encode_private_chat_query",
        attempt=1,
        state="RUNNING",
        step_type="application",
        worker_role=None,
        result_schema=private_chat_query_result_schema(value.child),
        input_pointer_manifest={"workflow_request_sha256": value.child.request_sha256},
        platform_job_id=None,
    )
    state = NS(depth=0, denied=False, saved=None, numeric=None, interrupted=False, cold_reads=0)
    lease = CommandLeaseIdentity("wfcmd_" + "6" * 32, "synthetic-private-runner", "test", 1)

    @contextmanager
    def root():
        state.depth += 1
        try:
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

                monkeypatch.setattr(session, "get", get)
                yield session
        finally:
            state.depth -= 1

    def source(session, request, current_lease, **identity):
        assert state.depth and request == value.child and current_lease == lease
        assert identity == dict(workflow_id=workflow.workflow_id, step_run_id=step.step_run_id)
        calls.append("source")
        if state.denied:
            raise ValueError("SYNTHETIC_CURRENT_AUTHORIZATION_REVOKED")
        return owner.resolve_submission(session, request, value.origin_context)

    def fence(_session, request, current_lease):
        assert state.depth and request == value.child and current_lease == lease
        calls.append("late")
        if state.denied:
            raise ValueError("SYNTHETIC_CURRENT_AUTHORIZATION_REVOKED")

    monkeypatch.setattr(owner, "resolve_execution_sources", source)
    monkeypatch.setattr(owner, "fence_mutation", fence)
    monkeypatch.setattr(
        executor, "native_fenced_runner_transaction", lambda *_args, **_kwargs: root()
    )
    # Only the command row/lease and OS numerical boundary are synthetic.
    from eom_workflow_runner import embedding_batch_source_authorization

    monkeypatch.setattr(
        embedding_batch_source_authorization, "require_command_lease", lambda *_args: None
    )
    publication_root = tmp_path / "private-child-output"
    publication_root.mkdir(mode=0o700)
    monkeypatch.setattr(material, "PRIVATE_QUERY_PUBLICATION_ROOT", publication_root)
    monkeypatch.setattr(
        material, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )

    def run(bound, batch, *, authorization):
        assert state.depth == 0, "child SQL/source root survived into physical execution"
        assert not physical, "one original private query may dispatch only once"
        physical.append(batch.request_sha256)
        with value.publisher.sessions.begin() as session, value.owner.admit(session, value.request):
            history = value.store.bind(
                session, bound, batch, authorize_child=authorization.authorize_binding
            )
        value.planned.bound, value.planned.batch = bound, batch
        numeric = execution_case(planned=value.planned)
        receipt = replace_receipt_parent(numeric.receipt, history.job_id)
        # The generic numerical fixture uses October24. This new launch is made
        # now; its declared synthetic completion must follow the real allocation.
        body = receipt.model_dump(mode="json")
        body["completed"] = seal(
            body["completed"]
            | {"retired_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")},
            "message_sha256",
        )
        receipt = type(receipt).model_validate(seal(body, "receipt_sha256"))
        saved = value.controls.publish_batch_execution_receipt(
            receipt,
            idempotency_key=batch_execution_receipt_publication_key(
                value.request.request_sha256, history.allocation.record_sha256
            ),
        )
        verified = NS(
            result=numeric.result,
            completed=receipt.completed,
            child_vectors=(memoryview(numeric.vectors),),
            assert_current=lambda: calls.append("physical-files"),
        )
        state.saved, state.numeric, state.receipt, state.verified = (
            saved,
            numeric,
            receipt,
            verified,
        )
        if state.interrupted:
            raise RuntimeError("synthetic interruption after canonical receipt commit")
        return PublishedEmbeddingBatchExecution(saved, verified)

    def cold(receipt, *, authorization):
        assert state.depth == 0 and receipt == state.receipt
        authorization.authorize_batch()
        state.cold_reads += 1
        return state.verified

    monkeypatch.setattr(active, "run", run)
    monkeypatch.setattr(executor, "read_completed_embedding_batch_result", cold)

    def execute(target=None, key=None):
        return (target or service).execute(
            workflow=workflow,
            step=step,
            request=value.child,
            command_lease=lease,
            idempotency_key=key
            or (
                f"private-chat-query-step:{workflow.workflow_id}:encode_private_chat_query:1:"
                f"{value.child.workflow_definition_sha256}"
            ),
            fenced_transaction=root,
        )

    def history():
        with root() as session:
            launch = read_native_query_launch(
                session,
                request=value.child,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
            assert launch is not None
            return launch, NativePrivateChatQueryCoordinator(value.child, launch).read(session)

    def existing():
        with value.publisher.sessions.begin() as session, value.owner.admit(session, value.request):
            parent = value.store.read(session)
        return executor.CatalogBatchPrivateChatQueryExecutor(
            operation, value.request, ExistingEmbeddingBatchExecution(parent), owner
        )

    return NS(**locals())


@pytest.fixture
def driver(guarded_engine, tmp_path, monkeypatch):
    nas = tmp_path / "nas"
    nas.mkdir(mode=0o700)
    publisher = ControlFileSetPublisher(
        guarded_engine,
        Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas, workspace_root=tmp_path),
    )
    return make_executor_case(tmp_path, monkeypatch, publisher=publisher)


def test_one_private_gpu_query_uses_original_parent_and_completes_four_phases(driver):
    output = driver.execute()
    assert type(output) is PrivateChatQueryStepOutputV2
    launch, history = driver.history()
    assert history.state == "SUCCEEDED" and len(history.records) == 4
    assert {record.schema_version for record in history.records} == {
        "native-private-chat-query-coordinator/2.1"
    }
    assert driver.execute() == output and driver.history() == (launch, history)
    assert len(driver.physical) == 1 and driver.state.cold_reads == 0
    assert "late" in driver.calls


def test_original_canonical_receipt_recovers_interrupted_child_without_second_dispatch(driver):
    driver.state.interrupted = True
    with pytest.raises(RuntimeError, match="canonical receipt commit"):
        driver.execute()
    launch, history = driver.history()
    assert len(history.records) == 1
    output = driver.execute(driver.existing())
    assert type(output) is PrivateChatQueryStepOutputV2
    assert driver.history()[0] == launch and len(driver.physical) == 1
    assert driver.state.cold_reads == 1


def test_completed_private_gpu_read_does_not_need_root_peer_or_local_workspace(driver, monkeypatch):
    output = driver.execute()
    history = driver.history()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("completed replay must not reconnect or read old physical output")

    monkeypatch.setattr(driver.channel, "require_direct_peer", forbidden)
    monkeypatch.setattr(executor, "read_completed_embedding_batch_result", forbidden)
    for path in (
        material.PRIVATE_QUERY_PUBLICATION_ROOT / history[0].native_launch_job_id[4:]
    ).iterdir():
        path.unlink()
    assert driver.execute(driver.existing()) == output
    assert driver.history() == history and len(driver.physical) == 1


def test_private_gpu_replay_reauthorizes_current_chat_and_command_sources(driver):
    driver.execute()
    history = driver.history()
    driver.state.denied = True
    with pytest.raises(ValueError, match="SYNTHETIC_CURRENT_AUTHORIZATION_REVOKED"):
        driver.execute()
    assert driver.history() == history and len(driver.physical) == 1


def test_wrong_step_key_cannot_allocate_or_dispatch_private_gpu_work(driver):
    with pytest.raises(ValueError):
        driver.execute(key="another-operation")
    assert not driver.physical


def test_busy_private_gpu_observation_reuses_original_allocation(driver):
    with driver.root() as session:
        launch = driver.service.allocate_execution(
            session=session,
            workflow=driver.workflow,
            step=driver.step,
            request=driver.value.child,
            command_lease=driver.lease,
        )
    driver.service._lock.acquire()
    try:
        result = driver.execute()
    finally:
        driver.service._lock.release()
    assert result == PrivateChatQueryStepPending(
        launch.native_launch_job_id, launch.association_sha256, "BUSY"
    )
    assert not driver.physical


def test_existing_private_parent_without_canonical_receipt_is_uncertain_not_restart(driver):
    with driver.root() as session:
        launch = driver.service.allocate_execution(
            session=session,
            workflow=driver.workflow,
            step=driver.step,
            request=driver.value.child,
            command_lease=driver.lease,
        )
    result = driver.execute(driver.existing())
    assert result == PrivateChatQueryStepPending(
        launch.native_launch_job_id, launch.association_sha256, "UNCERTAIN"
    )
    assert not driver.physical


def test_private_gpu_known_failure_keeps_history_and_never_starts_another_root(driver):
    with driver.root() as session:
        launch = driver.service.allocate_execution(
            session=session,
            workflow=driver.workflow,
            step=driver.step,
            request=driver.value.child,
            command_lease=driver.lease,
        )
        coordinator = NativePrivateChatQueryCoordinator(driver.value.child, launch)
        failed = coordinator.record_known_failure(session)
    with pytest.raises(ValueError):
        driver.execute()
    assert driver.history() == (launch, failed)
    assert not driver.physical


def test_private_gpu_concurrent_observation_does_not_dispatch_another_batch(driver, monkeypatch):
    entered, release = Event(), Event()
    original = driver.active.run

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(30), "test did not release synthetic original physical boundary"
        return original(*args, **kwargs)

    monkeypatch.setattr(driver.active, "run", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(driver.execute)
        try:
            assert entered.wait(30)
            pending = driver.execute()
            assert isinstance(pending, PrivateChatQueryStepPending) and pending.reason == "BUSY"
        finally:
            release.set()
        output = running.result(timeout=30)
    assert type(output) is PrivateChatQueryStepOutputV2
    assert len(driver.physical) == 1 and driver.execute() == output


def assert_private_port(
    value: executor.CatalogBatchPrivateChatQueryExecutor,
) -> PrivateChatQueryNativeExecutor:
    return value
