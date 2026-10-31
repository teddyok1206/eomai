"""Actual disposable parent/control concurrency and replay; IAM/source leaves synthetic."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from eom_orchestrator.embedding_batch_plan_store import EmbeddingBatchPlanStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.settings import Settings
from eom_workflow_runner import embedding_batch_execution as runtime
from eom_workflow_runner.document_embedding_parent_preparation import (
    prepare_document_embedding_parent,
)
from eom_workflow_runner.embedding_batch_execution import ExistingEmbeddingBatchExecution

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.document_embedding_parent_fixtures import parent_case as parent_case
from tests.unit.test_local_indexing_routed_sources import routed as routed

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def routed_publisher(guarded_engine, tmp_path):
    root = tmp_path / "nas"
    root.mkdir()
    return ControlFileSetPublisher(
        guarded_engine,
        Settings(
            staging_root=tmp_path / "staging",
            nas_artifact_root=root,
            workspace_root=tmp_path,
        ),
    ), guarded_engine


def prepare(value):
    return prepare_document_embedding_parent(value.pair, value.request, value.sources.configuration)


def allocate(value, candidate):
    with (
        value.routed.publisher.sessions.begin() as session,
        candidate.operation.admission.admit(session, candidate.request) as current,
    ):
        return EmbeddingBatchPlanStore(
            candidate.request, current.selection, current.policy
        ).allocate(session, candidate.allocation)


@pytest.mark.parametrize("routed", [None, "public", "registered_public"], indirect=True)
def test_concurrent_original_parent_preparation_and_allocation_have_one_identity_and_dispatch_owner(
    parent_case,
):
    value, gate = parent_case, Barrier(2)

    def start(_index):
        gate.wait(timeout=20)
        return prepare(value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        candidates = tuple(pool.map(start, range(2)))
    assert candidates[0].request == candidates[1].request
    assert candidates[0].allocation != candidates[1].allocation
    with ThreadPoolExecutor(max_workers=2) as pool:
        allocations = tuple(pool.map(lambda candidate: allocate(value, candidate), candidates))
    assert sum(created for _history, created in allocations) == 1
    assert allocations[0][0] == allocations[1][0]
    assert allocations[0][0].state == "CLAIMED"
    assert allocations[0][0].allocation in tuple(c.allocation for c in candidates)


@pytest.mark.parametrize("routed", [None, "public", "registered_public"], indirect=True)
def test_interruption_after_original_allocation_preserves_history_without_another_root(
    parent_case, monkeypatch
):
    value = parent_case
    original = prepare(value)
    history, created = allocate(value, original)
    assert created
    replay = prepare(value)
    assert replay.request == original.request and replay.allocation != original.allocation

    def no_dispatch(*_args, **_kwargs):
        raise AssertionError("replay dispatched another physical root")

    monkeypatch.setattr(runtime, "dispatch_embedding_batch_control", no_dispatch)
    with replay.operation.open(replay.request, replay.allocation) as observed:
        assert type(observed) is ExistingEmbeddingBatchExecution
        assert observed.history == history
    again, created = allocate(value, replay)
    assert not created and again == history


@pytest.mark.parametrize("routed", [None, "public", "registered_public"], indirect=True)
def test_metadata_release_change_replays_exact_original_parent_without_new_allocation(parent_case):
    value = parent_case
    original = prepare(value)
    history, created = allocate(value, original)
    assert created
    value.pair.cuda.controls.source_commit = "b" * 40
    replay = prepare(value)
    assert replay.operation.source_commit == "b" * 40
    assert replay.request == original.request
    again, created = allocate(value, replay)
    assert not created and again == history
