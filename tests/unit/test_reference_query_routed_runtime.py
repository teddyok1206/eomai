"""Installed/canonical-control leaves synthetic; actual current-owner composition exercised."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_workflow.reference_query_owner_configuration import (
    validate_supported_reference_query_service_configuration,
)
from eom_workflow.reference_query_routed_owner_configuration import (
    RoutedReferenceQueryOwnerConfiguration,
)
from eom_workflow_runner import reference_query_routed_runtime as module
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.reference_query_owner_runtime import ReferenceQueryOwnerRuntime
from eom_workflow_runner.reference_query_prepare_application import NativeReferenceQueryPreparation
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from eom_workflow_runner.reference_query_source_read import ReferenceQueryOwnerConfiguration

from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_routed_owner_configuration import selected as selected


@pytest.fixture
def installed(source, selected, monkeypatch):
    body, routing, cpu, cuda = selected
    config = RoutedReferenceQueryOwnerConfiguration.model_validate(body)
    base = validate_supported_reference_query_service_configuration(config.cpu_configuration)
    registry = EmbeddingRegistryOwnerConfiguration(
        base.corpus_id, base.namespace, cpu.spaces.document, base.recipe, base.source_classes
    )
    owner_config = ReferenceQueryOwnerConfiguration(
        registry,
        base.native_execution_policy,
        base.native_execution_policy_sha256,
        base.runtime_bundle,
    )
    runtime = ReferenceQueryOwnerRuntime(
        source.publisher.engine,
        base,
        source.publisher,
        source.owner.settings,
        owner_config,
        cpu.spaces,
        Mock(),
        Mock(),
        ReferenceQueryPrepareDriver(),
    )
    events = []
    session = Mock()
    session.execute.side_effect = lambda sql: events.append(str(sql))

    @contextmanager
    def root():
        events.append("root_enter")
        yield session
        events.append("root_exit")

    monkeypatch.setattr(source.publisher, "sessions", SimpleNamespace(begin=root))
    guard = Mock()
    provider = Mock()
    reader = Mock()
    controls = Mock(side_effect=((cpu, Mock()), (cuda, Mock())))
    monkeypatch.setattr(module, "require_current_reference_query_provider", provider)
    monkeypatch.setattr(module, "require_reference_query_database_owner", Mock())
    monkeypatch.setattr(
        module, "fixed_owner_identity", lambda: SimpleNamespace(owner_uid=990, owner_gid=1000)
    )
    monkeypatch.setattr(module.os, "geteuid", lambda: 990)
    monkeypatch.setattr(module.os, "getegid", lambda: 1000)
    monkeypatch.setattr(module.os, "getgroups", lambda: [])
    monkeypatch.setattr(module, "PinnedArtifactReadContext", lambda *_a: reader)
    monkeypatch.setattr(module, "resolve_embedding_device_routing_policy", lambda *_a: routing)
    monkeypatch.setattr(module, "read_selected_reference_query_controls", controls)
    applications = []

    def current_cpu(actual_runtime, capture):
        assert actual_runtime is runtime and capture is source.owner.identity.capture
        owner = CatalogReferenceQueryOwnerAdmission(
            runtime.engine,
            owner_config,
            capture=capture,
            session_fence=source.owner.identity.fence,
            settings=runtime.catalog_settings,
        )
        app = Mock(spec=NativeReferenceQueryPreparation)
        app.owner = owner
        applications.append(app)
        return app

    monkeypatch.setattr(ReferenceQueryOwnerRuntime, "application", current_cpu)
    return SimpleNamespace(
        runtime=runtime,
        config=config,
        routing=routing,
        cpu=cpu,
        cuda=cuda,
        guard=guard,
        provider=provider,
        reader=reader,
        controls=controls,
        events=events,
        applications=applications,
        capture=source.owner.identity.capture,
    )


def build(installed):
    return module.build_routed_reference_query_owner_factory(
        installed.runtime, installed.config, configuration_guard=installed.guard
    )


def test_read_only_factory_reuses_existing_lifecycle_and_separates_each_capture_operation(
    installed,
):
    factory = build(installed)
    assert installed.events == ["root_enter", "SET TRANSACTION READ ONLY", "root_exit"]
    assert not installed.applications
    a, b = factory.session(installed.capture), factory.session(installed.capture)
    assert a.cpu is not b.cpu and a.selection is not b.selection
    assert a.selection.cpu is a.cpu.owner and b.selection.cpu is b.cpu.owner
    assert (
        a.selection.cpu.identity.capture is a.selection.cuda.identity.capture is installed.capture
    )
    assert a.selection.cpu.identity.fence is a.selection.cuda.identity.fence
    assert (
        a.selection.cuda.configuration.registry.namespace.space_sha256
        == installed.cuda.spaces.document.space_sha256
    )
    assert (
        a.selection.cpu.configuration.registry.namespace.space_sha256
        == installed.cpu.spaces.document.space_sha256
    )
    assert (
        a.selection.cpu.catalog.engine
        is a.selection.cuda.catalog.engine
        is installed.runtime.engine
    )
    assert factory.runtime.driver is installed.runtime.driver
    assert not hasattr(factory, "capture")
    installed.reader.revalidate_provenance.assert_called_once()


@pytest.mark.parametrize(
    "fault",
    (
        "account",
        "supplementary_group",
        "configuration_guard",
        "cpu_configuration",
        "foreign_cuda_policy",
        "provider",
    ),
)
def test_unavailable_or_mixed_release_fails_without_constructing_human_or_starting_work(
    installed, monkeypatch, fault
):
    if fault == "account":
        monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    elif fault == "supplementary_group":
        monkeypatch.setattr(module.os, "getgroups", lambda: [0])
    elif fault == "configuration_guard":
        installed.guard.side_effect = ValueError("synthetic installed selection changed")
    elif fault == "provider":
        installed.provider.side_effect = ValueError("synthetic provider changed")
    elif fault == "cpu_configuration":
        body = installed.config.model_dump(mode="json")
        body["cpu_configuration"]["owner_source_commit"] = "e" * 40
        installed.config = RoutedReferenceQueryOwnerConfiguration.model_validate(body)
    else:
        installed.controls.side_effect = ((installed.cpu, Mock()), (installed.cpu, Mock()))
    with pytest.raises(ValueError):
        build(installed)
    assert not installed.applications


def test_changed_installed_selection_is_rechecked_before_every_new_operation(installed):
    factory = build(installed)
    installed.guard.side_effect = ValueError("synthetic withdrawn selection")
    with pytest.raises(ValueError, match="withdrawn"):
        factory.session(installed.capture)
    assert not installed.applications
