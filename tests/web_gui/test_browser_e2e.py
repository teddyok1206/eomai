from __future__ import annotations

from pathlib import Path

from tests.web_gui.helpers import INTAKE_ID, ITEM_ID, REVISION_ID, WORKFLOW_ID, login, make_client


def test_browser_flow_from_login_to_editorial_preview_and_explorer() -> None:
    """Exercise the complete browser/BFF contract with isolated in-process fixtures."""
    client, gateway = make_client()
    with client:
        assert client.get("/studio/login").status_code == 200
        session = login(client)
        csrf = {"X-CSRF-Token": session["csrf_token"]}
        shell = client.get("/studio/")
        assert shell.status_code == 200
        for marker in (
            "Workflow 상세",
            "Request Draft",
            "완성 문항",
            "Reviewer 승인",
            "HWPX Capability",
            "DB Explorer Lite",
            "Generic Demo Mode",
        ):
            assert marker in shell.text
        assert client.get("/studio/assets/styles.css").status_code == 200
        assert client.get("/studio/assets/app.js").status_code == 200

        draft = client.post(
            "/studio/api/v1/request-drafts",
            json={
                "original_request_text": "물리학에서 2차원 포물선 운동에 관한 계산 문항을 출제해줘."
            },
            headers=csrf,
        ).json()
        draft = client.put(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}",
            json={
                "subject": draft["subject"],
                "topic": draft["topic"],
                "item_format": draft["item_format"],
                "task_type": draft["task_type"],
                "difficulty": draft["difficulty"],
                "choice_count": draft["choice_count"],
                "equation_required": draft["equation_required"],
                "image_required": draft["image_required"],
                "quality_profile": draft["quality_profile"],
                "source_intake_batch_id": INTAKE_ID,
            },
            headers=csrf,
        ).json()
        submitted = client.post(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
            json={"idempotency_key": "browser-e2e-request-0001"},
            headers=csrf,
        )
        assert submitted.status_code == 202
        assert submitted.json()["command"]["resource_id"] == WORKFLOW_ID
        assert client.get(f"/studio/api/v1/workflows/{WORKFLOW_ID}").json()["timeline"]
        assert (
            client.post(
                f"/studio/api/v1/workflows/{WORKFLOW_ID}/approvals",
                json={
                    "etag": '"v4"',
                    "idempotency_key": "browser-e2e-approval-0001",
                    "reason": None,
                },
                headers=csrf,
            ).status_code
            == 202
        )
        preview = client.get(
            f"/studio/api/v1/items/{ITEM_ID}/revisions/{REVISION_ID}/preview"
        ).json()
        assert (
            preview["body"] and preview["choices"] and preview["answer"] and preview["explanation"]
        )
        assert preview["equations"] and preview["tables"]
        assert (
            client.get("/studio/api/v1/hwpx/capability").json()["state"] == "PREPARED_NOT_DEPLOYED"
        )
        assert (
            client.post(
                "/studio/api/v1/explorer/query",
                json={"entity": "workflows"},
                headers=csrf,
            ).status_code
            == 200
        )
        assert gateway.start_calls == gateway.approval_calls == 1


def test_browser_assets_are_offline_and_xss_safe() -> None:
    html = Path("apps/web_gui/eom_web_gui/static/index.html").read_text(encoding="utf-8")
    javascript = Path("apps/web_gui/eom_web_gui/static/app.js").read_text(encoding="utf-8")
    assert "https://" not in html and "http://" not in html
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript
    assert "innerHTML" not in javascript
    assert "textContent" in javascript
