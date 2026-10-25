"""Actual source/control reads, synthetic Workflow/identity/root/compute; not live GPU evidence."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from eom_workflow_runner import document_embedding_cuda_execution as module
from eom_workflow_runner.document_embedding_execution import DocumentExecutionState
from eom_workflow_runner.embedding_batch_execution import ActiveEmbeddingBatchExecution

from tests.unit.document_embedding_cuda_fixtures import document_cuda_case


@pytest.fixture
def cuda(tmp_path, monkeypatch):
    value = document_cuda_case(tmp_path, monkeypatch)
    value.stage = Mock(return_value="synthetic-publication-boundary")
    monkeypatch.setattr(module, "stage_batch_document_publication", value.stage)
    yield value
    value.engine.dispose()


def test_original_namespace_rows_execute_once_and_publication_replay_never_revives_root(cuda):
    value = cuda
    adapter, work = value.adapter, value.work
    adapter.assert_current_runtime(value.fixture.request)
    assert adapter.observe(work.association.intent) is DocumentExecutionState.NOT_STARTED
    assert (
        adapter.execute(work, source=value.source, transaction=value.transaction)
        == "synthetic-publication-boundary"
    )
    assert len(value.runs) == 1
    binding, batch = value.runs[0]
    assert batch.purpose == "DOCUMENT" and len(batch.children) == 1
    assert batch.children[0].request == work.request and len(work.request.rows) == 2
    assert binding.children[0].workflow_id == work.association.intent.workflow_id
    assert binding.children[0].selection_sha256 == adapter.active.request.child_selection_sha256s[0]
    adapter.active.channel.require_direct_peer.side_effect = AssertionError("replay revived root")
    adapter.assert_current_runtime(value.fixture.request)
    assert adapter.observe(work.association.intent) is DocumentExecutionState.SUCCEEDED
    adapter.execute(work, source=value.source, transaction=value.transaction)
    assert len(value.runs) == 1 and value.stage.call_count == 2


@pytest.mark.parametrize("fault", ("key", "request", "actor"))
def test_foreign_parent_equivalent_workflow_cannot_be_reported_fresh_or_executed(cuda, fault):
    if fault == "key":
        cuda.workflow.idempotency_key = "another-original-parent"
    elif fault == "request":
        cuda.workflow.initial_request = {}
    else:
        cuda.workflow.created_actor_id = "operator_" + "f" * 32
    with pytest.raises(ValueError):
        cuda.adapter.observe(cuda.work.association.intent)
    with pytest.raises(ValueError):
        cuda.adapter.execute(cuda.work, source=cuda.source, transaction=cuda.transaction)
    assert cuda.runs == [] and cuda.stage.call_count == 0


def test_hash_source_denial_and_native_failure_do_not_fallback_or_regrant(cuda, monkeypatch):
    cuda.source.resolve_launch.side_effect = PermissionError("source revoked")
    with pytest.raises(PermissionError):
        cuda.adapter.execute(cuda.work, source=cuda.source, transaction=cuda.transaction)
    assert cuda.runs == []
    cuda.source.resolve_launch.side_effect = None
    run = Mock(side_effect=ValueError("synthetic original execution failure"))
    monkeypatch.setattr(ActiveEmbeddingBatchExecution, "run", run)
    with pytest.raises(ValueError):
        cuda.adapter.execute(cuda.work, source=cuda.source, transaction=cuda.transaction)
    assert cuda.adapter.observe(cuda.work.association.intent) is DocumentExecutionState.UNCERTAIN
    with pytest.raises(ValueError):
        cuda.adapter.execute(cuda.work, source=cuda.source, transaction=cuda.transaction)
    assert run.call_count == 1 and cuda.stage.call_count == 0


def test_child_materialization_interruption_reuses_committed_original_compute(cuda):
    cuda.stage.side_effect = OSError("synthetic publication interruption")
    with pytest.raises(OSError):
        cuda.adapter.execute(cuda.work, source=cuda.source, transaction=cuda.transaction)
    assert cuda.adapter.observe(cuda.work.association.intent) is DocumentExecutionState.SUCCEEDED
    cuda.stage.side_effect = None
    cuda.adapter.execute(cuda.work, source=cuda.source, transaction=cuda.transaction)
    assert len(cuda.runs) == 1 and cuda.stage.call_count == 2


def test_parent_source_coverage_mismatch_cannot_grant_partial_selection(cuda):
    cuda.source.resolve_launch.return_value.scope.plan = type(cuda.fixture.plan).model_validate(
        cuda.fixture.plan.model_dump(mode="json")
    )
    # A different source-set witness is never inferred from just the owned subset.
    from tests.unit.local_embedding_admission_fixtures import native_fixture

    cuda.source.resolve_launch.return_value.scope.plan = native_fixture("c", device="CUDA").plan
    with pytest.raises(ValueError):
        cuda.adapter.execute(cuda.work, source=cuda.source, transaction=cuda.transaction)
    assert cuda.runs == []
