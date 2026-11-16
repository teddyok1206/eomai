"""Authenticated HTTP and API-peer socket verification, not provider login."""

import json
import os
import socket
import threading
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.catalog_application_client import CatalogApplicationClient
from eom_catalog_contracts.kakao_manual import KakaoManualEnd, KakaoManualMutation, KakaoManualRenew
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.kakao_manual_dispatch import KakaoManualApplication
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.unit.kakao_manual_fixtures import KEY, LEASE, NOW, session, start

ROOT = "/api/v1/kakao-archive/manual-sessions"


@pytest.fixture
def manual_client():
    services = disconnected_services()
    catalog = SimpleNamespace(
        start_kakao_manual=Mock(return_value=KakaoManualMutation(session=session(), replayed=True)),
        read_kakao_manual=Mock(return_value=session()),
        command_kakao_manual=Mock(),
    )
    services.catalog_application, services.audit = catalog, Mock()
    app = create_app(services)
    state = SimpleNamespace(
        authentication=replace(_authentication(admin=True), permissions=frozenset(PermissionKey))
    )

    def authenticated(request: Request):
        request.state.request_context.authentication = state.authentication
        return state.authentication

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as client:
        yield client, catalog, state
    services.engine.dispose()


def test_start_is_accepted_not_ready_and_get_is_read_only(manual_client):
    client, catalog, _ = manual_client
    response = client.post(
        ROOT, json=start().model_dump(mode="json"), headers={"Idempotency-Key": KEY}
    )
    assert response.status_code == 202, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["etag"] == '"v1"'
    assert response.json()["data"]["session"]["ready"] is False
    assert catalog.start_kakao_manual.call_args.kwargs["actor"].operator_id == OPERATOR_ID
    catalog.start_kakao_manual.reset_mock()
    for _ in range(2):
        read = client.get(ROOT + "/" + LEASE)
        assert read.status_code == 200 and read.json()["data"]["phase"] == "PREPARING"
    catalog.start_kakao_manual.assert_not_called()
    catalog.command_kakao_manual.assert_not_called()


@pytest.mark.parametrize(
    "admin,permissions", [(False, frozenset(PermissionKey)), (True, frozenset())]
)
def test_remote_operations_require_actual_admin_and_permission(manual_client, admin, permissions):
    client, catalog, state = manual_client
    state.authentication = replace(_authentication(admin=admin), permissions=permissions)
    assert client.get(ROOT + "/" + LEASE).status_code == 403
    assert (
        client.post(
            ROOT, json=start().model_dump(mode="json"), headers={"Idempotency-Key": KEY}
        ).status_code
        == 403
    )
    catalog.start_kakao_manual.assert_not_called()
    catalog.read_kakao_manual.assert_not_called()


def test_end_uses_resource_etag_renew_uses_grant_revision(manual_client):
    client, catalog, _ = manual_client
    path = ROOT + "/" + LEASE + "/commands"
    end = KakaoManualEnd(expected_resource_version=3).model_dump(mode="json")
    for tag in (None, '"v2"', 'W/"v3"'):
        headers = {"Idempotency-Key": KEY, **({"If-Match": tag} if tag else {})}
        assert client.post(path, json=end, headers=headers).status_code == 412
    catalog.command_kakao_manual.assert_not_called()
    catalog.command_kakao_manual.return_value = KakaoManualMutation(
        session=session("STOPPING", 4, 1), replayed=True
    )
    response = client.post(path, json=end, headers={"Idempotency-Key": KEY, "If-Match": '"v3"'})
    assert response.status_code == 200 and response.headers["etag"] == '"v4"'
    catalog.command_kakao_manual.return_value = KakaoManualMutation(
        session=session("ACTIVE", 4, 2), replayed=True
    )
    response = client.post(
        path,
        json=KakaoManualRenew(expected_grant_revision=1).model_dump(mode="json"),
        headers={"Idempotency-Key": KEY},
    )
    assert response.status_code == 200 and response.json()["data"]["session"]["grant_revision"] == 2


@pytest.mark.parametrize("field", ["actor_id", "profile_id", "fence_epoch", "upstream", "duration"])
def test_browser_cannot_claim_identity_runtime_or_longer_lifetime(manual_client, field):
    client, catalog, _ = manual_client
    response = client.post(
        ROOT,
        json={**start().model_dump(mode="json"), field: "untrusted"},
        headers={"Idempotency-Key": KEY},
    )
    assert response.status_code == 422
    catalog.start_kakao_manual.assert_not_called()


@contextmanager
def manual_socket(tmp_path, *, api_peer=True):
    directory = tmp_path / "manual-runtime"
    directory.mkdir(mode=0o750)
    owner = Mock()
    owner.get_session.return_value = session()
    owner.start_session.return_value = KakaoManualMutation(session=session(), replayed=True)
    application = KakaoManualApplication(owner, Mock(), Mock())
    server = CatalogApplicationServer(
        *(SimpleNamespace() for _ in range(5)),
        kakao_manual=application,
        socket_path=directory / "manager.sock",
        allowed_uid=os.getuid() if api_peer else os.getuid() + 100000,
        chat_owner_uid=os.getuid() + 200000 if api_peer else os.getuid(),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server, owner
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_same_api_request_reaches_same_intent_and_read_does_not_start(tmp_path):
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "6" * 32,
        request_id="webreq_manual_socket",
        authentication_time=NOW,
        permissions=frozenset(),
        source=ActorSource.APPLICATION_API,
    )
    with manual_socket(tmp_path) as (server, owner):
        client = CatalogApplicationClient(
            server.socket_path, expected_uid=os.getuid(), expected_gid=os.getgid()
        )
        for _ in range(2):
            assert client.start_kakao_manual(start(), actor=actor, idempotency_key=KEY).replayed
        assert owner.start_session.call_args_list[0] == owner.start_session.call_args_list[1]
        count = owner.start_session.call_count
        assert client.read_kakao_manual(LEASE, actor=actor) == session()
        assert owner.start_session.call_count == count


@pytest.mark.parametrize(
    "operation", ["START_KAKAO_MANUAL", "COMMAND_KAKAO_MANUAL", "READ_KAKAO_MANUAL"]
)
def test_chat_peer_cannot_control_remote_browser(tmp_path, operation):
    with manual_socket(tmp_path, api_peer=False) as (server, owner):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(server.socket_path))
            connection.sendall(json.dumps({"operation": operation}).encode() + b"\n")
            assert connection.recv(1024) == b""
        assert not owner.mock_calls
