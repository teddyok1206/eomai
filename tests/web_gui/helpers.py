from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from eom_web_gui.app import create_app
from eom_web_gui.contracts import (
    CodexAuthEnrollmentStatusView,
    CodexDeviceChallengeView,
    ContentIntakeOption,
    ContentIntakeSourcePointer,
    CurriculumEditorialOutline,
    ExplorerQuery,
    ExplorerResult,
    HwpxBuildRequest,
    HwpxBuildView,
    HwpxCapability,
    ItemPreview,
    KnowledgeAnalysisBatchRangeStatus,
    KnowledgeAnalysisBatchStatus,
    PreviewChoice,
    PreviewTable,
    RecentItemOption,
    StructuredItemImportRequest,
)
from eom_web_gui.gateways import (
    GatewayError,
    HwpxDownload,
    KnowledgeAnalysisRangePage,
    LoginResult,
)
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
        self.control_command_calls = 0
        self.auth_enrollment_calls = 0
        self.auth_challenge_reveal_calls = 0
        self.preset_mutation_calls = 0
        self.last_start_payload: dict[str, object] | None = None

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

    async def curriculum_editorial_outline(self, session: WebSession) -> CurriculumEditorialOutline:
        del session
        counts = (4, 6, 7, 7, 7, 4)
        units: list[dict[str, object]] = []
        for large_number, middle_count in enumerate(counts, start=1):
            volume = "i" if large_number <= 3 else "ii"
            units.append(
                {
                    "key": f"eom.is.large.{large_number}",
                    "level": "LARGE",
                    "code": str(large_number),
                    "label": f"테스트 대단원 {large_number}",
                    "parent_key": f"eom.is.volume.{volume}",
                    "ordinal": large_number if large_number <= 3 else large_number - 3,
                }
            )
            units.extend(
                {
                    "key": f"eom.is.middle.{large_number}-{middle_number}",
                    "level": "MIDDLE",
                    "code": f"{large_number}-({middle_number})",
                    "label": f"테스트 중단원 {large_number}-({middle_number})",
                    "parent_key": f"eom.is.large.{large_number}",
                    "ordinal": middle_number,
                }
                for middle_number in range(1, middle_count + 1)
            )
        return CurriculumEditorialOutline.model_validate(
            {
                "schema_version": "integrated-science-editorial-outline/1.0",
                "outline_key": "eom-integrated-science-editorial-outline",
                "outline_revision": "1.0",
                "subject_key": "integrated-science",
                "subject_label": "통합과학",
                "graph_mapping_status": "RESERVED_CANDIDATES_NOT_PUBLICATION_PROOF",
                "graph_grounding_available": False,
                "supported_product_levels": ["LARGE", "MIDDLE"],
                "unsupported_product_levels": ["SMALL"],
                "units": units,
            }
        )

    async def start_workflow(
        self, session: WebSession, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, Any]:
        del session, idempotency_key
        assert payload["request_name"] == "GENERATED_KNOWLEDGE_ITEM_REQUEST"
        assert payload["definition_version"] == "1.4.0"
        assert payload["pack_key"] == "generated-knowledge-item"
        expected_preset = (
            "knowledge-grounded-item" if "educational_retrieval" in payload else "standard-item"
        )
        assert payload["execution_preset_key"] == expected_preset
        assert payload["stimulus_asset_key"] is None
        assert payload["source_intake_batch_ids"] == []
        self.last_start_payload = payload
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

    async def recent_items(self, session: WebSession) -> tuple[RecentItemOption, ...]:
        del session
        return (
            RecentItemOption(
                item_id=ITEM_ID,
                item_revision_id=REVISION_ID,
                lifecycle_state="ACTIVE",
                human_reference_code="EOM-SAMPLE-001",
                created_at=NOW,
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
            source_artifact_revision_id="rev_" + "a" * 32,
            source_sha256="sha256:" + "a" * 64,
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
            created_by_operator_id="operator_" + "e" * 32,
            created_at=NOW,
            completed_at=NOW + timedelta(seconds=2),
            resource_version=3,
        )

    async def hwpx_download(self, session: WebSession, build_id: str) -> HwpxDownload:
        del session
        assert build_id == "hwpxbuild_" + "a" * 32
        return HwpxDownload(
            b"TEST_ONLY_HWPX",
            "application/vnd.hancom.hwpx",
            'attachment; filename="eom-test.hwpx"',
        )

    async def codex_accounts(self, session: WebSession) -> tuple[dict[str, Any], ...]:
        del session
        return (
            {
                "binding_id": "authbinding_" + "1" * 32,
                "slot_key": "slot01",
                "account_label": "account-01",
                "state": "READY",
                "reason_code": None,
                "codex_cli_version": "1.2.3",
                "observed_at": NOW.isoformat(),
                "valid_until": (NOW + timedelta(hours=1)).isoformat(),
                "resource_version": 2,
                "capabilities": [
                    {"model": "gpt-5.4", "reasoning_effort": "high", "state": "READY"}
                ],
                "active_lease_count": 0,
                "last_successful_job_id": "job_" + "2" * 32,
                "active_auth_enrollment_id": None,
                "active_auth_enrollment_state": None,
            },
        )

    async def start_codex_auth_enrollment(
        self,
        session: WebSession,
        binding_id: str,
        *,
        requested_account_label: str,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del session
        assert binding_id == "authbinding_" + "1" * 32
        assert requested_account_label == "teacher-account-01"
        assert resource_version == 2
        assert len(idempotency_key) >= 16
        self.auth_enrollment_calls += 1
        enrollment_id = "authflow_" + "3" * 32
        return {
            "command_id": enrollment_id,
            "resource_id": enrollment_id,
            "resource_type": "codex_auth_enrollment",
            "status": "ACCEPTED",
            "resource_version": 1,
            "status_url": f"/api/v1/codex-auth-enrollments/{enrollment_id}",
        }

    async def codex_auth_enrollment(
        self, session: WebSession, enrollment_id: str
    ) -> CodexAuthEnrollmentStatusView:
        del session
        assert enrollment_id == "authflow_" + "3" * 32
        return CodexAuthEnrollmentStatusView(
            enrollment_id=enrollment_id,
            binding_id="authbinding_" + "1" * 32,
            slot_key="slot01",
            requested_account_label="teacher-account-01",
            state="WAITING_FOR_USER",
            challenge_available=True,
            challenge_revealed_at=None,
            assignment_revision_id=None,
            error_code=None,
            requested_at=NOW,
            started_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
            completed_at=None,
            resource_version=4,
        )

    async def reveal_codex_auth_challenge(
        self, session: WebSession, enrollment_id: str
    ) -> CodexDeviceChallengeView:
        del session
        assert enrollment_id == "authflow_" + "3" * 32
        self.auth_challenge_reveal_calls += 1
        return CodexDeviceChallengeView(
            enrollment_id=enrollment_id,
            slot_key="slot01",
            verification_uri="https://auth.openai.com/codex/device",
            user_code="ABC1-DEF2",
            expires_at=NOW + timedelta(minutes=10),
        )

    async def knowledge_analysis_batches(
        self, session: WebSession
    ) -> tuple[KnowledgeAnalysisBatchStatus, ...]:
        del session
        return (
            KnowledgeAnalysisBatchStatus(
                batch_id="analysisbatch_" + "7" * 32,
                state="RUNNING",
                total_range_count=495,
                accepted_range_count=12,
                failed_range_count=0,
                failure_code=None,
                resource_version=4,
                created_at=NOW,
                started_at=NOW,
                completed_at=None,
                updated_at=NOW + timedelta(minutes=3),
            ),
        )

    async def knowledge_analysis_batch(
        self, session: WebSession, batch_id: str
    ) -> KnowledgeAnalysisBatchStatus:
        values = await self.knowledge_analysis_batches(session)
        assert batch_id == values[0].batch_id
        return values[0]

    async def knowledge_analysis_batch_ranges(
        self, session: WebSession, batch_id: str, *, cursor: str | None
    ) -> KnowledgeAnalysisRangePage:
        del session
        assert batch_id == "analysisbatch_" + "7" * 32
        offset = int(cursor.removeprefix("offset:")) if cursor else 0
        stop = min(offset + 200, 495)
        values = tuple(
            KnowledgeAnalysisBatchRangeStatus(
                range_id=f"analysisrange_{index:032x}",
                batch_id=batch_id,
                ordinal=index,
                document_id="edudoc_" + "8" * 32,
                document_revision_id="edudocrev_" + "9" * 32,
                first_physical_page=index + 1,
                last_physical_page=index + 1,
                curriculum_unit_keys=("1-(1)",),
                source_artifact_revision_id="rev_" + "a" * 32,
                source_sha256="sha256:" + "b" * 64,
                analysis_artifact_revision_id="rev_" + "c" * 32,
                analysis_schema_ref=(
                    "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0"
                ),
                analysis_run_id=(f"analysisrun_{index:032x}" if index < 12 else None),
                state="ACCEPTED" if index < 12 else "PENDING",
                updated_at=NOW + timedelta(minutes=3),
            )
            for index in range(offset, stop)
        )
        return KnowledgeAnalysisRangePage(
            values=values,
            next_cursor=f"offset:{stop}" if stop < 495 else None,
            has_more=stop < 495,
        )

    async def codex_account_command(
        self,
        session: WebSession,
        binding_id: str,
        *,
        command_type: str,
        reason_code: str | None,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del session, idempotency_key
        assert binding_id == "authbinding_" + "1" * 32
        assert command_type == "OBSERVE" and reason_code is None and resource_version == 2
        self.control_command_calls += 1
        return {
            "command_id": "codexcmd_" + "3" * 32,
            "resource_type": "codex_control_command",
            "resource_id": "codexcmd_" + "3" * 32,
            "status": "ACCEPTED",
            "resource_version": 2,
        }

    async def codex_control_command(self, session: WebSession, command_id: str) -> dict[str, Any]:
        del session
        assert command_id == "codexcmd_" + "3" * 32
        return {
            "command_id": command_id,
            "command_type": "OBSERVE",
            "binding_id": "authbinding_" + "1" * 32,
            "state": "SUCCEEDED",
            "attempts": 1,
            "result_resource_version": 3,
            "error_code": None,
            "requested_at": NOW.isoformat(),
            "processed_at": NOW.isoformat(),
        }

    async def execution_presets(self, session: WebSession) -> tuple[dict[str, Any], ...]:
        del session
        return (
            {
                "preset_id": "execpreset_" + "4" * 32,
                "preset_key": "standard-item",
                "current_revision_id": "execpresetrev_" + "5" * 32,
                "state": "ACTIVE",
                "created_at": NOW.isoformat(),
                "updated_at": NOW.isoformat(),
                "revisions": [],
            },
        )

    async def create_execution_preset_draft(
        self, session: WebSession, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        del session, payload, idempotency_key
        self.preset_mutation_calls += 1
        return {"resource_id": "execpresetrev_" + "6" * 32, "status": "COMPLETED"}

    async def release_execution_preset(
        self,
        session: WebSession,
        draft_revision_id: str,
        *,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del session, resource_version, idempotency_key
        self.preset_mutation_calls += 1
        return {"resource_id": draft_revision_id, "status": "COMPLETED"}

    async def deprecate_execution_preset(
        self,
        session: WebSession,
        preset_id: str,
        *,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del session, resource_version, idempotency_key
        self.preset_mutation_calls += 1
        return {"resource_id": preset_id, "status": "COMPLETED"}

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
