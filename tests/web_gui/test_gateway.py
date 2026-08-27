from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from eom_web_gui.contracts import ExplorerEntity, ExplorerQuery
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.sessions import ApiTokens, WebSession

from tests.web_gui.helpers import structured_item_content

NOW = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
TEST_REFRESH = "eom_rt_TEST_ONLY_REFRESH_" + "0" * 48


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
            return httpx.Response(200, json=_list([]))
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
        raise AssertionError(request.url.path)

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )
    assert await gateway.codex_accounts(_session()) == ()
    result = await gateway.codex_account_command(
        _session(),
        "authbinding_" + "2" * 32,
        command_type="OBSERVE",
        reason_code=None,
        resource_version=7,
        idempotency_key="stable-control-key-0001",
    )
    assert result["status"] == "ACCEPTED"
    assert len(requests) == 2
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
async def test_gateway_accepts_complete_application_hwpx_build_view() -> None:
    build_id = "hwpxbuild_" + "1" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/hwpx-builds/{build_id}"
        return httpx.Response(
            200,
            json=_single(_hwpx_build_data(build_id)),
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
    assert value.output_artifact_revision_id == "rev_" + "7" * 32
    assert value.resource_version == 3
    await gateway.close()


@pytest.mark.anyio
async def test_gateway_projects_bounded_recent_hwpx_builds_for_admin_ui() -> None:
    build_id = "hwpxbuild_" + "1" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/hwpx-builds"
        assert request.url.params["limit"] == "20"
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
    assert preview.equations == ("a^2+b^2=c^2",)
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
