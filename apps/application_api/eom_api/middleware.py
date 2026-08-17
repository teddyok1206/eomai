"""Request context, size/content checks, security headers, and safe access logging."""

from __future__ import annotations

import logging
import re
import secrets
import time
from datetime import UTC, datetime

from fastapi import Request
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from eom_api.problem_details import problem_response
from eom_api.redaction import fingerprint
from eom_api.request_context import RequestContext
from eom_api.security_headers import SECURITY_HEADERS

REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{15,127}$")
JSON_METHODS = frozenset({"POST", "PUT", "PATCH"})


class RequestBoundaryMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        body_limit: int,
        fingerprint_key: bytes,
        allowed_hosts: tuple[str, ...],
    ) -> None:
        self.app = app
        self.body_limit = body_limit
        self.fingerprint_key = fingerprint_key
        self.allowed_hosts = frozenset(allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        supplied = headers.get("x-request-id", "")
        request_id = supplied if REQUEST_ID.fullmatch(supplied) else f"req_{secrets.token_hex(16)}"
        started = datetime.now(UTC)
        scope.setdefault("state", {})["request_context"] = RequestContext(
            request_id=request_id,
            started_at=started,
            route_template=scope.get("path", ""),
            method=scope.get("method", ""),
            client_name=headers.get("x-eom-client-name"),
            source_address_hash=fingerprint(
                self.fingerprint_key,
                scope.get("client", (None,))[0] if scope.get("client") else None,
            ),
            user_agent_hash=fingerprint(self.fingerprint_key, headers.get("user-agent")),
        )

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    mutable[name] = value
                mutable["X-EOM-API-Version"] = "1"
                mutable["X-Request-ID"] = request_id
            await send(message)

        host = headers.get("host", "").rsplit(":", 1)[0]
        if host not in self.allowed_hosts:
            await self._send_problem(scope, receive, secured_send, 400, "API_REQUEST_INVALID")
            return
        method = scope.get("method", "")
        content_length = headers.get("content-length")
        has_body = bool(
            (content_length and content_length.isdigit() and int(content_length) > 0)
            or headers.get("transfer-encoding")
        )
        if method in JSON_METHODS and has_body:
            media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json" and not (
                media_type.startswith("application/") and media_type.endswith("+json")
            ):
                await self._send_problem(
                    scope, receive, secured_send, 415, "API_CONTENT_TYPE_UNSUPPORTED"
                )
                return
        if content_length and content_length.isdigit() and int(content_length) > self.body_limit:
            await self._send_problem(scope, receive, secured_send, 413, "API_BODY_TOO_LARGE")
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.body_limit:
                    raise BodyTooLarge
            return message

        began = time.monotonic()

        try:
            await self.app(scope, limited_receive, secured_send)
        except BodyTooLarge:
            await self._send_problem(scope, receive, secured_send, 413, "API_BODY_TOO_LARGE")
        finally:
            logging.getLogger("eom_api").info(
                "request completed",
                extra={
                    "event": "HTTP_REQUEST_COMPLETED",
                    "request_id": request_id,
                    "route_template": getattr(scope.get("route"), "path", scope.get("path")),
                    "http_method": method,
                    "duration_ms": round((time.monotonic() - began) * 1000, 3),
                },
            )

    async def _send_problem(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        code: str,
    ) -> None:
        request = Request(scope, receive)
        response: JSONResponse = problem_response(
            request,
            status=status,
            error_code=code,
            title="Request rejected",
            detail="The request does not meet the API transport requirements.",
        )
        await response(scope, receive, send)


class BodyTooLarge(Exception):
    pass
