from __future__ import annotations

from eom_api.app import create_app
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services


def test_public_health_and_protected_endpoint_boundary() -> None:
    services = disconnected_services()
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            live = client.get("/api/v1/health/live")
            assert live.status_code == 200
            assert live.json()["data"]["status"] == "LIVE"
            assert client.get("/api/v1/health/ready").status_code == 503
            protected = client.get("/api/v1/items")
            assert protected.status_code == 401
            assert protected.headers["WWW-Authenticate"] == "Bearer"
            assert protected.json()["error_code"] == "AUTH_TOKEN_INVALID"
            assert client.get("/api/v1/docs").status_code == 404
    finally:
        services.engine.dispose()


def test_wrong_host_is_problem_details() -> None:
    services = disconnected_services()
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            response = client.get("/api/v1/health/live", headers={"Host": "evil.example"})
            assert response.status_code == 400
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.json()["error_code"] == "API_REQUEST_INVALID"
    finally:
        services.engine.dispose()
