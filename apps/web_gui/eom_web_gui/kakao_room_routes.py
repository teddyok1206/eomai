"""Room mapping BFF uses existing session/CSRF and exact upstream concurrency headers."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Path, Query, Response

from eom_web_gui.contracts import StudioIdempotencyKey
from eom_web_gui.gateways import ApplicationGateway
from eom_web_gui.kakao_room_contracts import RoomCommand
from eom_web_gui.sessions import WebSession

BindingId = Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
RoomId = Annotated[str, Path(pattern=r"^kakaoroom_[0-9a-f]{32}$")]


def install_kakao_room_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive/rooms"

    @app.get(prefix)
    async def list_rooms(
        response: Response,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_room_list(
            session, source_binding_id, limit=limit, cursor=cursor
        )
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/{room_id}")
    async def read_room(
        response: Response,
        source_binding_id: BindingId,
        room_id: RoomId,
        session: Annotated[WebSession, Depends(require_session)],
        mapping_revision_id: str | None = Query(
            default=None, pattern=r"^kakaomappingrev_[0-9a-f]{32}$"
        ),
    ) -> dict[str, object]:
        result = await gateway.kakao_room_read(
            session, source_binding_id, room_id, mapping_revision_id=mapping_revision_id
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.resource_version}"'
        return result.model_dump(mode="json")

    @app.post(prefix + "/{room_id}/mapping")
    async def map_room(
        response: Response,
        source_binding_id: BindingId,
        room_id: RoomId,
        body: RoomCommand,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
        if_match: Annotated[str, Header(alias="If-Match", pattern=r'^"v[1-9][0-9]*"$')],
    ) -> dict[str, object]:
        result = await gateway.kakao_room_command(
            session, source_binding_id, room_id, body, idempotency_key, if_match
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.room.resource_version}"'
        return result.model_dump(mode="json")
