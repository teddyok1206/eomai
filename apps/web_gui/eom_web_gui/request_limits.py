"""Count actual ASGI request bytes, including chunked uploads and false lengths."""

from __future__ import annotations

import re

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 262_144
MAX_PDF_REVIEW_BODY_BYTES = 256 * 1024 * 1024
PDF_REVIEW_CONTENT_PATH = re.compile(
    r"^/studio/api/v1/pdf-document-reviews/(?:"
    r"upload-intents/pdfreviewintent_[0-9a-f]{32}/content|"
    r"sets/docreviewset_[0-9a-f]{32}/documents/(?:QUESTION|SOLUTION)/content"
    r")$"
)


def request_body_limit(method: str, path: str) -> int:
    if method == "PUT" and path == "/studio/api/v1/content-planning/imports":
        return 8 * 1024 * 1024
    if method == "POST" and path == "/studio/api/v1/content-planning/commands":
        # Large final arrays contain only small pointers, never uploaded files.
        return 4 * 1024 * 1024
    return (
        MAX_PDF_REVIEW_BODY_BYTES
        if method == "PUT"
        and (
            PDF_REVIEW_CONTENT_PATH.fullmatch(path)
            or path == "/studio/api/v1/material-learning/sources"
        )
        else MAX_BODY_BYTES
    )


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = request_body_limit(scope["method"], scope["path"])
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # HTTPException survives FastAPI's JSON parsing boundary;
                    # generic exceptions would be misreported as malformed JSON.
                    raise HTTPException(status_code=413, detail="WEB_BODY_TOO_LARGE")
            return message

        await self.app(scope, bounded_receive, send)
