"""Browser workbook transport: authenticated download, bounded upload and pinned replay."""

from collections.abc import Callable
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, Query, Request, Response

from eom_web_gui.content_workbook_contracts import (
    WORKBOOK_MAX_BYTES,
    WORKBOOK_MEDIA_TYPE,
    WorkbookCommit,
    WorkbookFilename,
    WorkbookQuery,
)
from eom_web_gui.contracts import StudioIdempotencyKey
from eom_web_gui.gateways import ApplicationGateway, GatewayError
from eom_web_gui.sessions import WebSession


def install_content_workbook_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/content-planning/imports"

    @app.get(f"{prefix}/template")
    async def template(session: Annotated[WebSession, Depends(require_session)]) -> Response:
        content = await gateway.content_workbook_template(session)
        filename = quote("EOM_교재_문항배치_입력양식_v1.xlsx")
        return Response(
            content,
            media_type=WORKBOOK_MEDIA_TYPE,
            headers={
                "Content-Disposition": (
                    'attachment; filename="eom-content-placement-template-v1.xlsx"; '
                    f"filename*=UTF-8''{filename}"
                ),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.put(prefix, status_code=201)
    async def upload(
        request: Request,
        session: Annotated[WebSession, Depends(require_csrf)],
        original_filename: Annotated[WorkbookFilename, Query()],
        content_length: Annotated[int, Header(ge=8, le=WORKBOOK_MAX_BYTES)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != WORKBOOK_MEDIA_TYPE:
            raise GatewayError(status=415, code="API_CONTENT_TYPE_UNSUPPORTED")
        result = await gateway.content_workbook_upload(
            session,
            original_filename=original_filename,
            content_length=content_length,
            content=request.stream(),
            idempotency_key=idempotency_key,
        )
        return result.model_dump(mode="json")

    @app.post(f"{prefix}/query")
    async def query(
        body: WorkbookQuery, session: Annotated[WebSession, Depends(require_csrf)]
    ) -> dict[str, object]:
        return (await gateway.content_workbook_query(session, body)).model_dump(mode="json")

    @app.post(f"{prefix}/commit")
    async def commit(
        body: WorkbookCommit,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        return (await gateway.content_workbook_commit(session, body, idempotency_key)).model_dump(
            mode="json"
        )
