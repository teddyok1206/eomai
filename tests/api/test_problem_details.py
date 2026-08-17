from __future__ import annotations

from eom_api.app import create_app
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services


def test_validation_transport_and_security_headers() -> None:
    services = disconnected_services()
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            validation = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "client_name": "test"},
                headers={"X-Request-ID": "client_request_123456"},
            )
            assert validation.status_code == 422
            assert validation.headers["content-type"].startswith("application/problem+json")
            assert validation.json()["request_id"] == "client_request_123456"
            assert validation.json()["errors"][0]["pointer"] == "/password"
            assert validation.headers["X-Frame-Options"] == "DENY"
            assert validation.headers["Cache-Control"] == "no-store"
            assert validation.headers["X-EOM-API-Version"] == "1"

            unsupported = client.post(
                "/api/v1/auth/login", content="{}", headers={"Content-Type": "text/plain"}
            )
            assert unsupported.status_code == 415
            assert unsupported.json()["error_code"] == "API_CONTENT_TYPE_UNSUPPORTED"

            oversized = client.post(
                "/api/v1/auth/login",
                content=b"x" * 1_048_577,
                headers={"Content-Type": "application/json"},
            )
            assert oversized.status_code == 413
            assert oversized.json()["error_code"] == "API_BODY_TOO_LARGE"
    finally:
        services.engine.dispose()


def test_invalid_request_id_is_replaced_and_cors_is_absent() -> None:
    services = disconnected_services()
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            response = client.get(
                "/api/v1/health/live", headers={"X-Request-ID": "invalid request id"}
            )
            assert response.status_code == 200
            assert response.headers["X-Request-ID"].startswith("req_")
            assert "access-control-allow-origin" not in response.headers
    finally:
        services.engine.dispose()
