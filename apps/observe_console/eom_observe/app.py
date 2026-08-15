"""FastAPI application exposing only authenticated, read-only observability projections."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from eom_observe_contracts import HealthResponse, NodeStatus, ObserveSnapshot, validate_contract
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from eom_observe.auth import AuthService
from eom_observe.database import build_readonly_engine
from eom_observe.errors import ObserveError, ObserveErrorCode
from eom_observe.repository import ObserveRepository
from eom_observe.resources import static_resource
from eom_observe.settings import ObserveSecrets, ObserveSettings, load_secrets, load_settings
from eom_observe.snapshot import SnapshotBuilder
from eom_observe.stream import SharedSnapshotPoller, StreamMessage, SubscriptionHub, format_sse

STATIC_ROOT = static_resource()
COOKIE_NAME = "eom_observe_session"
API_PREFIX = "/observe/api/v1"
WORKFLOW_ID_PATTERN = r"^workflow_[a-z0-9_]{8,55}$"
JOB_ID_PATTERN = r"^job_[a-z0-9_]{8,55}$"
EVENT_ID_PATTERN = r"^[a-z][a-z0-9_]{2,127}$"
STATUS_PATTERN = r"^[A-Z][A-Z0-9_]{0,39}$"
WorkerRole = Literal["authoring", "review", "image", "item_management", "support"]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=1024)


class AppServices:
    def __init__(
        self,
        settings: ObserveSettings,
        secrets_config: ObserveSecrets,
        repository: ObserveRepository,
        builder: SnapshotBuilder,
        auth: AuthService,
        hub: SubscriptionHub,
        poller: SharedSnapshotPoller,
    ) -> None:
        self.settings = settings
        self.secrets = secrets_config
        self.repository = repository
        self.builder = builder
        self.auth = auth
        self.hub = hub
        self.poller = poller


def build_services(
    settings: ObserveSettings | None = None, secrets_config: ObserveSecrets | None = None
) -> AppServices:
    actual_settings = settings or load_settings()
    actual_secrets = secrets_config or load_secrets()
    engine = build_readonly_engine(
        actual_secrets.database_url, actual_settings.snapshot.query_timeout_ms
    )
    repository = ObserveRepository(engine, event_limit=actual_settings.snapshot.recent_event_limit)
    builder = SnapshotBuilder(repository, actual_settings)
    auth = AuthService(
        actual_secrets.access_token_hash,
        actual_secrets.session_secret,
        actual_settings.auth.session_ttl_seconds,
    )
    hub = SubscriptionHub(actual_settings.server.max_stream_clients)
    poller = SharedSnapshotPoller(
        builder,
        hub,
        poll_interval_seconds=actual_settings.server.poll_interval_ms / 1000,
    )
    return AppServices(actual_settings, actual_secrets, repository, builder, auth, hub, poller)


def create_app(services: AppServices | None = None) -> FastAPI:
    actual = services or build_services()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await actual.poller.start()
        yield
        await actual.poller.stop()
        actual.repository.engine.dispose()

    docs_enabled = False
    app = FastAPI(
        title="EOM Observability Console",
        version="1.0",
        docs_url="/observe/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/observe/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.services = actual
    app.mount("/observe/assets", StaticFiles(directory=str(STATIC_ROOT)), name="observe-assets")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        request.state.request_id = f"request_{secrets.token_hex(8)}"
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        logging.getLogger("eom_observe.api").info(
            "observability request completed",
            extra={
                "event": "HTTP_REQUEST",
                "request_id": request.state.request_id,
                "http_status": response.status_code,
            },
        )
        return response

    async def require_session(
        session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME),
    ) -> str:
        claims = actual.auth.session(session_cookie)
        if claims is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return claims.nonce

    def client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    async def current_snapshot() -> ObserveSnapshot:
        return await actual.poller.ensure_snapshot()

    @app.exception_handler(ObserveError)
    async def observe_error_handler(_: Request, exc: ObserveError) -> JSONResponse:
        status = 503
        if exc.code == ObserveErrorCode.OBSERVE_STREAM_LIMIT_REACHED:
            status = 429
        return JSONResponse(
            status_code=status,
            content={"error_code": exc.code.value, "message": "observability request failed"},
        )

    @app.get("/observe", include_in_schema=False)
    async def observe_redirect() -> RedirectResponse:
        return RedirectResponse("/observe/", status_code=308)

    @app.get("/observe/", include_in_schema=False)
    async def console(
        session_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
    ) -> Response:
        if actual.auth.session(session_cookie) is None:
            return RedirectResponse("/observe/login", status_code=303)
        return FileResponse(str(static_resource("index.html")))

    @app.get("/observe/login", include_in_schema=False)
    async def login_page() -> FileResponse:
        return FileResponse(str(static_resource("login.html")))

    @app.post(
        f"{API_PREFIX}/session",
        status_code=204,
        response_model=None,
        response_class=Response,
    )
    async def login(payload: LoginRequest, request: Request, response: Response) -> None:
        key = client_key(request)
        if not actual.auth.rate_limiter.allowed(key):
            raise HTTPException(status_code=429, detail="login temporarily rate limited")
        if not actual.auth.authenticate(payload.token, key):
            raise HTTPException(status_code=401, detail="invalid credentials")
        response.set_cookie(
            COOKIE_NAME,
            actual.auth.signer.create(),
            httponly=True,
            secure=actual.settings.auth.secure_cookie,
            samesite="strict",
            path="/observe",
            max_age=actual.settings.auth.session_ttl_seconds,
        )

    @app.post(
        f"{API_PREFIX}/logout",
        status_code=204,
        response_model=None,
        response_class=Response,
    )
    async def logout(response: Response, _session: str = Depends(require_session)) -> None:
        response.delete_cookie(
            COOKIE_NAME,
            path="/observe",
            secure=actual.settings.auth.secure_cookie,
            httponly=True,
            samesite="strict",
        )

    @app.get(f"{API_PREFIX}/health/live", response_model=HealthResponse)
    async def health_live() -> HealthResponse:
        result = HealthResponse(status="LIVE", timestamp_utc=datetime.now(UTC))
        validate_contract("health", result.model_dump(mode="json"))
        return result

    @app.get(f"{API_PREFIX}/health/ready", response_model=HealthResponse)
    async def health_ready(
        _session: str = Depends(require_session),
    ) -> HealthResponse:
        ready = actual.repository.ping() and actual.repository.database_is_readonly()
        result = HealthResponse(
            status="READY" if ready else "DEGRADED", timestamp_utc=datetime.now(UTC)
        )
        validate_contract("health", result.model_dump(mode="json"))
        return result

    @app.get(f"{API_PREFIX}/snapshot", response_model=ObserveSnapshot)
    async def snapshot(
        _session: str = Depends(require_session),
    ) -> ObserveSnapshot:
        return await current_snapshot()

    @app.get(f"{API_PREFIX}/nodes")
    async def nodes(
        _session: str = Depends(require_session),
        status: Annotated[NodeStatus | None, Query()] = None,
        worker_role: Annotated[WorkerRole | None, Query()] = None,
    ) -> list[dict[str, Any]]:
        result = (await current_snapshot()).nodes
        return [
            node.model_dump(mode="json")
            for node in result
            if (status is None or node.status == status)
            and (worker_role is None or node.role == worker_role)
        ]

    @app.get(f"{API_PREFIX}/edges")
    async def edges(
        _session: str = Depends(require_session),
        workflow_id: Annotated[str | None, Query(pattern=WORKFLOW_ID_PATTERN)] = None,
        job_id: Annotated[str | None, Query(pattern=JOB_ID_PATTERN)] = None,
    ) -> list[dict[str, Any]]:
        result = (await current_snapshot()).edges
        return [
            edge.model_dump(mode="json")
            for edge in result
            if (workflow_id is None or edge.workflow_id == workflow_id)
            and (job_id is None or edge.job_id == job_id)
        ]

    @app.get(f"{API_PREFIX}/events")
    async def events(
        _session: str = Depends(require_session),
        after: Annotated[str | None, Query(pattern=EVENT_ID_PATTERN)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
        workflow_id: Annotated[str | None, Query(pattern=WORKFLOW_ID_PATTERN)] = None,
        job_id: Annotated[str | None, Query(pattern=JOB_ID_PATTERN)] = None,
        worker_role: Annotated[WorkerRole | None, Query()] = None,
        status: Annotated[str | None, Query(pattern=STATUS_PATTERN)] = None,
        since: Annotated[datetime | None, Query()] = None,
    ) -> list[dict[str, Any]]:
        values = list((await current_snapshot()).recent_events)
        if after:
            indexes = [index for index, item in enumerate(values) if item.event_id == after]
            values = values[indexes[-1] + 1 :] if indexes else []
        role_id = worker_role.replace("_", "-") if worker_role else None
        values = [
            item
            for item in values
            if (workflow_id is None or item.workflow_id == workflow_id)
            and (job_id is None or item.job_id == job_id)
            and (status is None or item.status == status)
            and (since is None or item.timestamp >= since)
            and (
                role_id is None or item.source_node_id == role_id or item.target_node_id == role_id
            )
        ][-limit:]
        return [item.model_dump(mode="json") for item in values]

    @app.get(f"{API_PREFIX}/workflows/{{workflow_id}}")
    async def workflow_detail(
        workflow_id: str,
        _session: str = Depends(require_session),
    ) -> dict[str, Any]:
        if not _valid_id(workflow_id, "workflow_"):
            raise HTTPException(status_code=422, detail="invalid workflow ID")
        detail = await asyncio.to_thread(actual.builder.workflow_detail, workflow_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        return detail.model_dump(mode="json")

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}")
    async def job_detail(
        job_id: str,
        _session: str = Depends(require_session),
    ) -> dict[str, Any]:
        if not _valid_id(job_id, "job_"):
            raise HTTPException(status_code=422, detail="invalid job ID")
        detail = await asyncio.to_thread(actual.builder.job_detail, job_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="job not found")
        return detail.model_dump(mode="json")

    @app.get(f"{API_PREFIX}/artifacts/{{artifact_id}}")
    async def artifact_detail(
        artifact_id: str,
        _session: str = Depends(require_session),
    ) -> dict[str, Any]:
        if not _valid_id(artifact_id, "artifact_"):
            raise HTTPException(status_code=422, detail="invalid artifact ID")
        detail = await asyncio.to_thread(actual.builder.artifact_detail, artifact_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return detail.model_dump(mode="json")

    @app.get(f"{API_PREFIX}/stream")
    async def stream(
        request: Request, _session: str = Depends(require_session)
    ) -> StreamingResponse:
        client_id, queue = await actual.hub.subscribe()
        initial = await current_snapshot()

        async def generate() -> AsyncIterator[str]:
            try:
                yield format_sse(
                    StreamMessage(
                        event_id=initial.snapshot_id,
                        event="snapshot",
                        data=initial.model_dump(mode="json"),
                    )
                )
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        message = await asyncio.wait_for(
                            queue.get(), timeout=actual.settings.server.heartbeat_seconds
                        )
                    except TimeoutError:
                        message = StreamMessage(
                            event_id=f"heartbeat_{int(datetime.now(UTC).timestamp())}",
                            event="heartbeat",
                            data={"timestamp_utc": datetime.now(UTC).isoformat()},
                        )
                    yield format_sse(message)
            except asyncio.CancelledError:
                raise
            finally:
                await actual.hub.unsubscribe(client_id)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    return app


def _valid_id(value: str, prefix: str) -> bool:
    if not value.startswith(prefix) or len(value) > 64:
        return False
    suffix = value.removeprefix(prefix)
    return len(suffix) >= 8 and suffix.replace("_", "").isalnum()
