"""Real dual Unix sockets/global capacity; provider/source/native authority are fixtures."""

import os
import socket
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)
from eom_orchestrator import reference_query_owner_server as module
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_orchestrator.private_chat_query_prepare_client import PrivateChatQueryPrepareClient

from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_private_chat_query_prepare_exchange import case as case
from tests.unit.test_reference_query_prepare_contracts import request_body


def endpoints(root):
    result = []
    for name in ("api", "chat"):
        parent = Path(root) / name
        parent.mkdir(mode=0o2750)
        parent.chmod(0o2750)
        result.append(
            ChatSocketEndpoint(parent / "owner.sock", os.getuid(), os.getgid(), parent_mode=0o2750)
        )
    return tuple(result)


@pytest.fixture
def profile(tmp_path, observation, case):
    api, chat = endpoints(tmp_path)
    application = SimpleNamespace(execute=Mock(side_effect=case.dispatch.execute))
    factory = SimpleNamespace(application=Mock(return_value=application))
    return SimpleNamespace(
        api=api,
        chat=chat,
        application=application,
        factory=factory,
        admission=ProtectedInstalledIdentityProviderAdmission(observation[0]),
        api_factory=Mock(side_effect=AssertionError("private cannot use API capture")),
        private=module.PrivateChatQueryListener(chat, os.getuid(), factory),
    )


def server(profile):
    return module.ReferenceQueryOwnerServer(
        endpoint=profile.api,
        api_uid=os.getuid() + 1,
        admission=profile.admission,
        application=profile.api_factory,
        private_queries=profile.private,
    )


@pytest.fixture
def running(profile):
    host = server(profile)
    thread = Thread(target=host.serve)
    thread.start()
    try:
        yield host
    finally:
        host.close()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert not profile.api.path.exists() and not profile.chat.path.exists()


def test_private_listener_authorizes_original_with_one_factory_and_no_api_capture(
    case, profile, running
):
    reply = PrivateChatQueryPrepareClient(profile.chat).execute(case.request)
    assert reply.status == "PENDING"
    profile.factory.application.assert_called_once_with(case.request.origin)
    profile.application.execute.assert_called_once_with(case.request)
    profile.api_factory.assert_not_called()
    assert running.pool._max_workers == 4


def test_private_peer_cannot_select_api_profile_by_sending_private_document(case, profile, running):
    with pytest.raises(ChatTransportError):
        PrivateChatQueryPrepareClient(profile.api).execute(case.request)
    profile.factory.application.assert_not_called()
    profile.api_factory.assert_not_called()


def test_reference_document_on_private_listener_never_attempts_human_capture(profile, running):
    with pytest.raises(ChatTransportError):
        exchange_chat_frame(
            profile.chat, request_body(), request_limit=32768, reply_limit=32768, timeout=3
        )
    profile.factory.application.assert_not_called()
    profile.api_factory.assert_not_called()


def test_wrong_private_peer_is_rejected_before_provider_or_factory(case, profile, monkeypatch):
    profile.private = replace(profile.private, chat_uid=os.getuid() + 2)
    host = server(profile)
    observed = Mock(side_effect=AssertionError("wrong peer cannot trigger provider reads"))
    monkeypatch.setattr(ProtectedInstalledIdentityProviderAdmission, "assert_current", observed)
    thread = Thread(target=host.serve)
    thread.start()
    try:
        with pytest.raises(ChatTransportError):
            PrivateChatQueryPrepareClient(profile.chat).execute(case.request)
        observed.assert_not_called()
        profile.factory.application.assert_not_called()
    finally:
        host.close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_changed_installed_provider_denies_private_factory_without_capture(
    case, profile, observation, running
):
    observation[1]["MainPID"] = "12346"
    with pytest.raises(ChatTransportError):
        PrivateChatQueryPrepareClient(profile.chat).execute(case.request)
    profile.factory.application.assert_not_called()
    profile.api_factory.assert_not_called()


def test_private_origin_factory_failure_is_one_redacted_final_response(case, profile, running):
    profile.factory.application.side_effect = RuntimeError("DO_NOT_DISCLOSE_SOURCE")
    reply = PrivateChatQueryPrepareClient(profile.chat).execute(case.request)
    assert reply.status == "FAILED" and reply.error_code == "PRIVATE_CHAT_QUERY_UNAVAILABLE"
    assert profile.factory.application.call_count == 1
    profile.application.execute.assert_not_called()


@pytest.mark.parametrize("extra_profile", ("api", "chat"))
def test_both_listeners_share_four_handlers_without_task_backlog(
    profile, monkeypatch, extra_profile
):
    # Handler behavior is deliberately synthetic here: this proves global finite
    # capacity, not two real service UIDs or authenticated API execution.
    entered, release = Event(), Event()
    calls = []

    def hold(_connection, **_kwargs):
        calls.append(1)
        if len(calls) == 4:
            entered.set()
        assert release.wait(timeout=10)

    monkeypatch.setattr(module, "handle_reference_query_prepare_connection", hold)
    monkeypatch.setattr(module, "handle_private_chat_query_prepare_connection", hold)
    host = server(profile)
    thread = Thread(target=host.serve)
    thread.start()
    clients = []
    try:
        for endpoint in (profile.api, profile.chat, profile.api, profile.chat):
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            clients.append(client)
            client.connect(str(endpoint.path))
        assert entered.wait(timeout=3)
        endpoint = profile.api if extra_profile == "api" else profile.chat
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as extra:
            extra.settimeout(3)
            extra.connect(str(endpoint.path))
            assert extra.recv(1) == b""
        assert len(calls) == 4
        profile.factory.application.assert_not_called()
    finally:
        release.set()
        for client in clients:
            client.close()
        host.close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    "fault", ("same_uid", "root_uid", "owner", "mode", "parent", "path", "factory")
)
def test_invalid_private_profile_is_rejected_before_any_socket_bind(profile, monkeypatch, fault):
    private = profile.private
    if fault == "same_uid":
        private = replace(private, chat_uid=os.getuid() + 1)
    elif fault == "root_uid":
        private = replace(private, chat_uid=0)
    elif fault == "owner":
        private = replace(private, endpoint=replace(private.endpoint, owner_uid=os.getuid() + 1))
    elif fault == "mode":
        private = replace(private, endpoint=replace(private.endpoint, parent_mode=0o750))
    elif fault == "parent":
        private = replace(
            private, endpoint=replace(private.endpoint, path=profile.api.path.parent / "other.sock")
        )
    elif fault == "path":
        private = replace(private, endpoint=profile.api)
    else:
        private = replace(private, factory=object())
    profile.private = private
    bind = Mock(side_effect=AssertionError("invalid profile must not bind"))
    monkeypatch.setattr(module, "bind_chat_listener", bind)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_LISTENER_UNAVAILABLE"):
        server(profile)
    bind.assert_not_called()


def test_failed_second_bind_removes_only_owned_first_socket_and_preserves_foreign(profile):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as foreign:
        foreign.bind(str(profile.chat.path))
        profile.chat.path.chmod(0o660)
        before = profile.chat.path.lstat()
        with pytest.raises(ChatTransportError):
            server(profile)
        assert not profile.api.path.exists()
        after = profile.chat.path.lstat()
        assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)


def test_shutdown_preserves_replacement_private_socket_and_removes_owned_api_socket(profile):
    host = server(profile)
    profile.chat.path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as replacement:
        replacement.bind(str(profile.chat.path))
        profile.chat.path.chmod(0o660)
        host.close()
        assert profile.chat.path.is_socket() and not profile.api.path.exists()
