"""KakaoTalk BFF transport reuses Studio session and CSRF; no collector here."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Path, Query, Response

from eom_web_gui.contracts import StudioIdempotencyKey
from eom_web_gui.gateways import ApplicationGateway
from eom_web_gui.kakao_archive_contracts import BindingCommand, BindingCreate
from eom_web_gui.sessions import WebSession


def install_kakao_archive_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_admin_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive/source-bindings"

    @app.get(prefix)
    async def list_bindings(
        response: Response,
        session: Annotated[WebSession, Depends(require_session)],
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, pattern=r"^kakaobinding_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_binding_list(session, limit=limit, cursor=cursor)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.post(prefix, status_code=201)
    async def create_binding(
        response: Response,
        body: BindingCreate,
        session: Annotated[WebSession, Depends(require_admin_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        result = await gateway.kakao_binding_create(session, body, idempotency_key)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.binding.resource_version}"'
        return result.model_dump(mode="json")

    @app.get(prefix + "/{source_binding_id}")
    async def read_binding(
        response: Response,
        source_binding_id: Annotated[str, Path(pattern=r"^kakaobinding_[0-9a-f]{32}$")],
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, object]:
        result = await gateway.kakao_binding_read(session, source_binding_id)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.resource_version}"'
        return result.model_dump(mode="json")

    @app.post(prefix + "/{source_binding_id}/commands")
    async def command_binding(
        response: Response,
        body: BindingCommand,
        source_binding_id: Annotated[str, Path(pattern=r"^kakaobinding_[0-9a-f]{32}$")],
        session: Annotated[WebSession, Depends(require_admin_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
        if_match: Annotated[str, Header(alias="If-Match", pattern=r'^"v[1-9][0-9]*"$')],
    ) -> dict[str, object]:
        result = await gateway.kakao_binding_command(
            session,
            source_binding_id,
            body,
            idempotency_key,
            if_match,
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.binding.resource_version}"'
        return result.model_dump(mode="json")
