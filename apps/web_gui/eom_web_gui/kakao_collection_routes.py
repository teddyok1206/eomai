"""Studio session/CSRF bridge to the accepted-run API."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Response

from .contracts import StudioIdempotencyKey
from .gateways import ApplicationGateway
from .kakao_collection_contracts import BindingId, RoomCollectionStart, RunId
from .sessions import WebSession


def install_kakao_collection_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_admin_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive/collections"

    @app.post(prefix, status_code=202)
    async def start_room_collection(
        response: Response,
        body: RoomCollectionStart,
        session: Annotated[WebSession, Depends(require_admin_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
        if_match: Annotated[str, Header(alias="If-Match", pattern=r'^"v[1-9][0-9]*"$')],
    ) -> dict[str, object]:
        result = await gateway.kakao_collection_start(session, body, idempotency_key, if_match)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/{run_id}")
    async def read_room_collection(
        response: Response,
        run_id: RunId,
        source_binding_id: Annotated[BindingId, Query()],
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, object]:
        result = await gateway.kakao_collection_status(session, source_binding_id, run_id)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")
