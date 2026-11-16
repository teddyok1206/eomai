"""Existing cookie/CSRF transport only. Reads never launch or renew a browser."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Path, Response

from eom_web_gui.contracts import StudioIdempotencyKey
from eom_web_gui.gateways import ApplicationGateway, GatewayError
from eom_web_gui.kakao_manual_contracts import ManualCommand, ManualEnd, ManualStart
from eom_web_gui.sessions import WebSession

LeaseId = Annotated[str, Path(pattern=r"^kakaoremotelease_[0-9a-f]{32}$")]


def install_kakao_manual_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive/manual-sessions"

    @app.post(prefix, status_code=202)
    async def start(
        response: Response,
        body: ManualStart,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        result = await gateway.kakao_manual_start(session, body, idempotency_key)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.session.resource_version}"'
        return result.model_dump(mode="json")

    @app.get(prefix + "/{lease_id}")
    async def read(
        response: Response,
        lease_id: LeaseId,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, object]:
        result = await gateway.kakao_manual_read(session, lease_id)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.resource_version}"'
        return result.model_dump(mode="json")

    @app.post(prefix + "/{lease_id}/commands")
    async def command(
        response: Response,
        lease_id: LeaseId,
        body: ManualCommand,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
        if_match: Annotated[
            str | None, Header(alias="If-Match", pattern=r'^"v[1-9][0-9]*"$')
        ] = None,
    ) -> dict[str, object]:
        if isinstance(body, ManualEnd) and if_match != f'"v{body.expected_resource_version}"':
            raise GatewayError(status=412, code="API_PRECONDITION_FAILED")
        result = await gateway.kakao_manual_command(
            session, lease_id, body, idempotency_key, if_match
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.session.resource_version}"'
        return result.model_dump(mode="json")
