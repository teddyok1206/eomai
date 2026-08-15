from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("httpx")
pytest.importorskip("eom_observe")

import httpx
from eom_observe_contracts import ObserveSnapshot, WorkflowDetail, validate_contract

BASE_URL = "http://127.0.0.1:8780"
TOKEN_PATH = Path("/home/eom/.eom-observe-initial-token")


def _first_sse_event(client: httpx.Client) -> list[str]:
    with client.stream("GET", "/observe/api/v1/stream") as response:
        assert response.status_code == 200
        lines: list[str] = []
        for line in response.iter_lines():
            if not line:
                break
            lines.append(line)
        return lines


@pytest.mark.observe_browser_live
def test_installed_service_login_snapshot_and_reconnect() -> None:
    if os.getenv("EOM_RUN_OBSERVE_BROWSER_LIVE") != "1":
        pytest.skip("set EOM_RUN_OBSERVE_BROWSER_LIVE=1 for the installed service test")
    if not TOKEN_PATH.is_file():
        pytest.skip("initial access token file is unavailable")

    token = TOKEN_PATH.read_text().strip()
    workflow_id = os.getenv("EOM_OBSERVE_WORKFLOW_ID")
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        login = client.post("/observe/api/v1/session", json={"token": token})
        assert login.status_code == 204
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "SameSite=strict" in login.headers["set-cookie"]

        page = client.get("/observe/")
        assert page.status_code == 200
        assert "EOM Observability Console" in page.text
        assert client.get("/observe/assets/app.js").status_code == 200

        snapshot_response = client.get("/observe/api/v1/snapshot")
        snapshot = ObserveSnapshot.model_validate(snapshot_response.json())
        validate_contract("snapshot", snapshot.model_dump(mode="json"))
        assert len(snapshot.deployment.source_commit) == 40
        assert snapshot.deployment.package_version == "0.1.1"
        assert snapshot.deployment_revision == snapshot.deployment.source_commit[:12]
        assert len(snapshot.nodes) == 10
        assert {node.role for node in snapshot.nodes if node.role} == {
            "authoring",
            "review",
            "image",
            "item_management",
            "support",
        }

        first = _first_sse_event(client)
        second = _first_sse_event(client)
        assert "event: snapshot" in first
        assert "event: snapshot" in second
        assert any(line.startswith("id: ") for line in first)
        assert "retry: 1000" in first

        if workflow_id:
            response = client.get(f"/observe/api/v1/workflows/{workflow_id}")
            detail = WorkflowDetail.model_validate(response.json())
            validate_contract("workflow-detail", detail.model_dump(mode="json"))
            assert detail.workflow_id == workflow_id
            assert detail.state == "COMPLETED"
            assert detail.step_runs
