"""Pinned public counterpart preparation; source/IAM/queue leaves explicitly synthetic."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import pytest
from eom_workflow_runner.local_embedding_service_reconciliation import (
    LocalEmbeddingServicePreparation,
)
from eom_workflow_runner.local_indexing_routed_namespace import RoutedLocalIndexingNamespaceRuntime

from tests.unit.test_local_embedding_source_plan_v3 import inputs
from tests.unit.test_public_solution_native_carriers import public_native_fixture


def preparation(*, public=True):
    fixture = public_native_fixture()
    request = fixture["request"]
    _, resolved, _ = inputs()
    namespace = request.namespace if public else fixture["original"]["request"].namespace
    registry = NS(corpus_id=request.corpus_id, namespace=namespace)
    root = object()
    sessions = MagicMock()
    settings = NS(nas_artifact_root="synthetic-same-root")
    caller = object()
    owner = NS(
        configuration=NS(registry=registry),
        settings=settings,
        resolve_reconciliation_controls=Mock(return_value=NS(caller=caller)),
        catalog=NS(resolve_selected_sources=Mock(return_value=resolved)),
        current_reconciliation_lookup=Mock(side_effect=AssertionError("must not reselect latest")),
    )
    counterpart_owner = NS(
        settings=settings,
        resolve_sources=Mock(return_value=NS(admission=NS(plan=fixture["plan"]))),
        registry_caller=Mock(return_value=caller),
        fence_current_actor=Mock(),
    )
    cpu = object.__new__(LocalEmbeddingServicePreparation)
    gpu = object.__new__(LocalEmbeddingServicePreparation)
    cpu.publisher = NS(engine=root, sessions=sessions)
    gpu.publisher = NS(engine=root)
    cpu.owner, gpu.owner = owner, counterpart_owner
    cpu.runtime_profile = object()
    cpu._prepare_request = Mock(return_value=request)
    return NS(**locals())


@pytest.mark.parametrize("maximum_sources", (1025, 16384))
def test_public_declared_population_uses_original_scope_not_newer_graph(maximum_sources):
    value = preparation()
    result = value.cpu.prepare_matching(value.gpu, value.request, maximum_sources=maximum_sources)
    assert result == value.request
    scope = value.owner.catalog.resolve_selected_sources.call_args.args[2].scope
    assert scope.maximum_sources == maximum_sources
    assert scope.graph_snapshot == value.request.graph_snapshot
    assert scope.policy_revision_id == value.request.access_policy_revision_id
    assert value.owner.catalog.resolve_selected_sources.call_args.args[
        2
    ].source_revision_ids == tuple(
        sorted(source.item_revision_id for source in value.fixture["plan"].sources)
    )
    value.owner.current_reconciliation_lookup.assert_not_called()
    value.counterpart_owner.fence_current_actor.assert_called_once()


@pytest.mark.parametrize("public,maximum", ((True, 16385), (False, 1025), (True, True), (True, 0)))
def test_cap_or_type_failure_precedes_source_work(public, maximum):
    value = preparation(public=public)
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        value.cpu.prepare_matching(value.gpu, value.request, maximum_sources=maximum)
    value.counterpart_owner.resolve_sources.assert_not_called()
    value.owner.catalog.resolve_selected_sources.assert_not_called()


def test_public_matching_rechecks_authority_before_creating_a_cpu_request():
    value = preparation()
    value.owner.resolve_reconciliation_controls.side_effect = ValueError("SOURCE_FORBIDDEN")
    with pytest.raises(ValueError, match="SOURCE_FORBIDDEN"):
        value.cpu.prepare_matching(value.gpu, value.request, maximum_sources=16384)
    value.cpu._prepare_request.assert_not_called()
    value.owner.catalog.resolve_selected_sources.assert_not_called()


@pytest.mark.parametrize("deny", (False, True))
def test_public_standby_delegates_original_request_to_existing_matching_and_start(deny):
    request = public_native_fixture()["request"]
    value = object.__new__(RoutedLocalIndexingNamespaceRuntime)
    matching = Mock(return_value=request)
    value.pair = NS(cpu=NS(prepare_matching=matching), cuda=object(), maximum_sources=16384)
    value.cpu_reconciliation = NS(run_once=Mock(), submit_prepared=Mock())
    if deny:
        matching.side_effect = ValueError("SOURCE_FORBIDDEN")
        with pytest.raises(ValueError, match="SOURCE_FORBIDDEN"):
            value._queue_cpu_standby(request)
        value.cpu_reconciliation.submit_prepared.assert_not_called()
    else:
        value._queue_cpu_standby(request)
        prepared = value.cpu_reconciliation.submit_prepared.call_args.args[0]
        assert prepared.request is request
        assert (
            prepared.observed.graph_snapshot_revision_id
            == request.graph_snapshot.graph_snapshot_revision_id
        )
    matching.assert_called_once_with(value.pair.cuda, request, maximum_sources=16384)
    value.cpu_reconciliation.run_once.assert_not_called()
