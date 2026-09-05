"""Loopback HTTP adapters for Application API and read-only Observability."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from eom_web_gui.contracts import (
    CodexAuthEnrollmentStatusView,
    CodexDeviceChallengeView,
    ContentIntakeOption,
    ContentIntakeSourcePointer,
    CurriculumEditorialOutline,
    ExplorerEntity,
    ExplorerQuery,
    ExplorerResult,
    HwpxBuildRequest,
    HwpxBuildView,
    HwpxCapability,
    ItemPreview,
    KnowledgeAnalysisBatchRangeStatus,
    KnowledgeAnalysisBatchStatus,
    PreviewChoice,
    PreviewEquationBlock,
    PreviewImageBlock,
    PreviewParagraphBlock,
    PreviewStatementExplanation,
    PreviewStatementSetBlock,
    PreviewTableBlock,
    RecentItemOption,
    StructuredItemImportRequest,
)
from eom_web_gui.redaction import sanitize_mapping
from eom_web_gui.sessions import ApiTokens, WebSession

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{7,127}$")
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
INTEGRATED_SCIENCE_OUTLINE_SHA256 = (
    "sha256:f11389c8ab26c2bd5b93acf66fe92d30fea9c1d0bc7e6b91a6b6751fdccb5108"
)
INTEGRATED_SCIENCE_CORPUS_KEY = "integrated-science-textbooks"


def _verified_curriculum_graph_corpus_key(capability: dict[str, Any]) -> str | None:
    """Validate the complete API-owned READY projection before returning its corpus identity."""

    if (
        capability.get("schema_version") == "curriculum-graph-capability/1.0"
        and capability.get("capability_state") == "READY"
        and capability.get("graph_grounding_available") is True
        and capability.get("reason") == "READY"
        and capability.get("corpus_key") == INTEGRATED_SCIENCE_CORPUS_KEY
        and capability.get("outline_key") == "eom-integrated-science-editorial-outline"
        and capability.get("outline_revision") == "1.0"
        and capability.get("outline_sha256") == INTEGRATED_SCIENCE_OUTLINE_SHA256
        and isinstance(capability.get("graph_snapshot_revision_id"), str)
        and re.fullmatch(r"graphrev_[0-9a-f]{32}", capability["graph_snapshot_revision_id"])
        and isinstance(capability.get("snapshot_sha256"), str)
        and SHA256_PATTERN.fullmatch(capability["snapshot_sha256"])
        and isinstance(capability.get("framework_revision_id"), str)
        and re.fullmatch(r"curriculumrev_[0-9a-f]{32}", capability["framework_revision_id"])
        and capability.get("unit_count") == 43
        and capability.get("closure_count") == 119
    ):
        return INTEGRATED_SCIENCE_CORPUS_KEY
    return None


def _ordered_preview_blocks(
    content: dict[str, Any], item_id: str, item_revision_id: str
) -> tuple[
    PreviewParagraphBlock
    | PreviewEquationBlock
    | PreviewTableBlock
    | PreviewImageBlock
    | PreviewStatementSetBlock,
    ...,
]:
    body = content.get("body")
    if not isinstance(body, list):
        raise ValueError("structured item body is not an ordered array")
    blocks: list[
        PreviewParagraphBlock
        | PreviewEquationBlock
        | PreviewTableBlock
        | PreviewImageBlock
        | PreviewStatementSetBlock
    ] = []
    for block in body:
        if not isinstance(block, dict):
            raise ValueError("structured item block is not an object")
        block_type = block.get("type")
        if block_type == "paragraph":
            blocks.append(PreviewParagraphBlock.model_validate(block))
        elif block_type == "equation":
            blocks.append(PreviewEquationBlock.model_validate(block))
        elif block_type == "table":
            blocks.append(PreviewTableBlock.model_validate(block))
        elif block_type == "statement_set":
            blocks.append(PreviewStatementSetBlock.model_validate(block))
        elif block_type == "image":
            artifact = block.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError("structured item image pointer is absent")
            blocks.append(
                PreviewImageBlock.model_validate(
                    {
                        "block_id": block.get("block_id"),
                        "type": "image",
                        "purpose": block.get("purpose"),
                        "media_url": (
                            f"/studio/api/v1/items/{item_id}/revisions/"
                            f"{item_revision_id}/media/{block.get('block_id')}"
                        ),
                        "media_type": artifact.get("media_type"),
                        "sha256": artifact.get("sha256"),
                        "alt_text": block.get("alt_text"),
                        "width_px": block.get("width_px"),
                        "height_px": block.get("height_px"),
                    }
                )
            )
        else:
            raise ValueError("structured item block type is unsupported")
    return tuple(blocks)


class GatewayError(RuntimeError):
    def __init__(self, *, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


class LoginResult:
    def __init__(self, *, operator: dict[str, Any], tokens: ApiTokens) -> None:
        self.operator = operator
        self.tokens = tokens


@dataclass(frozen=True)
class HwpxDownload:
    content: bytes
    content_type: str
    content_disposition: str


@dataclass(frozen=True)
class ItemMedia:
    content: bytes
    content_type: str
    etag: str


@dataclass(frozen=True)
class KnowledgeAnalysisRangePage:
    values: tuple[KnowledgeAnalysisBatchRangeStatus, ...]
    next_cursor: str | None
    has_more: bool


class ApplicationGateway(Protocol):
    async def health(self) -> dict[str, str]: ...

    async def login(self, username: str, password: str) -> LoginResult: ...

    async def logout(self, session: WebSession) -> None: ...

    async def accepted_intakes(self, session: WebSession) -> tuple[ContentIntakeOption, ...]: ...

    async def intake_sources(
        self, session: WebSession, intake_id: str
    ) -> tuple[ContentIntakeSourcePointer, ...]: ...

    async def curriculum_editorial_outline(
        self, session: WebSession
    ) -> CurriculumEditorialOutline: ...

    async def curriculum_graph_corpus_key(self, session: WebSession) -> str | None: ...

    async def start_workflow(
        self, session: WebSession, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, Any]: ...

    async def workflow_bundle(self, session: WebSession, workflow_id: str) -> dict[str, Any]: ...

    async def approve_workflow(
        self,
        session: WebSession,
        workflow_id: str,
        *,
        etag: str,
        idempotency_key: str,
        reason: str | None,
    ) -> dict[str, Any]: ...

    async def item_preview(
        self, session: WebSession, item_id: str, item_revision_id: str
    ) -> ItemPreview: ...

    async def item_media(
        self,
        session: WebSession,
        item_id: str,
        item_revision_id: str,
        block_id: str,
    ) -> ItemMedia: ...

    async def recent_items(self, session: WebSession) -> tuple[RecentItemOption, ...]: ...

    async def import_structured_item(
        self, session: WebSession, value: StructuredItemImportRequest
    ) -> dict[str, Any]: ...

    async def explorer(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult: ...

    async def hwpx_capability(self, session: WebSession) -> HwpxCapability: ...

    async def create_hwpx_build(
        self, session: WebSession, value: HwpxBuildRequest
    ) -> dict[str, Any]: ...

    async def hwpx_build(self, session: WebSession, build_id: str) -> HwpxBuildView: ...

    async def hwpx_download(self, session: WebSession, build_id: str) -> HwpxDownload: ...

    async def codex_accounts(self, session: WebSession) -> tuple[dict[str, Any], ...]: ...

    async def knowledge_analysis_batches(
        self, session: WebSession
    ) -> tuple[KnowledgeAnalysisBatchStatus, ...]: ...

    async def knowledge_analysis_batch(
        self, session: WebSession, batch_id: str
    ) -> KnowledgeAnalysisBatchStatus: ...

    async def knowledge_analysis_batch_ranges(
        self, session: WebSession, batch_id: str, *, cursor: str | None
    ) -> KnowledgeAnalysisRangePage: ...

    async def codex_account_command(
        self,
        session: WebSession,
        binding_id: str,
        *,
        command_type: str,
        reason_code: str | None,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def codex_control_command(
        self, session: WebSession, command_id: str
    ) -> dict[str, Any]: ...

    async def start_codex_auth_enrollment(
        self,
        session: WebSession,
        binding_id: str,
        *,
        requested_account_label: str,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def codex_auth_enrollment(
        self, session: WebSession, enrollment_id: str
    ) -> CodexAuthEnrollmentStatusView: ...

    async def reveal_codex_auth_challenge(
        self, session: WebSession, enrollment_id: str
    ) -> CodexDeviceChallengeView: ...

    async def execution_presets(self, session: WebSession) -> tuple[dict[str, Any], ...]: ...

    async def create_execution_preset_draft(
        self, session: WebSession, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]: ...

    async def release_execution_preset(
        self,
        session: WebSession,
        draft_revision_id: str,
        *,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def deprecate_execution_preset(
        self,
        session: WebSession,
        preset_id: str,
        *,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class ObserveClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        access_token: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._access_token = access_token
        self._authenticated = False
        self._login_lock = __import__("asyncio").Lock()

    async def health(self) -> str:
        try:
            response = await self._client.get("/observe/api/v1/health/live")
        except httpx.HTTPError:
            return "UNAVAILABLE"
        return "ACTIVE" if response.status_code == 200 else "UNAVAILABLE"

    async def get(self, path: str) -> dict[str, Any] | None:
        if self._access_token is None:
            return None
        await self._ensure_session()
        try:
            response = await self._client.get(path, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            return None
        if response.status_code == 401:
            self._authenticated = False
            await self._ensure_session()
            response = await self._client.get(path, headers={"Accept": "application/json"})
        if response.status_code != 200:
            return None
        value = response.json()
        return value if isinstance(value, dict) else None

    async def _ensure_session(self) -> None:
        if self._authenticated or self._access_token is None:
            return
        async with self._login_lock:
            if self._authenticated:
                return
            try:
                response = await self._client.post(
                    "/observe/api/v1/session",
                    json={"token": self._access_token},
                    headers={"Content-Type": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise GatewayError(status=503, code="OBSERVABILITY_UNAVAILABLE") from exc
            if response.status_code != 204:
                raise GatewayError(status=503, code="OBSERVABILITY_AUTH_UNAVAILABLE")
            self._authenticated = True

    async def close(self) -> None:
        await self._client.aclose()


class HttpApplicationGateway:
    def __init__(
        self,
        *,
        application_api_url: str,
        observability_url: str,
        timeout: float,
        observability_access_token: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
        observability_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=application_api_url,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.observe = ObserveClient(
            base_url=observability_url,
            timeout=timeout,
            access_token=observability_access_token,
            transport=observability_transport,
        )

    async def health(self) -> dict[str, str]:
        results: dict[str, str] = {}
        for key, path in (
            ("application_api", "/api/v1/health/live"),
            ("application_api_ready", "/api/v1/health/ready"),
        ):
            try:
                response = await self._client.get(path)
            except httpx.HTTPError:
                results[key] = "UNAVAILABLE"
            else:
                results[key] = "ACTIVE" if response.status_code == 200 else "UNAVAILABLE"
        results["observability"] = await self.observe.health()
        return results

    async def login(self, username: str, password: str) -> LoginResult:
        response = await self._request(
            "POST",
            "/api/v1/auth/login",
            json={
                "username": username,
                "password": password,
                "client_name": "EOM Scientific Studio",
            },
        )
        data = self._data(response)
        tokens = _tokens(data)
        me = await self._client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
                "Accept": "application/json",
            },
        )
        if me.status_code != 200:
            raise _gateway_error(me)
        operator = _operator_view(self._data(me))
        return LoginResult(operator=operator, tokens=tokens)

    async def logout(self, session: WebSession) -> None:
        try:
            await self._authorized(session, "POST", "/api/v1/auth/logout", json={})
        except GatewayError:
            return

    async def accepted_intakes(self, session: WebSession) -> tuple[ContentIntakeOption, ...]:
        response = await self._authorized(
            session,
            "GET",
            "/api/v1/content-intakes",
            params={"state": "ACCEPTED", "limit": 100},
        )
        values = self._list_data(response)
        try:
            return tuple(
                ContentIntakeOption.model_validate(
                    {
                        "intake_batch_id": value["intake_batch_id"],
                        "batch_name": value["batch_name"],
                        "state": value["state"],
                        "purpose": value["purpose"],
                        "updated_at": value["updated_at"],
                    }
                )
                for value in values
            )
        except (KeyError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def intake_sources(
        self, session: WebSession, intake_id: str
    ) -> tuple[ContentIntakeSourcePointer, ...]:
        _require_id(intake_id, "intake_")
        response = await self._authorized(session, "GET", f"/api/v1/content-intakes/{intake_id}")
        detail = self._data(response)
        sources = detail.get("source_files")
        if not isinstance(sources, list):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        try:
            return tuple(
                ContentIntakeSourcePointer.model_validate(
                    {
                        "source_file_id": source["source_file_id"],
                        "filename": source["filename"],
                        "artifact_id": source["artifact"]["artifact_id"],
                        "artifact_revision_id": source["artifact"]["artifact_revision_id"],
                        "artifact_member": source["artifact"]["artifact_member"],
                        "sha256": source["sha256"],
                        "media_type": source["media_type"],
                    }
                )
                for source in sources
                if isinstance(source, dict)
                and isinstance(source.get("artifact"), dict)
                and source.get("media_type") in {"image/png", "image/jpeg"}
            )
        except (KeyError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def curriculum_editorial_outline(self, session: WebSession) -> CurriculumEditorialOutline:
        response = await self._authorized(
            session,
            "GET",
            "/api/v1/curriculum/integrated-science-editorial-outline",
        )
        value = self._data(response)
        units = value.get("units")
        if not isinstance(units, list):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        graph_mapping_status = "RESERVED_CANDIDATES_NOT_PUBLICATION_PROOF"
        graph_grounding_available = False
        try:
            capability_response = await self._authorized(
                session,
                "GET",
                "/api/v1/curriculum/integrated-science-graph-capability",
            )
            capability = self._data(capability_response)
            if (
                _verified_curriculum_graph_corpus_key(capability) is not None
                and capability.get("outline_key") == value.get("outline_key")
                and capability.get("outline_revision") == value.get("outline_revision")
            ):
                graph_mapping_status = "PUBLISHED_CURRICULUM_GRAPH_VERIFIED"
                graph_grounding_available = True
        except GatewayError:
            pass
        try:
            return CurriculumEditorialOutline.model_validate(
                {
                    "schema_version": value["schema_version"],
                    "outline_key": value["outline_key"],
                    "outline_revision": value["outline_revision"],
                    "subject_key": value["subject_key"],
                    "subject_label": value["subject_label"],
                    "graph_mapping_status": graph_mapping_status,
                    "graph_grounding_available": graph_grounding_available,
                    "supported_product_levels": value["supported_product_levels"],
                    "unsupported_product_levels": value["unsupported_product_levels"],
                    "units": [
                        {
                            "key": unit["key"],
                            "level": unit["level"],
                            "code": unit["code"],
                            "label": unit["label"],
                            "parent_key": unit["parent_key"],
                            "ordinal": unit["ordinal"],
                        }
                        for unit in units
                        if isinstance(unit, dict)
                    ],
                }
            )
        except (KeyError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def curriculum_graph_corpus_key(self, session: WebSession) -> str | None:
        """Return the fresh API-owned corpus identity only while Graph grounding is READY."""

        try:
            response = await self._authorized(
                session,
                "GET",
                "/api/v1/curriculum/integrated-science-graph-capability",
            )
            capability = self._data(response)
        except GatewayError as exc:
            if exc.status in {404, 409, 503}:
                return None
            raise
        return _verified_curriculum_graph_corpus_key(capability)

    async def start_workflow(
        self, session: WebSession, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, Any]:
        response = await self._authorized(
            session,
            "POST",
            "/api/v1/workflows",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        return sanitize_mapping(self._data(response))

    async def codex_accounts(self, session: WebSession) -> tuple[dict[str, Any], ...]:
        response = await self._authorized(session, "GET", "/api/v1/codex-accounts")
        return tuple(sanitize_mapping(item) for item in self._list_data(response))

    async def knowledge_analysis_batches(
        self, session: WebSession
    ) -> tuple[KnowledgeAnalysisBatchStatus, ...]:
        response = await self._authorized(
            session,
            "GET",
            "/api/v1/knowledge-analysis-batches",
            params={"limit": 20},
        )
        try:
            return tuple(_knowledge_analysis_batch(value) for value in self._list_data(response))
        except (KeyError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def knowledge_analysis_batch(
        self, session: WebSession, batch_id: str
    ) -> KnowledgeAnalysisBatchStatus:
        _require_id(batch_id, "analysisbatch_")
        response = await self._authorized(
            session, "GET", f"/api/v1/knowledge-analysis-batches/{batch_id}"
        )
        try:
            return _knowledge_analysis_batch(self._data(response))
        except (KeyError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def knowledge_analysis_batch_ranges(
        self, session: WebSession, batch_id: str, *, cursor: str | None
    ) -> KnowledgeAnalysisRangePage:
        _require_id(batch_id, "analysisbatch_")
        if cursor is not None and (not cursor or len(cursor) > 1024):
            raise GatewayError(status=400, code="WEB_REQUEST_INVALID")
        params: dict[str, str | int | float | bool | None] = {"limit": 200}
        if cursor is not None:
            params["cursor"] = cursor
        response = await self._authorized(
            session,
            "GET",
            f"/api/v1/knowledge-analysis-batches/{batch_id}/ranges",
            params=params,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc
        page = payload.get("page") if isinstance(payload, dict) else None
        if not isinstance(page, dict):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        next_cursor = page.get("next_cursor")
        has_more = page.get("has_more")
        if (
            (
                next_cursor is not None
                and (not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 1024)
            )
            or not isinstance(has_more, bool)
            or has_more != (next_cursor is not None)
        ):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        try:
            values = tuple(
                KnowledgeAnalysisBatchRangeStatus.model_validate(
                    {
                        "range_id": value["range_id"],
                        "batch_id": value["batch_id"],
                        "ordinal": value["ordinal"],
                        "document_id": value["document_id"],
                        "document_revision_id": value["document_revision_id"],
                        "first_physical_page": value["first_physical_page"],
                        "last_physical_page": value["last_physical_page"],
                        "curriculum_unit_keys": value["curriculum_unit_keys"],
                        "source_artifact_revision_id": value["source_artifact_revision_id"],
                        "source_sha256": value["source_sha256"],
                        "analysis_artifact_revision_id": value["analysis_artifact_revision_id"],
                        "analysis_schema_ref": value["analysis_schema_ref"],
                        "analysis_run_id": value.get("analysis_run_id"),
                        "state": value["state"],
                        "updated_at": value["updated_at"],
                    }
                )
                for value in self._list_data(response)
            )
        except (KeyError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc
        return KnowledgeAnalysisRangePage(
            values=values,
            next_cursor=next_cursor,
            has_more=has_more,
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
        _require_id(binding_id, "authbinding_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/codex-accounts/{binding_id}/commands",
            json={"command_type": command_type, "reason_code": reason_code},
            headers={
                "If-Match": f'"v{resource_version}"',
                "Idempotency-Key": idempotency_key,
            },
        )
        return sanitize_mapping(self._data(response))

    async def codex_control_command(self, session: WebSession, command_id: str) -> dict[str, Any]:
        _require_id(command_id, "codexcmd_")
        response = await self._authorized(
            session, "GET", f"/api/v1/codex-control-commands/{command_id}"
        )
        return sanitize_mapping(self._data(response))

    async def start_codex_auth_enrollment(
        self,
        session: WebSession,
        binding_id: str,
        *,
        requested_account_label: str,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _require_id(binding_id, "authbinding_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/codex-accounts/{binding_id}/reauthentications",
            json={
                "requested_account_label": requested_account_label,
                "acknowledge_drain": True,
            },
            headers={
                "If-Match": f'"v{resource_version}"',
                "Idempotency-Key": idempotency_key,
            },
        )
        return sanitize_mapping(self._data(response))

    async def codex_auth_enrollment(
        self, session: WebSession, enrollment_id: str
    ) -> CodexAuthEnrollmentStatusView:
        _require_id(enrollment_id, "authflow_")
        response = await self._authorized(
            session,
            "GET",
            f"/api/v1/codex-auth-enrollments/{enrollment_id}",
        )
        try:
            return CodexAuthEnrollmentStatusView.model_validate(self._data(response))
        except ValueError as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def reveal_codex_auth_challenge(
        self, session: WebSession, enrollment_id: str
    ) -> CodexDeviceChallengeView:
        _require_id(enrollment_id, "authflow_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/codex-auth-enrollments/{enrollment_id}/challenge",
            json={},
        )
        try:
            return CodexDeviceChallengeView.model_validate(self._data(response))
        except ValueError as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def execution_presets(self, session: WebSession) -> tuple[dict[str, Any], ...]:
        response = await self._authorized(session, "GET", "/api/v1/execution-presets")
        return tuple(sanitize_mapping(item) for item in self._list_data(response))

    async def create_execution_preset_draft(
        self, session: WebSession, payload: dict[str, Any], idempotency_key: str
    ) -> dict[str, Any]:
        response = await self._authorized(
            session,
            "POST",
            "/api/v1/execution-presets",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        return sanitize_mapping(self._data(response))

    async def release_execution_preset(
        self,
        session: WebSession,
        draft_revision_id: str,
        *,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _require_id(draft_revision_id, "execpresetrev_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/execution-preset-revisions/{draft_revision_id}/releases",
            json={},
            headers={
                "If-Match": f'"v{resource_version}"',
                "Idempotency-Key": idempotency_key,
            },
        )
        return sanitize_mapping(self._data(response))

    async def deprecate_execution_preset(
        self,
        session: WebSession,
        preset_id: str,
        *,
        resource_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _require_id(preset_id, "execpreset_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/execution-presets/{preset_id}/deprecations",
            json={},
            headers={
                "If-Match": f'"v{resource_version}"',
                "Idempotency-Key": idempotency_key,
            },
        )
        return sanitize_mapping(self._data(response))

    async def workflow_bundle(self, session: WebSession, workflow_id: str) -> dict[str, Any]:
        _require_id(workflow_id, "workflow_")
        workflow_response = await self._authorized(
            session, "GET", f"/api/v1/workflows/{workflow_id}"
        )
        steps_response = await self._authorized(
            session, "GET", f"/api/v1/workflows/{workflow_id}/steps"
        )
        events_response = await self._authorized(
            session, "GET", f"/api/v1/workflows/{workflow_id}/events"
        )
        observe = await self.observe.get(f"/observe/api/v1/workflows/{workflow_id}")
        return {
            "workflow": sanitize_mapping(self._data(workflow_response)),
            "etag": workflow_response.headers.get("etag"),
            "steps": [sanitize_mapping(item) for item in self._list_data(steps_response)],
            "events": [sanitize_mapping(item) for item in self._list_data(events_response)],
            "observe": _sanitize_observe_workflow(observe),
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
        _require_id(workflow_id, "workflow_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/workflows/{workflow_id}/approvals",
            json={"reason": reason},
            headers={"Idempotency-Key": idempotency_key, "If-Match": etag},
        )
        return sanitize_mapping(self._data(response))

    async def item_preview(
        self, session: WebSession, item_id: str, item_revision_id: str
    ) -> ItemPreview:
        _require_id(item_id, "item_")
        _require_id(item_revision_id, "itemrev_")
        item_response = await self._authorized(session, "GET", f"/api/v1/items/{item_id}")
        revision_response = await self._authorized(
            session, "GET", f"/api/v1/item-revisions/{item_revision_id}"
        )
        components_response = await self._authorized(
            session, "GET", f"/api/v1/item-revisions/{item_revision_id}/components"
        )
        item = self._data(item_response)
        revision = self._data(revision_response)
        revision_etag = revision_response.headers.get("etag")
        if (
            revision.get("item_id") != item_id
            or item.get("current_revision_id") != item_revision_id
            or revision_etag is None
        ):
            raise GatewayError(status=409, code="ITEM_REVISION_POINTER_MISMATCH")
        components = self._list_data(components_response)
        template_delivery_available = any(
            component.get("item_revision_id") == item_revision_id
            and component.get("component_type") == "ITEM_CONTENT"
            and component.get("ordinal") == 0
            and component.get("required") is True
            and isinstance(component.get("artifact"), dict)
            and component["artifact"].get("schema_ref")
            in {
                "eom.assessment.item-content/1.0",
                "eom.assessment.item-content/2.0",
            }
            for component in components
        )
        structured_preview_available = any(
            component.get("item_revision_id") == item_revision_id
            and component.get("component_type") == "ITEM_CONTENT"
            and component.get("ordinal") == 0
            and component.get("required") is True
            and isinstance(component.get("artifact"), dict)
            and component["artifact"].get("schema_ref") == "eom.assessment.item-content/1.0"
            for component in components
        )
        content: dict[str, Any] | None = None
        if structured_preview_available:
            content_response = await self._authorized(
                session,
                "GET",
                f"/api/v1/item-revisions/{item_revision_id}/structured-content",
            )
            content = self._data(content_response)
        try:
            blocks = _ordered_preview_blocks(content, item_id, item_revision_id) if content else ()
        except (TypeError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc
        interaction = (content or {}).get("interaction")
        choices = interaction.get("choices", []) if isinstance(interaction, dict) else []
        solution = (content or {}).get("solution")
        correct_ids = solution.get("correct_choice_ids", []) if isinstance(solution, dict) else []
        statement_explanations = (
            solution.get("statement_explanations", []) if isinstance(solution, dict) else []
        )
        if content is not None and (
            not isinstance(interaction, dict)
            or not isinstance(choices, list)
            or any(not isinstance(choice, dict) for choice in choices)
            or not isinstance(solution, dict)
            or not isinstance(correct_ids, list)
            or not isinstance(statement_explanations, list)
            or any(not isinstance(value, dict) for value in statement_explanations)
        ):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        answer = next(
            (
                str(choice.get("label"))
                for choice in choices
                if isinstance(choice, dict) and choice.get("choice_id") in correct_ids
            ),
            None,
        )
        try:
            return ItemPreview(
                preview_state="AVAILABLE" if content is not None else "METADATA_ONLY",
                workflow_id=str(revision.get("workflow_id") or "unknown"),
                item_id=item_id,
                item_revision_id=item_revision_id,
                revision_etag=revision_etag,
                revision_state=str(revision.get("revision_state") or "UNKNOWN"),
                content_pack_release_id=str(revision.get("content_pack_release_id") or "unknown"),
                template_delivery_available=template_delivery_available,
                locale=(str(content.get("locale")) if content is not None else None),
                title=(str(content.get("title")) if content is not None else None),
                score_points=(
                    int(content["score"]["points"])
                    if content is not None and isinstance(content.get("score"), dict)
                    else None
                ),
                blocks=tuple(blocks),
                choices=tuple(
                    PreviewChoice(
                        choice_id=str(choice.get("choice_id")),
                        label=str(choice.get("label")),
                        text=str(choice.get("text")),
                    )
                    for choice in choices
                ),
                answer=answer,
                explanation=(
                    str(solution.get("explanation")) if isinstance(solution, dict) else None
                ),
                authoring_intent=(
                    str(solution.get("authoring_intent")) if isinstance(solution, dict) else None
                ),
                statement_explanations=tuple(
                    PreviewStatementExplanation.model_validate(value)
                    for value in statement_explanations
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def recent_items(self, session: WebSession) -> tuple[RecentItemOption, ...]:
        response = await self._authorized(
            session,
            "GET",
            "/api/v1/items",
            params={"state": "ACTIVE", "limit": 20},
        )
        values = self._list_data(response)
        try:
            return tuple(
                RecentItemOption.model_validate(
                    {
                        "item_id": value["item_id"],
                        "item_revision_id": value["current_revision_id"],
                        "lifecycle_state": value["lifecycle_state"],
                        "human_reference_code": value.get("human_reference_code"),
                        "created_at": value["created_at"],
                    }
                )
                for value in values
                if isinstance(value, dict) and value.get("current_revision_id") is not None
            )
        except (KeyError, ValueError) as exc:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID") from exc

    async def item_media(
        self,
        session: WebSession,
        item_id: str,
        item_revision_id: str,
        block_id: str,
    ) -> ItemMedia:
        _require_id(item_id, "item_")
        _require_id(item_revision_id, "itemrev_")
        _require_id(block_id, "block_")
        revision_response = await self._authorized(
            session,
            "GET",
            f"/api/v1/item-revisions/{item_revision_id}",
        )
        if self._data(revision_response).get("item_id") != item_id:
            raise GatewayError(status=409, code="ITEM_REVISION_POINTER_MISMATCH")
        response = await self._authorized(
            session,
            "GET",
            f"/api/v1/item-revisions/{item_revision_id}/media/{block_id}",
            headers={"Accept": "image/png,image/jpeg"},
        )
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        etag = response.headers.get("etag", "")
        content_length = response.headers.get("content-length", "")
        actual_sha256 = "sha256:" + hashlib.sha256(response.content).hexdigest()
        if (
            content_type not in {"image/png", "image/jpeg"}
            or response.headers.get("content-disposition") is not None
            or not content_length.isascii()
            or not content_length.isdigit()
            or int(content_length) != len(response.content)
            or len(response.content) < 1
            or len(response.content) > 16 * 1024 * 1024
            or etag != f'"{actual_sha256}"'
        ):
            raise GatewayError(status=502, code="ITEM_MEDIA_RESPONSE_INVALID")
        return ItemMedia(content=response.content, content_type=content_type, etag=etag)

    async def import_structured_item(
        self, session: WebSession, value: StructuredItemImportRequest
    ) -> dict[str, Any]:
        _require_id(value.base_revision_id, "itemrev_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/item-revisions/{value.base_revision_id}/structured-content-imports",
            json={
                "reviewed": value.reviewed,
                "review_reason": value.review_reason,
                "content": value.content,
            },
            headers={
                "If-Match": value.revision_etag,
                "Idempotency-Key": value.idempotency_key,
            },
        )
        return sanitize_mapping(self._data(response))

    async def hwpx_capability(self, session: WebSession) -> HwpxCapability:
        response = await self._authorized(session, "GET", "/api/v1/capabilities/hwpx")
        value = self._data(response)
        state = str(value.get("state") or "UNAVAILABLE")
        profiles_value = value.get("delivery_profiles")
        profiles = profiles_value if isinstance(profiles_value, list) else []
        template_ready = any(
            isinstance(profile, dict)
            and profile.get("renderer") == "eom-template"
            and profile.get("renderer_version") == "1.0.0"
            and profile.get("document_profile") == "eom-question-template-v1"
            and profile.get("source_schema_ref") == "eom.assessment.item-content/1.0"
            for profile in profiles
        )
        content_team_ready = any(
            isinstance(profile, dict)
            and profile.get("renderer") == "content-team"
            and profile.get("renderer_version") == "2.0.0"
            and profile.get("document_profile") == "content-team-hwp-question-editor-v2"
            and profile.get("source_schema_ref") == "eom.assessment.item-content/2.0"
            for profile in profiles
        )
        if state == "READY" and not (template_ready and content_team_ready):
            state = "DEGRADED"
        supports_value = value.get("supports")
        supports: dict[str, Any] = supports_value if isinstance(supports_value, dict) else {}
        messages = {
            "READY": ("승인된 EOM 문항 템플릿이 격리된 Kordoc 4.9.0 경계에서 준비되었습니다."),
            "PREPARED_NOT_DEPLOYED": "HWPX Renderer 운영 배포 필요",
            "DEGRADED": "HWPX renderer 무결성 또는 manager 상태를 점검해야 합니다.",
            "UNAVAILABLE": "HWPX renderer를 사용할 수 없습니다.",
        }
        return HwpxCapability.model_validate(
            {
                "state": state,
                "renderer_key": "item-revision-auto",
                "renderer_version": "1.0.0",
                "document_profile": "item-revision-auto",
                "build_available": state == "READY" and template_ready and content_team_ready,
                "native_equations": bool(supports.get("native_equations")),
                "native_tables": bool(supports.get("native_tables")),
                "detail_code": str(value.get("detail_code") or "HWPX_CAPABILITY_UNKNOWN"),
                "message": messages.get(state, messages["UNAVAILABLE"]),
            }
        )

    async def create_hwpx_build(
        self, session: WebSession, value: HwpxBuildRequest
    ) -> dict[str, Any]:
        _require_id(value.item_revision_id, "itemrev_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/item-revisions/{value.item_revision_id}/hwpx-builds",
            json={
                "renderer": "auto",
                "options": {
                    "include_explanation": True,
                    "require_native_equations": value.require_native_equations,
                    "require_native_tables": value.require_native_tables,
                    "document_preset": "report",
                    "document_profile": "item-revision-auto",
                    "item_number": value.item_number,
                },
            },
            headers={"Idempotency-Key": value.idempotency_key},
        )
        return sanitize_mapping(self._data(response))

    async def hwpx_build(self, session: WebSession, build_id: str) -> HwpxBuildView:
        _require_id(build_id, "hwpxbuild_")
        response = await self._authorized(session, "GET", f"/api/v1/hwpx-builds/{build_id}")
        return HwpxBuildView.model_validate(self._data(response))

    async def hwpx_download(self, session: WebSession, build_id: str) -> HwpxDownload:
        _require_id(build_id, "hwpxbuild_")
        response = await self._authorized(
            session,
            "GET",
            f"/api/v1/hwpx-builds/{build_id}/download",
            headers={"Accept": "application/vnd.hancom.hwpx"},
        )
        content_type = response.headers.get("content-type", "")
        disposition = response.headers.get("content-disposition", "")
        if (
            content_type.split(";", 1)[0] != "application/vnd.hancom.hwpx"
            or not disposition.startswith('attachment; filename="')
            or len(response.content) > 64 * 1024 * 1024
        ):
            raise GatewayError(status=502, code="HWPX_DOWNLOAD_RESPONSE_INVALID")
        return HwpxDownload(response.content, content_type, disposition)

    async def explorer(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult:
        if query.entity == ExplorerEntity.ITEM_REVISIONS:
            return await self._item_revision_explorer(session, query)
        if query.entity in {ExplorerEntity.WORKFLOW_EVENTS, ExplorerEntity.WORKFLOW_COMMANDS}:
            return await self._event_explorer(session, query)
        if query.entity in OBSERVE_EXACT_ENTITIES:
            return await self._observe_explorer(query)
        if query.entity == ExplorerEntity.HWPX_BUILDS:
            hwpx_columns = (
                "build_id",
                "item_id",
                "item_revision_id",
                "state",
                "renderer",
                "validation_state",
                "native_equation_count",
                "native_table_count",
                "output_artifact_revision_id",
                "created_at",
                "completed_at",
            )
            if query.exact_id:
                _require_id(query.exact_id, "hwpxbuild_")
                response = await self._authorized(
                    session, "GET", f"/api/v1/hwpx-builds/{query.exact_id}"
                )
                values = [self._data(response)]
            else:
                response = await self._authorized(
                    session,
                    "GET",
                    "/api/v1/hwpx-builds",
                    params={
                        "limit": query.limit,
                        "cursor": query.cursor,
                        "state": query.status,
                    },
                )
                values = self._list_data(response)
            hwpx_page = response.json().get("page", {})
            return ExplorerResult(
                entity=query.entity,
                columns=hwpx_columns,
                rows=tuple(_filtered_rows(values, hwpx_columns, query)),
                next_cursor=(hwpx_page.get("next_cursor") if isinstance(hwpx_page, dict) else None),
                has_more=(
                    bool(hwpx_page.get("has_more")) if isinstance(hwpx_page, dict) else False
                ),
            )
        spec = EXPLORER_SPECS.get(query.entity)
        if spec is None:
            raise GatewayError(status=422, code="EXPLORER_ENTITY_UNSUPPORTED")
        path, columns, detail_template = spec
        if query.exact_id and detail_template:
            _require_generic_id(query.exact_id)
            response = await self._authorized(
                session, "GET", detail_template.format(identifier=query.exact_id)
            )
            values = [self._data(response)]
            page: dict[str, Any] = {}
        else:
            params: dict[str, str | int | float | bool | None] = {"limit": query.limit}
            if query.cursor:
                params["cursor"] = query.cursor
            if query.status and query.entity in {ExplorerEntity.WORKFLOWS, ExplorerEntity.ITEMS}:
                params["state"] = query.status
            response = await self._authorized(session, "GET", path, params=params)
            values = self._list_data(response)
            page = response.json().get("page", {})
        rows = _filtered_rows(values, columns, query)
        return ExplorerResult(
            entity=query.entity,
            columns=columns,
            rows=tuple(rows),
            next_cursor=page.get("next_cursor") if isinstance(page, dict) else None,
            has_more=bool(page.get("has_more")) if isinstance(page, dict) else False,
        )

    async def _observe_explorer(self, query: ExplorerQuery) -> ExplorerResult:
        if not query.exact_id:
            return ExplorerResult(
                entity=query.entity,
                columns=OBSERVE_EXACT_ENTITIES[query.entity][1],
                rows=(),
                capability="EXACT_ID_REQUIRED",
            )
        _require_generic_id(query.exact_id)
        route, columns = OBSERVE_EXACT_ENTITIES[query.entity]
        value = await self.observe.get(route.format(identifier=query.exact_id))
        if value is None:
            raise GatewayError(status=404, code="EXPLORER_RECORD_NOT_FOUND")
        rows_source: list[dict[str, Any]]
        if query.entity == ExplorerEntity.ARTIFACT_REVISIONS:
            raw = value.get("revisions", [])
            rows_source = [item for item in raw if isinstance(item, dict)]
        elif query.entity == ExplorerEntity.STEP_RUNS:
            raw = value.get("step_runs", [])
            rows_source = [item for item in raw if isinstance(item, dict)]
        else:
            rows_source = [value]
        rows = _filtered_rows(rows_source, columns, query)
        return ExplorerResult(entity=query.entity, columns=columns, rows=tuple(rows))

    async def _event_explorer(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult:
        columns = EXPLORER_SPECS[query.entity][1]
        params: dict[str, str | int | float | bool | None] = {"limit": query.limit}
        if query.cursor:
            params["after_cursor"] = query.cursor
        if query.exact_id:
            _require_generic_id(query.exact_id)
            params["aggregate_id"] = query.exact_id
        if query.date_from:
            params["from_time"] = query.date_from.isoformat()
        if query.date_to:
            params["to_time"] = query.date_to.isoformat()
        response = await self._authorized(session, "GET", "/api/v1/events", params=params)
        values = self._list_data(response)
        page = response.json().get("page", {})
        rows = _filtered_rows(values, columns, query)
        return ExplorerResult(
            entity=query.entity,
            columns=columns,
            rows=tuple(rows),
            next_cursor=page.get("next_cursor") if isinstance(page, dict) else None,
            has_more=bool(page.get("has_more")) if isinstance(page, dict) else False,
        )

    async def _item_revision_explorer(
        self, session: WebSession, query: ExplorerQuery
    ) -> ExplorerResult:
        columns = EXPLORER_SPECS[ExplorerEntity.ITEM_REVISIONS][1]
        if not query.exact_id:
            return ExplorerResult(
                entity=query.entity,
                columns=columns,
                rows=(),
                capability="EXACT_ID_REQUIRED",
            )
        _require_generic_id(query.exact_id)
        if query.exact_id.startswith("itemrev_"):
            response = await self._authorized(
                session, "GET", f"/api/v1/item-revisions/{query.exact_id}"
            )
            values = [self._data(response)]
        elif query.exact_id.startswith("item_"):
            response = await self._authorized(
                session, "GET", f"/api/v1/items/{query.exact_id}/revisions"
            )
            values = self._list_data(response)
        else:
            raise GatewayError(status=422, code="RESOURCE_ID_INVALID")
        rows = _filtered_rows(values, columns, query)
        return ExplorerResult(entity=query.entity, columns=columns, rows=tuple(rows))

    async def _authorized(
        self,
        session: WebSession,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str | int | float | bool | None] | None = None,
    ) -> httpx.Response:
        used_access_token = session.tokens.access_token
        response = await self._client.request(
            method,
            path,
            json=json,
            params=params,
            headers={
                "Authorization": f"Bearer {used_access_token}",
                "Accept": "application/json",
                **(headers or {}),
            },
        )
        if response.status_code != 401:
            if response.status_code >= 400:
                raise _gateway_error(response)
            return response
        async with session.refresh_lock:
            if session.tokens.access_token == used_access_token:
                refresh = await self._request(
                    "POST",
                    "/api/v1/auth/refresh",
                    json={"refresh_token": session.tokens.refresh_token},
                )
                session.tokens = _tokens(self._data(refresh))
        response = await self._client.request(
            method,
            path,
            json=json,
            params=params,
            headers={
                "Authorization": f"Bearer {session.tokens.access_token}",
                "Accept": "application/json",
                **(headers or {}),
            },
        )
        if response.status_code >= 400:
            raise _gateway_error(response)
        return response

    async def _request(self, method: str, path: str, *, json: dict[str, object]) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                path,
                json=json,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise GatewayError(status=503, code="APPLICATION_API_UNAVAILABLE") from exc
        if response.status_code >= 400:
            raise _gateway_error(response)
        return response

    @staticmethod
    def _data(response: httpx.Response) -> dict[str, Any]:
        value = response.json()
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(data, dict):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        return data

    @staticmethod
    def _list_data(response: httpx.Response) -> list[dict[str, Any]]:
        value = response.json()
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        return data

    async def close(self) -> None:
        await self._client.aclose()
        await self.observe.close()


EXPLORER_SPECS: dict[ExplorerEntity, tuple[str, tuple[str, ...], str | None]] = {
    ExplorerEntity.WORKFLOWS: (
        "/api/v1/workflows",
        ("workflow_id", "state", "stage", "current_step_key", "created_at", "updated_at"),
        "/api/v1/workflows/{identifier}",
    ),
    ExplorerEntity.ITEMS: (
        "/api/v1/items",
        ("item_id", "lifecycle_state", "current_revision_id", "created_at"),
        "/api/v1/items/{identifier}",
    ),
    ExplorerEntity.ITEM_REVISIONS: (
        "/api/v1/items",
        (
            "item_revision_id",
            "item_id",
            "revision_number",
            "revision_state",
            "workflow_id",
            "created_at",
        ),
        "/api/v1/item-revisions/{identifier}",
    ),
    ExplorerEntity.CONTENT_PACK_RELEASES: (
        "/api/v1/content-pack-releases",
        ("content_pack_release_id", "pack_key", "release_version", "release_state", "created_at"),
        "/api/v1/content-pack-releases/{identifier}",
    ),
    ExplorerEntity.USAGE_PLANS: (
        "/api/v1/usage-plans",
        ("usage_plan_id", "item_id", "usage_type", "status", "created_at"),
        "/api/v1/usage-plans/{identifier}",
    ),
    ExplorerEntity.USAGE_RECORDS: (
        "/api/v1/usage-records",
        ("usage_record_id", "usage_plan_id", "item_id", "status", "created_at"),
        "/api/v1/usage-records/{identifier}",
    ),
    ExplorerEntity.WORKFLOW_EVENTS: (
        "/api/v1/events",
        ("event_id", "aggregate_type", "aggregate_id", "event_type", "new_state", "created_at"),
        None,
    ),
    ExplorerEntity.WORKFLOW_COMMANDS: (
        "/api/v1/events",
        ("event_id", "aggregate_id", "event_type", "actor_id", "created_at"),
        None,
    ),
}

OBSERVE_EXACT_ENTITIES: dict[ExplorerEntity, tuple[str, tuple[str, ...]]] = {
    ExplorerEntity.STEP_RUNS: (
        "/observe/api/v1/workflows/{identifier}",
        (
            "step_run_id",
            "step_key",
            "attempt",
            "state",
            "platform_job_id",
            "started_at",
            "finished_at",
        ),
    ),
    ExplorerEntity.JOBS: (
        "/observe/api/v1/jobs/{identifier}",
        (
            "job_id",
            "status",
            "task_type",
            "worker_slot_id",
            "created_at",
            "updated_at",
            "completed_at",
        ),
    ),
    ExplorerEntity.ARTIFACTS: (
        "/observe/api/v1/artifacts/{identifier}",
        ("artifact_id", "artifact_type", "approved", "job_id", "created_at"),
    ),
    ExplorerEntity.ARTIFACT_REVISIONS: (
        "/observe/api/v1/artifacts/{identifier}",
        ("revision_id", "content_hash", "manifest_hash", "content_bytes", "approved", "created_at"),
    ),
}


def _tokens(data: dict[str, Any]) -> ApiTokens:
    try:
        access = str(data["access_token"])
        refresh = str(data["refresh_token"])
        access_expiry = _datetime(data["access_expires_at"])
        refresh_expiry = _datetime(data["refresh_expires_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GatewayError(status=502, code="APPLICATION_API_AUTH_RESPONSE_INVALID") from exc
    if not access.startswith("eom_at_") or not refresh.startswith("eom_rt_"):
        raise GatewayError(status=502, code="APPLICATION_API_AUTH_RESPONSE_INVALID")
    return ApiTokens(access, refresh, access_expiry, refresh_expiry)


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(UTC)


def _gateway_error(response: httpx.Response) -> GatewayError:
    code = "APPLICATION_API_REQUEST_FAILED"
    try:
        value = response.json()
        if isinstance(value, dict) and isinstance(value.get("error_code"), str):
            candidate = value["error_code"]
            if candidate.replace("_", "").isalnum() and candidate.upper() == candidate:
                code = candidate[:64]
    except ValueError:
        pass
    return GatewayError(status=response.status_code, code=code)


def _operator_view(value: dict[str, Any]) -> dict[str, Any]:
    roles = value.get("roles", [])
    permissions = value.get("effective_permissions", [])
    if not isinstance(roles, list) or not all(isinstance(item, str) for item in roles):
        raise GatewayError(status=502, code="APPLICATION_API_OPERATOR_INVALID")
    if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
        raise GatewayError(status=502, code="APPLICATION_API_OPERATOR_INVALID")
    result: dict[str, Any] = {}
    for key in ("operator_id", "username", "display_name", "password_change_required"):
        item = value.get(key)
        if isinstance(item, (str, bool)):
            result[key] = item
    result["roles"] = roles
    result["effective_permissions"] = permissions
    return result


def _require_id(value: str, prefix: str) -> None:
    if not value.startswith(prefix) or ID_PATTERN.fullmatch(value) is None:
        raise GatewayError(status=422, code="RESOURCE_ID_INVALID")


def _knowledge_analysis_batch(value: dict[str, Any]) -> KnowledgeAnalysisBatchStatus:
    return KnowledgeAnalysisBatchStatus.model_validate(
        {
            "batch_id": value["batch_id"],
            "state": value["state"],
            "total_range_count": value["total_range_count"],
            "accepted_range_count": value["accepted_range_count"],
            "failed_range_count": value["failed_range_count"],
            "failure_code": value.get("failure_code"),
            "resource_version": value["resource_version"],
            "created_at": value["created_at"],
            "started_at": value.get("started_at"),
            "completed_at": value.get("completed_at"),
            "updated_at": value["updated_at"],
        }
    )


def _require_generic_id(value: str) -> None:
    if ID_PATTERN.fullmatch(value) is None:
        raise GatewayError(status=422, code="RESOURCE_ID_INVALID")


def _sanitize_observe_workflow(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result: dict[str, Any] = dict(sanitize_mapping(value))
    for key in ("step_runs", "approvals", "events"):
        values = value.get(key, [])
        if isinstance(values, list):
            result[key] = [sanitize_mapping(item) for item in values if isinstance(item, dict)]
    return result


def _filtered_rows(
    values: list[dict[str, Any]], columns: tuple[str, ...], query: ExplorerQuery
) -> list[dict[str, Any]]:
    rows = [
        {key: sanitize_mapping({key: value.get(key)}).get(key) for key in columns}
        for value in values
    ]
    if query.status:
        rows = [
            row
            for row in rows
            if query.status
            in {
                str(row.get(key) or "")
                for key in ("state", "status", "revision_state", "release_state")
            }
        ]
    timestamp_key = "updated_at" if query.sort.startswith("updated") else "created_at"
    if query.date_from:
        rows = [row for row in rows if _row_time(row.get(timestamp_key)) >= query.date_from]
    if query.date_to:
        rows = [row for row in rows if _row_time(row.get(timestamp_key)) <= query.date_to]
    rows.sort(
        key=lambda row: (str(row.get(timestamp_key) or ""), str(next(iter(row.values()), ""))),
        reverse=query.sort.endswith("desc"),
    )
    return rows[: query.limit]


def _row_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return _datetime(value)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)
