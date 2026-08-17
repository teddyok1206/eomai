from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.api_service_live


def test_installed_service_live_boundary() -> None:
    if os.environ.get("EOM_RUN_API_SERVICE_LIVE") != "1":
        pytest.skip("set EOM_RUN_API_SERVICE_LIVE=1 after deploying eom-api.service")
    response = httpx.get("http://127.0.0.1:8765/api/v1/health/live", timeout=5)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "LIVE"
    assert response.headers["X-EOM-API-Version"] == "1"
