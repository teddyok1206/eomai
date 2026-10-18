"""Startup composition; SQL roots, installed provider/OS/runtime reads are declared fixtures."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_orchestrator.native_embedding_query_systemd import FixedNativeQueryLauncher
from eom_orchestrator.native_private_chat_query_systemd import FixedNativePrivateQueryLauncher
from eom_workflow.private_chat_query_owner_configuration import PrivateChatQueryServiceConfiguration
from eom_workflow_runner import private_chat_query_owner_runtime as module
from eom_workflow_runner.native_query_prepare_driver import NativeQueryPrepareDriver
from eom_workflow_runner.reference_query_owner_runtime import ReferenceQueryOwnerRuntime

from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_query_owner_configuration import (
    private_body,
    reference_configuration,
)
from tests.unit.test_private_chat_query_source_owner import make_private_source_case


@pytest.fixture
def source(tmp_path, monkeypatch):
    return make_private_source_case(
        tmp_path,
        monkeypatch,
        resource_profile=reference_prepared().workflow_request.resource_profile,
    )


@pytest.fixture
def startup(source, monkeypatch):
    reference = reference_configuration(source)
    private = PrivateChatQueryServiceConfiguration.model_validate(private_body(source, reference))
    driver = NativeQueryPrepareDriver()
    runtime = ReferenceQueryOwnerRuntime(
        source.publisher.engine,
        reference,
        source.publisher,
        source.owner.settings,
        source.owner.configuration,
        source.policy.spaces,
        FixedNativeQueryLauncher("d" * 64, "e" * 64, lambda: None),
        Mock(),
        driver,
    )
    events = []
    session = Mock()
    session.execute.side_effect = lambda sql: events.append(str(sql))

    @contextmanager
    def root():
        events.append("root_enter")
        try:
            yield session
        finally:
            events.append("root_exit")

    monkeypatch.setattr(source.publisher, "sessions", SimpleNamespace(begin=root))
    provider = Mock()
    database = Mock()
    guard = Mock()
    endpoint = Mock()
    reader = Mock()
    controls = Mock(return_value=(source.policy, source.bundle))
    monkeypatch.setattr(module, "require_current_reference_query_provider", provider)
    monkeypatch.setattr(module, "require_reference_query_database_owner", database)
    monkeypatch.setattr(
        module, "fixed_owner_identity", lambda: SimpleNamespace(owner_uid=990, owner_gid=1000)
    )
    monkeypatch.setattr(module.os, "geteuid", lambda: 990)
    monkeypatch.setattr(module.os, "getegid", lambda: 1000)
    monkeypatch.setattr(module.os, "getgroups", lambda: [])
    monkeypatch.setattr(module, "fixed_private_chat_query_source_endpoint", lambda: endpoint)
    monkeypatch.setattr(module, "PinnedArtifactReadContext", lambda *_: reader)
    monkeypatch.setattr(module, "read_pinned_private_chat_query_controls", controls)

    def installed(actual):
        assert events[-1] == "root_exit"  # No native wait while startup SQL root is held.
        events.append("installed")

    monkeypatch.setattr(FixedNativePrivateQueryLauncher, "assert_current_runtime", installed)
    try:
        yield SimpleNamespace(
            runtime=runtime,
            private=private,
            guard=guard,
            provider=provider,
            database=database,
            endpoint=endpoint,
            controls=controls,
            reader=reader,
            session=session,
            events=events,
        )
    finally:
        driver.close()


def build(startup):
    return module.build_private_chat_query_owner_factory(
        startup.runtime, startup.private, configuration_guard=startup.guard
    )


def test_optional_private_factory_shares_existing_engine_publisher_and_driver(startup):
    factory = build(startup)
    assert factory.engine is startup.runtime.engine
    assert factory.publisher is startup.runtime.publisher
    assert factory.driver is startup.runtime.driver
    assert factory.configuration_guard is startup.guard
    assert factory.chat.endpoint is startup.endpoint
    assert (
        factory.launcher.assert_runtime_current is startup.runtime.launcher.assert_runtime_current
    )
    assert factory.operator_owner.role_name == "eom_app"
    assert factory.operator_owner.role_oid == startup.runtime.configuration.database_owner.role_oid
    assert factory.configuration.native_execution_policy == startup.private.native_execution_policy
    assert startup.events == ["root_enter", "SET TRANSACTION READ ONLY", "root_exit", "installed"]
    startup.endpoint.require_socket.assert_called_once_with()
    startup.reader.revalidate_provenance.assert_called_once_with()
    assert startup.guard.call_count == startup.provider.call_count == 2
    assert not startup.runtime.driver.observe().active


@pytest.mark.parametrize(
    "fault",
    (
        "baseline",
        "guard",
        "provider",
        "uid",
        "gid",
        "groups",
        "source",
        "database",
        "controls",
        "runtime",
        "late_guard",
        "space",
    ),
)
def test_wrong_current_configuration_source_or_runtime_never_starts_work(
    startup, monkeypatch, fault
):
    value = startup
    if fault == "baseline":
        value.private = value.private.model_copy(
            update={"reference_configuration_raw_sha256": "sha256:" + "0" * 64}
        )
    elif fault == "guard":
        value.guard.side_effect = ValueError("synthetic configuration replaced")
    elif fault == "late_guard":
        value.guard.side_effect = [None, ValueError("synthetic configuration replaced")]
    elif fault == "provider":
        value.provider.side_effect = ValueError("synthetic provider changed")
    elif fault == "uid":
        monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    elif fault == "gid":
        monkeypatch.setattr(module.os, "getegid", lambda: 0)
    elif fault == "groups":
        monkeypatch.setattr(module.os, "getgroups", lambda: [1000])
    elif fault == "source":
        value.endpoint.require_socket.side_effect = ValueError("synthetic socket changed")
    elif fault == "database":
        value.database.side_effect = ValueError("synthetic database owner changed")
    elif fault == "controls":
        value.controls.side_effect = ValueError("synthetic canonical control mismatch")
    elif fault == "runtime":

        def denied(_actual):
            raise ValueError("synthetic installed runtime changed")

        monkeypatch.setattr(FixedNativePrivateQueryLauncher, "assert_current_runtime", denied)
    else:
        value.private = value.private.model_copy(
            update={
                "namespace": value.private.namespace.model_copy(
                    update={"space_sha256": "sha256:" + "0" * 64}
                )
            }
        )
    with pytest.raises(ValueError):
        build(value)
    assert not value.runtime.driver.observe().active
    if fault in {"baseline", "guard", "provider", "uid", "gid", "groups", "source", "space"}:
        value.controls.assert_not_called()
    if fault == "baseline":
        value.guard.assert_not_called()


def test_foreign_runtime_or_noncallable_snapshot_guard_is_rejected(startup):
    with pytest.raises(ValueError, match="COMPOSITION_INVALID"):
        module.build_private_chat_query_owner_factory(
            object(), startup.private, configuration_guard=startup.guard
        )
    with pytest.raises(ValueError, match="COMPOSITION_INVALID"):
        module.build_private_chat_query_owner_factory(
            startup.runtime, startup.private, configuration_guard=None
        )
    startup.guard.assert_not_called()
