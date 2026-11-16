"""Actual HTTP and API-only socket paths; admission is intentionally not public."""

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
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_catalog_contracts.kakao_rooms import KakaoRoomMutation, KakaoRoomPage
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.unit.kakao_room_fixtures import (
    BINDING_ID,
    KEY,
    MAPPING_ID,
    NOW,
    ROOM_ID,
    map_command,
    room,
    unmap_command,
)

ROOT = "/api/v1/kakao-archive/rooms"
PARAMS = {"source_binding_id": BINDING_ID}


@pytest.fixture
def room_client():
    services = disconnected_services()
    catalog = SimpleNamespace(
        command_kakao_room=Mock(
            return_value=KakaoRoomMutation(room=room(mapped=True), replayed=False)
        ),
        read_kakao_room=Mock(return_value=room()),
        list_kakao_rooms=Mock(return_value=KakaoRoomPage(items=(room(),), next_cursor=None)),
    )
    services.catalog_application, services.audit = catalog, Mock()
    app = create_app(services)
    state = SimpleNamespace(
        authentication=replace(_authentication(admin=False), permissions=frozenset(PermissionKey))
    )

    def authenticated(request: Request):
        request.state.request_context.authentication = state.authentication
        return state.authentication

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as client:
        yield client, catalog, state
    services.engine.dispose()


def test_explicit_binding_pins_permissions_and_no_public_admission(room_client):
    client, catalog, state = room_client
    assert client.get(ROOT).status_code == 422
    assert client.post(ROOT, json={}, params=PARAMS).status_code == 405
    read = client.get(ROOT + "/" + ROOM_ID, params={**PARAMS, "mapping_revision_id": MAPPING_ID})
    assert (
        read.status_code == 200
        and read.headers["cache-control"] == "no-store"
        and read.headers["etag"] == '"v1"'
    )
    assert catalog.read_kakao_room.call_args.args == (BINDING_ID, ROOM_ID)
    assert catalog.read_kakao_room.call_args.kwargs["mapping_revision_id"] == MAPPING_ID
    assert catalog.read_kakao_room.call_args.kwargs["actor"].operator_id == OPERATOR_ID
    assert client.get(ROOT, params=PARAMS).status_code == 200
    for command, value in [
        (map_command(), room(mapped=True)),
        (unmap_command(), room(changed=True)),
    ]:
        catalog.command_kakao_room.return_value = KakaoRoomMutation(room=value, replayed=True)
        response = client.post(
            ROOT + "/" + ROOM_ID + "/mapping",
            params=PARAMS,
            json=command.model_dump(mode="json"),
            headers={"Idempotency-Key": KEY, "If-Match": '"v1"'},
        )
        assert response.status_code == 200, response.text
        assert response.headers["etag"] == '"v2"' and response.json()["data"]["replayed"]
    state.authentication = replace(
        state.authentication, permissions=frozenset({PermissionKey.KAKAO_ARCHIVE_READ})
    )
    count = catalog.command_kakao_room.call_count
    assert (
        client.post(
            ROOT + "/" + ROOM_ID + "/mapping",
            params=PARAMS,
            json=map_command().model_dump(mode="json"),
            headers={"Idempotency-Key": KEY, "If-Match": '"v1"'},
        ).status_code
        == 403
    )
    assert catalog.command_kakao_room.call_count == count
    state.authentication = replace(state.authentication, permissions=frozenset())
    assert client.get(ROOT, params=PARAMS).status_code == 403


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 400),
        ({"Idempotency-Key": KEY}, 428),
        ({"Idempotency-Key": KEY, "If-Match": '"v2"'}, 412),
        ({"Idempotency-Key": KEY, "If-Match": 'W/"v1"'}, 412),
    ],
)
def test_exact_etag_and_key_required(room_client, headers, status):
    client, catalog, _ = room_client
    response = client.post(
        ROOT + "/" + ROOM_ID + "/mapping",
        params=PARAMS,
        json=map_command().model_dump(mode="json"),
        headers=headers,
    )
    assert response.status_code == status
    catalog.command_kakao_room.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", OPERATOR_ID),
        ("roles", ["ADMIN"]),
        ("source_binding_id", BINDING_ID),
        ("student_display_name", "same name"),
    ],
)
def test_untrusted_authority_and_name_mapping_rejected(room_client, field, value):
    client, catalog, _ = room_client
    response = client.post(
        ROOT + "/" + ROOM_ID + "/mapping",
        params=PARAMS,
        json={**map_command().model_dump(mode="json"), field: value},
        headers={"Idempotency-Key": KEY, "If-Match": '"v1"'},
    )
    assert response.status_code == 422
    catalog.command_kakao_room.assert_not_called()


@pytest.mark.parametrize(
    "code,status",
    [
        ("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", 404),
        ("KAKAO_ARCHIVE_PERMISSION_DENIED", 403),
        ("KAKAO_ARCHIVE_STUDENT_STALE", 409),
        ("KAKAO_ARCHIVE_ROOM_RETIRED", 409),
        ("KAKAO_ARCHIVE_PRECONDITION_FAILED", 412),
        ("private error", 503),
    ],
)
def test_safe_errors(room_client, code, status):
    client, catalog, _ = room_client
    catalog.read_kakao_room.side_effect = CatalogApplicationClientError(
        code, "private student token"
    )
    response = client.get(ROOT + "/" + ROOM_ID, params=PARAMS)
    assert response.status_code == status and "private student" not in response.text


@contextmanager
def room_socket(tmp_path, *, api_peer=True):
    directory = tmp_path / "room-runtime"
    directory.mkdir(mode=0o750)
    directory.chmod(0o750)
    owner = Mock()
    owner.get_room.return_value = room()
    owner.list_rooms.return_value = KakaoRoomPage(items=(room(),), next_cursor=None)
    owner.command_room.return_value = KakaoRoomMutation(room=room(mapped=True), replayed=True)
    server = CatalogApplicationServer(
        *(SimpleNamespace() for _ in range(5)),
        kakao_rooms=owner,
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


def test_api_peer_socket_preserves_pins_and_replay(tmp_path):
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "6" * 32,
        request_id="webreq_room_socket",
        authentication_time=NOW,
        permissions=frozenset(),
        source=ActorSource.APPLICATION_API,
    )
    with room_socket(tmp_path) as (server, owner):
        client = CatalogApplicationClient(
            server.socket_path, expected_uid=os.getuid(), expected_gid=os.getgid()
        )
        assert (
            client.read_kakao_room(BINDING_ID, ROOM_ID, actor=actor, mapping_revision_id=MAPPING_ID)
            == room()
        )
        assert len(client.list_kakao_rooms(BINDING_ID, actor=actor).items) == 1
        for _ in range(2):
            assert client.command_kakao_room(
                BINDING_ID, ROOM_ID, map_command(), actor=actor, idempotency_key=KEY
            ).replayed
        assert owner.command_room.call_args_list[0] == owner.command_room.call_args_list[1]
        assert not owner.command_room.call_args.args[0].permissions


@pytest.mark.parametrize("operation", ["COMMAND_KAKAO_ROOM", "READ_KAKAO_ROOM", "LIST_KAKAO_ROOMS"])
def test_chat_peer_cannot_use_room_transport(tmp_path, operation):
    with room_socket(tmp_path, api_peer=False) as (server, owner):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(server.socket_path))
            connection.sendall(json.dumps({"operation": operation}).encode() + b"\n")
            assert connection.recv(1024) == b""
        assert not owner.mock_calls
