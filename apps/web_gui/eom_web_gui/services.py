"""Application services for session, draft, timeline, and capability use cases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from eom_web_gui.contracts import (
    CodexAccountAdminCommand,
    ContentIntakeOption,
    ContentIntakeSourcePointer,
    ExecutionPresetDraftSubmission,
    ExecutionPresetLifecycleCommand,
    ExplorerQuery,
    ExplorerResult,
    HwpxBuildRequest,
    HwpxBuildView,
    HwpxCapability,
    ItemPreview,
    KnowledgeAnalysisBatchRangeStatus,
    KnowledgeAnalysisBatchStatus,
    KnowledgeAnalysisQualityReport,
    RequestDraft,
    RequestDraftInput,
    RequestDraftUpdate,
    StructuredItemImportRequest,
    WorkflowApproval,
)
from eom_web_gui.gateways import ApplicationGateway, GatewayError, LoginResult
from eom_web_gui.knowledge_quality import build_knowledge_quality_report
from eom_web_gui.request_drafts import normalize_request, update_draft, workflow_start_payload
from eom_web_gui.sessions import SessionStore, WebSession, utc_now
from eom_web_gui.settings import WebSettings
from eom_web_gui.timeline import map_timeline


@dataclass(slots=True)
class WebServices:
    settings: WebSettings
    gateway: ApplicationGateway
    sessions: SessionStore

    async def login(
        self, username: str, password: str, *, now: datetime | None = None
    ) -> WebSession:
        current = now or utc_now()
        result: LoginResult = await self.gateway.login(username, password)
        return self.sessions.create(operator=result.operator, tokens=result.tokens, now=current)

    async def logout(self, session: WebSession) -> None:
        self.sessions.delete(session.session_id)
        await self.gateway.logout(session)

    async def accepted_intakes(self, session: WebSession) -> tuple[ContentIntakeOption, ...]:
        return await self.gateway.accepted_intakes(session)

    async def intake_sources(
        self, session: WebSession, intake_id: str
    ) -> tuple[ContentIntakeSourcePointer, ...]:
        return await self.gateway.intake_sources(session, intake_id)

    def create_draft(
        self, session: WebSession, value: RequestDraftInput, *, now: datetime | None = None
    ) -> RequestDraft:
        draft = normalize_request(value, now=now)
        self.sessions.save_draft(session, draft)
        return draft

    def update_draft(
        self,
        session: WebSession,
        draft_id: str,
        value: RequestDraftUpdate,
        *,
        now: datetime | None = None,
    ) -> RequestDraft:
        draft = self.draft(session, draft_id)
        updated = update_draft(draft, value, now=now or datetime.now(UTC))
        self.sessions.save_draft(session, updated)
        return updated

    @staticmethod
    def draft(session: WebSession, draft_id: str) -> RequestDraft:
        try:
            return session.drafts[draft_id]
        except KeyError as exc:
            raise GatewayError(status=404, code="REQUEST_DRAFT_NOT_FOUND") from exc

    async def submit_draft(
        self, session: WebSession, draft_id: str, idempotency_key: str
    ) -> dict[str, Any]:
        replay_key = (draft_id, idempotency_key)
        existing = session.replay_results.get(replay_key)
        if existing is not None:
            return {**existing, "replayed": True}
        draft = self.draft(session, draft_id)
        command = await self.gateway.start_workflow(
            session, workflow_start_payload(draft), idempotency_key
        )
        result = {
            "mode": "KNOWLEDGE_ITEM",
            "request_draft_id": draft.request_draft_id,
            "request_sha256": draft.original_request_sha256,
            "command": command,
            "replayed": False,
        }
        session.replay_results[replay_key] = result
        return result

    async def workflow(self, session: WebSession, workflow_id: str) -> dict[str, Any]:
        value = await self.gateway.workflow_bundle(session, workflow_id)
        value["timeline"] = [
            item.model_dump(mode="json")
            for item in map_timeline(
                steps=value.get("steps", []),
                events=value.get("events", []),
                observe=value.get("observe"),
            )
        ]
        return value

    async def approve(
        self, session: WebSession, workflow_id: str, value: WorkflowApproval
    ) -> dict[str, Any]:
        return await self.gateway.approve_workflow(
            session,
            workflow_id,
            etag=value.etag,
            idempotency_key=value.idempotency_key,
            reason=value.reason,
        )

    async def preview(
        self, session: WebSession, item_id: str, item_revision_id: str
    ) -> ItemPreview:
        return await self.gateway.item_preview(session, item_id, item_revision_id)

    async def import_structured_item(
        self,
        session: WebSession,
        value: StructuredItemImportRequest,
    ) -> dict[str, Any]:
        roles = session.operator.get("roles", ())
        if not isinstance(roles, (list, tuple)) or "ADMIN" not in roles:
            raise GatewayError(status=403, code="ADMIN_ROLE_REQUIRED")
        return await self.gateway.import_structured_item(session, value)

    async def explore(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult:
        _require_admin(session)
        return await self.gateway.explorer(session, query)

    async def codex_accounts(self, session: WebSession) -> tuple[dict[str, Any], ...]:
        _require_admin(session)
        return await self.gateway.codex_accounts(session)

    async def knowledge_analysis_batches(
        self, session: WebSession
    ) -> tuple[KnowledgeAnalysisBatchStatus, ...]:
        _require_admin(session)
        return await self.gateway.knowledge_analysis_batches(session)

    async def knowledge_analysis_quality(
        self, session: WebSession, batch_id: str
    ) -> KnowledgeAnalysisQualityReport:
        _require_admin(session)
        batch = await self.gateway.knowledge_analysis_batch(session, batch_id)
        ranges: list[KnowledgeAnalysisBatchRangeStatus] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(5):
            page = await self.gateway.knowledge_analysis_batch_ranges(
                session, batch_id, cursor=cursor
            )
            ranges.extend(page.values)
            if len(ranges) > 1000:
                raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
            if not page.has_more:
                break
            next_cursor = page.next_cursor
            if next_cursor is None or next_cursor in seen_cursors:
                raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        return build_knowledge_quality_report(batch, ranges)

    async def codex_account_command(
        self,
        session: WebSession,
        binding_id: str,
        value: CodexAccountAdminCommand,
    ) -> dict[str, Any]:
        _require_admin(session)
        return await self.gateway.codex_account_command(
            session,
            binding_id,
            command_type=value.command_type,
            reason_code=value.reason_code,
            resource_version=value.resource_version,
            idempotency_key=value.idempotency_key,
        )

    async def codex_control_command(self, session: WebSession, command_id: str) -> dict[str, Any]:
        _require_admin(session)
        return await self.gateway.codex_control_command(session, command_id)

    async def execution_presets(self, session: WebSession) -> tuple[dict[str, Any], ...]:
        _require_admin(session)
        return await self.gateway.execution_presets(session)

    async def create_execution_preset_draft(
        self, session: WebSession, value: ExecutionPresetDraftSubmission
    ) -> dict[str, Any]:
        _require_admin(session)
        payload = value.model_dump(mode="json", exclude={"idempotency_key"})
        return await self.gateway.create_execution_preset_draft(
            session, payload, value.idempotency_key
        )

    async def release_execution_preset(
        self,
        session: WebSession,
        draft_revision_id: str,
        value: ExecutionPresetLifecycleCommand,
    ) -> dict[str, Any]:
        _require_admin(session)
        return await self.gateway.release_execution_preset(
            session,
            draft_revision_id,
            resource_version=value.resource_version,
            idempotency_key=value.idempotency_key,
        )

    async def deprecate_execution_preset(
        self,
        session: WebSession,
        preset_id: str,
        value: ExecutionPresetLifecycleCommand,
    ) -> dict[str, Any]:
        _require_admin(session)
        return await self.gateway.deprecate_execution_preset(
            session,
            preset_id,
            resource_version=value.resource_version,
            idempotency_key=value.idempotency_key,
        )

    async def hwpx_capability(self, session: WebSession) -> HwpxCapability:
        return await self.gateway.hwpx_capability(session)

    async def create_hwpx_build(
        self, session: WebSession, value: HwpxBuildRequest
    ) -> dict[str, Any]:
        return await self.gateway.create_hwpx_build(session, value)

    async def hwpx_build(self, session: WebSession, build_id: str) -> HwpxBuildView:
        return await self.gateway.hwpx_build(session, build_id)


def build_services(settings: WebSettings, gateway: ApplicationGateway) -> WebServices:
    return WebServices(
        settings=settings,
        gateway=gateway,
        sessions=SessionStore(
            ttl_seconds=settings.sessions.ttl_seconds,
            maximum_sessions=settings.sessions.maximum_sessions,
            maximum_drafts=settings.sessions.maximum_drafts_per_session,
        ),
    )


def validate_download_request(build_id: str) -> None:
    if re.fullmatch(r"hwpxbuild_[a-f0-9]{32}", build_id) is None:
        raise GatewayError(status=422, code="HWPX_BUILD_ID_INVALID")


def _require_admin(session: WebSession) -> None:
    roles = session.operator.get("roles", ())
    if not isinstance(roles, (list, tuple)) or "ADMIN" not in roles:
        raise GatewayError(status=403, code="ADMIN_ROLE_REQUIRED")
