from __future__ import annotations

from tests.web_gui.helpers import (
    INTAKE_ID,
    ITEM_ID,
    REVISION_ID,
    WORKFLOW_ID,
    FakeGateway,
    login,
    make_client,
    structured_item_content,
)


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
        assert value["schema_version"] == "3.0"
        assert value["topic"] == "2차원 포물선 운동"
        assert value["source_intake_batch_id"] is None
        assert value["authoring_guidance_sha256"].startswith("sha256:")
        intakes = client.get("/studio/api/v1/content-intakes/accepted")
        assert intakes.status_code == 200
        assert intakes.json()[0]["intake_batch_id"] == INTAKE_ID
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
                "image_required": True,
                "quality_profile": "deep",
                "source_intake_batch_id": INTAKE_ID,
                "authoring_guidance": "포물체 운동의 두 성분을 함께 해석하는 계산 문항을 출제한다.",
                "knowledge_grounding": False,
                "curriculum_selected_unit_key": None,
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
        assert first.json()["draft_spec_sha256"] == updated.json()["draft_spec_sha256"]
        assert gateway.start_calls == 1


def test_request_draft_replay_fails_closed_after_spec_change() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"]}
        draft = client.post(
            "/studio/api/v1/request-drafts",
            json={"original_request_text": "충분히 긴 통합과학 개념 문항 생성 요청입니다."},
            headers=headers,
        ).json()
        replay_key = "studio:changed-draft-conflict-0001"
        first = client.post(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
            json={"idempotency_key": replay_key},
            headers=headers,
        )
        assert first.status_code == 202
        updated = client.put(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}",
            json={
                "subject": draft["subject"],
                "topic": "변경된 통합과학 주제",
                "item_format": draft["item_format"],
                "task_type": draft["task_type"],
                "difficulty": draft["difficulty"],
                "choice_count": draft["choice_count"],
                "equation_required": draft["equation_required"],
                "image_required": draft["image_required"],
                "quality_profile": draft["quality_profile"],
                "source_intake_batch_id": None,
                "authoring_guidance": "변경된 주제를 반영한 통합과학 개념 문항을 출제한다.",
                "knowledge_grounding": False,
                "curriculum_selected_unit_key": None,
            },
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json()["draft_spec_sha256"] != first.json()["draft_spec_sha256"]
        conflict = client.post(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
            json={"idempotency_key": replay_key},
            headers=headers,
        )
        assert conflict.status_code == 409
        assert conflict.json()["error_code"] == "REQUEST_DRAFT_IDEMPOTENCY_CONFLICT"
        assert gateway.start_calls == 1


def test_request_draft_submission_allows_source_free_general_knowledge() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        draft = client.post(
            "/studio/api/v1/request-drafts",
            json={"original_request_text": "충분히 긴 물리학 계산 문항 생성 요청입니다."},
            headers={"X-CSRF-Token": session["csrf_token"]},
        ).json()
        response = client.post(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
            json={"idempotency_key": "studio:missing-intake-0001"},
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 202
        assert response.json()["mode"] == "KNOWLEDGE_ITEM"
        assert gateway.start_calls == 1
        assert gateway.last_start_payload is not None
        assert "educational_retrieval" not in gateway.last_start_payload


def test_request_draft_submission_can_opt_in_to_bounded_graph_grounding() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"]}
        draft = client.post(
            "/studio/api/v1/request-drafts",
            json={"original_request_text": "통합과학 판 경계 자료 해석 문항을 생성해 주세요."},
            headers=headers,
        ).json()
        updated = client.put(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}",
            json={
                "subject": "통합과학",
                "topic": "판 경계",
                "item_format": "multiple_choice",
                "task_type": "data_interpretation",
                "difficulty": "hard",
                "choice_count": 5,
                "equation_required": True,
                "image_required": True,
                "quality_profile": "deep",
                "source_intake_batch_id": None,
                "authoring_guidance": (
                    "판 경계 자료를 해석하고 지각 변동을 추론하는 문항을 출제한다."
                ),
                "knowledge_grounding": True,
                "curriculum_selected_unit_key": "eom.is.middle.3-2",
            },
            headers=headers,
        )
        assert updated.status_code == 200
        response = client.post(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
            json={"idempotency_key": "studio:graph-grounding-0001"},
            headers=headers,
        )
        assert response.status_code == 202
        assert gateway.last_start_payload is not None
        requirement = gateway.last_start_payload["educational_retrieval"]
        assert isinstance(requirement, dict)
        assert requirement["corpus_key"] == "science-core"
        assert requirement["curriculum_root_key"] is None
        assert "graph_snapshot_revision_id" not in requirement
        assert gateway.last_start_payload["execution_preset_key"] == "knowledge-grounded-item"


def test_curriculum_outline_is_authenticated_and_reviewed() -> None:
    client, _ = make_client()
    with client:
        assert client.get("/studio/api/v1/curriculum/editorial-outline").status_code == 401
        login(client)
        response = client.get("/studio/api/v1/curriculum/editorial-outline")
        assert response.status_code == 200
        outline = response.json()
        assert outline["schema_version"] == "integrated-science-editorial-outline/1.0"
        assert outline["graph_mapping_status"] == "RESERVED_CANDIDATES_NOT_PUBLICATION_PROOF"
        assert outline["graph_grounding_available"] is False
        units = outline["units"]
        assert any(unit["key"] == "eom.is.large.3" for unit in units)
        assert any(
            unit["key"] == "eom.is.middle.3-2" and unit["parent_key"] == "eom.is.large.3"
            for unit in units
        )
        assert all(unit["level"] != "SMALL" for unit in units)


def test_workflow_timeline_approval_etag_and_item_preview() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"]}
        workflow = client.get(f"/studio/api/v1/workflows/{WORKFLOW_ID}")
        assert workflow.status_code == 200
        assert workflow.json()["etag"] == '"v4"'
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
                "etag": '"v4"',
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


def test_recent_items_returns_current_revision_pointers() -> None:
    client, _ = make_client()
    with client:
        login(client)
        response = client.get("/studio/api/v1/items/recent")
        assert response.status_code == 200
        assert response.json() == [
            {
                "item_id": ITEM_ID,
                "item_revision_id": REVISION_ID,
                "lifecycle_state": "ACTIVE",
                "human_reference_code": "EOM-SAMPLE-001",
                "created_at": "2026-08-21T07:00:00Z",
            }
        ]


def test_reviewed_structured_item_import_uses_pinned_intake_member_and_revision() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"]}
        sources = client.get(f"/studio/api/v1/content-intakes/{INTAKE_ID}/sources")
        assert sources.status_code == 200
        assert sources.json()[0]["artifact_member"] == "source/diagram.png"

        response = client.post(
            "/studio/api/v1/items/structured-content-imports",
            headers=headers,
            json={
                "base_revision_id": REVISION_ID,
                "revision_etag": '"v1"',
                "idempotency_key": "studio:structured-import:0001",
                "reviewed": True,
                "review_reason": "구조화 문항의 의미와 source pointer를 검토했습니다.",
                "content": structured_item_content(),
            },
        )
        assert response.status_code == 200
        assert response.json()["resource_type"] == "item_revision"
        assert gateway.structured_import_calls == 1


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


def test_codex_control_plane_is_admin_only_and_never_accepts_credentials() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        accounts = client.get("/studio/api/v1/admin/codex-accounts")
        assert accounts.status_code == 200
        account = accounts.json()[0]
        assert account["state"] == "READY"
        assert not {"token", "password", "credential_path", "auth_json"}.intersection(account)
        response = client.post(
            f"/studio/api/v1/admin/codex-accounts/{account['binding_id']}/commands",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json={
                "command_type": "OBSERVE",
                "resource_version": account["resource_version"],
                "idempotency_key": "studio:codex-observe:0001",
                "reason_code": None,
            },
        )
        assert response.status_code == 202
        assert gateway.control_command_calls == 1
        command = client.get(
            f"/studio/api/v1/admin/codex-control-commands/{response.json()['command_id']}"
        )
        assert command.status_code == 200
        assert command.json()["state"] == "SUCCEEDED"
        enrollment = client.post(
            f"/studio/api/v1/admin/codex-accounts/{account['binding_id']}/reauthentications",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json={
                "requested_account_label": "teacher-account-01",
                "acknowledge_drain": True,
                "resource_version": account["resource_version"],
                "idempotency_key": "studio:codex-reauth:0001",
            },
        )
        assert enrollment.status_code == 202
        assert enrollment.headers["cache-control"] == "no-store"
        assert gateway.auth_enrollment_calls == 1
        enrollment_id = enrollment.json()["resource_id"]
        status = client.get(f"/studio/api/v1/admin/codex-auth-enrollments/{enrollment_id}")
        assert status.status_code == 200
        assert status.headers["cache-control"] == "no-store"
        assert status.json()["challenge_available"] is True
        challenge = client.post(
            f"/studio/api/v1/admin/codex-auth-enrollments/{enrollment_id}/challenge",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json={"confirm": True},
        )
        assert challenge.status_code == 200
        assert challenge.headers["cache-control"] == "no-store"
        assert challenge.json()["verification_uri"] == "https://auth.openai.com/codex/device"
        assert challenge.json()["user_code"] == "ABC1-DEF2"
        assert gateway.auth_challenge_reveal_calls == 1
        assert not {"token", "password", "auth_json"}.intersection(challenge.json())
        presets = client.get("/studio/api/v1/admin/execution-presets")
        assert presets.status_code == 200
        assert presets.json()[0]["preset_key"] == "standard-item"
        batches = client.get("/studio/api/v1/admin/knowledge-analysis-batches")
        assert batches.status_code == 200
        assert batches.json()[0]["total_range_count"] == 495
        assert batches.json()[0]["accepted_range_count"] == 12
        quality = client.get(
            "/studio/api/v1/admin/knowledge-analysis-batches/"
            + batches.json()[0]["batch_id"]
            + "/quality"
        )
        assert quality.status_code == 200
        assert quality.json()["quality_state"] == "PASS"
        assert quality.json()["visual_input_page_count"] == 495


def test_codex_control_plane_rejects_non_admin_and_credential_fields() -> None:
    client, _ = make_client(gateway=FakeGateway(roles=["EDITOR"]))
    with client:
        session = login(client)
        assert client.get("/studio/api/v1/admin/codex-accounts").status_code == 403
        assert client.get("/studio/api/v1/admin/knowledge-analysis-batches").status_code == 403
        assert (
            client.get(
                "/studio/api/v1/admin/knowledge-analysis-batches/analysisbatch_"
                + "7" * 32
                + "/quality"
            ).status_code
            == 403
        )
        response = client.post(
            "/studio/api/v1/admin/codex-accounts/authbinding_" + "1" * 32 + "/commands",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json={
                "command_type": "OBSERVE",
                "resource_version": 1,
                "idempotency_key": "studio:codex-observe:0002",
                "reason_code": None,
                "token": "MUST_NOT_ENTER_CONTRACT",
            },
        )
        assert response.status_code == 422
        assert "MUST_NOT_ENTER_CONTRACT" not in response.text
        reauth = client.post(
            "/studio/api/v1/admin/codex-accounts/authbinding_" + "1" * 32 + "/reauthentications",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json={
                "requested_account_label": "teacher-account-01",
                "acknowledge_drain": True,
                "resource_version": 1,
                "idempotency_key": "studio:codex-reauth:0002",
                "password": "MUST_NOT_ENTER_CONTRACT",
            },
        )
        assert reauth.status_code == 422
        assert "MUST_NOT_ENTER_CONTRACT" not in reauth.text


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
