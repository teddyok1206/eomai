"""Actual HTTP dependency gates and Catalog RPC roundtrip, with application owner mocked."""

import json
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
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingMutation, KakaoBindingPage
from eom_catalog_service.kakao_archive_dispatch import dispatch_kakao_binding
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import OPERATOR_ID, _authentication
from tests.unit.kakao_binding_fixtures import (
    BINDING_ID,
    KEY,
    NOW,
    POLICY_ID,
    create_command,
    retire_command,
    source_binding,
)

ROOT = "/api/v1/kakao-archive/source-bindings"


@pytest.fixture
def kakao_client():
    services = disconnected_services()
    catalog = SimpleNamespace(
        create_kakao_binding=Mock(
            return_value=KakaoBindingMutation(binding=source_binding(), replayed=False)
        ),
        command_kakao_binding=Mock(
            return_value=KakaoBindingMutation(binding=source_binding(retired=True), replayed=False)
        ),
        read_kakao_binding=Mock(return_value=source_binding()),
        list_kakao_bindings=Mock(
            return_value=KakaoBindingPage(items=(source_binding(),), next_cursor=None)
        ),
    )
    services.catalog_application, services.audit = catalog, Mock()
    app = create_app(services)
    state = SimpleNamespace(authentication=_authentication())

    def authenticated(request: Request):
        request.state.request_context.authentication = state.authentication
        return state.authentication

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as client:
        yield client, catalog, state
    services.engine.dispose()


def test_create_read_list_and_retire_headers_use_authenticated_actor(kakao_client):
    client, catalog, _ = kakao_client
    created = client.post(
        ROOT, json=create_command().model_dump(mode="json"), headers={"Idempotency-Key": KEY}
    )
    assert created.status_code == 201, created.text
    assert created.headers["etag"] == '"v1"'
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["data"]["binding"]["source_binding_id"] == BINDING_ID
    call = catalog.create_kakao_binding.call_args
    assert call.kwargs["actor"].operator_id == OPERATOR_ID
    assert call.kwargs["idempotency_key"] == KEY
    assert call.args[0] == create_command()
    read = client.get(ROOT + "/" + BINDING_ID)
    assert read.status_code == 200 and read.headers["etag"] == '"v1"'
    assert read.json()["data"]["policy_revision"]["policy_revision_id"] == POLICY_ID
    page = client.get(ROOT, params={"limit": 1})
    assert page.status_code == 200 and len(page.json()["data"]["items"]) == 1
    assert catalog.list_kakao_bindings.call_args.kwargs["limit"] == 1
    retired = client.post(
        ROOT + "/" + BINDING_ID + "/commands",
        json=retire_command().model_dump(mode="json"),
        headers={"Idempotency-Key": KEY, "If-Match": '"v1"'},
    )
    assert retired.status_code == 200, retired.text
    assert (
        retired.headers["etag"] == '"v2"'
        and retired.json()["data"]["binding"]["state"] == "RETIRED"
    )


@pytest.mark.parametrize(
    "field,value",
    [("actor_id", OPERATOR_ID), ("permissions", ["ADMIN"]), ("source_binding_id", BINDING_ID)],
)
def test_public_body_cannot_add_authority_or_server_identity(kakao_client, field, value):
    client, catalog, _ = kakao_client
    response = client.post(
        ROOT,
        json={**create_command().model_dump(mode="json"), field: value},
        headers={"Idempotency-Key": KEY},
    )
    assert response.status_code == 422
    catalog.create_kakao_binding.assert_not_called()


def test_admin_role_and_current_permission_are_independent_http_gates(kakao_client):
    client, catalog, state = kakao_client
    state.authentication = replace(
        _authentication(admin=False), permissions=frozenset(PermissionKey)
    )
    response = client.post(
        ROOT, json=create_command().model_dump(mode="json"), headers={"Idempotency-Key": KEY}
    )
    assert response.status_code == 403
    state.authentication = replace(_authentication(), permissions=frozenset())
    assert client.get(ROOT).status_code == 403
    assert (
        client.post(
            ROOT, json=create_command().model_dump(mode="json"), headers={"Idempotency-Key": KEY}
        ).status_code
        == 403
    )
    catalog.create_kakao_binding.assert_not_called()
    catalog.list_kakao_bindings.assert_not_called()


def test_missing_login_is_401_before_catalog():
    services = disconnected_services()
    services.catalog_application = Mock()
    with TestClient(create_app(services), base_url="http://localhost") as client:
        assert client.get(ROOT).status_code == 401
    services.catalog_application.list_kakao_bindings.assert_not_called()
    services.engine.dispose()


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 400),
        ({"Idempotency-Key": KEY}, 428),
        ({"Idempotency-Key": KEY, "If-Match": '"v2"'}, 412),
        ({"Idempotency-Key": KEY, "If-Match": 'W/"v1"'}, 412),
    ],
)
def test_mutation_requires_exact_precondition_before_owner(kakao_client, headers, status):
    client, catalog, _ = kakao_client
    response = client.post(
        ROOT + "/" + BINDING_ID + "/commands",
        json=retire_command().model_dump(mode="json"),
        headers=headers,
    )
    assert response.status_code == status, response.text
    catalog.command_kakao_binding.assert_not_called()


@pytest.mark.parametrize(
    "code,status",
    [
        ("KAKAO_ARCHIVE_PERMISSION_DENIED", 403),
        ("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND", 404),
        ("KAKAO_ARCHIVE_PRECONDITION_FAILED", 412),
        ("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT", 409),
        ("KAKAO_ARCHIVE_STORED_POLICY_INVALID", 503),
        ("PRIVATE_UNSAFE_ERROR", 503),
    ],
)
def test_owner_errors_remain_stable_without_private_details(kakao_client, code, status):
    client, catalog, _ = kakao_client
    catalog.read_kakao_binding.side_effect = CatalogApplicationClientError(
        code, "private source text credential"
    )
    response = client.get(ROOT + "/" + BINDING_ID)
    assert response.status_code == status
    assert "private source text" not in response.text and "credential" not in response.text
    expected = code if code != "PRIVATE_UNSAFE_ERROR" else "KAKAO_ARCHIVE_UNAVAILABLE"
    assert response.json()["error_code"] == expected


def test_client_rpc_roundtrip_preserves_replay_key_body_and_actual_actor(monkeypatch):
    owner = Mock()
    owner.create_binding.return_value = KakaoBindingMutation(
        binding=source_binding(), replayed=True
    )
    owner.get_binding.return_value = source_binding()
    client = CatalogApplicationClient(expected_gid=12345)
    wires = []

    def transport(payload, **_):
        wires.append(payload)
        return json.loads(dispatch_kakao_binding(owner, payload))

    monkeypatch.setattr(client, "_raw_request", transport)
    actor = ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "6" * 32,
        request_id="webreq_kakao",
        authentication_time=NOW,
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )
    for _ in range(2):
        result = client.create_kakao_binding(create_command(), actor=actor, idempotency_key=KEY)
        assert result.replayed and result.binding.source_binding_id == BINDING_ID
    assert wires[0] == wires[1]
    assert "permissions" not in wires[0] and "roles" not in wires[0]
    assert wires[0]["command"] == create_command().model_dump(mode="json")
    assert owner.create_binding.call_args.args[0].permissions == frozenset()
    assert client.read_kakao_binding(BINDING_ID, actor=actor) == source_binding()
    with pytest.raises(CatalogApplicationClientError):
        client.read_kakao_binding("kakaobinding_" + "9" * 32, actor=actor)
