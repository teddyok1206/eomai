from __future__ import annotations

from tests.web_gui.helpers import ITEM_ID, REVISION_ID, WORKFLOW_ID, FakeGateway, login, make_client


def test_login_session_cookie_csrf_and_security_headers() -> None:
    client, _ = make_client()
    with client:
        response = client.get("/studio/", follow_redirects=False)
        assert response.status_code == 303
        session = login(client)
        cookie = client.cookies.get("eom_studio_session")
        assert cookie and "TEST_ONLY" not in cookie
        assert session["csrf_token"]
        page = client.get("/studio/")
        assert page.status_code == 200
        assert "EOM Scientific Studio" in page.text
        assert "default-src 'self'" in page.headers["content-security-policy"]
        assert page.headers["x-frame-options"] == "DENY"


def test_login_requires_same_origin_and_never_echoes_password() -> None:
    client, _ = make_client()
    with client:
        response = client.post(
            "/studio/api/v1/session",
            json={"username": "admin", "password": "TEST_ONLY_PASSWORD"},
        )
        assert response.status_code == 403
        assert "TEST_ONLY_PASSWORD" not in response.text


def test_request_draft_workflow_submission_and_replay() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"]}
        draft = client.post(
            "/studio/api/v1/request-drafts",
            json={
                "original_request_text": "물리학에서 2차원 포물선 운동에 관한 계산 문항을 출제해줘."
            },
            headers=headers,
        )
        assert draft.status_code == 201
        value = draft.json()
        assert value["topic"] == "2차원 포물선 운동"
        updated = client.put(
            f"/studio/api/v1/request-drafts/{value['request_draft_id']}",
            json={
                "subject": "물리학",
                "topic": "포물체 운동",
                "item_format": "multiple_choice",
                "task_type": "calculation",
                "difficulty": "hard",
                "choice_count": 5,
                "equation_required": True,
                "image_required": False,
                "quality_profile": "deep",
            },
            headers=headers,
        )
        assert updated.status_code == 200
        payload = {"idempotency_key": "studio:test-replay-0001"}
        first = client.post(
            f"/studio/api/v1/request-drafts/{value['request_draft_id']}/submissions",
            json=payload,
            headers=headers,
        )
        second = client.post(
            f"/studio/api/v1/request-drafts/{value['request_draft_id']}/submissions",
            json=payload,
            headers=headers,
        )
        assert first.status_code == second.status_code == 202
        assert first.json()["replayed"] is False
        assert second.json()["replayed"] is True
        assert gateway.start_calls == 1


def test_workflow_timeline_approval_etag_and_item_preview() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"]}
        workflow = client.get(f"/studio/api/v1/workflows/{WORKFLOW_ID}")
        assert workflow.status_code == 200
        assert workflow.json()["etag"] == '"4"'
        assert {item["label"] for item in workflow.json()["timeline"]} >= {
            "Workflow 생성",
            "authoring 완료",
            "review 완료",
            "승인 대기",
            "Job 종료",
        }
        approval = client.post(
            f"/studio/api/v1/workflows/{WORKFLOW_ID}/approvals",
            json={
                "etag": '"4"',
                "idempotency_key": "studio:test-approval-0001",
                "reason": "검토 완료",
            },
            headers=headers,
        )
        assert approval.status_code == 202
        assert gateway.approval_calls == 1
        preview = client.get(f"/studio/api/v1/items/{ITEM_ID}/revisions/{REVISION_ID}/preview")
        assert preview.status_code == 200
        assert preview.json()["preview_state"] == "AVAILABLE"
        assert len(preview.json()["equations"]) == 2
        assert len(preview.json()["tables"]) == 1


def test_hwpx_is_application_api_only_and_not_faked() -> None:
    client, _ = make_client()
    with client:
        session = login(client)
        value = client.get("/studio/api/v1/hwpx/capability").json()
        assert value["boundary"] == "APPLICATION_API_ONLY"
        assert value["state"] == "PREPARED_NOT_DEPLOYED"
        assert value["build_available"] is False
        response = client.post(
            "/studio/api/v1/hwpx/builds",
            json={
                "item_revision_id": REVISION_ID,
                "idempotency_key": "studio:hwpx:not-ready-0001",
            },
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "HWPX_RENDERER_NOT_READY"


def test_hwpx_ready_build_status_and_download_use_application_api_boundary() -> None:
    gateway = FakeGateway(hwpx_state="READY")
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        capability = client.get("/studio/api/v1/hwpx/capability")
        assert capability.status_code == 200
        assert capability.json()["state"] == "READY"
        response = client.post(
            "/studio/api/v1/hwpx/builds",
            json={
                "item_revision_id": REVISION_ID,
                "idempotency_key": "studio:hwpx:test-0001",
                "require_native_equations": True,
                "require_native_tables": True,
            },
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 202
        build_id = response.json()["resource_id"]
        status = client.get(f"/studio/api/v1/hwpx/builds/{build_id}")
        assert status.json()["native_equation_count"] == 5
        assert status.json()["native_table_count"] == 2
        assert status.json()["download_available"] is True
        download = client.get(f"/studio/api/v1/hwpx/builds/{build_id}/download")
        assert download.status_code == 200
        assert download.content == b"TEST_ONLY_HWPX"
        assert gateway.hwpx_build_calls == 1


def test_db_explorer_is_admin_read_only_allowlist() -> None:
    client, _ = make_client()
    with client:
        session = login(client)
        response = client.post(
            "/studio/api/v1/explorer/query",
            json={
                "schema_version": "1.0",
                "entity": "workflows",
                "exact_id": None,
                "status": None,
                "date_from": None,
                "date_to": None,
                "sort": "created_desc",
                "cursor": None,
                "limit": 50,
            },
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 200
        assert response.json()["rows"][0]["workflow_id"] == WORKFLOW_ID
        forbidden = client.post(
            "/studio/api/v1/explorer/query",
            json={"entity": "raw_sql", "sql": "DELETE FROM workflows"},
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert forbidden.status_code == 422
        assert "DELETE FROM" not in forbidden.text


def test_db_explorer_rejects_non_admin_in_backend() -> None:
    client, _ = make_client(gateway=FakeGateway(roles=["REVIEWER"]))
    with client:
        session = login(client)
        response = client.post(
            "/studio/api/v1/explorer/query",
            json={"entity": "workflows"},
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "ADMIN_ROLE_REQUIRED"


def test_mutations_require_csrf() -> None:
    client, _ = make_client()
    with client:
        login(client)
        response = client.post(
            "/studio/api/v1/request-drafts",
            json={"original_request_text": "충분히 긴 테스트 과학 문항 요청입니다."},
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "CSRF_TOKEN_INVALID"


def test_hwpx_download_route_rejects_invalid_build_identifier() -> None:
    client, _ = make_client()
    with client:
        login(client)
        response = client.get(
            "/studio/api/v1/hwpx/builds/not-a-build/download",
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "HWPX_BUILD_ID_INVALID"
