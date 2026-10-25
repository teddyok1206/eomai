"""Real disposable START/Runner/claims/registration; OS/GPU/model leaves synthetic."""

import pytest
from eom_workflow_runner.document_embedding_parent_preparation import (
    PreparedDocumentEmbeddingParent,
)
from eom_workflow_runner.document_embedding_routed_execution import (
    DrivenDocumentEmbeddingParent,
    drive_routed_document_embedding_parent_once,
)
from eom_workflow_runner.embedding_batch_execution import ExistingEmbeddingBatchExecution

from tests.integration.test_local_embedding_native_executor import execution as execution
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.mark.parametrize("execution", ["cuda_deferred"], indirect=True)
def test_routed_parent_composes_actual_start_runner_cuda_and_registered_index_without_cpu(
    execution,
):
    value = execution
    parent = PreparedDocumentEmbeddingParent(
        value.gpu.operation, value.gpu.request, value.gpu.allocation
    )
    outcome = drive_routed_document_embedding_parent_once(
        parent, value.gpu.pair, value.request, value.launcher
    )
    assert type(outcome) is DrivenDocumentEmbeddingParent
    assert (
        outcome.device == "CUDA" and outcome.parent_request_sha256 == parent.request.request_sha256
    )
    assert outcome.workflow_request_sha256 == value.request.request_sha256
    assert outcome.workflow_state == "COMPLETED" and outcome.command_state == "SUCCEEDED"
    assert len(value.gpu.dispatches) == 1 and value.gpu.acked
    assert value.launcher.forwards == 0
    replay = drive_routed_document_embedding_parent_once(
        parent, value.gpu.pair, value.request, value.launcher
    )
    assert type(replay) is ExistingEmbeddingBatchExecution
    assert replay.history.state == "SUCCEEDED"
    assert len(value.gpu.dispatches) == 1 and value.launcher.forwards == 0


@pytest.mark.parametrize("execution", ["cuda_deferred"], indirect=True)
def test_revoked_source_stops_routed_parent_before_any_root_or_cpu_dispatch(execution):
    value = execution
    parent = PreparedDocumentEmbeddingParent(
        value.gpu.operation, value.gpu.request, value.gpu.allocation
    )
    value.current.allowed = False
    with pytest.raises((ValueError, AssertionError)):
        drive_routed_document_embedding_parent_once(
            parent, value.gpu.pair, value.request, value.launcher
        )
    assert value.gpu.dispatches == [] and value.launcher.forwards == 0
