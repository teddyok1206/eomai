"""Closed config5 runtime composition with synthetic OS/SQL leaves; no activation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import canonical_json_bytes
from eom_identity_service.local_indexing_runtime import AuthenticatedLocalIndexingRuntime
from eom_workflow.local_indexing_owner_configuration import (
    parse_cpu_local_indexing_owner_configuration,
)
from eom_workflow.local_indexing_routed_owner_configuration import (
    RoutedLocalIndexingOwnerConfiguration,
    local_indexing_routed_owner_configuration_bytes,
)
from eom_workflow_runner import local_indexing_service_runtime as runtime

from tests.unit.test_local_indexing_dual_projection_owner import compose
from tests.unit.test_local_indexing_routed_owner_configuration import routed_document


def test_only_executable_dispatcher_explicitly_accepts_routed5_and_preserves_poll_cadence():
    body, _policy = routed_document(dual=True)
    selected = RoutedLocalIndexingOwnerConfiguration.model_validate(body)
    wire = local_indexing_routed_owner_configuration_bytes(selected)
    assert runtime.parse_indexing_service_configuration(wire) == selected
    assert selected.poll_interval_seconds == selected.cpu_configuration.poll_interval_seconds
    with pytest.raises(ValueError):
        parse_cpu_local_indexing_owner_configuration(wire)
    for raw in (
        wire + b"\n",
        canonical_json_bytes(body | {"roles": ["ADMIN"]}),
        b" " * (65536 + 1),
    ):
        with pytest.raises(ValueError):
            runtime.parse_indexing_service_configuration(raw)


def runtime_case(monkeypatch):
    case = compose(monkeypatch)
    body, _policy = routed_document(dual=True)
    selected = RoutedLocalIndexingOwnerConfiguration.model_validate(body)
    monkeypatch.setattr(
        AuthenticatedLocalIndexingRuntime,
        "read_owner_configuration",
        lambda _self: local_indexing_routed_owner_configuration_bytes(selected),
    )
    pairs = tuple(SimpleNamespace(namespace=index) for index in range(6))
    sources = Mock(return_value=SimpleNamespace(namespaces=pairs))
    namespace = Mock(side_effect=lambda pair, *_args: pair)
    monkeypatch.setattr(runtime, "build_routed_indexing_sources", sources)
    monkeypatch.setattr(runtime, "RoutedLocalIndexingNamespaceRuntime", namespace)
    return case, selected, sources, namespace


def test_actual_capture_and_preflight_compose_six_routed_namespaces_without_old_cpu_discovery(
    monkeypatch,
):
    case, selected, sources, namespace = runtime_case(monkeypatch)
    value = runtime.build_local_indexing_service_runtime(case.capture, case.pin)
    assert value.configuration == selected and len(value.namespaces) == 6
    case.current.assert_called_once()
    sources.assert_called_once()
    assert sources.call_args.args[2].pin == case.pin
    assert sources.call_args.args[3] == selected
    assert namespace.call_count == 6 and case.owners == []
    assert all(call.args[3] is sources.call_args.args[2] for call in namespace.call_args_list)
    case.launcher.return_value.assert_current_runtime.assert_called_once()
    runtime.EmbeddingEncodingReservationStorage.require_mixed_ownership_protocol.assert_called_once()


def test_routed_source_denial_disposes_runtime_without_falling_back_to_cpu_discovery(monkeypatch):
    case, _selected, sources, namespace = runtime_case(monkeypatch)
    sources.side_effect = PermissionError("synthetic current routed grant denied")
    with pytest.raises(PermissionError):
        runtime.build_local_indexing_service_runtime(case.capture, case.pin)
    case.engine.dispose.assert_called_once()
    namespace.assert_not_called()
    assert case.owners == []
