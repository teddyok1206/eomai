from __future__ import annotations

import os
import stat
import subprocess
from importlib.util import find_spec
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.api_service_live


def _require_live_run() -> None:
    if os.environ.get("EOM_RUN_API_SERVICE_LIVE") != "1":
        pytest.skip("set EOM_RUN_API_SERVICE_LIVE=1 after deploying eom-api.service")


def _systemctl(*arguments: str) -> str:
    return subprocess.run(
        ("systemctl", *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_installed_service_live_boundary() -> None:
    _require_live_run()
    assert _systemctl("is-active", "eom-api.service") == "active"
    assert _systemctl("is-enabled", "eom-api.service") == "enabled"
    assert _systemctl("show", "-p", "User", "--value", "eom-api.service") == "eom-api"
    assert (
        _systemctl("show", "-p", "WorkingDirectory", "--value", "eom-api.service")
        == "/var/lib/eom-api"
    )
    inaccessible = _systemctl("show", "-p", "InaccessiblePaths", "--value", "eom-api.service")
    for path in (
        "/home/eom/EOM",
        "/home/eom/EOMIS",
        "/root/.codex",
        "/srv/eom/worker-homes",
        "/mnt/nas",
        "/var/run/docker.sock",
    ):
        assert path in inaccessible

    listeners = subprocess.run(
        ("ss", "-H", "-lnt", "sport = :8765"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert len(listeners) == 1
    assert "127.0.0.1:8765" in listeners[0]

    for module in ("eom_api", "eom_api_contracts", "eom_operator_identity"):
        spec = find_spec(module)
        assert spec is not None and spec.origin is not None
        assert "/site-packages/" in spec.origin
        assert not spec.origin.startswith("/home/eom/EOM")

    response = httpx.get("http://127.0.0.1:8765/api/v1/health/live", timeout=5)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "LIVE"
    assert response.headers["X-EOM-API-Version"] == "1"

    ready = httpx.get("http://127.0.0.1:8765/api/v1/health/ready", timeout=5)
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "READY"


def test_installed_service_auth_refresh_and_logout() -> None:
    _require_live_run()
    username = os.environ.get("EOM_API_SMOKE_USERNAME")
    password_path = os.environ.get("EOM_API_SMOKE_PASSWORD_FILE")
    assert username, "EOM_API_SMOKE_USERNAME is required for the live service test"
    assert password_path, "EOM_API_SMOKE_PASSWORD_FILE is required for the live service test"
    credential = Path(password_path)
    assert credential.is_file()
    assert stat.S_IMODE(credential.stat().st_mode) & 0o077 == 0
    password = credential.read_text(encoding="utf-8").rstrip("\n")

    with httpx.Client(base_url="http://127.0.0.1:8765", timeout=5) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={
                "username": username,
                "password": password,
                "client_name": "pytest-service-live",
            },
        )
        assert login.status_code == 200
        login_data = login.json()["data"]
        access = login_data["access_token"]
        refresh = login_data["refresh_token"]

        authenticated = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert authenticated.status_code == 200
        rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert rotated.status_code == 200
        rotated_access = rotated.json()["data"]["access_token"]
        rotated_headers = {"Authorization": f"Bearer {rotated_access}"}
        assert client.post("/api/v1/auth/logout", headers=rotated_headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=rotated_headers).status_code == 401
