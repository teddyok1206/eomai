"""Actual HTTP→protected API-peer socket, without browser or provider operations."""

import os
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.catalog_application_client import CatalogApplicationClient
from eom_catalog_contracts.kakao_collection import KakaoCollectionStatus
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import _authentication
from tests.unit.kakao_room_fixtures import BINDING_ID, KEY, NOW, ROOM_ID

ROOT = "/api/v1/kakao-archive/collections"
RUN = "kakaorun_" + "a" * 32


def test_http_collection_start_and_read_use_separate_api_peer_operations(tmp_path):
    owner = Mock()
    published = KakaoCollectionStatus(
        run_id=RUN,
        source_binding_id=BINDING_ID,
        state="QUEUED",
        resource_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    owner.start_registered_room.return_value = published
    owner.get_status.return_value = published
    directory = tmp_path / "collection-runtime"
    directory.mkdir()
    directory.chmod(0o750)
    server = CatalogApplicationServer(
        *(SimpleNamespace() for _ in range(5)),
        kakao_collections=owner,
        socket_path=directory / "manager.sock",
        allowed_uid=os.getuid(),
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    services = disconnected_services()
    services.catalog_application = CatalogApplicationClient(
        server.socket_path,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    services.audit = Mock()
    app = create_app(services)
    auth = replace(_authentication(admin=True), permissions=frozenset(PermissionKey))

    def authenticated(request: Request):
        request.state.request_context.authentication = auth
        return auth

    app.dependency_overrides[get_authentication] = authenticated
    body = dict(
        selection=dict(
            schema_version="kakao-capability-confirmation/1.0",
            source_binding_id=BINDING_ID,
            room_id=ROOM_ID,
            expected_binding_version=1,
        ),
        expected_policy_revision_id="kakaopolicyrev_" + "c" * 32,
    )
    headers = {"Idempotency-Key": KEY, "If-Match": '"v1"'}
    try:
        with TestClient(app, base_url="http://localhost") as client:
            assert (
                client.post(ROOT, json=body, headers=headers | {"If-Match": '"v2"'}).status_code
                == 412
            )
            assert (
                client.post(
                    ROOT, json=body | {"browser_url": "not accepted"}, headers=headers
                ).status_code
                == 422
            )
            owner.start_registered_room.assert_not_called()
            started = client.post(ROOT, json=body, headers=headers)
            assert started.status_code == 202, started.text
            assert started.headers["cache-control"] == "no-store"
            assert started.json()["data"]["run_id"] == RUN
            for _ in range(2):
                result = client.get(ROOT + "/" + RUN, params={"source_binding_id": BINDING_ID})
                assert result.status_code == 200 and result.json()["data"]["state"] == "QUEUED"
            owner.start_registered_room.assert_called_once()
            assert owner.get_status.call_count == 2
            auth = replace(auth, permissions=frozenset({PermissionKey.KAKAO_ARCHIVE_READ}))
            assert client.post(ROOT, json=body, headers=headers).status_code == 403
            owner.start_registered_room.assert_called_once()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        services.engine.dispose()
