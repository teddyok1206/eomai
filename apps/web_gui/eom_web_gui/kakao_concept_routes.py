"""Same-origin session/CSRF and verified binary delivery for optional textbook recommendations."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Path, Query, Response

from .contracts import StudioIdempotencyKey
from .gateways import ApplicationGateway
from .kakao_concept_contracts import ConceptCreate
from .sessions import WebSession

BindingId = Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
TaskId = Annotated[str, Path(pattern=r"^kakaoconcepttask_[0-9a-f]{32}$")]


def install_kakao_concept_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive/concepts"

    @app.post(prefix, status_code=202)
    async def start(
        response: Response,
        body: ConceptCreate,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        result = await gateway.kakao_concept_start(session, body, idempotency_key)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix)
    async def history(
        response: Response,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, pattern=r"^kakaoconcepttask_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_concept_list(
            session, source_binding_id, limit=limit, cursor=cursor
        )
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/{task_id}")
    async def read(
        response: Response,
        task_id: TaskId,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, object]:
        result = await gateway.kakao_concept_read(session, source_binding_id, task_id)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix + "/{task_id}/pages/{page_key}")
    async def page(
        task_id: TaskId,
        source_binding_id: BindingId,
        page_key: Annotated[str, Path(pattern=r"^E[1-3]P[1-9][0-9]{0,4}$")],
        session: Annotated[WebSession, Depends(require_session)],
    ) -> Response:
        result = await gateway.kakao_concept_page(session, source_binding_id, task_id, page_key)
        return Response(
            result.content,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": "inline",
                "X-Content-Type-Options": "nosniff",
                "ETag": result.etag,
            },
        )
