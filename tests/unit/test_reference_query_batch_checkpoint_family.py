"""Real batch allocation/checkpoint contracts; SQL, Identity and physical IO are synthetic."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_workflow.native_reference_query_coordinator import validate_native_reference_query_history
from eom_workflow_runner import reference_query_batch_executor as module
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_registered_public_reference_query_execution import (
    registered_public_workflow_case,
)


@pytest.mark.parametrize("family", ("legacy", "public", "registered"))
def test_batch_allocation_and_replay_keep_the_request_checkpoint_family(monkeypatch, family):
    value = (
        case(device="CUDA")
        if family == "legacy"
        else public_workflow_case(device="CUDA")
        if family == "public"
        else registered_public_workflow_case(device="CUDA")
    )
    expected = (
        "native-reference-query-coordinator/1.2"
        if family == "legacy"
        else "native-reference-query-coordinator/2.0"
    )
    engine = object()
    publisher = SimpleNamespace(engine=engine)
    group = SimpleNamespace(
        publisher=publisher,
        active=SimpleNamespace(request=object()),
        ordinal=Mock(return_value=0),
        assert_available=Mock(),
        assert_gathering=Mock(),
        assert_original_material=Mock(),
        source_commit="a" * 40,
    )
    executor = object.__new__(module.CatalogBatchReferenceQueryExecutor)
    executor.group, executor.publisher = group, publisher
    executor.owner = Mock()
    executor.owner.resolve_execution_sources.return_value = SimpleNamespace(
        policy=value.policy, bundle=value.bundle
    )
    session = Mock()
    session.get_transaction.return_value = SimpleNamespace(is_active=True)
    session.in_nested_transaction.return_value = False
    session.get_bind.return_value = engine
    session.get.return_value = SimpleNamespace(idempotency_key="synthetic-original-query")
    workflow = SimpleNamespace(workflow_id=value.launch.workflow_id)
    step = SimpleNamespace(step_run_id=value.launch.step_run_id)
    lease = CommandLeaseIdentity(value.launch.original_command_id, "test", "test", 1)
    original = None
    records = ()

    def create(_session, *, request, launch):
        nonlocal original
        assert request == value.request and launch == value.launch
        original = launch
        return original

    class Coordinator:
        def __init__(self, request, launch):
            assert request == value.request and launch == value.launch

        def read(self, _session):
            validate_native_reference_query_history(records, value.launch, value.request)
            return SimpleNamespace(state="RUNNING" if records else "CLAIMED", records=records)

        def append(self, _session, record):
            nonlocal records
            # This real guard rejects legacy checkpoints for public QUERY inputs.
            validate_native_reference_query_history((*records, record), value.launch, value.request)
            records = (*records, record)
            return self.read(_session)

    monkeypatch.setattr(
        module, "embedding_batch_query_key", lambda *_args: "synthetic-original-query"
    )
    monkeypatch.setattr(module, "require_batch_query_publication_layout", Mock())
    monkeypatch.setattr(module, "read_native_reference_query_launch", lambda *_a, **_k: original)
    monkeypatch.setattr(module, "create_native_reference_query_launch", create)
    monkeypatch.setattr(
        module,
        "prepare_reference_query_launch_candidate",
        lambda *_a, **_k: SimpleNamespace(association=value.launch, request=value.native_input),
    )
    monkeypatch.setattr(module, "NativeReferenceQueryCoordinator", Coordinator)
    first, history = executor._prepared(session, workflow, step, value.request, lease)
    assert history.records[0].schema_version == expected
    second, replay = executor._prepared(session, workflow, step, value.request, lease)
    assert first == second and history.records == replay.records
    assert len(records) == 1 and records[0].schema_version == expected
    group.assert_gathering.assert_called_once()
