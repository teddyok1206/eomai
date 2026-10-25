"""Original verified BUSY to the existing CPU owner; real disposable DB, synthetic OS/model."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_models import EmbeddingIndexRecord
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_workflow_runner.document_embedding_batch_driver import (
    drive_document_embedding_batch_once,
    start_document_embedding_batch,
)
from eom_workflow_runner.document_embedding_cpu_batch_execution import (
    CatalogCpuDocumentBatchExecution,
)
from eom_workflow_runner.document_embedding_execution import DocumentExecutionState
from sqlalchemy import select

from tests.integration.test_document_embedding_cuda_execution import native_history, purpose_runner
from tests.integration.test_local_embedding_native_executor import execution as execution
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.inference_transfer_embedding_fixtures import seal

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_original_busy_route_uses_cpu_index_workflow_without_gpu_grant(execution):
    value = execution
    original = value.gpu.adapter.unavailable
    assert original.history.route.decision.reason == "GPU_BUSY_CPU_FALLBACK"
    started = start_document_embedding_batch(value.executor)
    runner = purpose_runner(value)
    command = drive_document_embedding_batch_once(
        value.executor, runner, started.workflow.workflow_id
    )
    assert command is not None and command.state == "SUCCEEDED"
    assert value.launcher.forwards == 1 and len(value.gpu.dispatches) == 1
    assert not value.gpu.channel.send_binding.called and not hasattr(value.gpu, "numeric")
    with value.sessions.begin() as session:
        history = value.gpu.store.read(session)
        assert history.state == "SUCCEEDED" and history.bound is not None
        assert history.route == original.history.route
        assert history.bound.children[0].workflow_id == started.workflow.workflow_id
        rows = tuple(
            session.scalars(
                select(EmbeddingIndexRecord).where(
                    EmbeddingIndexRecord.corpus_id == value.request.corpus_id
                )
            )
        )
        assert rows and all(row.space_sha256 == value.request.space.space_sha256 for row in rows)
    assert value.request.space.runtime.device == "CPU"
    replay = start_document_embedding_batch(value.executor)
    assert replay.workflow.workflow_id == started.workflow.workflow_id
    assert (
        drive_document_embedding_batch_once(value.executor, runner, started.workflow.workflow_id)
        is None
    )
    assert value.launcher.forwards == 1


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
@pytest.mark.parametrize(
    "boundary", ("owned_before", "owned_after", "receipt_before", "receipt_after")
)
def test_publication_replay_stays_cpu_even_if_gpu_becomes_available(
    execution, monkeypatch, boundary
):
    value = execution
    first = value.start()
    target = (
        EmbeddingArtifactStore
        if boundary.startswith("owned")
        else NativeEmbeddingCompletionPublisher
    )
    method = "publish_owned_batch" if boundary.startswith("owned") else "publish"
    original = getattr(target, method)
    failed = []

    def interrupt(self, *args, **kwargs):
        if not failed:
            failed.append(True)
            if boundary.endswith("after"):
                original(self, *args, **kwargs)
            raise RuntimeError("synthetic CPU publication interruption")
        return original(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(target, method, interrupt)
        with pytest.raises(RuntimeError, match="synthetic CPU publication interruption"):
            value.advance(*first)
    intent, prior = native_history(value, first[0])
    value.gpu.channel.receive_allocation = Mock(side_effect=AssertionError("GPU reconsidered"))
    assert value.advance(*first) is True
    value.finish(*first)
    final_intent, completed = native_history(value, first[0])
    assert intent == final_intent and completed.records[: len(prior.records)] == prior.records
    assert completed.state == "SUCCEEDED" and value.launcher.forwards == 1
    assert len(value.gpu.dispatches) == 1 and not hasattr(value.gpu, "numeric")


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_current_source_revocation_stops_cpu_fallback_without_dispatch(execution):
    value = execution
    first = value.start()
    value.current.allowed = False
    with pytest.raises((ValueError, AssertionError, PermissionError)):
        value.advance(*first)
    assert value.launcher.forwards == 0 and not hasattr(value.gpu, "numeric")


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_cpu_uncertainty_keeps_original_work_pending_not_gpu_retry(execution):
    value = execution
    first = value.start()
    value.launcher.observe = Mock(return_value=())
    assert value.advance(*first) is False
    assert value.launcher.forwards == 0 and len(value.gpu.dispatches) == 1
    intent, _history = native_history(value, first[0])
    assert value.gpu.adapter.observe(intent) is DocumentExecutionState.UNCERTAIN
    assert not hasattr(value.gpu, "numeric")


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_unrelated_root_busy_proof_does_not_authorize_cpu_numerical_work(execution):
    value = execution
    adapter = value.gpu.adapter
    original = adapter.unavailable
    foreign = type(original.root_observation).model_validate(
        seal(
            original.root_observation.model_dump(mode="json") | {"controller_release": "f" * 40},
            "message_sha256",
        )
    )
    with pytest.raises(ValueError, match="DOCUMENT_CPU_ROUTE_INVALID"):
        CatalogCpuDocumentBatchExecution(
            value.gpu.operation,
            value.gpu.request,
            replace(original, root_observation=foreign),
            value.owner,
            value.request,
            adapter.execution,
        )
    assert value.launcher.forwards == 0 and len(value.gpu.dispatches) == 1
    assert not hasattr(value.gpu, "numeric")


@pytest.mark.parametrize("execution", ["cpu_fallback"], indirect=True)
def test_concurrent_start_and_claim_keep_one_original_cpu_workflow_and_launch(execution):
    value = execution
    start_gate = Barrier(2)

    def start():
        start_gate.wait(timeout=10)
        return start_document_embedding_batch(value.executor)

    with ThreadPoolExecutor(max_workers=2) as pool:
        starts = tuple(pool.map(lambda _index: start(), range(2)))
    assert len({result.workflow.workflow_id for result in starts}) == 1
    assert len({result.command.command_id for result in starts}) == 1
    assert sum(result.workflow_created for result in starts) == 1
    assert sum(result.command_created for result in starts) == 1
    claim_gate = Barrier(2)

    def claim():
        runner = purpose_runner(value)
        claim_gate.wait(timeout=10)
        return drive_document_embedding_batch_once(
            value.executor, runner, starts[0].workflow.workflow_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        commands = tuple(pool.map(lambda _index: claim(), range(2)))
    actual = tuple(command for command in commands if command is not None)
    assert len(actual) == 1 and actual[0].state == "SUCCEEDED"
    assert value.launcher.forwards == 1 and len(value.gpu.dispatches) == 1
    assert not hasattr(value.gpu, "numeric")
