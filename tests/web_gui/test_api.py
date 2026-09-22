from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest
from eom_web_gui.contracts import CustomerSupportCaseView, StudioProblem
from jsonschema import Draft202012Validator

from tests.web_gui.helpers import (
    INTAKE_ID,
    ITEM_ID,
    PDF_REVIEW_INTENT_ID,
    PDF_REVIEW_WORKFLOW_ID,
    REVISION_ID,
    SUPPORT_WORKFLOW_ID,
    WORKFLOW_ID,
    FakeGateway,
    login,
    make_client,
    structured_item_content,
)


def test_pdf_document_review_upload_list_detail_and_page_use_authenticated_bff() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        intent = client.post(
            "/studio/api/v1/pdf-document-reviews/upload-intents",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json={
                "original_filename": "review.pdf",
                "content_length": 12,
                "preset_key": "MOCK_EXAM",
                "additional_guidance": "과학적 정확성과 편집 품질을 함께 검토해 주세요.",
                "idempotency_key": "studio:pdf-review:test-intent-0001",
            },
        )
        assert intent.status_code == 201
        assert intent.json()["upload_intent_id"] == PDF_REVIEW_INTENT_ID
        assert gateway.pdf_review_create_calls == 1

        denied = client.put(
            f"/studio/api/v1/pdf-document-reviews/upload-intents/{PDF_REVIEW_INTENT_ID}/content",
            headers={
                "Content-Type": "application/pdf",
                "Idempotency-Key": "studio:pdf-review:test-content-0001",
            },
            content=b"%PDF-test!!!",
        )
        assert denied.status_code == 403

        uploaded = client.put(
            f"/studio/api/v1/pdf-document-reviews/upload-intents/{PDF_REVIEW_INTENT_ID}/content",
            headers={
                "Content-Type": "application/pdf",
                "Idempotency-Key": "studio:pdf-review:test-content-0001",
                "X-CSRF-Token": session["csrf_token"],
            },
            content=b"%PDF-test!!!",
        )
        assert uploaded.status_code == 202
        assert uploaded.json()["workflow_id"] == PDF_REVIEW_WORKFLOW_ID
        assert gateway.pdf_review_uploaded_bytes == b"%PDF-test!!!"

        listing = client.get("/studio/api/v1/pdf-document-reviews")
        assert listing.status_code == 200
        assert listing.json()["values"][0]["workflow_id"] == PDF_REVIEW_WORKFLOW_ID

        detail = client.get(f"/studio/api/v1/pdf-document-reviews/{PDF_REVIEW_WORKFLOW_ID}")
        assert detail.status_code == 200
        assert detail.json()["state"] == "REVIEWING"

        page = client.get(
            f"/studio/api/v1/pdf-document-reviews/{PDF_REVIEW_WORKFLOW_ID}/pages/1/image"
        )
        assert page.status_code == 200
        assert page.headers["content-type"] == "image/png"
        assert page.content.startswith(b"\x89PNG")


def test_customer_support_create_list_and_read_use_authenticated_bff() -> None:
    client, gateway = make_client()
    with client:
        session = login(client)
        empty = client.get("/studio/api/v1/customer-support/cases")
        assert empty.status_code == 200
        assert empty.json() == {"values": [], "next_cursor": None, "has_more": False}

        denied = client.post(
            "/studio/api/v1/customer-support/cases",
            json={
                "category": "TECHNICAL_ERROR",
                "subject": "미리보기 상태 확인",
                "question": "문항 미리보기가 준비 중으로만 표시되는 이유를 알려주세요.",
                "browser_route": "/studio/",
                "stable_error_code": "ITEM_PREVIEW_NOT_READY",
                "idempotency_key": "studio:support:test-without-csrf",
            },
        )
        assert denied.status_code == 403

        created = client.post(
            "/studio/api/v1/customer-support/cases",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json={
                "category": "TECHNICAL_ERROR",
                "subject": "미리보기 상태 확인",
                "question": "문항 미리보기가 준비 중으로만 표시되는 이유를 알려주세요.",
                "browser_route": "/studio/",
                "stable_error_code": "ITEM_PREVIEW_NOT_READY",
                "idempotency_key": "studio:support:test-create-0001",
            },
        )
        assert created.status_code == 202
        assert created.json()["resource_id"] == SUPPORT_WORKFLOW_ID
        assert gateway.customer_support_create_calls == 1
        expected_inquiry = (
            "webreq_" + hashlib.sha256(b"studio:support:test-create-0001").hexdigest()[:24]
        )
        assert gateway.customer_support_inquiry_ids == [expected_inquiry]

        listed = client.get("/studio/api/v1/customer-support/cases")
        assert listed.status_code == 200
        assert listed.json()["values"][0]["subject"] == "미리보기 상태 확인"
        assert "operator_summary" not in listed.text

        older = client.get("/studio/api/v1/customer-support/cases?cursor=cursor_page_2")
        assert older.status_code == 200
        assert gateway.customer_support_cursors == [None, None, "cursor_page_2"]

        detail = client.get(f"/studio/api/v1/customer-support/cases/{SUPPORT_WORKFLOW_ID}")
        assert detail.status_code == 200
        assert detail.json()["state"] == "SUBMITTED"


def test_customer_support_bff_rejects_mixed_state_and_answer_projection() -> None:
    with pytest.raises(ValueError, match="non-answered customer-support case"):
        CustomerSupportCaseView.model_validate(
            {
                "workflow_id": SUPPORT_WORKFLOW_ID,
                "category": "HOW_TO",
                "subject": "조회 상태 확인",
                "question": "아직 처리 중인 문의에 답변이 섞이면 안 됩니다.",
                "state": "DIAGNOSING",
                "classification": "USAGE_GUIDANCE",
                "answer_text": "잘못 섞인 답변",
                "recommended_actions": [],
                "needs_operator": False,
                "failure_code": None,
                "created_at": "2026-09-17T00:00:00Z",
                "updated_at": "2026-09-17T00:00:00Z",
                "resource_version": 1,
            }
        )

    with pytest.raises(ValueError, match="requires a classified answer"):
        CustomerSupportCaseView.model_validate(
            {
                "workflow_id": SUPPORT_WORKFLOW_ID,
                "category": "HOW_TO",
                "subject": "완료 상태 확인",
                "question": "답변 완료 상태에는 실제 답변이 반드시 있어야 합니다.",
                "state": "ANSWERED",
                "classification": None,
                "answer_text": None,
                "recommended_actions": [],
                "needs_operator": False,
                "failure_code": None,
                "created_at": "2026-09-17T00:00:00Z",
                "updated_at": "2026-09-17T00:00:00Z",
                "resource_version": 1,
            }
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


def test_problem_request_id_matches_header_log_and_typed_contract(caplog) -> None:
    client, _ = make_client()
    with client, caplog.at_level(logging.INFO, logger="eom_web_gui"):
        login(client)
        response = client.post(
            "/studio/api/v1/request-drafts",
            json={"original_request_text": "충분히 긴 통합과학 문항 요청입니다."},
        )

    assert response.status_code == 403
    problem = StudioProblem.model_validate(response.json())
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2] / "schemas/web-gui/studio-problem-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(problem.model_dump(mode="json"))
    assert response.headers["X-Request-ID"] == problem.request_id
    records = [record for record in caplog.records if record.msg == "web request completed"]
    assert records[-1].request_id == problem.request_id


def test_early_request_boundary_problem_keeps_correlation_and_security_headers() -> None:
    client, _ = make_client()
    with client:
        response = client.get("/studio/", headers={"Host": "invalid.example"})

    assert response.status_code == 400
    problem = StudioProblem.model_validate(response.json())
    assert response.headers["X-Request-ID"] == problem.request_id
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


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
        assert value["schema_version"] == "4.0"
        assert value["material_requirement"]["form"] == "AUTO"
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
                "material_requirement": {
                    "schema_version": "content-team-material-requirement/1.0",
                    "form": "IMAGE",
                    "panel_count": 1,
                },
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
                "material_requirement": draft["material_requirement"],
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
    client, gateway = make_client(gateway=FakeGateway(graph_grounding_available=True))
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
                "material_requirement": {
                    "schema_version": "content-team-material-requirement/1.0",
                    "form": "TABLE",
                    "panel_count": 1,
                },
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
        assert requirement["corpus_key"] == "integrated-science-textbooks"
        assert requirement["curriculum_root_key"] is None
        assert "graph_snapshot_revision_id" not in requirement
        assert gateway.last_start_payload["execution_preset_key"] == "knowledge-grounded-item"


def test_grounded_submission_rechecks_capability_before_any_workflow_call() -> None:
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
                "material_requirement": {
                    "schema_version": "content-team-material-requirement/1.0",
                    "form": "TABLE",
                    "panel_count": 1,
                },
                "quality_profile": "deep",
                "source_intake_batch_id": None,
                "authoring_guidance": "판 경계 자료를 해석하고 지각 변동을 추론한다.",
                "knowledge_grounding": True,
                "curriculum_selected_unit_key": "eom.is.middle.3-2",
            },
            headers=headers,
        )
        assert updated.status_code == 200

        response = client.post(
            f"/studio/api/v1/request-drafts/{draft['request_draft_id']}/submissions",
            json={"idempotency_key": "studio:graph-capability-stale-0001"},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["error_code"] == "CURRICULUM_GRAPH_UNAVAILABLE"
        assert gateway.start_calls == 0


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


def test_graph_item_bank_is_authenticated_and_keeps_exam_unit_pointers() -> None:
    client, _ = make_client()
    with client:
        assert client.get("/studio/api/v1/item-bank/entries").status_code == 401
        login(client)
        response = client.get(
            "/studio/api/v1/item-bank/entries",
            params={
                "curriculum_unit_key": "eom.is.middle.3-3",
                "administration_year": 2025,
                "administration_month": 6,
                "item_number": 12,
            },
        )
        assert response.status_code == 200
        page = response.json()
        assert page["has_more"] is False
        assert page["next_cursor"] is None
        assert len(page["values"]) == 1
        item = page["values"][0]
        assert item["item_number"] == 12
        assert item["item_revision_state"] == "APPROVED"
        assert item["curriculum_units"][0]["unit_key"] == "eom.is.middle.3-3"
        assert item["graph_snapshot_revision_id"].startswith("graphrev_")


def test_mock_exam_assembly_policy_is_authenticated() -> None:
    client, _ = make_client()
    with client:
        assert client.get("/studio/api/v1/mock-exam-assemblies/policy").status_code == 401
        login(client)
        response = client.get("/studio/api/v1/mock-exam-assemblies/policy")
        assert response.status_code == 200
        policy = response.json()
        assert policy["item_count"] == 25
        assert policy["total_points_milli"] == 50_000
        assert policy["required_slot_count"] == 21
        assert policy["balance_slot_count"] == 4


def test_server_planned_mock_exam_routes_are_authenticated_and_csrf_protected() -> None:
    client, gateway = make_client()
    with client:
        assert client.get("/studio/api/v1/mock-exam-assemblies/plan").status_code == 401
        session = login(client)
        plan = client.get("/studio/api/v1/mock-exam-assemblies/plan")
        assert plan.status_code == 200
        assert plan.json()["status"] == "SHORTAGE"
        payload = {
            "idempotency_key": "mockexam:test-planned-0001",
            "deliverable_key": "2026-integrated-science-mock-01",
            "title": "2026 통합과학 모의고사 1회",
            "edition": "1회",
            "form_key": "main",
            "display_label": "본시험지",
            "policy_revision_id": plan.json()["policy_revision_id"],
            "policy_sha256": plan.json()["policy_sha256"],
            "graph_snapshot_revision_id": plan.json()["graph_snapshot_revision_id"],
            "graph_snapshot_sha256": plan.json()["graph_snapshot_sha256"],
            "expected_plan_sha256": plan.json()["plan_sha256"],
            "planned_at": plan.json()["planned_at"],
        }
        assert (
            client.post("/studio/api/v1/mock-exam-assemblies/planned", json=payload).status_code
            == 403
        )
        response = client.post(
            "/studio/api/v1/mock-exam-assemblies/planned",
            json=payload,
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 201
        assert response.json()["resource_id"].startswith("assemblyrev_")
        assert gateway.planned_mock_exam_calls == 1


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
        assert preview.json()["schema_version"] == "3.0"
        assert preview.json()["preview_state"] == "AVAILABLE"
        assert [block["type"] for block in preview.json()["blocks"]] == [
            "paragraph",
            "table",
            "image",
            "equation",
            "paragraph",
            "statement_set",
        ]
        media = client.get(
            f"/studio/api/v1/items/{ITEM_ID}/revisions/{REVISION_ID}/media/block_image"
        )
        assert media.status_code == 200
        assert media.headers["content-type"] == "image/png"
        assert media.headers["x-content-type-options"] == "nosniff"
        assert media.content.startswith(b"\x89PNG")
        visual = client.get(f"/studio/api/v1/items/{ITEM_ID}/revisions/{REVISION_ID}/visuals/0")
        assert visual.status_code == 200
        assert visual.headers["content-type"] == "image/png"
        assert visual.headers["cache-control"] == "no-store"


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
        assert status.json()["renderer"] == "content-team"
        assert status.json()["native_equation_count"] == 5
        assert status.json()["native_table_count"] == 2
        assert status.json()["download_available"] is True
        download = client.get(f"/studio/api/v1/hwpx/builds/{build_id}/download")
        assert download.status_code == 200
        assert download.content == b"TEST_ONLY_HWPX"
        assert gateway.hwpx_build_calls == 1


def test_mock_exam_hwpx_build_status_and_download_use_application_api_boundary() -> None:
    gateway = FakeGateway(hwpx_state="READY")
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        response = client.post(
            "/studio/api/v1/mock-exam-hwpx/builds",
            json={
                "assessment_assembly_revision_id": "assemblyrev_" + "1" * 32,
                "idempotency_key": "studio:mock-exam-hwpx:test-0001",
            },
            headers={"X-CSRF-Token": session["csrf_token"]},
        )
        assert response.status_code == 202
        build_id = response.json()["resource_id"]
        status = client.get(f"/studio/api/v1/mock-exam-hwpx/builds/{build_id}")
        assert status.status_code == 200
        assert status.json()["item_count"] == status.json()["section_count"] == 25
        assert status.json()["visual_count"] == 9
        assert status.json()["download_available"] is True
        download = client.get(f"/studio/api/v1/mock-exam-hwpx/builds/{build_id}/download")
        assert download.status_code == 200
        assert download.content == b"TEST_ONLY_MOCK_EXAM_HWPX"
        assert gateway.mock_exam_hwpx_build_calls == 1


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
        assert account["usage_observation"]["plan_type"] == "edu"
        assert account["usage_observation"]["windows"][0]["window_duration_minutes"] == 10080
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
        assert command.json()["usage_observation"]["windows"][0]["used_percent"] == 41
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
        corpus = client.get("/studio/api/v1/admin/assessment-learning-corpus")
        assert corpus.status_code == 200
        assert corpus.json()["source_pdf_count"] == 50
        assert corpus.json()["exam_count"] == 25
        assert corpus.json()["approved_item_count"] == 520
        assert corpus.json()["solution_report_completed_count"] == 520
        assert "batch" not in repr(corpus.json())
        exams = client.get("/studio/api/v1/admin/assessment-learning-corpus/exams")
        assert exams.status_code == 200
        assert "batch" not in repr(exams.json())
        occurrence_revision_id = exams.json()[0]["assessment_occurrence_revision_id"]
        pages = client.get(
            f"/studio/api/v1/admin/assessment-learning-corpus/exams/{occurrence_revision_id}/pages"
        )
        assert pages.status_code == 200
        assert "batch" not in repr(pages.json())
        page_input_id = pages.json()[0]["page_input_id"]
        media = client.get(
            f"/studio/api/v1/admin/assessment-learning-corpus/exams/"
            f"{occurrence_revision_id}/pages/{page_input_id}/image"
        )
        assert media.status_code == 200
        assert media.headers["content-type"] == "image/png"
        assert media.content.startswith(b"\x89PNG")


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
