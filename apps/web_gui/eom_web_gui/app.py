"""FastAPI routes and security boundary for EOM Scientific Studio."""

import asyncio
import hashlib
import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from eom_web_gui.contracts import (
    CodexAccountAdminCommand,
    DraftSubmission,
    ExecutionPresetDraftSubmission,
    ExecutionPresetLifecycleCommand,
    ExplorerQuery,
    HwpxBuildRequest,
    RequestDraftInput,
    RequestDraftUpdate,
    StructuredItemImportRequest,
    WorkflowApproval,
)
from eom_web_gui.gateways import ApplicationGateway, GatewayError, HttpApplicationGateway
from eom_web_gui.resources import static_resource
from eom_web_gui.services import WebServices, build_services, validate_download_request
from eom_web_gui.sessions import WebSession, utc_now
from eom_web_gui.settings import WebSecrets, WebSettings, load_secrets, load_settings

COOKIE_NAME = "eom_studio_session"
API_PREFIX = "/studio/api/v1"
MAX_BODY_BYTES = 262_144


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    username: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


def create_app(
    services: WebServices | None = None,
    *,
    settings: WebSettings | None = None,
    secrets_config: WebSecrets | None = None,
    gateway: ApplicationGateway | None = None,
) -> FastAPI:
    actual_settings = settings or (services.settings if services else load_settings())
    owned_gateway = gateway
    if services is None:
        secret_values = secrets_config or load_secrets()
        owned_gateway = owned_gateway or HttpApplicationGateway(
            application_api_url=actual_settings.upstreams.application_api_url,
            observability_url=actual_settings.upstreams.observability_url,
            timeout=actual_settings.upstreams.request_timeout_seconds,
            observability_access_token=(
                secret_values.observability_access_token.get_secret_value()
                if secret_values.observability_access_token is not None
                else None
            ),
        )
        services = build_services(actual_settings, owned_gateway)
    actual = services

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await actual.gateway.close()

    app = FastAPI(
        title="EOM Scientific Studio",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.services = actual
    app.mount("/studio/assets", StaticFiles(directory=str(static_resource())), name="studio-assets")

    @app.middleware("http")
    async def request_boundary(request: Request, call_next: Any) -> Response:
        request_id = f"webreq_{secrets.token_hex(12)}"
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in actual_settings.server.allowed_hosts:
            return _problem(400, "WEB_HOST_INVALID", request_id)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
            return _problem(413, "WEB_BODY_TOO_LARGE", request_id)
        response: Response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; "
                    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                    "form-action 'self'; object-src 'none'"
                ),
                "Cross-Origin-Opener-Policy": "same-origin",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-Request-ID": request_id,
            }
        )
        logging.getLogger("eom_web_gui").info(
            "web request completed",
            extra={
                "event": "WEB_REQUEST",
                "request_id": request_id,
                "http_status": response.status_code,
            },
        )
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error(_: Request, exc: GatewayError) -> JSONResponse:
        return _problem(exc.status, exc.code, f"webreq_{secrets.token_hex(12)}")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return _problem(422, "WEB_REQUEST_INVALID", f"webreq_{secrets.token_hex(12)}")

    def require_session(
        session_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
    ) -> WebSession:
        session = actual.sessions.get(session_cookie, now=utc_now())
        if session is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return session

    def require_csrf(
        session: Annotated[WebSession, Depends(require_session)],
        csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> WebSession:
        if not csrf_token or not secrets.compare_digest(csrf_token, session.csrf_token):
            raise GatewayError(status=403, code="CSRF_TOKEN_INVALID")
        return session

    @app.get("/studio", include_in_schema=False)
    async def studio_redirect() -> RedirectResponse:
        return RedirectResponse("/studio/", status_code=308)

    @app.get("/studio/", include_in_schema=False)
    async def studio_page(
        session_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
    ) -> Response:
        if actual.sessions.get(session_cookie, now=utc_now()) is None:
            return RedirectResponse("/studio/login", status_code=303)
        return FileResponse(str(static_resource("index.html")))

    @app.get("/studio/login", include_in_schema=False)
    async def login_page() -> FileResponse:
        return FileResponse(str(static_resource("login.html")))

    @app.get(f"{API_PREFIX}/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "LIVE", "timestamp_utc": datetime.now(UTC).isoformat()}

    @app.get(f"{API_PREFIX}/health/ready")
    async def health_ready() -> dict[str, str]:
        status = await actual.gateway.health()
        ready = status.get("application_api") == "ACTIVE"
        return {"status": "READY" if ready else "DEGRADED", **status}

    @app.post(f"{API_PREFIX}/session", status_code=201)
    async def login(payload: LoginPayload, request: Request, response: Response) -> dict[str, Any]:
        _require_same_origin(request)
        session = await actual.login(payload.username, payload.password.get_secret_value())
        response.set_cookie(
            COOKIE_NAME,
            session.session_id,
            httponly=True,
            secure=actual_settings.sessions.cookie_secure,
            samesite="strict",
            path="/studio",
            max_age=actual_settings.sessions.ttl_seconds,
        )
        return _session_view(session)

    @app.get(f"{API_PREFIX}/session")
    async def session_view(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, Any]:
        return _session_view(session)

    @app.post(f"{API_PREFIX}/logout", status_code=204, response_model=None)
    async def logout(
        response: Response, session: Annotated[WebSession, Depends(require_csrf)]
    ) -> None:
        await actual.logout(session)
        response.delete_cookie(
            COOKIE_NAME,
            path="/studio",
            secure=actual_settings.sessions.cookie_secure,
            httponly=True,
            samesite="strict",
        )

    @app.post(f"{API_PREFIX}/request-drafts", status_code=201)
    async def create_draft(
        value: RequestDraftInput, session: Annotated[WebSession, Depends(require_csrf)]
    ) -> dict[str, Any]:
        draft = actual.create_draft(session, value)
        return draft.model_dump(mode="json")

    @app.get(f"{API_PREFIX}/curriculum/editorial-outline")
    async def curriculum_editorial_outline(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, Any]:
        return (await actual.curriculum_editorial_outline(session)).model_dump(mode="json")

    @app.get(f"{API_PREFIX}/content-intakes/accepted")
    async def accepted_content_intakes(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> list[dict[str, Any]]:
        return [value.model_dump(mode="json") for value in await actual.accepted_intakes(session)]

    @app.get(f"{API_PREFIX}/content-intakes/{{intake_id}}/sources")
    async def content_intake_sources(
        intake_id: str,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> list[dict[str, Any]]:
        return [
            value.model_dump(mode="json")
            for value in await actual.intake_sources(session, intake_id)
        ]

    @app.get(f"{API_PREFIX}/request-drafts/{{draft_id}}")
    async def get_draft(
        draft_id: str, session: Annotated[WebSession, Depends(require_session)]
    ) -> dict[str, Any]:
        return actual.draft(session, draft_id).model_dump(mode="json")

    @app.put(f"{API_PREFIX}/request-drafts/{{draft_id}}")
    async def replace_draft(
        draft_id: str,
        value: RequestDraftUpdate,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return actual.update_draft(session, draft_id, value).model_dump(mode="json")

    @app.post(f"{API_PREFIX}/request-drafts/{{draft_id}}/submissions", status_code=202)
    async def submit_draft(
        draft_id: str,
        value: DraftSubmission,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return await actual.submit_draft(session, draft_id, value.idempotency_key)

    @app.get(f"{API_PREFIX}/workflows/{{workflow_id}}")
    async def workflow(
        workflow_id: str, session: Annotated[WebSession, Depends(require_session)]
    ) -> dict[str, Any]:
        return await actual.workflow(session, workflow_id)

    @app.get(f"{API_PREFIX}/workflows/{{workflow_id}}/stream")
    async def workflow_stream(
        request: Request,
        workflow_id: str,
        session: Annotated[WebSession, Depends(require_session)],
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        async def generate() -> AsyncIterator[str]:
            previous = last_event_id
            while not await request.is_disconnected():
                value = await actual.workflow(session, workflow_id)
                encoded = json.dumps(
                    value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                )
                event_id = f"snapshot_{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"
                if event_id != previous:
                    yield f"id: {event_id}\nevent: workflow\ndata: {encoded}\n\n"
                    previous = event_id
                else:
                    timestamp = datetime.now(UTC).isoformat()
                    yield f'event: heartbeat\ndata: {{"timestamp_utc":"{timestamp}"}}\n\n'
                await asyncio.sleep(2)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post(f"{API_PREFIX}/workflows/{{workflow_id}}/approvals", status_code=202)
    async def approve_workflow(
        workflow_id: str,
        value: WorkflowApproval,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return await actual.approve(session, workflow_id, value)

    @app.get(f"{API_PREFIX}/items/{{item_id}}/revisions/{{item_revision_id}}/preview")
    async def item_preview(
        item_id: str,
        item_revision_id: str,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, Any]:
        value = await actual.preview(session, item_id, item_revision_id)
        return value.model_dump(mode="json")

    @app.get(f"{API_PREFIX}/items/recent")
    async def recent_items(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> tuple[dict[str, object], ...]:
        return await actual.recent_items(session)

    @app.post(f"{API_PREFIX}/items/structured-content-imports")
    async def structured_item_import(
        value: StructuredItemImportRequest,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return await actual.import_structured_item(session, value)

    @app.get(f"{API_PREFIX}/hwpx/capability")
    async def hwpx_capability(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, Any]:
        return (await actual.hwpx_capability(session)).model_dump(mode="json")

    @app.post(f"{API_PREFIX}/hwpx/builds", status_code=202)
    async def hwpx_build(
        value: HwpxBuildRequest,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return await actual.create_hwpx_build(session, value)

    @app.get(f"{API_PREFIX}/hwpx/builds/{{build_id}}")
    async def hwpx_build_status(
        build_id: str,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, Any]:
        return (await actual.hwpx_build(session, build_id)).model_dump(mode="json")

    @app.get(f"{API_PREFIX}/hwpx/builds/{{build_id}}/download")
    async def hwpx_download(
        build_id: str,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> Response:
        validate_download_request(build_id)
        value = await actual.gateway.hwpx_download(session, build_id)
        return Response(
            content=value.content,
            media_type=value.content_type,
            headers={"Content-Disposition": value.content_disposition},
        )

    @app.get(f"{API_PREFIX}/admin/codex-accounts")
    async def codex_accounts(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> tuple[dict[str, Any], ...]:
        return await actual.codex_accounts(session)

    @app.get(f"{API_PREFIX}/admin/knowledge-analysis-batches")
    async def knowledge_analysis_batches(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            value.model_dump(mode="json")
            for value in await actual.knowledge_analysis_batches(session)
        )

    @app.get(f"{API_PREFIX}/admin/knowledge-analysis-batches/{{batch_id}}/quality")
    async def knowledge_analysis_quality(
        batch_id: str,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, Any]:
        return (await actual.knowledge_analysis_quality(session, batch_id)).model_dump(mode="json")

    @app.post(f"{API_PREFIX}/admin/codex-accounts/{{binding_id}}/commands", status_code=202)
    async def codex_account_command(
        binding_id: str,
        value: CodexAccountAdminCommand,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return await actual.codex_account_command(session, binding_id, value)

    @app.get(f"{API_PREFIX}/admin/codex-control-commands/{{command_id}}")
    async def codex_control_command(
        command_id: str,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, Any]:
        return await actual.codex_control_command(session, command_id)

    @app.get(f"{API_PREFIX}/admin/execution-presets")
    async def execution_presets(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> tuple[dict[str, Any], ...]:
        return await actual.execution_presets(session)

    @app.post(f"{API_PREFIX}/admin/execution-presets", status_code=201)
    async def create_execution_preset_draft(
        value: ExecutionPresetDraftSubmission,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return await actual.create_execution_preset_draft(session, value)

    @app.post(f"{API_PREFIX}/admin/execution-preset-revisions/{{draft_revision_id}}/releases")
    async def release_execution_preset(
        draft_revision_id: str,
        value: ExecutionPresetLifecycleCommand,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return await actual.release_execution_preset(session, draft_revision_id, value)

    @app.post(f"{API_PREFIX}/admin/execution-presets/{{preset_id}}/deprecations")
    async def deprecate_execution_preset(
        preset_id: str,
        value: ExecutionPresetLifecycleCommand,
        session: Annotated[WebSession, Depends(require_csrf)],
    ) -> dict[str, Any]:
        return await actual.deprecate_execution_preset(session, preset_id, value)

    @app.post(f"{API_PREFIX}/explorer/query")
    async def explorer(
        value: ExplorerQuery, session: Annotated[WebSession, Depends(require_csrf)]
    ) -> dict[str, Any]:
        result = await actual.explore(session, value)
        return result.model_dump(mode="json")

    return app


def _session_view(session: WebSession) -> dict[str, Any]:
    return {
        "operator": session.operator,
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at.isoformat(),
        "mode": "GENERIC_DEMO",
    }


def _problem(status: int, code: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error_code": code,
            "message": "request could not be completed",
            "request_id": request_id,
        },
    )


def _require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        raise GatewayError(status=403, code="ORIGIN_REQUIRED")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host"):
        raise GatewayError(status=403, code="ORIGIN_INVALID")
