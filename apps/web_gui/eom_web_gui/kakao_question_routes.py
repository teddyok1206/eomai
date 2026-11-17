"""Session/CSRF transport for exact question reads and human review decisions."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Path, Query, Response

from .contracts import StudioIdempotencyKey
from .downloads import download_response
from .gateways import ApplicationGateway
from .kakao_question_contracts import QuestionComposition, QuestionCreate, QuestionReview
from .sessions import WebSession

BindingId = Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
RoomId = Annotated[str, Query(pattern=r"^kakaoroom_[0-9a-f]{32}$")]
QuestionId = Annotated[str, Path(pattern=r"^kakaoquestion_[0-9a-f]{32}$")]
RevisionId = Annotated[str, Path(pattern=r"^kakaoquestionrev_[0-9a-f]{32}$")]


def install_kakao_question_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive/questions"

    @app.post(prefix + "/compose")
    async def compose_questions(
        response: Response,
        body: QuestionComposition,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        result = await gateway.kakao_question_compose(session, body, idempotency_key)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.get(prefix)
    async def list_questions(
        response: Response,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
        room_id: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, pattern=r"^kakaoquestion_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_question_list(
            session, source_binding_id, room_id=room_id, limit=limit, cursor=cursor
        )
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.post(prefix, status_code=201)
    async def create_question(
        response: Response,
        body: QuestionCreate,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        result = await gateway.kakao_question_create(session, body, idempotency_key)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.question.resource_version}"'
        return result.model_dump(mode="json")

    @app.get(prefix + "/{question_id}/revisions/{revision_id}")
    async def read_question(
        response: Response,
        question_id: QuestionId,
        revision_id: RevisionId,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
        room_id: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_question_read(
            session, source_binding_id, room_id, question_id, revision_id
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.question.resource_version}"'
        return result.model_dump(mode="json")

    @app.get(prefix + "/{question_id}/revisions/{revision_id}/edit-context")
    async def read_edit_context(
        response: Response,
        question_id: QuestionId,
        revision_id: RevisionId,
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
        room_id: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_question_edit_context(
            session, source_binding_id, room_id, question_id, revision_id
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.resource_version}"'
        return result.model_dump(mode="json")

    @app.post(prefix + "/{question_id}/review")
    async def review_question(
        response: Response,
        question_id: QuestionId,
        source_binding_id: BindingId,
        room_id: RoomId,
        body: QuestionReview,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
        if_match: Annotated[str, Header(alias="If-Match", pattern=r'^"v[1-9][0-9]*"$')],
    ) -> dict[str, object]:
        result = await gateway.kakao_question_review(
            session, source_binding_id, room_id, question_id, body, idempotency_key, if_match
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.question.resource_version}"'
        return result.model_dump(mode="json")

    @app.get(prefix + "/{question_id}/revisions/{revision_id}/images/{attachment_id}")
    async def read_image(
        question_id: QuestionId,
        revision_id: RevisionId,
        attachment_id: Annotated[str, Path(pattern=r"^kakaoattachment_[0-9a-f]{32}$")],
        source_binding_id: BindingId,
        session: Annotated[WebSession, Depends(require_session)],
        room_id: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
    ) -> Response:
        value = await gateway.kakao_question_image(
            session, source_binding_id, room_id, question_id, revision_id, attachment_id
        )
        return download_response(
            value.content,
            media_type=value.content_type,
            headers={"Content-Disposition": "inline", "ETag": value.etag},
        )
