"""Supervisor-child wiring with declared OS/provider/file/runtime ports; never root proof."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_runtime_files
from eom_identity_service import installed_owner_session_provider
from eom_orchestrator import reference_query_owner_server
from eom_workflow.private_chat_query_owner_configuration import (
    PrivateChatQueryServiceConfiguration,
    private_chat_query_service_configuration_bytes,
)
from eom_workflow_runner import (
    private_chat_query_owner_runtime,
    reference_query_owner_runtime,
)
from eom_workflow_runner import (
    reference_query_owner_entry as module,
)

from tests.unit.test_private_chat_query_owner_configuration import (
    private_body,
    reference_configuration,
)
from tests.unit.test_private_chat_query_source_owner import source as source


@pytest.fixture
def child(source, monkeypatch):
    reference = reference_configuration(source)
    raw = private_chat_query_service_configuration_bytes(
        PrivateChatQueryServiceConfiguration.model_validate(private_body(source, reference))
    )
    events = []
    files = Mock()
    files.assert_unchanged = Mock()
    files.read.side_effect = lambda path, **_: (
        raw if path == module._PRIVATE_CONFIGURATION else b"reference fixture"
    )
    monkeypatch.setattr(embedding_runtime_files, "NumericalRuntimeFileSnapshots", lambda: files)
    monkeypatch.setattr(
        module.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(
            pw_uid={"eom-workflow-runner": 990, "eom-api": 982, "eom-general-chat": 977}[name],
            pw_gid=1000,
        ),
    )
    monkeypatch.setattr(module.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=977))
    for operation in ("setgroups", "setresgid", "setresuid"):
        monkeypatch.setattr(module.os, operation, lambda *_, name=operation: events.append(name))
    monkeypatch.setattr(
        module, "_require_dropped_identity", lambda *_: events.append("dropped_verified")
    )
    monkeypatch.setattr(module.signal, "signal", lambda *_: None)
    monkeypatch.setattr(module.signal, "pthread_sigmask", lambda *_: set())
    monkeypatch.setattr(
        installed_owner_session_provider,
        "ProtectedInstalledIdentityProviderAdmission",
        lambda _: object(),
    )
    runtime = Mock()
    builder = Mock(return_value=runtime)
    private_builder = Mock(return_value=SimpleNamespace(application=Mock()))
    host = Mock()
    server = Mock(return_value=host)
    monkeypatch.setattr(
        reference_query_owner_runtime, "build_reference_query_owner_runtime", builder
    )
    monkeypatch.setattr(
        private_chat_query_owner_runtime, "build_private_chat_query_owner_factory", private_builder
    )
    monkeypatch.setattr(reference_query_owner_server, "ReferenceQueryOwnerServer", server)
    return SimpleNamespace(
        configuration=reference,
        raw=raw,
        files=files,
        runtime=runtime,
        builder=builder,
        private_builder=private_builder,
        server=server,
        host=host,
        events=events,
    )


@pytest.mark.parametrize("enabled", (False, True))
def test_same_dropped_child_and_runtime_own_both_optional_listeners_and_shutdown(child, enabled):
    assert (
        module._serve_child(
            child.configuration,
            object(),
            "sha256:" + "a" * 64,
            set(),
            private_raw=child.raw if enabled else None,
        )
        == 0
    )
    assert child.events == ["setgroups", "setresgid", "setresuid", "dropped_verified"]
    assert child.builder.call_count == 1
    private = child.server.call_args.kwargs["private_queries"]
    if enabled:
        assert private is not None and private.chat_uid == 977
        assert str(private.endpoint.path) == "/run/eom-private-chat-query-owner/prepare.sock"
        assert private.factory is child.private_builder.return_value
        args = child.private_builder.call_args
        assert args.args[0] is child.runtime
        assert args.kwargs["configuration_guard"] == child.files.assert_unchanged
        assert len(child.files.read.call_args_list) == 2
    else:
        assert private is None
        child.private_builder.assert_not_called()
        assert len(child.files.read.call_args_list) == 1
    child.host.serve.assert_called_once_with()
    child.host.close.assert_called_once_with()
    child.runtime.close.assert_called_once_with()


def test_private_startup_failure_closes_existing_runtime_without_binding_either_listener(
    child, capsys
):
    child.private_builder.side_effect = ValueError("DO_NOT_DISCLOSE_CONFIGURATION")
    assert (
        module._serve_child(
            child.configuration, object(), "sha256:" + "a" * 64, set(), private_raw=child.raw
        )
        == 1
    )
    child.server.assert_not_called()
    child.runtime.close.assert_called_once_with()
    assert "DO_NOT_DISCLOSE" not in capsys.readouterr().out


def test_private_configuration_change_fails_before_optional_factory_or_socket(child):
    child.files.read.side_effect = [b"reference fixture", ValueError("synthetic changed bytes")]
    assert (
        module._serve_child(
            child.configuration, object(), "sha256:" + "a" * 64, set(), private_raw=child.raw
        )
        == 1
    )
    child.private_builder.assert_not_called()
    child.server.assert_not_called()
    child.runtime.close.assert_called_once_with()
