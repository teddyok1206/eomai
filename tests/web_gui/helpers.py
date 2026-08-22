from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from eom_web_gui.app import create_app
from eom_web_gui.contracts import (
    ContentIntakeOption,
    ContentIntakeSourcePointer,
    ExplorerQuery,
    ExplorerResult,
    HwpxBuildRequest,
    HwpxBuildView,
    HwpxCapability,
    ItemPreview,
    PreviewChoice,
    PreviewTable,
    StructuredItemImportRequest,
)
from eom_web_gui.gateways import GatewayError, HwpxDownload, LoginResult
from eom_web_gui.services import WebServices, build_services
from eom_web_gui.sessions import ApiTokens, WebSession
from eom_web_gui.settings import ServerSettings, WebSettings
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 21, 7, 0, tzinfo=UTC)
TOKEN_EXPIRY_BASE = datetime(2099, 1, 1, 0, 0, tzinfo=UTC)
WORKFLOW_ID = "workflow_test0000000000000000000000000001"
ITEM_ID = "item_test000000000000000000000000000001"
REVISION_ID = "itemrev_test00000000000000000000000001"
INTAKE_ID = "intake_00000000000000000000000000000001"


def structured_item_content() -> dict[str, object]:
    """Return a Web-boundary fixture without importing Catalog runtime packages."""
    return {
        "schema_version": "1.0",
        "locale": "ko-KR",
        "title": "삼각함수 문항",
        "body": [
            {
                "block_id": "block_stem",
                "type": "paragraph",
                "purpose": "stem",
                "text": "다음 자료를 보고 물음에 답하시오.",
            },
            {
                "block_id": "block_data",
                "type": "table",
                "purpose": "data",
                "caption": None,
                "headers": ["각", "사인", "코사인"],
                "rows": [["30", "1/2", "sqrt(3)/2"]],
            },
            {
                "block_id": "block_image",
                "type": "image",
                "purpose": "stimulus",
                "artifact": {
                    "artifact_id": "artifact_" + "1" * 32,
                    "artifact_revision_id": "rev_" + "2" * 32,
                    "artifact_member": "diagram.png",
                    "sha256": "sha256:" + "3" * 64,
                    "media_type": "image/png",
                },
                "alt_text": "삼각형 도식",
                "width_px": 800,
                "height_px": 500,
            },
            {
                "block_id": "block_equation",
                "type": "equation",
                "purpose": "stimulus",
                "notation": "hancom-equation-script",
                "source": "a^2+b^2=c^2",
            },
            {
                "block_id": "block_prompt",
                "type": "paragraph",
                "purpose": "prompt",
                "text": "옳은 것만을 고른 것은?",
            },
        ],
        "interaction": {
            "type": "single_choice",
            "choices": [
                {"choice_id": f"choice_{index}", "label": str(index), "text": f"선택지 {index}"}
                for index in range(1, 6)
            ],
        },
        "solution": {
            "correct_choice_ids": ["choice_3"],
            "accepted_answers": [],
            "explanation": "정답 해설",
            "authoring_intent": "삼각함수의 기본 관계를 평가한다.",
            "statement_explanations": [],
        },
        "score": {"points": 3},
    }


class FakeGateway:
    def __init__(
        self,
        *,
        roles: list[str] | None = None,
        hwpx_state: str = "PREPARED_NOT_DEPLOYED",
    ) -> None:
        self.start_calls = 0
        self.approval_calls = 0
        self.closed = False
        self.roles = roles or ["ADMIN", "REVIEWER"]
        self.hwpx_state = hwpx_state
        self.hwpx_build_calls = 0
        self.structured_import_calls = 0

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
                TOKEN_EXPIRY_BASE,
                TOKEN_EXPIRY_BASE + timedelta(days=1),
            ),
        )

    async def logout(self, session: WebSession) -> None:
        del session

    async def accepted_intakes(self, session: WebSession) -> tuple[ContentIntakeOption, ...]:
        del session
        return (
            ContentIntakeOption(
                intake_batch_id=INTAKE_ID,
                batch_name="테스트 물리학 소스",
                purpose="Generic Demo",
                updated_at=NOW,
            ),
        )

    async def intake_sources(
        self, session: WebSession, intake_id: str
    ) -> tuple[ContentIntakeSourcePointer, ...]:
        del session
        assert intake_id == INTAKE_ID
        return (
            ContentIntakeSourcePointer(
                source_file_id="sourcefile_" + "1" * 32,
                filename="diagram.png",
                artifact_id="artifact_" + "2" * 32,
                artifact_revision_id="rev_" + "3" * 32,
                artifact_member="source/diagram.png",
                sha256="sha256:" + "4" * 64,
                media_type="image/png",
            ),
        )

    async def start_workflow(
        self, session: WebSession, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, Any]:
        del session, idempotency_key
        assert payload["request_name"] == "GENERATED_KNOWLEDGE_ITEM_REQUEST"
        assert payload["definition_version"] == "1.3.0"
        assert payload["pack_key"] == "generated-knowledge-item"
        assert payload["stimulus_asset_key"] is None
        assert payload["source_intake_batch_ids"] == []
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
            "etag": '"v4"',
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
        assert etag == '"v4"'
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
            revision_etag='"v1"',
            revision_state="APPROVED",
            content_pack_release_id="packrel_test_physics",
            template_delivery_available=True,
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

    async def import_structured_item(
        self, session: WebSession, value: StructuredItemImportRequest
    ) -> dict[str, Any]:
        del session
        assert value.base_revision_id == REVISION_ID
        self.structured_import_calls += 1
        return {
            "command_id": "apicmd_" + "5" * 32,
            "resource_type": "item_revision",
            "resource_id": "itemrev_" + "6" * 32,
            "status": "COMPLETED",
            "resource_version": 1,
            "status_url": "/api/v1/item-revisions/" + "itemrev_" + "6" * 32,
        }

    async def explorer(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult:
        del session
        return ExplorerResult(
            entity=query.entity,
            columns=("workflow_id", "state", "created_at"),
            rows=(
                ({"workflow_id": WORKFLOW_ID, "state": "COMPLETED", "created_at": NOW.isoformat()}),
            ),
        )

    async def hwpx_capability(self, session: WebSession) -> HwpxCapability:
        del session
        return HwpxCapability.model_validate(
            {
                "state": self.hwpx_state,
                "renderer_key": "eom-template",
                "renderer_version": "1.0.0",
                "document_profile": "eom-question-template-v1",
                "build_available": self.hwpx_state == "READY",
                "native_equations": self.hwpx_state == "READY",
                "native_tables": self.hwpx_state == "READY",
                "detail_code": (
                    "HWPX_READY" if self.hwpx_state == "READY" else "HWPX_BUILDER_NOT_DEPLOYED"
                ),
                "message": "ready" if self.hwpx_state == "READY" else "운영 배포 필요",
            }
        )

    async def create_hwpx_build(
        self, session: WebSession, value: HwpxBuildRequest
    ) -> dict[str, Any]:
        del session
        if self.hwpx_state != "READY":
            raise GatewayError(status=503, code="HWPX_RENDERER_NOT_READY")
        assert value.item_revision_id == REVISION_ID
        self.hwpx_build_calls += 1
        return {
            "command_id": "hwpxcmd_" + "a" * 32,
            "resource_type": "hwpx_build",
            "resource_id": "hwpxbuild_" + "a" * 32,
            "status": "ACCEPTED",
            "resource_version": 1,
            "status_url": "/api/v1/hwpx-builds/hwpxbuild_" + "a" * 32,
        }

    async def hwpx_build(self, session: WebSession, build_id: str) -> HwpxBuildView:
        del session
        assert build_id == "hwpxbuild_" + "a" * 32
        return HwpxBuildView(
            build_id=build_id,
            item_id=ITEM_ID,
            item_revision_id=REVISION_ID,
            renderer="eom-template",
            renderer_version="1.0.0",
            state="SUCCEEDED",
            validation_state="PASS",
            native_equation_count=5,
            native_table_count=2,
            output_artifact_id="artifact_" + "b" * 32,
            output_artifact_revision_id="rev_" + "c" * 32,
            output_sha256="sha256:" + "d" * 64,
            download_available=True,
            created_at=NOW,
            completed_at=NOW + timedelta(seconds=2),
        )

    async def hwpx_download(self, session: WebSession, build_id: str) -> HwpxDownload:
        del session
        assert build_id == "hwpxbuild_" + "a" * 32
        return HwpxDownload(
            b"TEST_ONLY_HWPX",
            "application/vnd.hancom.hwpx",
            'attachment; filename="eom-test.hwpx"',
        )

    async def close(self) -> None:
        self.closed = True


def make_services(*, gateway: FakeGateway | None = None) -> tuple[WebServices, FakeGateway]:
    fake = gateway or FakeGateway()
    settings = WebSettings(server=ServerSettings(allowed_hosts=("testserver.local",)))
    return build_services(settings, fake), fake


def make_client(*, gateway: FakeGateway | None = None) -> tuple[TestClient, FakeGateway]:
    services, fake = make_services(gateway=gateway)
    # RFC 6265 cookie jars normalize single-label hosts to a synthetic .local
    # domain. Use that explicit test host so session path/domain behavior matches
    # a real browser rather than depending on a client-library compatibility quirk.
    return TestClient(create_app(services), base_url="http://testserver.local"), fake


def login(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/studio/api/v1/session",
        json={"username": "admin", "password": "TEST_ONLY_PASSWORD"},
        headers={"Origin": "http://testserver.local"},
    )
    assert response.status_code == 201
    return response.json()
