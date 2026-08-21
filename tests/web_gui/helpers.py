from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from eom_web_gui.app import create_app
from eom_web_gui.contracts import (
    ExplorerQuery,
    ExplorerResult,
    ItemPreview,
    PreviewChoice,
    PreviewTable,
)
from eom_web_gui.gateways import LoginResult
from eom_web_gui.services import WebServices, build_services
from eom_web_gui.sessions import ApiTokens, WebSession
from eom_web_gui.settings import ServerSettings, WebSettings
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 21, 7, 0, tzinfo=UTC)
WORKFLOW_ID = "workflow_test0000000000000000000000000001"
ITEM_ID = "item_test000000000000000000000000000001"
REVISION_ID = "itemrev_test00000000000000000000000001"


class FakeGateway:
    def __init__(self, *, roles: list[str] | None = None) -> None:
        self.start_calls = 0
        self.approval_calls = 0
        self.closed = False
        self.roles = roles or ["ADMIN", "REVIEWER"]

    async def health(self) -> dict[str, str]:
        return {
            "application_api": "ACTIVE",
            "application_api_ready": "ACTIVE",
            "observability": "ACTIVE",
        }

    async def login(self, username: str, password: str) -> LoginResult:
        if username != "admin" or password != "TEST_ONLY_PASSWORD":
            from eom_web_gui.gateways import GatewayError

            raise GatewayError(status=401, code="AUTHENTICATION_FAILED")
        return LoginResult(
            operator={
                "operator_id": "operator_test_admin",
                "username": "admin",
                "display_name": "테스트 관리자",
                "roles": self.roles,
                "effective_permissions": ["WORKFLOW_READ", "WORKFLOW_APPROVE"],
            },
            tokens=ApiTokens(
                "TEST_ONLY_ACCESS",
                "TEST_ONLY_REFRESH",
                NOW + timedelta(hours=1),
                NOW + timedelta(days=1),
            ),
        )

    async def logout(self, session: WebSession) -> None:
        del session

    async def start_workflow(
        self, session: WebSession, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, Any]:
        del session, idempotency_key
        assert payload["request_name"] == "PLACEHOLDER_REQUEST"
        self.start_calls += 1
        return {
            "command_id": "command_test_workflow_start",
            "resource_type": "workflow",
            "resource_id": WORKFLOW_ID,
            "status": "ACCEPTED",
            "resource_version": 1,
        }

    async def workflow_bundle(self, session: WebSession, workflow_id: str) -> dict[str, Any]:
        del session
        assert workflow_id == WORKFLOW_ID
        return {
            "workflow": {
                "workflow_id": WORKFLOW_ID,
                "definition_key": "generic-item-development",
                "definition_version": "1.1.0",
                "state": "AWAITING_HUMAN_APPROVAL",
                "stage": "APPROVAL",
                "current_step_key": "approval",
                "resource_version": 4,
                "created_at": NOW.isoformat(),
                "updated_at": (NOW + timedelta(seconds=5)).isoformat(),
            },
            "etag": '"4"',
            "steps": [
                {
                    "step_run_id": "steprun_test_authoring",
                    "workflow_id": WORKFLOW_ID,
                    "step_key": "authoring",
                    "attempt": 1,
                    "step_type": "WORKER",
                    "worker_role": "authoring",
                    "state": "SUCCEEDED",
                    "started_at": (NOW + timedelta(seconds=1)).isoformat(),
                    "finished_at": (NOW + timedelta(seconds=3)).isoformat(),
                    "platform_job_id": "job_test_authoring",
                    "error_code": None,
                },
                {
                    "step_run_id": "steprun_test_review",
                    "workflow_id": WORKFLOW_ID,
                    "step_key": "review",
                    "attempt": 1,
                    "step_type": "WORKER",
                    "worker_role": "review",
                    "state": "SUCCEEDED",
                    "started_at": (NOW + timedelta(seconds=3)).isoformat(),
                    "finished_at": (NOW + timedelta(seconds=5)).isoformat(),
                    "platform_job_id": "job_test_review",
                    "error_code": None,
                },
            ],
            "events": [
                {
                    "event_id": "event_test_created",
                    "event_type": "WORKFLOW_CREATED",
                    "new_state": "RUNNING",
                    "created_at": NOW.isoformat(),
                },
                {
                    "event_id": "event_test_approval",
                    "event_type": "APPROVAL_REQUESTED",
                    "new_state": "AWAITING_HUMAN_APPROVAL",
                    "created_at": (NOW + timedelta(seconds=5)).isoformat(),
                },
            ],
            "observe": {
                "events": [
                    {
                        "event_id": "event_test_job",
                        "event_type": "JOB_SUCCEEDED",
                        "timestamp": (NOW + timedelta(seconds=4)).isoformat(),
                        "status": "SUCCEEDED",
                        "job_id": "job_test_authoring",
                        "artifact_id": "artifact_test_authoring",
                    }
                ]
            },
        }

    async def approve_workflow(
        self,
        session: WebSession,
        workflow_id: str,
        *,
        etag: str,
        idempotency_key: str,
        reason: str | None,
    ) -> dict[str, Any]:
        del session, idempotency_key, reason
        assert workflow_id == WORKFLOW_ID
        assert etag == '"4"'
        self.approval_calls += 1
        return {
            "command_id": "command_test_approval",
            "resource_id": workflow_id,
            "status": "ACCEPTED",
            "resource_version": 5,
        }

    async def item_preview(
        self, session: WebSession, item_id: str, item_revision_id: str
    ) -> ItemPreview:
        del session
        assert item_id == ITEM_ID and item_revision_id == REVISION_ID
        return ItemPreview(
            preview_state="AVAILABLE",
            workflow_id=WORKFLOW_ID,
            item_id=item_id,
            item_revision_id=item_revision_id,
            revision_state="APPROVED",
            content_pack_release_id="packrel_test_physics",
            body="공기 저항을 무시할 때 수평으로 던진 물체의 2초 후 수평 이동 거리를 구하시오.",
            choices=tuple(
                PreviewChoice(label=f"{index}.", text=f"{index * 5} m") for index in range(1, 6)
            ),
            answer="4.",
            explanation="수평 방향 속도는 일정하므로 x = v₀t를 사용한다.",
            equations=("x=v_0 t", "y=\\frac{1}{2}gt^2"),
            tables=(
                PreviewTable(
                    caption="운동 조건",
                    headers=("물리량", "값"),
                    rows=(("시간", "2 s"), ("수평 속도", "10 m/s")),
                ),
            ),
        )

    async def explorer(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult:
        del session
        return ExplorerResult(
            entity=query.entity,
            columns=("workflow_id", "state", "created_at"),
            rows=(
                ({"workflow_id": WORKFLOW_ID, "state": "COMPLETED", "created_at": NOW.isoformat()}),
            ),
        )

    async def close(self) -> None:
        self.closed = True


def make_services(*, gateway: FakeGateway | None = None) -> tuple[WebServices, FakeGateway]:
    fake = gateway or FakeGateway()
    settings = WebSettings(server=ServerSettings(allowed_hosts=("testserver",)))
    return build_services(settings, fake), fake


def make_client(*, gateway: FakeGateway | None = None) -> tuple[TestClient, FakeGateway]:
    services, fake = make_services(gateway=gateway)
    return TestClient(create_app(services)), fake


def login(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/studio/api/v1/session",
        json={"username": "admin", "password": "TEST_ONLY_PASSWORD"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 201
    return response.json()
