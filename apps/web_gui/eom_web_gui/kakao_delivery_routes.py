"""Existing Studio session/CSRF/download boundaries for packet and student PDF use."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Path, Query, Response

from .contracts import StudioIdempotencyKey
from .downloads import download_response
from .gateways import ApplicationGateway
from .kakao_delivery_contracts import ExportCreate, PacketCreate
from .sessions import WebSession

BindingId = Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
PacketId = Annotated[str, Path(pattern=r"^kakaopacket_[0-9a-f]{32}$")]
PacketRevisionId = Annotated[str, Path(pattern=r"^kakaopacketrev_[0-9a-f]{32}$")]
ExportId = Annotated[str, Path(pattern=r"^kakaoexport_[0-9a-f]{32}$")]


def install_kakao_delivery_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive"

    @app.post(prefix + "/question-packets", status_code=201)
    async def create_packet(
        response: Response,
        body: PacketCreate,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        result = await gateway.kakao_packet_create(session, body, idempotency_key)
        response.headers.update(
            {"Cache-Control": "no-store", "ETag": f'"v{result.packet.resource_version}"'}
        )
        return result.model_dump(mode="json")

    @app.get(prefix + "/question-packets")
    async def list_packets(
        response: Response,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, pattern=r"^kakaopacket_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_packet_list(
            session, source_binding_id, limit=limit, cursor=cursor
        )
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/question-packets/{packet_id}/revisions/{revision_id}")
    async def read_packet(
        response: Response,
        packet_id: PacketId,
        revision_id: PacketRevisionId,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, object]:
        result = await gateway.kakao_packet_read(session, source_binding_id, packet_id, revision_id)
        response.headers.update(
            {"Cache-Control": "no-store", "ETag": f'"v{result.packet.resource_version}"'}
        )
        return result.model_dump(mode="json")

    @app.post(prefix + "/exports", status_code=202)
    async def create_export(
        response: Response,
        body: ExportCreate,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        result = await gateway.kakao_export_create(session, body, idempotency_key)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/exports")
    async def list_exports(
        response: Response,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, pattern=r"^kakaoexport_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_export_list(
            session, source_binding_id, limit=limit, cursor=cursor
        )
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/exports/{export_id}")
    async def read_export(
        response: Response,
        export_id: ExportId,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, object]:
        result = await gateway.kakao_export_read(session, source_binding_id, export_id)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/exports/{export_id}/file")
    async def download_export(
        export_id: ExportId,
        source_binding_id: BindingId,
        revision_id: Annotated[str, Query(pattern=r"^kakaoexportrev_[0-9a-f]{32}$")],
        session: Annotated[WebSession, Depends(require_session)],
    ) -> Response:
        result = await gateway.kakao_export_pdf(session, source_binding_id, export_id, revision_id)
        return download_response(
            result.content,
            media_type="application/pdf",
            headers={
                "ETag": result.etag,
                "Content-Disposition": f'attachment; filename="{export_id}.pdf"',
            },
        )
