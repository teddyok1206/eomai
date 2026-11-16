"""Actual student API routes, authenticated transport, and RPC owner dispatch."""

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
from eom_catalog_contracts.kakao_students import KakaoStudentMutation, KakaoStudentPage
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.kakao_student_dispatch import dispatch_kakao_student
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.unit.kakao_student_fixtures import (
    KEY,
    NOW,
    REVISION_ID,
    STUDENT_ID,
    create_command,
    rename_command,
    retire_command,
    student,
)

ROOT = "/api/v1/kakao-archive/students"


@pytest.fixture
def student_client():
    services = disconnected_services()
    catalog = SimpleNamespace(
        create_kakao_student=Mock(
            return_value=KakaoStudentMutation(student=student(), replayed=False)
        ),
        command_kakao_student=Mock(
            return_value=KakaoStudentMutation(student=student(retired=True), replayed=False)
        ),
        read_kakao_student=Mock(return_value=student()),
        list_kakao_students=Mock(
            return_value=KakaoStudentPage(items=(student(),), next_cursor=None)
        ),
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


def test_nonadmin_with_edit_permission_can_create_rename_retire_and_read_exact_revision(
    student_client,
):
    client, catalog, _ = student_client
    headers = {"Idempotency-Key": KEY}
    created = client.post(ROOT, json=create_command().model_dump(mode="json"), headers=headers)
    assert created.status_code == 201, created.text
    assert created.headers["etag"] == '"v1"' and created.headers["cache-control"] == "no-store"
    assert catalog.create_kakao_student.call_args.kwargs["actor"].operator_id == OPERATOR_ID
    assert catalog.create_kakao_student.call_args.kwargs["idempotency_key"] == KEY
    read = client.get(ROOT + "/" + STUDENT_ID, params={"display_revision_id": REVISION_ID})
    assert read.status_code == 200 and read.json()["data"]["display_revision_id"] == REVISION_ID
    assert catalog.read_kakao_student.call_args.kwargs["display_revision_id"] == REVISION_ID
    page = client.get(ROOT, params={"limit": 1})
    assert page.status_code == 200 and len(page.json()["data"]["items"]) == 1
    for command, successor in [
        (retire_command(), student(retired=True)),
        (rename_command(), student(renamed=True)),
    ]:
        catalog.command_kakao_student.return_value = KakaoStudentMutation(
            student=successor, replayed=False
        )
        response = client.post(
            ROOT + "/" + STUDENT_ID + "/commands",
            json=command.model_dump(mode="json"),
            headers={**headers, "If-Match": '"v1"'},
        )
        assert response.status_code == 200, response.text
        assert response.headers["etag"] == '"v2"'
        assert response.json()["data"]["student"]["state"] == successor.state


def test_read_and_edit_permissions_are_separate(student_client):
    client, catalog, state = student_client
    state.authentication = replace(
        state.authentication, permissions=frozenset({PermissionKey.KAKAO_ARCHIVE_READ})
    )
    assert client.get(ROOT).status_code == 200
    assert (
        client.post(
            ROOT, json=create_command().model_dump(mode="json"), headers={"Idempotency-Key": KEY}
        ).status_code
        == 403
    )
    catalog.create_kakao_student.assert_not_called()
    state.authentication = replace(state.authentication, permissions=frozenset())
    assert client.get(ROOT).status_code == 403


@pytest.mark.parametrize(
    "field,value",
    [("actor_id", OPERATOR_ID), ("permissions", ["ADMIN"]), ("student_id", STUDENT_ID)],
)
def test_browser_cannot_supply_identity_or_authority(student_client, field, value):
    client, catalog, _ = student_client
    response = client.post(
        ROOT,
        json={**create_command().model_dump(mode="json"), field: value},
        headers={"Idempotency-Key": KEY},
    )
    assert response.status_code == 422
    catalog.create_kakao_student.assert_not_called()


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 400),
        ({"Idempotency-Key": KEY}, 428),
        ({"Idempotency-Key": KEY, "If-Match": '"v2"'}, 412),
        ({"Idempotency-Key": KEY, "If-Match": 'W/"v1"'}, 412),
    ],
)
def test_command_requires_exact_strong_etag_and_replay_key(student_client, headers, status):
    client, catalog, _ = student_client
    response = client.post(
        ROOT + "/" + STUDENT_ID + "/commands",
        json=retire_command().model_dump(mode="json"),
        headers=headers,
    )
    assert response.status_code == status
    catalog.command_kakao_student.assert_not_called()


@pytest.mark.parametrize(
    "code,status",
    [
        ("KAKAO_ARCHIVE_PERMISSION_DENIED", 403),
        ("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", 404),
        ("KAKAO_ARCHIVE_STUDENT_RETIRED", 409),
        ("KAKAO_ARCHIVE_PRECONDITION_FAILED", 412),
        ("KAKAO_ARCHIVE_STORED_STUDENT_INVALID", 503),
        ("secret-exception", 503),
    ],
)
def test_failure_projection_does_not_expose_private_details(student_client, code, status):
    client, catalog, _ = student_client
    catalog.read_kakao_student.side_effect = CatalogApplicationClientError(
        code, "private name credentials"
    )
    response = client.get(ROOT + "/" + STUDENT_ID)
    assert response.status_code == status
    assert "private name" not in response.text and "credentials" not in response.text


def test_missing_authentication_is_denied_before_catalog():
    services = disconnected_services()
    services.catalog_application = Mock()
    with TestClient(create_app(services), base_url="http://localhost") as client:
        assert client.get(ROOT).status_code == 401
    services.catalog_application.list_kakao_students.assert_not_called()
    services.engine.dispose()


def test_client_dispatch_preserves_original_key_and_exact_revision(monkeypatch):
    owner = Mock()
    owner.create_student.return_value = KakaoStudentMutation(student=student(), replayed=True)
    owner.get_student.return_value = student()
    client = CatalogApplicationClient(expected_gid=12345)
    wires = []

    def transport(payload, **_):
        wires.append(payload)
        return json.loads(dispatch_kakao_student(owner, payload))

    monkeypatch.setattr(client, "_raw_request", transport)
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "6" * 32,
        request_id="webreq_student",
        authentication_time=NOW,
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )
    for _ in range(2):
        assert client.create_kakao_student(
            create_command(), actor=actor, idempotency_key=KEY
        ).replayed
    assert wires[0] == wires[1] and "permissions" not in wires[0] and "roles" not in wires[0]
    assert not owner.create_student.call_args.args[0].permissions
    assert (
        client.read_kakao_student(STUDENT_ID, actor=actor, display_revision_id=REVISION_ID)
        == student()
    )
    assert owner.get_student.call_args.kwargs["display_revision_id"] == REVISION_ID
    with pytest.raises(CatalogApplicationClientError):
        client.read_kakao_student(
            STUDENT_ID, actor=actor, display_revision_id="kakaostudentrev_" + "9" * 32
        )


@contextmanager
def student_socket(tmp_path, *, api_peer=True):
    directory = tmp_path / "student-runtime"
    directory.mkdir(mode=0o750)
    directory.chmod(0o750)
    owner = Mock()
    owner.create_student.return_value = KakaoStudentMutation(student=student(), replayed=False)
    owner.command_student.return_value = KakaoStudentMutation(
        student=student(retired=True), replayed=False
    )
    owner.get_student.return_value = student()
    owner.list_students.return_value = KakaoStudentPage(items=(student(),), next_cursor=None)
    server = CatalogApplicationServer(
        *(SimpleNamespace() for _ in range(5)),
        kakao_students=owner,
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


def test_actual_api_peer_socket_routes_student_operations(tmp_path):
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "6" * 32,
        request_id="webreq_student_socket",
        authentication_time=NOW,
        permissions=frozenset(),
        source=ActorSource.APPLICATION_API,
    )
    with student_socket(tmp_path) as (server, owner):
        client = CatalogApplicationClient(
            server.socket_path, expected_uid=os.getuid(), expected_gid=os.getgid()
        )
        assert (
            client.create_kakao_student(
                create_command(), actor=actor, idempotency_key=KEY
            ).student.student_id
            == STUDENT_ID
        )
        assert (
            client.read_kakao_student(STUDENT_ID, actor=actor, display_revision_id=REVISION_ID)
            == student()
        )
        assert len(client.list_kakao_students(actor=actor).items) == 1
        assert (
            client.command_kakao_student(
                STUDENT_ID, retire_command(), actor=actor, idempotency_key=KEY
            ).student.state
            == "RETIRED"
        )
        assert owner.get_student.call_args.kwargs["display_revision_id"] == REVISION_ID


@pytest.mark.parametrize(
    "operation",
    ["CREATE_KAKAO_STUDENT", "COMMAND_KAKAO_STUDENT", "READ_KAKAO_STUDENT", "LIST_KAKAO_STUDENTS"],
)
def test_chat_peer_cannot_use_private_student_transport(tmp_path, operation):
    with student_socket(tmp_path, api_peer=False) as (server, owner):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(server.socket_path))
            connection.sendall(json.dumps({"operation": operation}).encode() + b"\n")
            assert connection.recv(1) == b""
        assert owner.mock_calls == []
