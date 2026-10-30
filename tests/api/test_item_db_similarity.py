"""Real HTTP route/security, synthetic current principal and QUERY/Catalog leaves."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_identity_service.tokens import SessionTokenService
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import FakeAudit
from tests.unit.test_item_db_similarity_application import flow as flow
from tests.unit.test_reference_query_prepare_transport import api_context

PATH = "/api/v1/item-db/similarity"


@pytest.fixture
def client(flow):
    services = disconnected_services()
    services.audit = FakeAudit()
    services.item_db_similarity = flow.app
    app = create_app(services)

    def authenticated(request: Request):
        value = flow.context.authentication
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as http:
        yield http, flow, app
    services.engine.dispose()


def post(client, value, *, body=None, key=None):
    return client.post(
        PATH,
        json=body or value.body.model_dump(mode="json"),
        headers={"Idempotency-Key": key or value.value.key},
    )


def test_db_selection_to_official_query_read_and_current_navigation_over_http(client):
    http, value, _app = client
    response = post(http, value)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert data["status"] == "READY" and data["candidates"][0]["kind"] == "GRAPH_ITEM"
    assert (
        data["candidates"][0]["entry"]["item_revision_id"]
        == value.value.context.candidates[0].source.item_revision_id
    )
    current = value.queries.prepare.call_args.args[0]
    assert current is not value.context and current.authentication is value.authentication
    assert (
        value.selector.resolve.call_args.args[0].actor_id
        == value.authentication.operator.operator_id
    )


@pytest.mark.parametrize("field", ("actor_id", "permissions", "runtime", "vectors", "path"))
def test_public_http_body_cannot_supply_authority_execution_or_paths(client, field):
    http, value, _app = client
    body = value.body.model_dump(mode="json") | {field: "untrusted"}
    response = post(http, value, body=body)
    assert response.status_code == 422 and response.json()["error_code"] == "API_REQUEST_INVALID"
    value.selector.resolve.assert_not_called()


def test_pointer_schema_error_is_safe_input_failure_not_internal_error(client):
    http, value, _app = client
    body = value.body.model_dump(mode="json")
    body["selection"]["item_revision_id"] = "latest"
    response = post(http, value, body=body)
    assert response.status_code == 422 and response.json()["error_code"] == "API_REQUEST_INVALID"
    value.selector.resolve.assert_not_called()


def test_missing_read_permission_fails_before_source_or_model_work(client):
    http, value, _app = client
    value.context.authentication = replace(
        value.authentication,
        permissions=value.authentication.permissions - {PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE},
    )
    response = post(http, value)
    assert response.status_code == 403
    value.selector.resolve.assert_not_called()
    value.queries.prepare.assert_not_called()


def test_pinned_original_query_cannot_move_to_a_fresh_key(client):
    http, value, _app = client
    body = value.body.model_dump(mode="json") | {
        "pinned_query": value.value.query.model_dump(mode="json")
    }
    response = post(http, value, body=body, key="another-search-key")
    assert response.status_code == 409
    assert response.json()["error_code"] == "ITEM_DB_SIMILARITY_REQUEST_CONFLICT"
    value.selector.resolve.assert_not_called()


def test_real_auth_dependency_captures_current_access_for_official_query(flow, monkeypatch):
    source, _context = api_context(monkeypatch)
    source.permissions = frozenset(PermissionKey)
    services = disconnected_services()
    services.audit = FakeAudit()
    services.auth = Mock()
    pair = SessionTokenService(source.codec).authenticate_and_capture_access(
        source, source.raw_token
    )
    services.auth.authenticate_and_capture_access.return_value = pair
    services.auth.authenticate_access.side_effect = AssertionError("current capture required")
    services.item_db_similarity = flow.app
    try:
        with TestClient(create_app(services), base_url="http://localhost") as http:
            response = http.post(
                PATH,
                json=flow.body.model_dump(mode="json"),
                headers={
                    "Idempotency-Key": flow.value.key,
                    "Authorization": "Bearer synthetic-test-only-token",
                },
            )
        assert response.status_code == 200
        actual = flow.queries.prepare.call_args.args[0]
        assert actual.authenticated_access is pair
        services.auth.authenticate_and_capture_access.assert_called_once()
        services.auth.authenticate_access.assert_not_called()
    finally:
        services.engine.dispose()
