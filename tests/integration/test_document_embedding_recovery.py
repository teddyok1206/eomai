"""Disposable canonical receipt/reservations/publication; explicit synthetic OS/math leaves."""

from unittest.mock import Mock

import pytest
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
    batch_execution_receipt_publication_key,
)
from eom_orchestrator.models import JobRecord
from eom_workflow_runner import document_embedding_cuda_execution as active_module
from eom_workflow_runner import document_embedding_recovery as recovery
from eom_workflow_runner.embedding_batch_execution import ExistingEmbeddingBatchExecution
from eom_workflow_runner.local_embedding_native_executor import CatalogNativeEmbeddingExecutor
from sqlalchemy import select

from tests.integration.test_local_embedding_native_executor import execution as execution
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
def test_planning_success_without_committed_completion_never_regrants_a_model(
    execution, monkeypatch
):
    value = execution
    started = value.start()
    monkeypatch.setattr(
        LocalEmbeddingControlArtifactPublisher,
        "publish_batch_execution_receipt",
        Mock(side_effect=OSError("synthetic completion publication interrupted")),
    )
    with pytest.raises(OSError, match="completion publication interrupted"):
        value.advance(*started)
    assert value.gpu.acked and len(value.gpu.dispatches) == 1
    with (
        value.publisher.sessions.begin() as session,
        value.gpu.operation.admission.admit(session, value.gpu.request) as sources,
    ):
        from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore

        history = EmbeddingBatchPlanStore(
            value.gpu.request, sources.selection, sources.policy
        ).read(session)
        assert history.state == "SUCCEEDED"
    assert (
        recovery.read_document_embedding_completion(value.gpu.operation, value.gpu.request) is None
    )
    with value.gpu.operation.open(value.gpu.request, value.gpu.allocation) as existing:
        assert type(existing) is ExistingEmbeddingBatchExecution
    assert len(value.gpu.dispatches) == 1 and value.launcher.forwards == 0


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
def test_cold_adapter_resumes_original_committed_result_without_channel_or_second_root(
    execution, monkeypatch
):
    value = execution
    started = value.start()
    fail_child_stage = Mock(side_effect=OSError("synthetic child staging interrupted"))
    monkeypatch.setattr(active_module, "stage_batch_document_publication", fail_child_stage)
    with pytest.raises(OSError, match="child staging interrupted"):
        value.advance(*started)
    assert len(value.gpu.dispatches) == 1 and value.gpu.acked
    completed = recovery.read_document_embedding_completion(value.gpu.operation, value.gpu.request)
    assert completed is not None
    assert completed.history.state == "SUCCEEDED"
    with value.sessions() as session:
        assert session.get(type(started[0]), started[0].workflow_id).state == "RUNNING"
    controls = LocalEmbeddingControlArtifactPublisher(value.publisher, source_commit="a" * 40)
    pointer = controls.find_batch_execution_receipt(
        parent_request_sha256=value.gpu.request.request_sha256,
        allocation_record_sha256=completed.history.allocation.record_sha256,
    )
    assert pointer is not None

    # Fresh process-local objects. OS/materialization leaves are intentionally
    # synthetic here; separate file/DAC tests perform actual original-byte reads.
    def original_bytes(receipt, *, authorization):
        assert receipt == completed.receipt
        authorization.authorize_batch()
        assert authorization.batch_request_sha256 == value.gpu.verified.staged.batch.request_sha256
        return value.gpu.verified

    monkeypatch.setattr(recovery, "read_completed_embedding_batch_result", original_bytes)
    value.gpu.channel.require_direct_peer.side_effect = AssertionError("recovery revived root")
    backend = recovery.CatalogRecoveredCudaDocumentEmbeddingExecution(
        value.gpu.operation, value.gpu.request, completed, value.owner, value.request
    )
    executor = CatalogNativeEmbeddingExecutor(
        owner=value.owner,
        publisher=value.publisher,
        execution_backend=backend,
        runtime_profile=value.executor.runtime_profile,
        source_commit=value.executor.source_commit,
    )
    assert value.advance(*started, selected_executor=executor) is True
    value.finish(*started, selected_executor=executor)
    assert len(value.gpu.dispatches) == 1 and value.launcher.forwards == 0
    assert (
        controls.find_batch_execution_receipt(
            parent_request_sha256=value.gpu.request.request_sha256,
            allocation_record_sha256=completed.history.allocation.record_sha256,
        )
        == pointer
    )


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
def test_missing_completion_is_not_success_and_incomplete_receipt_is_not_missing(
    execution, monkeypatch
):
    value = execution
    assert (
        recovery.read_document_embedding_completion(value.gpu.operation, value.gpu.request) is None
    )
    started = value.start()
    monkeypatch.setattr(
        active_module,
        "stage_batch_document_publication",
        Mock(side_effect=OSError("synthetic original staging interruption")),
    )
    with pytest.raises(OSError):
        value.advance(*started)
    completed = recovery.read_document_embedding_completion(value.gpu.operation, value.gpu.request)
    assert completed is not None
    key = batch_execution_receipt_publication_key(
        value.gpu.request.request_sha256, completed.history.allocation.record_sha256
    )
    with value.sessions.begin() as session:
        row = session.scalar(select(JobRecord).where(JobRecord.idempotency_key == key))
        row.status = "FAILED"  # Deliberate isolated corruption fixture only.
        failed_job_id = row.job_id
    with pytest.raises(ControlPlaneError) as failure:
        recovery.read_document_embedding_completion(value.gpu.operation, value.gpu.request)
    assert getattr(failure.value, "code", None) == "CONTROL_FILE_SET_INCOMPLETE"
    with value.sessions() as session:
        assert session.get(JobRecord, failed_job_id).status == "FAILED"
    assert len(value.gpu.dispatches) == 1 and value.launcher.forwards == 0


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
@pytest.mark.parametrize("authority", ("parent", "child"))
def test_completed_canonical_receipt_cannot_bypass_current_source_revocation(
    execution, monkeypatch, authority
):
    value = execution
    started = value.start()
    monkeypatch.setattr(
        active_module,
        "stage_batch_document_publication",
        Mock(side_effect=OSError("synthetic original staging interruption")),
    )
    with pytest.raises(OSError):
        value.advance(*started)
    completed = recovery.read_document_embedding_completion(value.gpu.operation, value.gpu.request)
    assert completed is not None
    if authority == "parent":
        value.gpu.denied = True
        with pytest.raises((ValueError, PermissionError, AssertionError)):
            recovery.read_document_embedding_completion(value.gpu.operation, value.gpu.request)
    else:
        value.current.allowed = False
        with pytest.raises((ValueError, PermissionError, AssertionError)):
            recovery.CatalogRecoveredCudaDocumentEmbeddingExecution(
                value.gpu.operation, value.gpu.request, completed, value.owner, value.request
            )
    assert len(value.gpu.dispatches) == 1 and value.launcher.forwards == 0


@pytest.mark.parametrize("execution", ["cuda"], indirect=True)
@pytest.mark.parametrize("terminal", ("FAILED", "CANCELLED"))
def test_completion_never_reinterprets_a_terminal_workflow_or_creates_a_successor(
    execution, monkeypatch, terminal
):
    value = execution
    started = value.start()
    monkeypatch.setattr(
        active_module,
        "stage_batch_document_publication",
        Mock(side_effect=OSError("synthetic original staging interruption")),
    )
    with pytest.raises(OSError):
        value.advance(*started)
    completed = recovery.read_document_embedding_completion(value.gpu.operation, value.gpu.request)
    assert completed is not None
    with value.sessions.begin() as session:
        row = session.get(type(started[0]), started[0].workflow_id)
        row.state = terminal  # Explicit terminal fixture only, never operating history.
    with pytest.raises(ValueError):
        recovery.CatalogRecoveredCudaDocumentEmbeddingExecution(
            value.gpu.operation, value.gpu.request, completed, value.owner, value.request
        )
    with value.sessions() as session:
        assert session.get(type(started[0]), started[0].workflow_id).state == terminal
    assert len(value.gpu.dispatches) == 1 and value.launcher.forwards == 0
