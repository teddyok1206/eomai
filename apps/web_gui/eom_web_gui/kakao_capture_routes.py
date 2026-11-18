"""Current Studio admin/CSRF → existing API transport; no collection side effects."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Response

from .contracts import StudioIdempotencyKey
from .gateways import ApplicationGateway
from .kakao_capture_contracts import CaptureConfirm, PhotoCheckSelection
from .sessions import WebSession


def install_kakao_capture_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_admin_session: Callable[..., WebSession],
    require_admin_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive/manual-captures"

    @app.get(prefix)
    async def list_captures(
        response: Response,
        source_binding_id: Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")],
        session: Annotated[WebSession, Depends(require_admin_session)],
    ) -> dict[str, object]:
        result = await gateway.kakao_capture_list(session, source_binding_id)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/photo-occurrence")
    async def check_photo(
        response: Response,
        selection: Annotated[PhotoCheckSelection, Query()],
        session: Annotated[WebSession, Depends(require_admin_session)],
    ) -> dict[str, object]:
        result = await gateway.kakao_photo_check(session, selection)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.post(prefix + "/confirm-room")
    async def confirm_capture(
        response: Response,
        body: CaptureConfirm,
        session: Annotated[WebSession, Depends(require_admin_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
        if_match: Annotated[str, Header(alias="If-Match", pattern=r'^"v[1-9][0-9]*"$')],
    ) -> dict[str, object]:
        result = await gateway.kakao_capture_confirm(session, body, idempotency_key, if_match)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.room.resource_version}"'
        return result.model_dump(mode="json")
