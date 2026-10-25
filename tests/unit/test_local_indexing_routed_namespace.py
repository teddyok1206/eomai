"""Real prepared control IO, synthetic queue/numerical leaves; not runtime admission."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_orchestrator.native_embedding_index_systemd import FixedNativeIndexLauncher
from eom_workflow_runner import local_indexing_routed_namespace as namespace
from eom_workflow_runner.document_embedding_routed_execution import DrivenDocumentEmbeddingParent
from eom_workflow_runner.embedding_batch_execution import ExistingEmbeddingBatchExecution
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingReconciliationResult,
    PreparedLocalEmbeddingReconciliation,
    ReconciliationState,
)

from tests.unit.document_embedding_parent_fixtures import parent_case as parent_case
from tests.unit.test_local_indexing_routed_sources import routed as routed
from tests.unit.test_local_indexing_routed_sources import routed_publisher as routed_publisher


@pytest.fixture
def service(parent_case, monkeypatch):
    case = parent_case
    runner = Mock()
    factory = Mock(return_value=runner)
    monkeypatch.setattr(namespace, "build_local_indexing_workflow_runner", factory)
    peek = Mock(return_value=None)
    monkeypatch.setattr(namespace, "peek_command_candidate", peek)
    launcher = Mock(spec=FixedNativeIndexLauncher)
    value = namespace.RoutedLocalIndexingNamespaceRuntime(
        case.pair, case.sources.configuration, launcher, case.routed.fence
    )
    observed = LocalEmbeddingReconciliationResult(
        ReconciliationState.PREPARED,
        case.request.graph_snapshot.graph_snapshot_revision_id,
        selected_target_count=len(case.plan.sources),
        missing_binding_count=len(case.plan.sources),
    )
    prepare = Mock(return_value=PreparedLocalEmbeddingReconciliation(observed, case.request))
    monkeypatch.setattr(case.pair.cuda, "prepare_once", prepare)
    drive = Mock(
        return_value=DrivenDocumentEmbeddingParent(
            "CUDA",
            "sha256:" + "1" * 64,
            case.request.request_sha256,
            "workflow_" + "1" * 32,
            "wfcmd_" + "2" * 32,
            "COMPLETED",
            "SUCCEEDED",
        )
    )
    monkeypatch.setattr(namespace, "drive_routed_document_embedding_parent_once", drive)
    monkeypatch.setattr(namespace, "prepare_document_catch_up_parent", lambda base, *_args: base)
    return SimpleNamespace(
        value=value,
        case=case,
        runner=runner,
        prepare=prepare,
        drive=drive,
        peek=peek,
        factory=factory,
    )


def test_original_cpu_queue_is_drained_without_new_gpu_discovery(service):
    command = service.runner.run_once.return_value
    assert service.value.run_once() is command
    service.runner.run_once.assert_called_once()
    service.prepare.assert_not_called()
    service.drive.assert_not_called()


def test_new_gpu_reconciliation_pins_original_and_distinguishes_batch_from_corpus_completion(
    service,
):
    result = service.value.reconcile_once()
    assert result.state is ReconciliationState.BATCH_COMPLETED
    assert result.selected_target_count == len(service.case.plan.sources)
    assert result.workflow_state == "COMPLETED" and result.command_state == "SUCCEEDED"
    parent, pair, original, launcher = service.drive.call_args.args
    assert parent.request.parent_request_sha256 == original.request_sha256
    assert pair is service.case.pair and original == service.case.request
    assert launcher is service.value.launcher
    assert service.case.routed.guard.call_count > 0


def test_no_work_observation_does_not_allocate_or_submit_model_work(service):
    service.prepare.return_value = PreparedLocalEmbeddingReconciliation(
        LocalEmbeddingReconciliationResult(ReconciliationState.UP_TO_DATE, "graph")
    )
    assert service.value.reconcile_once().state is ReconciliationState.UP_TO_DATE
    service.drive.assert_not_called()


def test_planning_success_cannot_be_reported_as_child_numerical_completion(service):
    service.drive.return_value = ExistingEmbeddingBatchExecution(SimpleNamespace(state="SUCCEEDED"))
    assert service.value.reconcile_once().state is ReconciliationState.RECOVERY_REQUIRED


def test_other_original_workflow_is_not_replaced_by_new_source_discovery(service, monkeypatch):
    monkeypatch.setattr(
        service.value, "_pending_gpu", lambda: (service.case.request, "original", "foreign-key")
    )
    result = service.value.reconcile_once()
    assert (
        result.state is ReconciliationState.RECOVERY_REQUIRED and result.workflow_id == "original"
    )
    service.prepare.assert_not_called()
    service.drive.assert_not_called()


def test_current_service_fence_precedes_even_queue_header_read(service):
    service.case.routed.current.deny = True
    with pytest.raises(PermissionError):
        service.value.reconcile_once()
    service.peek.assert_not_called()
    service.prepare.assert_not_called()
    service.drive.assert_not_called()
