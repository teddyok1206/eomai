"""KakaoTalk BFF transport reuses Studio session and CSRF; no collector here."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Path, Query, Response

from eom_web_gui.contracts import StudioIdempotencyKey
from eom_web_gui.gateways import ApplicationGateway
from eom_web_gui.kakao_student_contracts import StudentCommand, StudentCreate
from eom_web_gui.sessions import WebSession


def install_kakao_student_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_csrf: Callable[..., WebSession],
) -> None:
    prefix = "/studio/api/v1/kakao-archive/students"

    @app.get(prefix)
    async def list_students(
        response: Response,
        session: Annotated[WebSession, Depends(require_session)],
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, pattern=r"^kakaostudent_[0-9a-f]{32}$"),
    ) -> dict[str, object]:
        result = await gateway.kakao_student_list(session, limit=limit, cursor=cursor)
        response.headers["Cache-Control"] = "no-store"
        return result.model_dump(mode="json")

    @app.post(prefix, status_code=201)
    async def create_student(
        response: Response,
        body: StudentCreate,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        result = await gateway.kakao_student_create(session, body, idempotency_key)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.student.resource_version}"'
        return result.model_dump(mode="json")

    @app.get(prefix + "/{student_id}")
    async def read_student(
        response: Response,
        student_id: Annotated[str, Path(pattern=r"^kakaostudent_[0-9a-f]{32}$")],
        session: Annotated[WebSession, Depends(require_session)],
        display_revision_id: str | None = Query(
            default=None, pattern=r"^kakaostudentrev_[0-9a-f]{32}$"
        ),
    ) -> dict[str, object]:
        result = await gateway.kakao_student_read(
            session, student_id, display_revision_id=display_revision_id
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.resource_version}"'
        return result.model_dump(mode="json")

    @app.post(prefix + "/{student_id}/commands")
    async def command_student(
        response: Response,
        body: StudentCommand,
        student_id: Annotated[str, Path(pattern=r"^kakaostudent_[0-9a-f]{32}$")],
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
        if_match: Annotated[str, Header(alias="If-Match", pattern=r'^"v[1-9][0-9]*"$')],
    ) -> dict[str, object]:
        result = await gateway.kakao_student_command(
            session,
            student_id,
            body,
            idempotency_key,
            if_match,
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.student.resource_version}"'
        return result.model_dump(mode="json")
