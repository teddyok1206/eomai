from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from eom_web_gui.contracts import ExplorerQuery
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.sessions import ApiTokens, WebSession

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
