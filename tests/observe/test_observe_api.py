from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("eom_observe")

from eom_observe.app import AppServices, create_app
from eom_observe.auth import AuthService
from eom_observe.security import hash_access_token
from eom_observe.settings import ObserveSecrets
from eom_observe.stream import SharedSnapshotPoller, SubscriptionHub
from fastapi.testclient import TestClient

from tests.observe.helpers import artifact_detail, job_detail, settings, snapshot, workflow_detail

ACCESS_TOKEN = "observe-test-token-that-is-long-enough"


class FakeEngine:
    def dispose(self) -> None:
        pass


class FakeRepository:
    engine = FakeEngine()

    def ping(self) -> bool:
        return True

    def database_is_readonly(self) -> bool:
        return True


class FakeBuilder:
    def build(self):
        return snapshot()

    def stale_copy(self, value):
        return value

    def workflow_detail(self, workflow_id: str):
        return workflow_detail() if workflow_id == "workflow_12345678" else None

    def job_detail(self, job_id: str):
        return job_detail() if job_id == "job_12345678" else None

    def artifact_detail(self, artifact_id: str):
        return artifact_detail() if artifact_id == "artifact_12345678" else None


@pytest.fixture
def client() -> TestClient:
    config = settings()
    repository = FakeRepository()
    builder = FakeBuilder()
    auth = AuthService(hash_access_token(ACCESS_TOKEN), "s" * 43, 3600)
    hub = SubscriptionHub(max_clients=5)
    poller = SharedSnapshotPoller(builder, hub, poll_interval_seconds=60)
    services = AppServices(
        config,
        ObserveSecrets(
            database_url="postgresql+psycopg://redacted@127.0.0.1/eom",
            access_token_hash=hash_access_token(ACCESS_TOKEN),
            session_secret="s" * 43,
        ),
        repository,
        builder,
        auth,
        hub,
        poller,
    )
    with TestClient(create_app(services)) as test_client:
        yield test_client


def login(client: TestClient) -> None:
    response = client.post("/observe/api/v1/session", json={"token": ACCESS_TOKEN})
    assert response.status_code == 204


def test_health_live_is_public_and_minimal(client: TestClient) -> None:
    response = client.get("/observe/api/v1/health/live")
    assert response.status_code == 200
    assert set(response.json()) == {"schema_version", "status", "timestamp_utc"}


def test_unauthenticated_data_access_rejected(client: TestClient) -> None:
    assert client.get("/observe/api/v1/snapshot").status_code == 401
    assert client.get("/observe/api/v1/stream").status_code == 401


def test_login_failure_and_success_cookie(client: TestClient) -> None:
    assert (
        client.post("/observe/api/v1/session", json={"token": "wrong-token-value"}).status_code
        == 401
    )
    response = client.post("/observe/api/v1/session", json={"token": ACCESS_TOKEN})
    cookie = response.headers["set-cookie"]
    assert response.status_code == 204
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/observe" in cookie
    assert "Max-Age=3600" in cookie


def test_logout_clears_cookie(client: TestClient) -> None:
    login(client)
    response = client.post("/observe/api/v1/logout")
    assert response.status_code == 204
    assert 'eom_observe_session=""' in response.headers["set-cookie"]


def test_authenticated_health_and_snapshot_endpoints(client: TestClient) -> None:
    login(client)
    assert client.get("/observe/api/v1/health/ready").json()["status"] == "READY"
    response = client.get("/observe/api/v1/snapshot")
    assert response.status_code == 200
    assert len(response.json()["nodes"]) == 10
    assert len(client.get("/observe/api/v1/nodes").json()) == 10
    assert len(client.get("/observe/api/v1/edges").json()) == 1
    assert len(client.get("/observe/api/v1/events").json()) == 1


@pytest.mark.parametrize(
    ("path", "identity"),
    [
        ("/observe/api/v1/workflows/workflow_12345678", "workflow_12345678"),
        ("/observe/api/v1/jobs/job_12345678", "job_12345678"),
        ("/observe/api/v1/artifacts/artifact_12345678", "artifact_12345678"),
    ],
)
def test_detail_endpoints(client: TestClient, path: str, identity: str) -> None:
    login(client)
    response = client.get(path)
    assert response.status_code == 200
    assert identity in response.text


def test_invalid_ids_and_limit_validation(client: TestClient) -> None:
    login(client)
    assert client.get("/observe/api/v1/jobs/not-a-job").status_code == 422
    assert client.get("/observe/api/v1/events?limit=501").status_code == 422
    assert client.get("/observe/api/v1/events?worker_role=unknown").status_code == 422
    assert client.get("/observe/api/v1/events?status=running").status_code == 422
    assert client.get("/observe/api/v1/events?after=invalid%20cursor").status_code == 422
    assert client.get("/observe/api/v1/edges?workflow_id=job_12345678").status_code == 422
    assert client.get("/observe/api/v1/workflows/workflow_99999999").status_code == 404


def test_no_mutation_endpoints(client: TestClient) -> None:
    login(client)
    for path in (
        "/observe/api/v1/snapshot",
        "/observe/api/v1/jobs/job_12345678",
        "/observe/api/v1/workflows/workflow_12345678",
    ):
        assert client.post(path).status_code == 405


def test_security_headers_and_csp(client: TestClient) -> None:
    response = client.get("/observe/login")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]


def test_console_redirect_and_local_assets(client: TestClient) -> None:
    response = client.get("/observe/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/observe/login"
    asset = client.get("/observe/assets/app.js")
    assert asset.status_code == 200
    assert "https://" not in asset.text


def test_sse_route_is_get_only_and_reconnect_contract_exists(client: TestClient) -> None:
    login(client)
    route = next(
        route
        for route in client.app.routes
        if getattr(route, "path", "") == "/observe/api/v1/stream"
    )
    assert route.methods == {"GET"}
    assert client.post("/observe/api/v1/stream").status_code == 405
