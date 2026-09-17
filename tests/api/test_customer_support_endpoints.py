from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.query_adapter import PageResult
from eom_api_contracts.customer_support import CustomerSupportCaseView
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import OperatorProjection, PermissionKey, RoleKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import FakeAudit, MemoryIdempotency

NOW = datetime(2026, 9, 17, tzinfo=UTC)
OPERATOR_ID = "operator_" + "1" * 32
WORKFLOW_ID = "workflow_" + "2" * 32


def _authentication(*, readable: bool = True, writable: bool = True) -> AccessAuthentication:
    permissions = frozenset(
        permission
        for permission, included in (
            (PermissionKey.CUSTOMER_SUPPORT_READ, readable),
            (PermissionKey.CUSTOMER_SUPPORT_CREATE, writable),
        )
        if included
    )
    operator = OperatorProjection(
        operator_id=OPERATOR_ID,
        username="support-user",
        display_name="Support User",
        status="ACTIVE",
        must_change_password=False,
        roles=(RoleKey.VIEWER,),
        effective_permissions=tuple(sorted(permissions, key=str)),
        resource_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return AccessAuthentication(
        operator=operator,
        session_id="apisession_" + "3" * 32,
        authenticated_at=NOW,
        access_expires_at=NOW + timedelta(hours=1),
        permissions=permissions,
        password_change_required=False,
    )


def _case(*, state: str = "ANSWERED") -> CustomerSupportCaseView:
    return CustomerSupportCaseView(
        workflow_id=WORKFLOW_ID,
        category="HOW_TO",
        subject="HWPX 내려받기",
        question="완성된 문항의 HWPX 파일을 내려받는 방법을 알려주세요.",
        state=state,
        classification="USAGE_GUIDANCE" if state == "ANSWERED" else None,
        answer_text="HWPX 화면에서 완성된 제작 결과를 선택합니다." if state == "ANSWERED" else None,
        recommended_actions=(
            (
                {
                    "title": "HWPX 화면 열기",
                    "instruction": "왼쪽 메뉴에서 HWPX를 선택합니다.",
                },
            )
            if state == "ANSWERED"
            else ()
        ),
        created_at=NOW,
        updated_at=NOW,
        resource_version=2,
    )


class FakeQueries:
    def __init__(self) -> None:
        self.actor_ids: list[str] = []

    def list_customer_support_cases(self, **values: Any) -> PageResult[CustomerSupportCaseView]:
        self.actor_ids.append(values["actor_id"])
        return PageResult((_case(),), None, False)

    def customer_support_case(self, **values: Any) -> CustomerSupportCaseView:
        self.actor_ids.append(values["actor_id"])
        assert values["workflow_id"] == WORKFLOW_ID
        return _case()


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def start_customer_support(
        self, request: object, actor: object, **values: Any
    ) -> tuple[str, str, int]:
        self.calls.append({"request": request, "actor": actor, **values})
        return "wfcmd_" + "4" * 32, WORKFLOW_ID, 1


def _client(
    *,
    readable: bool = True,
    writable: bool = True,
) -> tuple[TestClient, Any, FakeQueries, FakeCommands]:
    services = disconnected_services()
    queries = FakeQueries()
    commands = FakeCommands()
    services.queries = queries  # type: ignore[assignment]
    services.commands = commands  # type: ignore[assignment]
    services.idempotency = MemoryIdempotency()  # type: ignore[assignment]
    services.audit = FakeAudit()  # type: ignore[assignment]
    app = create_app(services)

    def authenticated(request: Request) -> AccessAuthentication:
        value = _authentication(readable=readable, writable=writable)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services, queries, commands


def test_customer_support_endpoints_scope_reads_to_authenticated_operator(monkeypatch) -> None:
    monkeypatch.setattr(
        "eom_api.routers.customer_support.get_build_info",
        lambda: SimpleNamespace(source_commit="5" * 40),
    )
    client, services, queries, commands = _client()
    try:
        with client:
            created = client.post(
                "/api/v1/customer-support/cases",
                headers={"Idempotency-Key": "support-create-test-0001"},
                json={
                    "category": "HOW_TO",
                    "subject": "HWPX 내려받기",
                    "question": "완성된 문항의 HWPX 파일을 내려받는 방법을 알려주세요.",
                    "locale": "ko-KR",
                    "browser_route": "/studio/",
                    "inquiry_id": "webreq_" + "6" * 24,
                    "web_release_commit": "7" * 40,
                },
            )
            listed = client.get("/api/v1/customer-support/cases")
            detail = client.get(f"/api/v1/customer-support/cases/{WORKFLOW_ID}")
        assert created.status_code == 202
        assert created.json()["data"]["resource_id"] == WORKFLOW_ID
        assert listed.status_code == detail.status_code == 200
        assert listed.json()["data"][0]["state"] == "ANSWERED"
        assert detail.json()["data"]["answer_text"].startswith("HWPX 화면")
        assert queries.actor_ids == [OPERATOR_ID, OPERATOR_ID]
        assert commands.calls[0]["api_release_commit"] == "5" * 40
        assert commands.calls[0]["request"].web_release_commit == "7" * 40
    finally:
        services.engine.dispose()


def test_customer_support_create_replays_when_only_server_diagnostics_change(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "eom_api.routers.customer_support.get_build_info",
        lambda: SimpleNamespace(source_commit="5" * 40),
    )
    client, services, _queries, commands = _client()
    request_body = {
        "category": "TECHNICAL_ERROR",
        "subject": "미리보기 상태 확인",
        "question": "문항 미리보기의 현재 상태를 확인하는 방법을 알려주세요.",
        "locale": "ko-KR",
        "browser_route": "/studio/",
        "stable_error_code": "ITEM_PREVIEW_NOT_READY",
        "inquiry_id": "webreq_" + "6" * 24,
        "web_release_commit": "7" * 40,
    }
    try:
        with client:
            first = client.post(
                "/api/v1/customer-support/cases",
                headers={"Idempotency-Key": "support-create-replay-0001"},
                json=request_body,
            )
            replay = client.post(
                "/api/v1/customer-support/cases",
                headers={"Idempotency-Key": "support-create-replay-0001"},
                json={
                    **request_body,
                    "inquiry_id": "webreq_" + "8" * 24,
                    "web_release_commit": "9" * 40,
                },
            )
            conflict = client.post(
                "/api/v1/customer-support/cases",
                headers={"Idempotency-Key": "support-create-replay-0001"},
                json={
                    **request_body,
                    "question": "같은 키로 다른 문의 내용을 제출하면 거부되어야 합니다.",
                },
            )
        assert first.status_code == replay.status_code == 202
        assert first.json()["data"] == replay.json()["data"]
        assert conflict.status_code == 409
        assert conflict.json()["error_code"] == "API_IDEMPOTENCY_CONFLICT"
        assert len(commands.calls) == 1
    finally:
        services.engine.dispose()


def test_customer_support_permissions_fail_closed() -> None:
    client, services, _queries, _commands = _client(readable=False, writable=False)
    try:
        with client:
            listed = client.get("/api/v1/customer-support/cases")
            created = client.post(
                "/api/v1/customer-support/cases",
                headers={"Idempotency-Key": "support-create-denied-0001"},
                json={
                    "category": "HOW_TO",
                    "subject": "도움 요청 제목",
                    "question": "권한이 없을 때 이 문의는 접수되면 안 됩니다.",
                    "locale": "ko-KR",
                },
            )
        assert listed.status_code == created.status_code == 403
        assert listed.json()["error_code"] == "PERMISSION_DENIED"
    finally:
        services.engine.dispose()


def test_customer_support_rejects_query_or_fragment_from_diagnostic_route() -> None:
    client, services, _queries, commands = _client()
    try:
        with client:
            response = client.post(
                "/api/v1/customer-support/cases",
                headers={"Idempotency-Key": "support-create-route-secret-0001"},
                json={
                    "category": "TECHNICAL_ERROR",
                    "subject": "진단 경로 확인",
                    "question": "주소의 query 값은 고객지원 진단에 포함되면 안 됩니다.",
                    "locale": "ko-KR",
                    "browser_route": "/studio/?access_token=forbidden",
                },
            )
        assert response.status_code == 422
        assert commands.calls == []
    finally:
        services.engine.dispose()
