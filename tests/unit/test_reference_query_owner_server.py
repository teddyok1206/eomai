"""Real local Unix host/capacity; API PID/UID observation/application are synthetic."""

import os
import socket
import tempfile
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services.reference_query_prepare_client import NativeReferenceQueryPrepareClient
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReply,
    ReferenceQueryPrepareRequest,
)
from eom_identity_service.installed_owner_session_provider import (
    ProtectedInstalledIdentityProviderAdmission,
)
from eom_orchestrator import reference_query_owner_server as module
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.reference_query_prepare_transport import (
    handle_reference_query_prepare_connection,
)

from tests.unit.test_catalog_owner_capture_peer import SyntheticApiPeer
from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_reference_query_prepare_contracts import reply_body, request_body
from tests.unit.test_reference_query_prepare_transport import api_context


def host(directory, observation, application):
    parent = Path(directory)
    parent.chmod(0o2750)
    endpoint = ChatSocketEndpoint(
        parent / "owner.sock", os.geteuid(), os.getegid(), parent_mode=0o2750
    )
    return module.ReferenceQueryOwnerServer(
        endpoint=endpoint,
        api_uid=1000,
        admission=ProtectedInstalledIdentityProviderAdmission(observation[0]),
        application=application,
    )


def test_real_host_uses_existing_current_capture_exchange_and_removes_own_socket(
    observation, monkeypatch
):
    source, context = api_context(monkeypatch)
    calls = []

    def factory(capture):
        calls.append(capture.operator_id)
        return SimpleNamespace(
            prepare=lambda request: ReferenceQueryPrepareReply.model_validate(reply_body(request))
        )

    def physical_peer(connection, **kwargs):
        with SyntheticApiPeer(connection.detach()) as peer:
            return handle_reference_query_prepare_connection(peer, **kwargs)

    monkeypatch.setattr(module, "handle_reference_query_prepare_connection", physical_peer)
    with tempfile.TemporaryDirectory(prefix="eom-query-host-") as directory:
        server = host(directory, observation, factory)
        thread = Thread(target=server.serve)
        thread.start()
        try:
            request = ReferenceQueryPrepareRequest.model_validate(request_body())
            reply = NativeReferenceQueryPrepareClient(server.endpoint).prepare(context, request)
            assert reply.status == "PENDING" and calls == [source.operator.operator_id]
        finally:
            server.close()
            thread.join(timeout=3)
        assert not thread.is_alive() and not server.endpoint.path.exists()


def test_request_saturation_closes_extra_connection_without_memory_backlog(
    observation, monkeypatch
):
    entered, release = Event(), Event()
    calls = []

    def hold(_connection, **_kwargs):
        calls.append(1)
        if len(calls) == 4:
            entered.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(module, "handle_reference_query_prepare_connection", hold)
    with tempfile.TemporaryDirectory(prefix="eom-query-capacity-") as directory:
        server = host(directory, observation, Mock(side_effect=AssertionError("no application")))
        thread = Thread(target=server.serve)
        thread.start()
        clients = []
        try:
            for _ in range(4):
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                clients.append(client)
                client.connect(str(server.endpoint.path))
            assert entered.wait(timeout=3)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as extra:
                extra.settimeout(3)
                extra.connect(str(server.endpoint.path))
                assert extra.recv(1) == b""
            assert len(calls) == 4
        finally:
            release.set()
            for client in clients:
                client.close()
            server.close()
            thread.join(timeout=3)
        assert not thread.is_alive()


def test_shutdown_never_unlinks_a_replacement_socket(observation):
    with tempfile.TemporaryDirectory(prefix="eom-query-replacement-") as directory:
        server = host(directory, observation, Mock())
        server.endpoint.path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as replacement:
            replacement.bind(str(server.endpoint.path))
            server.endpoint.path.chmod(0o660)
            server.close()
            assert server.endpoint.path.is_socket()


def test_root_listener_or_untrusted_profile_is_denied_before_bind(
    observation, monkeypatch, tmp_path
):
    bind = Mock(side_effect=AssertionError("root must not accept user requests"))
    monkeypatch.setattr(module, "bind_chat_listener", bind)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError):
        module.ReferenceQueryOwnerServer(
            endpoint=ChatSocketEndpoint(tmp_path / "owner.sock", 0, 0, parent_mode=0o2750),
            api_uid=1000,
            admission=ProtectedInstalledIdentityProviderAdmission(observation[0]),
            application=Mock(),
        )
    bind.assert_not_called()
