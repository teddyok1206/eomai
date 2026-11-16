"""Existing cookie/CSRF transport only. Reads never launch or renew a browser."""

from collections.abc import Callable
from typing import Annotated

from eom_kakao_archive_contracts.kakao_remote import (
    RemoteAuthorizationError,
    RemotePresentation,
    RemoteRequest,
    RemoteTransportPolicy,
    validate_remote_transport,
)
from fastapi import Depends, FastAPI, Header, Path, Request, Response
from pydantic import ValidationError

from eom_web_gui.contracts import StudioIdempotencyKey
from eom_web_gui.gateways import ApplicationGateway, GatewayError
from eom_web_gui.kakao_manual_contracts import ManualCommand, ManualEnd, ManualSession, ManualStart
from eom_web_gui.sessions import KakaoManualPointer, WebSession, utc_now

LeaseId = Annotated[str, Path(pattern=r"^kakaoremotelease_[0-9a-f]{32}$")]


def _snapshot(
    session: WebSession, *, new_intent: bool = False
) -> tuple[int, KakaoManualPointer | None]:
    with session.kakao_manual_lock:
        if new_intent:
            session.kakao_manual_generation += 1
        return session.kakao_manual_generation, session.kakao_manual


def _remember(
    session: WebSession,
    value: ManualSession,
    generation: int,
    previous: KakaoManualPointer | None,
) -> None:
    # SessionStore expiry/deletion may run in a sync dependency thread. Never hold over I/O.
    with session.kakao_manual_lock:
        if session.kakao_manual_generation != generation or session.kakao_manual is not previous:
            return
        if previous is not None:
            if value.lease_id == previous.lease_id:
                if (
                    value.source_binding_id != previous.source_binding_id
                    or value.created_at != previous.created_at
                    or value.resource_version < previous.resource_version
                ):
                    return
            elif value.created_at <= previous.created_at:
                return
        if value.phase in {"STOPPING", "ENDED", "ERROR"}:
            if previous is not None and value.lease_id == previous.lease_id:
                session.kakao_manual = None
            return
        session.kakao_manual = KakaoManualPointer(
            value.lease_id, value.source_binding_id, value.created_at, value.resource_version
        )


def _forwarded_request(request: Request) -> RemoteRequest:
    def header(name: str) -> str | None:
        values = request.headers.getlist(name)
        if len(values) > 1:
            raise GatewayError(status=403, code="KAKAO_REMOTE_TRANSPORT_DENIED")
        return (values[0] or None) if values else None

    if request.scope.get("query_string"):
        raise GatewayError(status=403, code="KAKAO_REMOTE_TRANSPORT_DENIED")
    try:
        return RemoteRequest(
            schema_version="kakao-remote-request/1.0",
            method=header("X-Forwarded-Method") or "",
            path=header("X-Forwarded-Uri") or "",
            protocol=header("X-EOM-Remote-Protocol") or "",
            origin=header("X-EOM-Remote-Origin"),
            upgrade=header("X-EOM-Remote-Upgrade"),
            connection=header("X-EOM-Remote-Connection"),
            websocket_version=header("X-EOM-Remote-Version"),
            websocket_key=header("X-EOM-Remote-Key"),
        )
    except ValidationError:
        raise GatewayError(status=403, code="KAKAO_REMOTE_TRANSPORT_DENIED") from None


def install_kakao_manual_routes(
    app: FastAPI,
    gateway: ApplicationGateway,
    require_session: Callable[..., WebSession],
    require_csrf: Callable[..., WebSession],
    *,
    remote_transport_policy: RemoteTransportPolicy | None = None,
) -> None:
    prefix = "/studio/api/v1/kakao-archive/manual-sessions"

    @app.get("/studio/api/v1/kakao-archive/remote/configuration")
    async def configuration(
        session: Annotated[WebSession, Depends(require_session)],
    ) -> RemotePresentation:
        return RemotePresentation(remote_view_enabled=remote_transport_policy is not None)

    @app.post(prefix, status_code=202)
    async def start(
        response: Response,
        body: ManualStart,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
    ) -> dict[str, object]:
        generation, previous = _snapshot(session, new_intent=True)
        result = await gateway.kakao_manual_start(session, body, idempotency_key)
        # A replay is an immutable command receipt, not the current phase of that lease.
        current = (
            await gateway.kakao_manual_read(session, result.session.lease_id)
            if result.replayed
            else result.session
        )
        if current.source_binding_id != body.source_binding_id:
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        _remember(session, current, generation, previous)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.session.resource_version}"'
        return result.model_dump(mode="json")

    @app.get(prefix + "/{lease_id}")
    async def read(
        response: Response,
        lease_id: LeaseId,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> dict[str, object]:
        generation, previous = _snapshot(session)
        result = await gateway.kakao_manual_read(session, lease_id)
        _remember(session, result, generation, previous)
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.resource_version}"'
        return result.model_dump(mode="json")

    @app.post(prefix + "/{lease_id}/commands")
    async def command(
        response: Response,
        lease_id: LeaseId,
        body: ManualCommand,
        session: Annotated[WebSession, Depends(require_csrf)],
        idempotency_key: Annotated[StudioIdempotencyKey, Header(alias="Idempotency-Key")],
        if_match: Annotated[
            str | None, Header(alias="If-Match", pattern=r'^"v[1-9][0-9]*"$')
        ] = None,
    ) -> dict[str, object]:
        if isinstance(body, ManualEnd) and if_match != f'"v{body.expected_resource_version}"':
            raise GatewayError(status=412, code="API_PRECONDITION_FAILED")
        generation, previous = _snapshot(session, new_intent=isinstance(body, ManualEnd))
        result = await gateway.kakao_manual_command(
            session, lease_id, body, idempotency_key, if_match
        )
        with session.kakao_manual_lock:
            if (
                isinstance(body, ManualEnd)
                and previous is not None
                and previous.lease_id == lease_id
                and session.kakao_manual is previous
                and session.kakao_manual_generation == generation
            ):
                session.kakao_manual = None
        response.headers["Cache-Control"] = "no-store"
        response.headers["ETag"] = f'"v{result.session.resource_version}"'
        return result.model_dump(mode="json")

    @app.get("/studio/api/v1/kakao-archive/remote/authorize", status_code=204)
    async def authorize(
        request: Request,
        session: Annotated[WebSession, Depends(require_session)],
    ) -> Response:
        forwarded = _forwarded_request(request)
        if remote_transport_policy is None:
            raise GatewayError(status=503, code="KAKAO_REMOTE_RUNTIME_UNAVAILABLE")
        try:
            validate_remote_transport(forwarded, remote_transport_policy)
        except RemoteAuthorizationError as error:
            raise GatewayError(status=error.status_code, code=error.code) from None
        generation, pointer = _snapshot(session)
        if pointer is None:
            raise GatewayError(status=403, code="KAKAO_REMOTE_LEASE_UNAVAILABLE")
        await gateway.kakao_manual_authorize(session, pointer.lease_id)
        with session.kakao_manual_lock:
            if (
                session.kakao_manual_generation != generation
                or session.kakao_manual is not pointer
                or session.expires_at <= utc_now()
            ):
                raise GatewayError(status=403, code="KAKAO_REMOTE_LEASE_UNAVAILABLE")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
