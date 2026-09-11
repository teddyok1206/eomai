from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from eom_api_contracts import AssessmentHwpxBuildView
from eom_catalog_contracts import (
    build_mock_exam_assembly_plan,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    load_integrated_science_mock_exam_rating_policy,
)
from eom_identifiers import content_sha256
from eom_web_gui.contracts import (
    ExplorerEntity,
    ExplorerQuery,
    HwpxBuildRequest,
    MockExamHwpxBuildRequest,
    PlannedMockExamAssemblySubmission,
)
from eom_web_gui.gateways import (
    GatewayError,
    HttpApplicationGateway,
    _verified_mock_exam_plan,
)
from eom_web_gui.sessions import ApiTokens, WebSession

from tests.unit.test_mock_exam_assembly_contracts import (
    _planning_candidates,
    _planning_candidates_v2,
    _usage_snapshot,
)
from tests.web_gui.helpers import structured_item_content

NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
TEST_REFRESH = "eom_rt_TEST_ONLY_REFRESH_" + "0" * 48
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _single(data: dict[str, object]) -> dict[str, object]:
    return {"data": data, "meta": {"request_id": "req_test", "api_version": "1"}}


def _list(data: list[dict[str, object]]) -> dict[str, object]:
    return {
        "data": data,
        "page": {"next_cursor": None, "has_more": False, "limit": 50},
        "meta": {"request_id": "req_test", "api_version": "1"},
    }


def _token_data(access: str = "eom_at_TEST_ONLY_ACCESS") -> dict[str, object]:
    return {
        "access_token": access,
        "refresh_token": TEST_REFRESH,
        "access_expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "refresh_expires_at": (NOW + timedelta(days=1)).isoformat(),
    }


def _hwpx_build_data(build_id: str) -> dict[str, object]:
    return {
        "build_id": build_id,
        "item_id": "item_" + "2" * 32,
        "item_revision_id": "itemrev_" + "3" * 32,
        "source_artifact_revision_id": "rev_" + "4" * 32,
        "source_sha256": "sha256:" + "5" * 64,
        "renderer": "eom-template",
        "renderer_version": "1.0.0",
        "state": "SUCCEEDED",
        "validation_state": "PASS",
        "native_equation_count": 1,
        "native_table_count": 1,
        "output_artifact_id": "artifact_" + "6" * 32,
        "output_artifact_revision_id": "rev_" + "7" * 32,
        "output_sha256": "sha256:" + "8" * 64,
        "download_available": True,
        "failure_code": None,
        "failure_detail_sanitized": None,
        "created_by_operator_id": "operator_" + "9" * 32,
        "created_at": NOW.isoformat(),
        "started_at": NOW.isoformat(),
        "completed_at": (NOW + timedelta(seconds=2)).isoformat(),
        "resource_version": 3,
    }


def _session(access: str = "eom_at_TEST_ONLY_ACCESS") -> WebSession:
    return WebSession(
        session_id="websession_test",
        csrf_token="csrf_test",
        operator={"roles": ["ADMIN"]},
        tokens=ApiTokens(
            access,
            TEST_REFRESH,
            NOW + timedelta(hours=1),
            NOW + timedelta(days=1),
        ),
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


@pytest.mark.anyio
async def test_http_gateway_login_and_operator_projection() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json=_single(_token_data()))
        if request.url.path == "/api/v1/auth/me":
            assert request.headers["authorization"].startswith("Bearer ")
            return httpx.Response(
                200,
                json=_single(
                    {
                        "operator_id": "operator_test",
                        "username": "admin",
                        "display_name": "관리자",
                        "roles": ["ADMIN"],
                        "effective_permissions": ["WORKFLOW_READ"],
                        "session_id": "api_session_private",
                    }
                ),
            )
        raise AssertionError(request.url.path)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.login("admin", "TEST_ONLY_PASSWORD")
    assert result.operator["roles"] == ["ADMIN"]
    assert "session_id" not in result.operator
    assert result.tokens.access_token.startswith("eom_at_")
    assert len(requests) == 2
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_refreshes_once_and_preserves_idempotency_key() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("idempotency-key")))
        if request.url.path == "/api/v1/workflows" and request.headers["authorization"].endswith(
            "OLD"
        ):
            return httpx.Response(401, json={"error_code": "AUTH_ACCESS_EXPIRED"})
        if request.url.path == "/api/v1/auth/refresh":
            return httpx.Response(200, json=_single(_token_data("eom_at_TEST_ONLY_NEW")))
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(
                202,
                json=_single(
                    {
                        "command_id": "command_test",
                        "resource_id": "workflow_test",
                        "resource_type": "workflow",
                        "status": "ACCEPTED",
                        "resource_version": 1,
                    }
                ),
            )
        raise AssertionError(request.url.path)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    session = _session("eom_at_TEST_ONLY_OLD")
    await gateway.start_workflow(
        session, {"request_name": "PLACEHOLDER_REQUEST"}, "stable-key-0000001"
    )
    assert session.tokens.access_token == "eom_at_TEST_ONLY_NEW"
    workflow_calls = [item for item in seen if item[0] == "/api/v1/workflows"]
    assert workflow_calls == [
        ("/api/v1/workflows", "stable-key-0000001"),
        ("/api/v1/workflows", "stable-key-0000001"),
    ]
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_control_plane_preserves_etag_idempotency_and_no_credentials() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/codex-accounts":
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "binding_id": "authbinding_" + "2" * 32,
                            "slot_key": "slot01",
                            "account_label": "teacher-account-01",
                            "state": "READY",
                            "reason_code": None,
                            "codex_cli_version": "0.147.0",
                            "observed_at": "2026-08-27T12:00:00Z",
                            "valid_until": "2026-08-27T13:00:00Z",
                            "resource_version": 7,
                            "capabilities": [
                                {
                                    "model": "gpt-5.6-terra",
                                    "reasoning_effort": "high",
                                    "state": "READY",
                                }
                            ],
                            "active_lease_count": 0,
                            "last_successful_job_id": None,
                            "active_auth_enrollment_id": None,
                            "active_auth_enrollment_state": None,
                            "usage_observation": {
                                "plan_type": "pro",
                                "observed_at": "2026-08-27T12:00:01Z",
                                "windows": [
                                    {
                                        "limit_id": "codex",
                                        "limit_name": None,
                                        "window_kind": "PRIMARY",
                                        "used_percent": 51,
                                        "window_duration_minutes": 10080,
                                        "resets_at": "2026-09-03T12:00:00Z",
                                    }
                                ],
                            },
                        }
                    ]
                ),
            )
        if request.url.path.endswith("/reauthentications"):
            assert request.headers["if-match"] == '"v7"'
            assert request.headers["idempotency-key"] == "stable-reauth-key-0001"
            body = request.read().decode()
            assert "teacher-account-01" in body
            assert "password" not in body and "token" not in body
            return httpx.Response(
                202,
                json=_single(
                    {
                        "command_id": "authflow_" + "3" * 32,
                        "resource_id": "authflow_" + "3" * 32,
                        "resource_type": "codex_auth_enrollment",
                        "status": "ACCEPTED",
                        "resource_version": 1,
                        "status_url": "/api/v1/codex-auth-enrollments/authflow_" + "3" * 32,
                    }
                ),
            )
        if request.url.path == "/api/v1/codex-auth-enrollments/authflow_" + "3" * 32:
            return httpx.Response(
                200,
                json=_single(
                    {
                        "enrollment_id": "authflow_" + "3" * 32,
                        "binding_id": "authbinding_" + "2" * 32,
                        "slot_key": "slot01",
                        "requested_account_label": "teacher-account-01",
                        "state": "WAITING_FOR_USER",
                        "challenge_available": True,
                        "challenge_revealed_at": None,
                        "assignment_revision_id": None,
                        "error_code": None,
                        "requested_at": "2026-08-27T12:00:00Z",
                        "started_at": "2026-08-27T12:00:01Z",
                        "expires_at": "2026-08-27T12:15:00Z",
                        "completed_at": None,
                        "resource_version": 4,
                    }
                ),
            )
        if request.url.path.endswith("/challenge"):
            assert request.read() == b"{}"
            return httpx.Response(
                200,
                headers={"Cache-Control": "no-store"},
                json=_single(
                    {
                        "enrollment_id": "authflow_" + "3" * 32,
                        "slot_key": "slot01",
                        "verification_uri": "https://auth.openai.com/codex/device",
                        "user_code": "ABC1-DEF2",
                        "expires_at": "2026-08-27T12:10:00Z",
                    }
                ),
            )
        if request.url.path.endswith("/commands"):
            assert request.headers["if-match"] == '"v7"'
            assert request.headers["idempotency-key"] == "stable-control-key-0001"
            body = request.read().decode()
            assert "credential" not in body and "token" not in body
            return httpx.Response(
                202,
                json=_single(
                    {
                        "command_id": "codexcmd_" + "1" * 32,
                        "resource_id": "codexcmd_" + "1" * 32,
                        "resource_type": "codex_control_command",
                        "status": "ACCEPTED",
                        "resource_version": 7,
                    }
                ),
            )
        if request.url.path == "/api/v1/codex-control-commands/codexcmd_" + "1" * 32:
            return httpx.Response(
                200,
                json=_single(
                    {
                        "command_id": "codexcmd_" + "1" * 32,
                        "command_type": "OBSERVE",
                        "binding_id": "authbinding_" + "2" * 32,
                        "state": "SUCCEEDED",
                        "attempts": 1,
                        "result_resource_version": 8,
                        "error_code": None,
                        "requested_at": "2026-08-27T12:00:00Z",
                        "processed_at": "2026-08-27T12:00:02Z",
                        "usage_observation": {
                            "plan_type": "pro",
                            "observed_at": "2026-08-27T12:00:01Z",
                            "windows": [
                                {
                                    "limit_id": "codex",
                                    "limit_name": None,
                                    "window_kind": "PRIMARY",
                                    "used_percent": 51,
                                    "window_duration_minutes": 10080,
                                    "resets_at": "2026-09-03T12:00:00Z",
                                }
                            ],
                        },
                    }
                ),
            )
        raise AssertionError(request.url.path)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    accounts = await gateway.codex_accounts(_session())
    assert accounts[0]["capabilities"][0]["model"] == "gpt-5.6-terra"
    assert accounts[0]["usage_observation"]["plan_type"] == "pro"
    assert accounts[0]["usage_observation"]["windows"][0]["used_percent"] == 51
    result = await gateway.codex_account_command(
        _session(),
        "authbinding_" + "2" * 32,
        command_type="OBSERVE",
        reason_code=None,
        resource_version=7,
        idempotency_key="stable-control-key-0001",
    )
    assert result["status"] == "ACCEPTED"
    control_status = await gateway.codex_control_command(_session(), "codexcmd_" + "1" * 32)
    assert control_status["usage_observation"]["windows"][0]["used_percent"] == 51
    enrollment = await gateway.start_codex_auth_enrollment(
        _session(),
        "authbinding_" + "2" * 32,
        requested_account_label="teacher-account-01",
        resource_version=7,
        idempotency_key="stable-reauth-key-0001",
    )
    assert enrollment["resource_type"] == "codex_auth_enrollment"
    status = await gateway.codex_auth_enrollment(_session(), "authflow_" + "3" * 32)
    assert status.challenge_available is True
    challenge = await gateway.reveal_codex_auth_challenge(_session(), "authflow_" + "3" * 32)
    assert challenge.user_code == "ABC1-DEF2"
    assert len(requests) == 6
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_lists_only_accepted_content_intakes() -> None:
    intake_id = "intake_" + "1" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/content-intakes"
        assert dict(request.url.params) == {"state": "ACCEPTED", "limit": "100"}
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json=_list(
                [
                    {
                        "intake_batch_id": intake_id,
                        "batch_name": "물리학 검토 소스",
                        "state": "ACCEPTED",
                        "purpose": "Generic Demo",
                        "received_by": "operator_test",
                        "resource_version": 3,
                        "created_at": NOW.isoformat(),
                        "updated_at": NOW.isoformat(),
                        "source_manifest": None,
                    }
                ]
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    values = await gateway.accepted_intakes(_session())
    assert len(values) == 1
    assert values[0].intake_batch_id == intake_id
    assert values[0].state == "ACCEPTED"
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_projects_reviewed_curriculum_outline_without_graph_internals() -> None:
    source = json.loads(
        (ROOT / "content/curriculum/eom-integrated-science-editorial-outline-v1.json").read_text(
            encoding="utf-8"
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        if request.url.path == "/api/v1/curriculum/integrated-science-editorial-outline":
            return httpx.Response(200, json=_single(source))
        assert request.url.path == "/api/v1/curriculum/integrated-science-graph-capability"
        return httpx.Response(
            200,
            json=_single(
                {
                    "schema_version": "curriculum-graph-capability/1.0",
                    "corpus_key": "integrated-science-textbooks",
                    "outline_key": source["outline_key"],
                    "outline_revision": source["outline_revision"],
                    "outline_sha256": (
                        "sha256:f11389c8ab26c2bd5b93acf66fe92d30fea9c1d0bc7e6b91a6b6751fdccb5108"
                    ),
                    "capability_state": "READY",
                    "graph_grounding_available": True,
                    "reason": "READY",
                    "graph_snapshot_revision_id": "graphrev_" + "2" * 32,
                    "snapshot_sha256": "sha256:" + "3" * 64,
                    "framework_revision_id": "curriculumrev_" + "4" * 32,
                    "unit_count": 43,
                    "closure_count": 119,
                }
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    outline = await gateway.curriculum_editorial_outline(_session())
    assert len(outline.units) == 41
    assert outline.graph_grounding_available is True
    assert outline.graph_mapping_status == "PUBLISHED_CURRICULUM_GRAPH_VERIFIED"
    assert outline.units[14].key == "eom.is.middle.3-2"
    assert "graph_stable_key" not in outline.model_dump(mode="json")["units"][14]
    assert await gateway.curriculum_graph_corpus_key(_session()) == ("integrated-science-textbooks")
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_keeps_curriculum_classification_when_capability_is_unavailable() -> None:
    source = json.loads(
        (ROOT / "content/curriculum/eom-integrated-science-editorial-outline-v1.json").read_text(
            encoding="utf-8"
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("integrated-science-editorial-outline"):
            return httpx.Response(200, json=_single(source))
        return httpx.Response(503, json={"error_code": "API_DEPENDENCY_UNAVAILABLE"})

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    outline = await gateway.curriculum_editorial_outline(_session())
    assert outline.graph_grounding_available is False
    assert outline.graph_mapping_status == "RESERVED_CANDIDATES_NOT_PUBLICATION_PROOF"
    assert len(outline.units) == 41
    assert await gateway.curriculum_graph_corpus_key(_session()) is None
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_validates_item_bank_page_and_forwards_graph_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/item-bank/entries"
        assert request.url.params["curriculum_unit_key"] == "eom.is.middle.3-3"
        assert request.url.params["administration_year"] == "2025"
        assert request.url.params["administration_month"] == "6"
        assert request.url.params["target_school_level"] == "HIGH_SCHOOL"
        assert request.url.params["target_grade"] == "1"
        assert request.url.params["item_number"] == "12"
        assert "cursor" not in request.url.params
        return httpx.Response(
            200,
            json=_list(
                [
                    {
                        "schema_version": "item-bank-entry-view/1.0",
                        "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
                        "snapshot_sha256": "sha256:" + "2" * 64,
                        "analysis_run_id": "analysisrun_" + "3" * 32,
                        "graph_placement_node_id": "knode_" + "d" * 32,
                        "assessment_occurrence_id": "occurrence_" + "4" * 32,
                        "assessment_occurrence_revision_id": "occurrev_" + "5" * 32,
                        "assessment_occurrence_revision_sha256": "sha256:" + "6" * 64,
                        "occurrence_display_label": "2025년 고1 6월 통합과학",
                        "administration_year": 2025,
                        "administration_month": 6,
                        "target_school_level": "HIGH_SCHOOL",
                        "target_grade": 1,
                        "subject_key": "integrated-science",
                        "item_number": 12,
                        "item_id": "item_" + "7" * 32,
                        "item_revision_id": "itemrev_" + "8" * 32,
                        "item_revision_state": "APPROVED",
                        "item_type_key": "multiple-choice",
                        "difficulty_band": None,
                        "item_manifest_sha256": "sha256:" + "9" * 64,
                        "curriculum_units": [
                            {
                                "curriculum_unit_id": "currunit_" + "a" * 32,
                                "unit_key": "eom.is.middle.3-3",
                                "unit_code": "3-(3)",
                                "label": "중력장 내의 운동",
                                "unit_level": "MINOR",
                                "parent_unit_id": "currunit_" + "b" * 32,
                            }
                        ],
                        "placement_sha256": "sha256:" + "c" * 64,
                    }
                ]
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    page = await gateway.item_bank_entries(
        _session(),
        curriculum_unit_key="eom.is.middle.3-3",
        administration_year=2025,
        administration_month=6,
        item_number=12,
        cursor=None,
    )
    assert page.values[0].item_revision_id == "itemrev_" + "8" * 32
    assert page.values[0].curriculum_units[0].label == "중력장 내의 운동"
    assert page.has_more is False
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_accepts_complete_application_hwpx_build_view() -> None:
    build_id = "hwpxbuild_" + "1" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/hwpx-builds/{build_id}"
        value = _hwpx_build_data(build_id)
        value["native_equation_count"] = 128
        return httpx.Response(
            200,
            json=_single(value),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    value = await gateway.hwpx_build(_session(), build_id)
    assert value.state == "SUCCEEDED"
    assert value.download_available is True
    assert value.native_equation_count == 128
    assert value.output_artifact_revision_id == "rev_" + "7" * 32
    assert value.resource_version == 3
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_requests_revision_derived_hwpx_profile_without_shape_requirements() -> None:
    revision_id = "itemrev_" + "3" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/item-revisions/{revision_id}/hwpx-builds"
        assert request.headers["idempotency-key"] == "studio:hwpx:auto-profile"
        assert json.loads(request.read()) == {
            "renderer": "auto",
            "options": {
                "include_explanation": True,
                "require_native_equations": False,
                "require_native_tables": False,
                "document_preset": "report",
                "document_profile": "item-revision-auto",
                "item_number": 4,
            },
        }
        return httpx.Response(
            202,
            json=_single(
                {
                    "command_id": "hwpxcmd_" + "1" * 32,
                    "resource_type": "hwpx_build",
                    "resource_id": "hwpxbuild_" + "1" * 32,
                    "status": "ACCEPTED",
                    "resource_version": 1,
                    "status_url": "/api/v1/hwpx-builds/hwpxbuild_" + "1" * 32,
                }
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    value = HwpxBuildRequest(
        item_revision_id=revision_id,
        idempotency_key="studio:hwpx:auto-profile",
        item_number=4,
    )

    await gateway.create_hwpx_build(_session(), value)
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_uses_pinned_assembly_for_whole_exam_hwpx() -> None:
    assembly_revision_id = "assemblyrev_" + "1" * 32
    build_id = "hwpxbuild_" + "2" * 32
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.method == "POST":
            assert request.url.path == (
                f"/api/v1/assessment-assembly-revisions/{assembly_revision_id}/hwpx-builds"
            )
            assert request.headers["idempotency-key"] == "studio:mock-exam-hwpx:test"
            assert json.loads(request.read()) == {
                "renderer": "content-team-exam",
                "include_explanation": True,
            }
            return httpx.Response(
                202,
                json=_single(
                    {
                        "command_id": "hwpxcmd_" + "2" * 32,
                        "resource_type": "assessment_hwpx_build",
                        "resource_id": build_id,
                        "status": "ACCEPTED",
                        "resource_version": 1,
                        "status_url": f"/api/v1/assessment-hwpx-builds/{build_id}",
                    }
                ),
            )
        assert request.url.path == f"/api/v1/assessment-hwpx-builds/{build_id}"
        api_view = AssessmentHwpxBuildView(
            build_id=build_id,
            assessment_assembly_id="assembly_" + "1" * 32,
            assessment_assembly_revision_id=assembly_revision_id,
            assembly_manifest_sha256="sha256:" + "3" * 64,
            policy_revision_id="assemblypolicyrev_" + "4" * 32,
            policy_sha256="sha256:" + "5" * 64,
            graph_snapshot_revision_id="graphrev_" + "6" * 32,
            graph_snapshot_sha256="sha256:" + "7" * 64,
            item_set_sha256="sha256:" + "8" * 64,
            renderer="content-team-exam",
            renderer_version="3.0.0",
            state="SUCCEEDED",
            validation_state="PASS",
            item_count=25,
            section_count=25,
            native_equation_count=20,
            native_table_count=8,
            visual_count=11,
            output_artifact_id="artifact_" + "9" * 32,
            output_artifact_revision_id="rev_" + "a" * 32,
            output_sha256="sha256:" + "b" * 64,
            download_available=True,
            failure_code=None,
            failure_detail_sanitized=None,
            created_by_operator_id="operator_" + "c" * 32,
            created_at=NOW,
            started_at=NOW,
            completed_at=NOW,
            resource_version=3,
        )
        return httpx.Response(
            200,
            json=_single(api_view.model_dump(mode="json")),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    await gateway.create_mock_exam_hwpx_build(
        _session(),
        MockExamHwpxBuildRequest(
            assessment_assembly_revision_id=assembly_revision_id,
            idempotency_key="studio:mock-exam-hwpx:test",
        ),
    )
    value = await gateway.mock_exam_hwpx_build(_session(), build_id)
    assert value.item_count == value.section_count == 25
    assert value.renderer_version == "3.0.0"
    assert value.visual_count == 11
    assert calls == 2
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_creates_only_the_exact_previewed_server_plan() -> None:
    policy = load_integrated_science_mock_exam_policy()
    layout = load_integrated_science_mock_exam_layout_policy()
    rating = load_integrated_science_mock_exam_rating_policy()
    candidates = _planning_candidates()
    graph_revision_id = "graphrev_" + "a" * 32
    graph_sha256 = "sha256:" + "b" * 64
    planned_at = datetime.now(UTC)
    plan = build_mock_exam_assembly_plan(
        policy=policy,
        layout_policy=layout,
        rating_policy=rating,
        graph_snapshot_revision_id=graph_revision_id,
        graph_snapshot_sha256=graph_sha256,
        usage_snapshot=_usage_snapshot(
            captured_at=planned_at,
            candidate_revision_count=len(candidates),
        ),
        resolved_candidate_count=len(candidates),
        candidates=candidates,
        planned_at=planned_at,
    )
    policy_data = {
        "schema_version": policy.schema_version,
        "policy_key": policy.policy_key,
        "policy_revision_id": policy.policy_revision_id,
        "policy_sha256": content_sha256(policy.model_dump(mode="json")),
        "subject_key": policy.subject_key,
        "item_count": policy.item_count,
        "total_points_milli": policy.total_points_milli,
        "score_distribution": [row.model_dump(mode="json") for row in policy.score_distribution],
        "required_slot_count": policy.required_slot_count,
        "balance_slot_count": policy.balance_slot_count,
        "inquiry_min_count": policy.inquiry_min_count,
        "inquiry_max_count": policy.inquiry_max_count,
        "coverage_requirements": [
            row.model_dump(mode="json") for row in policy.coverage_requirements
        ],
        "eligible_item_revision_states": list(policy.eligible_item_revision_states),
        "outline_key": policy.outline_key,
        "outline_revision": policy.outline_revision,
        "outline_sha256": policy.outline_sha256,
        "guidance_revision": policy.guidance_pointer.revision,
        "guidance_reviewed_document_sha256": (policy.guidance_pointer.reviewed_document_sha256),
        "guidance_original_sha256": policy.guidance_pointer.original_sha256,
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/assessment-assemblies/policy":
            return httpx.Response(200, json=_single(policy_data))
        if request.url.path == "/api/v1/curriculum/integrated-science-graph-capability":
            return httpx.Response(
                200,
                json=_single(
                    {
                        "schema_version": "curriculum-graph-capability/1.0",
                        "capability_state": "READY",
                        "graph_grounding_available": True,
                        "reason": "READY",
                        "corpus_key": "integrated-science-textbooks",
                        "outline_key": "eom-integrated-science-editorial-outline",
                        "outline_revision": "1.0",
                        "outline_sha256": (
                            "sha256:f11389c8ab26c2bd5b93acf66fe92d30"
                            "fea9c1d0bc7e6b91a6b6751fdccb5108"
                        ),
                        "graph_snapshot_revision_id": graph_revision_id,
                        "snapshot_sha256": graph_sha256,
                        "framework_revision_id": "curriculumrev_" + "c" * 32,
                        "unit_count": 43,
                        "closure_count": 119,
                    }
                ),
            )
        if request.url.path == "/api/v1/assessment-assemblies/plan":
            assert dict(request.url.params) == {
                "policy_revision_id": policy.policy_revision_id,
                "policy_sha256": policy_data["policy_sha256"],
                "graph_snapshot_revision_id": graph_revision_id,
                "graph_snapshot_sha256": graph_sha256,
            }
            return httpx.Response(200, json=_single(plan.model_dump(mode="json")))
        if request.url.path == "/api/v1/deliverables" and request.method == "POST":
            return httpx.Response(
                201,
                json=_single(
                    {
                        "resource_id": "deliverable_" + "d" * 32,
                        "resource_type": "deliverable",
                        "status": "COMPLETED",
                        "resource_version": 1,
                    }
                ),
            )
        if request.url.path == "/api/v1/deliverables/" + "deliverable_" + "d" * 32:
            return httpx.Response(
                200,
                json=_single({"deliverable_revision_id": "delivrev_" + "e" * 32}),
            )
        assert request.url.path == "/api/v1/assessment-assemblies/planned"
        body = json.loads(request.read())
        assert body["expected_plan_sha256"] == plan.plan_sha256
        assert body["planned_at"] == plan.model_dump(mode="json")["planned_at"]
        assert "placements" not in body
        return httpx.Response(
            201,
            json=_single(
                {
                    "resource_id": "assemblyrev_" + "f" * 32,
                    "resource_type": "assessment_assembly_revision",
                    "status": "COMPLETED",
                    "resource_version": 1,
                }
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    preview = await gateway.mock_exam_assembly_plan(_session())
    submission = PlannedMockExamAssemblySubmission(
        idempotency_key="mockexam:test-planned-0001",
        deliverable_key="2026-integrated-science-mock-01",
        title="2026 통합과학 모의고사 1회",
        edition="1회",
        form_key="main",
        display_label="본시험지",
        policy_revision_id=preview["policy_revision_id"],
        policy_sha256=preview["policy_sha256"],
        graph_snapshot_revision_id=preview["graph_snapshot_revision_id"],
        graph_snapshot_sha256=preview["graph_snapshot_sha256"],
        expected_plan_sha256=preview["plan_sha256"],
        planned_at=preview["planned_at"],
    )
    result = await gateway.create_planned_mock_exam_assembly(
        _session(),
        submission,
    )
    assert result["resource_id"] == "assemblyrev_" + "f" * 32
    assert len(requests) == 8
    with pytest.raises(GatewayError, match="ASSEMBLY_PLAN_CHANGED"):
        await gateway.create_planned_mock_exam_assembly(
            _session(),
            submission.model_copy(update={"graph_snapshot_revision_id": "graphrev_" + "9" * 32}),
        )
    assert (
        sum(
            request.url.path == "/api/v1/deliverables" and request.method == "POST"
            for request in requests
        )
        == 1
    )
    await gateway.close()


def test_web_plan_projection_rejects_tampered_or_duplicate_revisions() -> None:
    policy = load_integrated_science_mock_exam_policy()
    candidates = _planning_candidates()
    graph_revision_id = "graphrev_" + "a" * 32
    graph_sha256 = "sha256:" + "b" * 64
    plan = build_mock_exam_assembly_plan(
        policy=policy,
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=graph_revision_id,
        graph_snapshot_sha256=graph_sha256,
        usage_snapshot=_usage_snapshot(
            captured_at=NOW,
            candidate_revision_count=len(candidates),
        ),
        resolved_candidate_count=len(candidates),
        candidates=candidates,
        planned_at=NOW,
    )
    value = plan.model_dump(mode="json")
    arguments = {
        "policy_revision_id": policy.policy_revision_id,
        "policy_sha256": value["policy_sha256"],
        "graph_snapshot_revision_id": graph_revision_id,
        "graph_snapshot_sha256": graph_sha256,
        "item_count": policy.item_count,
    }
    assert _verified_mock_exam_plan(value, **arguments) == value

    hash_tampered = json.loads(json.dumps(value))
    hash_tampered["placements"][0]["usage_count"] += 1
    assert _verified_mock_exam_plan(hash_tampered, **arguments) is None

    duplicate = json.loads(json.dumps(value))
    duplicate["placements"][1]["item_revision_id"] = duplicate["placements"][0]["item_revision_id"]
    duplicate["plan_sha256"] = content_sha256(
        {key: item for key, item in duplicate.items() if key != "plan_sha256"}
    )
    assert _verified_mock_exam_plan(duplicate, **arguments) is None


def test_web_plan_projection_accepts_only_exact_v3_content_for_plan_v2() -> None:
    policy = load_integrated_science_mock_exam_policy()
    candidates = _planning_candidates_v2()
    graph_revision_id = "graphrev_" + "c" * 32
    graph_sha256 = "sha256:" + "d" * 64
    plan = build_mock_exam_assembly_plan(
        policy=policy,
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        rating_policy=load_integrated_science_mock_exam_rating_policy(),
        graph_snapshot_revision_id=graph_revision_id,
        graph_snapshot_sha256=graph_sha256,
        usage_snapshot=_usage_snapshot(
            captured_at=NOW,
            candidate_revision_count=len(candidates),
        ),
        resolved_candidate_count=len(candidates),
        candidates=candidates,
        planned_at=NOW,
    )
    value = plan.model_dump(mode="json")
    arguments = {
        "policy_revision_id": policy.policy_revision_id,
        "policy_sha256": value["policy_sha256"],
        "graph_snapshot_revision_id": graph_revision_id,
        "graph_snapshot_sha256": graph_sha256,
        "item_count": policy.item_count,
    }
    assert value["schema_version"] == "mock-exam-assembly-plan/2.0"
    assert _verified_mock_exam_plan(value, **arguments) == value

    mixed = json.loads(json.dumps(value))
    mixed["placements"][0]["content"]["schema_ref"] = "eom.assessment.item-content/2.0"
    mixed["plan_sha256"] = content_sha256(
        {key: item for key, item in mixed.items() if key != "plan_sha256"}
    )
    assert _verified_mock_exam_plan(mixed, **arguments) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content_team_profile", "expected_state"),
    (
        (
            {
                "renderer": "content-team",
                "renderer_version": "2.0.0",
                "document_profile": "content-team-hwp-question-editor-v2",
                "source_schema_ref": "eom.assessment.item-content/2.0",
            },
            "READY",
        ),
        (
            {
                "renderer": "content-team",
                "renderer_version": "3.0.0",
                "document_profile": "content-team-hwp-question-editor-v3",
                "source_schema_ref": "eom.assessment.item-content/3.0",
            },
            "READY",
        ),
        (
            {
                "renderer": "content-team",
                "renderer_version": "3.0.0",
                "document_profile": "content-team-hwp-question-editor-v2",
                "source_schema_ref": "eom.assessment.item-content/3.0",
            },
            "DEGRADED",
        ),
    ),
)
async def test_gateway_requires_both_closed_profiles_for_automatic_hwpx_delivery(
    content_team_profile: dict[str, str], expected_state: str
) -> None:
    profiles = [
        {
            "renderer": "eom-template",
            "renderer_version": "1.0.0",
            "document_profile": "eom-question-template-v1",
            "source_schema_ref": "eom.assessment.item-content/1.0",
        },
        content_team_profile,
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_single(
                {
                    "state": "READY",
                    "supports": {"native_equations": True, "native_tables": True},
                    "delivery_profiles": profiles,
                    "detail_code": "HWPX_READY",
                }
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )

    capability = await gateway.hwpx_capability(_session())

    assert capability.state == expected_state
    assert capability.renderer_key == "item-revision-auto"
    assert capability.document_profile == "item-revision-auto"
    assert capability.build_available is (expected_state == "READY")
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_projects_bounded_recent_hwpx_builds_for_admin_ui() -> None:
    build_id = "hwpxbuild_" + "1" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/hwpx-builds"
        assert request.url.params["limit"] == "20"
        assert "cursor" not in request.url.params
        assert "state" not in request.url.params
        return httpx.Response(200, json=_list([_hwpx_build_data(build_id)]))

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.explorer(
        _session(),
        ExplorerQuery(entity=ExplorerEntity.HWPX_BUILDS, sort="created_desc", limit=20),
    )
    assert result.capability == "READY"
    assert result.rows[0]["build_id"] == build_id
    assert result.rows[0]["item_revision_id"] == "itemrev_" + "3" * 32
    assert result.rows[0]["output_artifact_revision_id"] == "rev_" + "7" * 32
    await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "expected_state"),
    (("SUCCEEDED", "SUCCEEDED"), ("COMPLETED", None)),
)
async def test_gateway_forwards_only_valid_hwpx_state_filters(
    status: str, expected_state: str | None
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/hwpx-builds"
        assert request.url.params.get("state") == expected_state
        return httpx.Response(200, json=_list([]))

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.explorer(
        _session(),
        ExplorerQuery(entity=ExplorerEntity.HWPX_BUILDS, status=status, limit=20),
    )
    assert result.rows == ()
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_maps_authorized_transport_failure_to_stable_unavailable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test-only unavailable", request=request)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GatewayError) as failure:
        await gateway.explorer(
            _session(),
            ExplorerQuery(entity=ExplorerEntity.HWPX_BUILDS, sort="created_desc", limit=20),
        )
    assert failure.value.status == 503
    assert failure.value.code == "APPLICATION_API_UNAVAILABLE"
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_maps_invalid_application_json_to_stable_response_error() -> None:
    build_id = "hwpxbuild_" + "1" * 32
    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"test-only-not-json")),
    )
    with pytest.raises(GatewayError) as failure:
        await gateway.hwpx_build(_session(), build_id)
    assert failure.value.status == 502
    assert failure.value.code == "APPLICATION_API_RESPONSE_INVALID"
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_projects_recent_items_with_current_revision_in_one_query() -> None:
    requests: list[httpx.Request] = []
    item_id = "item_" + "1" * 32
    revision_id = "itemrev_" + "2" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/api/v1/items"
        assert request.url.params["state"] == "ACTIVE"
        assert request.url.params["limit"] == "20"
        return httpx.Response(
            200,
            json=_list(
                [
                    {
                        "item_id": item_id,
                        "human_reference_code": "EOM-SAMPLE-001",
                        "lifecycle_state": "ACTIVE",
                        "current_revision_id": revision_id,
                        "resource_version": 1,
                        "created_at": NOW.isoformat(),
                    },
                    {
                        "item_id": "item_" + "3" * 32,
                        "human_reference_code": None,
                        "lifecycle_state": "ACTIVE",
                        "current_revision_id": None,
                        "resource_version": 1,
                        "created_at": NOW.isoformat(),
                    },
                ]
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.recent_items(_session())
    assert len(requests) == 1
    assert len(result) == 1
    assert result[0].item_id == item_id
    assert result[0].item_revision_id == revision_id
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_projects_bounded_knowledge_analysis_batch_progress() -> None:
    batch_id = "analysisbatch_" + "a" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/knowledge-analysis-batches"
        assert request.url.params["limit"] == "20"
        return httpx.Response(
            200,
            json=_list(
                [
                    {
                        "batch_id": batch_id,
                        "request_sha256": "sha256:" + "1" * 64,
                        "preset_id": "execpreset_" + "2" * 32,
                        "preset_revision_id": "execpresetrev_" + "3" * 32,
                        "preset_sha256": "sha256:" + "4" * 64,
                        "risk_policy_revision_id": "analysisriskrev_" + "5" * 32,
                        "risk_policy_sha256": "sha256:" + "6" * 64,
                        "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
                        "review_policy": "PREAUTHORIZED_APPROVE_VALIDATED",
                        "authorized_by_operator_id": "operator_" + "7" * 32,
                        "authorized_at": NOW.isoformat(),
                        "state": "RUNNING",
                        "total_range_count": 495,
                        "accepted_range_count": 17,
                        "failed_range_count": 0,
                        "failure_code": None,
                        "resource_version": 6,
                        "created_at": NOW.isoformat(),
                        "started_at": NOW.isoformat(),
                        "completed_at": None,
                        "updated_at": (NOW + timedelta(minutes=2)).isoformat(),
                    }
                ]
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    values = await gateway.knowledge_analysis_batches(_session())
    assert len(values) == 1
    assert values[0].batch_id == batch_id
    assert values[0].accepted_range_count == 17
    assert values[0].total_range_count == 495
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_validates_assessment_learning_batch_and_exam_progress() -> None:
    batch_id = "legacybatch_" + "1" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/assessment-learning-batches":
            assert request.url.params["limit"] == "20"
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "schema_version": "assessment-learning-batch-view/1.0",
                            "extraction_batch_id": batch_id,
                            "inventory_id": "legacyinventory_" + "2" * 32,
                            "inventory_sha256": "sha256:" + "3" * 64,
                            "state": "RUNNING",
                            "exam_count": 25,
                            "total_work_unit_count": 108,
                            "image_required_work_unit_count": 108,
                            "image_observation_mode": "REQUIRED",
                            "text_evidence_mode": "AUXILIARY_WHEN_AVAILABLE",
                            "work_units": {
                                "pending": 107,
                                "claimed": 0,
                                "submitted": 0,
                                "awaiting_review": 0,
                                "accepted": 1,
                                "failed": 0,
                                "cancelled": 0,
                            },
                            "items": {
                                "expected": 520,
                                "accepted": 5,
                                "promoted": 2,
                                "analysis_active": 1,
                                "analysis_accepted": 1,
                                "analysis_failed": 0,
                                "graph_published": 0,
                            },
                            "current_graph_snapshot_revision_id": "graphrev_" + "4" * 32,
                            "resource_version": 2,
                            "created_at": NOW.isoformat(),
                            "started_at": NOW.isoformat(),
                            "completed_at": None,
                            "updated_at": NOW.isoformat(),
                        }
                    ]
                ),
            )
        assert request.url.path == f"/api/v1/assessment-learning-batches/{batch_id}/exams"
        assert request.url.params["limit"] == "500"
        return httpx.Response(
            200,
            json=_list(
                [
                    {
                        "schema_version": "assessment-learning-exam-view/1.0",
                        "extraction_batch_id": batch_id,
                        "assessment_occurrence_id": "occurrence_" + "5" * 32,
                        "assessment_occurrence_revision_id": "occurrev_" + "6" * 32,
                        "assessment_occurrence_revision_sha256": "sha256:" + "7" * 64,
                        "assessment_source_bundle_revision_id": "assessbundlerev_" + "8" * 32,
                        "display_label": "2025년 고1 6월 통합과학",
                        "administration_year": 2025,
                        "administration_month": 6,
                        "target_school_level": "HIGH_SCHOOL",
                        "target_grade": 1,
                        "subject_key": "integrated-science",
                        "total_work_unit_count": 4,
                        "image_required_work_unit_count": 4,
                        "work_units": {
                            "pending": 3,
                            "claimed": 0,
                            "submitted": 0,
                            "awaiting_review": 0,
                            "accepted": 1,
                            "failed": 0,
                            "cancelled": 0,
                        },
                        "items": {
                            "expected": 20,
                            "accepted": 5,
                            "promoted": 2,
                            "analysis_active": 1,
                            "analysis_accepted": 1,
                            "analysis_failed": 0,
                            "graph_published": 0,
                        },
                    }
                ]
            ),
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    batches = await gateway.assessment_learning_batches(_session())
    exams = await gateway.assessment_learning_exams(_session(), batch_id)
    assert batches[0].items.expected == 520
    assert batches[0].image_observation_mode == "REQUIRED"
    assert exams[0].display_label == "2025년 고1 6월 통합과학"
    assert exams[0].items.graph_published == 0
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_validates_assessment_page_pointer_and_png_bytes() -> None:
    batch_id = "legacybatch_" + "1" * 32
    occurrence_revision_id = "occurrev_" + "2" * 32
    page_input_id = "assessmentpage_" + "3" * 32
    content = b"\x89PNG\r\n\x1a\nWEB_PAGE"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pages"):
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "schema_version": "assessment-learning-page-view/1.0",
                            "extraction_batch_id": batch_id,
                            "assessment_occurrence_revision_id": occurrence_revision_id,
                            "page_input_id": page_input_id,
                            "source_role": "PROBLEM_DOCUMENT",
                            "physical_page": 1,
                            "artifact_id": "artifact_" + "4" * 32,
                            "artifact_revision_id": "rev_" + "5" * 32,
                            "artifact_member": "pages/problem-1.png",
                            "sha256": digest,
                            "media_type": "image/png",
                            "content_length": len(content),
                            "width_px": 1240,
                            "height_px": 1754,
                        }
                    ]
                ),
            )
        return httpx.Response(
            200,
            content=content,
            headers={
                "Content-Type": "image/png",
                "Content-Length": str(len(content)),
                "ETag": f'"{digest}"',
            },
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    pages = await gateway.assessment_learning_pages(_session(), batch_id, occurrence_revision_id)
    media = await gateway.assessment_learning_page_media(
        _session(), batch_id, occurrence_revision_id, page_input_id
    )
    assert pages[0].artifact_revision_id == "rev_" + "5" * 32
    assert media.content == content
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_projects_exact_analysis_range_page_and_opaque_cursor() -> None:
    batch_id = "analysisbatch_" + "a" * 32
    next_cursor = "opaque-range-cursor"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/knowledge-analysis-batches/{batch_id}/ranges"
        assert request.url.params["limit"] == "200"
        assert "cursor" not in request.url.params
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "range_id": "analysisrange_" + "1" * 32,
                        "batch_id": batch_id,
                        "ordinal": 0,
                        "document_id": "edudoc_" + "2" * 32,
                        "document_revision_id": "edudocrev_" + "3" * 32,
                        "first_physical_page": 1,
                        "last_physical_page": 4,
                        "curriculum_unit_keys": ["1-(1)"],
                        "source_artifact_revision_id": "rev_" + "4" * 32,
                        "source_sha256": "sha256:" + "5" * 64,
                        "analysis_artifact_revision_id": "rev_" + "6" * 32,
                        "analysis_schema_ref": (
                            "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
                        ),
                        "analysis_run_id": "analysisrun_" + "7" * 32,
                        "state": "ACCEPTED",
                        "updated_at": NOW.isoformat(),
                    }
                ],
                "page": {"next_cursor": next_cursor, "has_more": True, "limit": 200},
                "meta": {"request_id": "req_test", "api_version": "1"},
            },
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    page = await gateway.knowledge_analysis_batch_ranges(_session(), batch_id, cursor=None)
    assert page.has_more is True
    assert page.next_cursor == next_cursor
    assert page.values[0].analysis_schema_ref.endswith("/2.0")
    assert page.values[0].curriculum_unit_keys == ("1-(1)",)
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_rejects_incoherent_analysis_range_pagination() -> None:
    batch_id = "analysisbatch_" + "a" * 32

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [],
                "page": {"next_cursor": None, "has_more": True, "limit": 200},
                "meta": {"request_id": "req_test", "api_version": "1"},
            },
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
        await gateway.knowledge_analysis_batch_ranges(_session(), batch_id, cursor=None)
    await gateway.close()


@pytest.mark.anyio
async def test_item_preview_fails_on_revision_pointer_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/v1/items/"):
            return httpx.Response(200, json=_single({"current_revision_id": "itemrev_other"}))
        if request.url.path.startswith("/api/v1/item-revisions/"):
            return httpx.Response(
                200,
                json=_single(
                    {
                        "item_id": "item_test0001",
                        "workflow_id": "workflow_test0001",
                        "revision_state": "APPROVED",
                        "content_pack_release_id": "packrel_test0001",
                    }
                ),
            )
        raise AssertionError(request.url.path)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GatewayError, match="ITEM_REVISION_POINTER_MISMATCH"):
        await gateway.item_preview(_session(), "item_test0001", "itemrev_test0001")
    await gateway.close()


@pytest.mark.anyio
async def test_item_preview_reports_exact_structured_template_component() -> None:
    item_id = "item_test0001"
    revision_id = "itemrev_test0001"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v1/items/{item_id}":
            return httpx.Response(200, json=_single({"current_revision_id": revision_id}))
        if request.url.path == f"/api/v1/item-revisions/{revision_id}":
            return httpx.Response(
                200,
                headers={"ETag": '"v1"'},
                json=_single(
                    {
                        "item_id": item_id,
                        "workflow_id": "workflow_test0001",
                        "revision_state": "APPROVED",
                        "content_pack_release_id": "packrel_test0001",
                    }
                ),
            )
        if request.url.path == f"/api/v1/item-revisions/{revision_id}/components":
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "item_revision_id": revision_id,
                            "component_type": "ITEM_CONTENT",
                            "ordinal": 0,
                            "required": True,
                            "artifact": {
                                "schema_ref": "eom.assessment.item-content/1.0",
                            },
                        }
                    ]
                ),
            )
        if request.url.path == f"/api/v1/item-revisions/{revision_id}/structured-content":
            return httpx.Response(200, json=_single(structured_item_content()))
        raise AssertionError(request.url.path)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    preview = await gateway.item_preview(_session(), item_id, revision_id)
    assert preview.template_delivery_available is True
    assert preview.preview_state == "AVAILABLE"
    assert preview.revision_etag == '"v1"'
    assert [block.type for block in preview.blocks] == [
        "paragraph",
        "table",
        "image",
        "equation",
        "paragraph",
        "statement_set",
    ]
    equation = next(block for block in preview.blocks if block.type == "equation")
    assert equation.source == "a^2+b^2=c^2"
    image = next(block for block in preview.blocks if block.type == "image")
    assert image.media_url.endswith(f"/{revision_id}/media/block_image")
    await gateway.close()


@pytest.mark.anyio
async def test_content_team_item_preview_exposes_hwpx_delivery_without_v1_projection() -> None:
    item_id = "item_test0002"
    revision_id = "itemrev_test0002"
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == f"/api/v1/items/{item_id}":
            return httpx.Response(200, json=_single({"current_revision_id": revision_id}))
        if request.url.path == f"/api/v1/item-revisions/{revision_id}":
            return httpx.Response(
                200,
                headers={"ETag": '"v1"'},
                json=_single(
                    {
                        "item_id": item_id,
                        "workflow_id": "workflow_test0002",
                        "revision_state": "APPROVED",
                        "content_pack_release_id": "packrel_test0002",
                    }
                ),
            )
        if request.url.path == f"/api/v1/item-revisions/{revision_id}/components":
            return httpx.Response(
                200,
                json=_list(
                    [
                        {
                            "item_revision_id": revision_id,
                            "component_type": "ITEM_CONTENT",
                            "ordinal": 0,
                            "required": True,
                            "artifact": {
                                "schema_ref": "eom.assessment.item-content/2.0",
                            },
                        }
                    ]
                ),
            )
        raise AssertionError(request.url.path)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )

    preview = await gateway.item_preview(_session(), item_id, revision_id)

    assert preview.preview_state == "METADATA_ONLY"
    assert preview.template_delivery_available is True
    assert f"/api/v1/item-revisions/{revision_id}/structured-content" not in paths
    await gateway.close()


@pytest.mark.anyio
async def test_item_revision_explorer_requires_exact_pinned_identity() -> None:
    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    result = await gateway.explorer(_session(), ExplorerQuery(entity="item_revisions"))
    assert result.capability == "EXACT_ID_REQUIRED"
    assert result.rows == ()
    await gateway.close()
