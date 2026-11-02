"""HTTP history/result endpoints, with real application and synthetic owner ports."""

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import FakeAudit
from tests.unit.test_item_db_similarity_application import flow as flow
from tests.unit.test_item_db_similarity_searches import search_case as search_case


@pytest.fixture
def http(search_case):
    services = disconnected_services()
    services.audit = FakeAudit()
    services.item_db_similarity_searches = search_case.app
    app = create_app(services)

    def authenticated(request: Request):
        request.state.request_context.authentication = search_case.flow.authentication
        return search_case.flow.authentication

    app.dependency_overrides[get_authentication] = authenticated
    with TestClient(app, base_url="http://localhost") as client:
        yield client, search_case
    services.engine.dispose()


def test_completed_get_and_repeated_get_read_existing_selectors_only(http):
    client, case = http
    path = f"/api/v1/item-db/similarity/searches/{case.record.search_id}/results/0"
    first, second = client.get(path), client.get(path)
    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert first.headers["Cache-Control"] == "no-store"
    case.flow.queries.prepare.assert_not_called()
    case.store.observe.assert_not_called()


def test_submit_body_is_a_list_and_cannot_supply_actor_or_runtime(http):
    client, case = http
    path = "/api/v1/item-db/similarity/searches"
    headers = {"Idempotency-Key": case.record.idempotency_key}
    for invalid in (
        {"selections": []},
        {"actor_id": case.record.operator_id},
        {"runtime": "CUDA"},
        {"top_k": True},
        {"top_k": 65},
    ):
        response = client.post(
            path, json=case.body.model_dump(mode="json") | invalid, headers=headers
        )
        assert response.status_code == 422
    case.store.admit.assert_not_called()
    response = client.post(path, json=case.body.model_dump(mode="json"), headers=headers)
    assert response.status_code == 200
    case.flow.queries.prepare.assert_not_called()


def test_malformed_source_is_safe_http_validation_error(http):
    client, case = http
    raw = case.body.model_dump(mode="json")
    raw["selections"][0]["item_revision_id"] = "latest"
    response = client.post(
        "/api/v1/item-db/similarity/searches",
        json=raw,
        headers={"Idempotency-Key": case.record.idempotency_key},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "API_REQUEST_INVALID"
    case.store.admit.assert_not_called()
