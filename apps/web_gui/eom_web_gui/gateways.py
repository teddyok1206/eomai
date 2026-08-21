"""Loopback HTTP adapters for Application API and read-only Observability."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from eom_web_gui.contracts import (
    ExplorerEntity,
    ExplorerQuery,
    ExplorerResult,
    ItemPreview,
)
from eom_web_gui.redaction import sanitize_mapping
from eom_web_gui.sessions import ApiTokens, WebSession

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{7,127}$")


class GatewayError(RuntimeError):
    def __init__(self, *, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


class LoginResult:
    def __init__(self, *, operator: dict[str, Any], tokens: ApiTokens) -> None:
        self.operator = operator
        self.tokens = tokens


class ApplicationGateway(Protocol):
    async def health(self) -> dict[str, str]: ...

    async def login(self, username: str, password: str) -> LoginResult: ...

    async def logout(self, session: WebSession) -> None: ...

    async def start_workflow(
        self, session: WebSession, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, Any]: ...

    async def workflow_bundle(self, session: WebSession, workflow_id: str) -> dict[str, Any]: ...

    async def approve_workflow(
        self,
        session: WebSession,
        workflow_id: str,
        *,
        etag: str,
        idempotency_key: str,
        reason: str | None,
    ) -> dict[str, Any]: ...

    async def item_preview(
        self, session: WebSession, item_id: str, item_revision_id: str
    ) -> ItemPreview: ...

    async def explorer(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult: ...

    async def close(self) -> None: ...


class ObserveClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        access_token: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._access_token = access_token
        self._authenticated = False
        self._login_lock = __import__("asyncio").Lock()

    async def health(self) -> str:
        try:
            response = await self._client.get("/observe/api/v1/health/live")
        except httpx.HTTPError:
            return "UNAVAILABLE"
        return "ACTIVE" if response.status_code == 200 else "UNAVAILABLE"

    async def get(self, path: str) -> dict[str, Any] | None:
        if self._access_token is None:
            return None
        await self._ensure_session()
        try:
            response = await self._client.get(path, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            return None
        if response.status_code == 401:
            self._authenticated = False
            await self._ensure_session()
            response = await self._client.get(path, headers={"Accept": "application/json"})
        if response.status_code != 200:
            return None
        value = response.json()
        return value if isinstance(value, dict) else None

    async def _ensure_session(self) -> None:
        if self._authenticated or self._access_token is None:
            return
        async with self._login_lock:
            if self._authenticated:
                return
            try:
                response = await self._client.post(
                    "/observe/api/v1/session",
                    json={"token": self._access_token},
                    headers={"Content-Type": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise GatewayError(status=503, code="OBSERVABILITY_UNAVAILABLE") from exc
            if response.status_code != 204:
                raise GatewayError(status=503, code="OBSERVABILITY_AUTH_UNAVAILABLE")
            self._authenticated = True

    async def close(self) -> None:
        await self._client.aclose()


class HttpApplicationGateway:
    def __init__(
        self,
        *,
        application_api_url: str,
        observability_url: str,
        timeout: float,
        observability_access_token: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
        observability_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=application_api_url,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.observe = ObserveClient(
            base_url=observability_url,
            timeout=timeout,
            access_token=observability_access_token,
            transport=observability_transport,
        )

    async def health(self) -> dict[str, str]:
        results: dict[str, str] = {}
        for key, path in (
            ("application_api", "/api/v1/health/live"),
            ("application_api_ready", "/api/v1/health/ready"),
        ):
            try:
                response = await self._client.get(path)
            except httpx.HTTPError:
                results[key] = "UNAVAILABLE"
            else:
                results[key] = "ACTIVE" if response.status_code == 200 else "UNAVAILABLE"
        results["observability"] = await self.observe.health()
        return results

    async def login(self, username: str, password: str) -> LoginResult:
        response = await self._request(
            "POST",
            "/api/v1/auth/login",
            json={
                "username": username,
                "password": password,
                "client_name": "EOM Scientific Studio",
            },
        )
        data = self._data(response)
        tokens = _tokens(data)
        me = await self._client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
                "Accept": "application/json",
            },
        )
        if me.status_code != 200:
            raise _gateway_error(me)
        operator = _operator_view(self._data(me))
        return LoginResult(operator=operator, tokens=tokens)

    async def logout(self, session: WebSession) -> None:
        try:
            await self._authorized(session, "POST", "/api/v1/auth/logout", json={})
        except GatewayError:
            return

    async def start_workflow(
        self, session: WebSession, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, Any]:
        response = await self._authorized(
            session,
            "POST",
            "/api/v1/workflows",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        return sanitize_mapping(self._data(response))

    async def workflow_bundle(self, session: WebSession, workflow_id: str) -> dict[str, Any]:
        _require_id(workflow_id, "workflow_")
        workflow_response = await self._authorized(
            session, "GET", f"/api/v1/workflows/{workflow_id}"
        )
        steps_response = await self._authorized(
            session, "GET", f"/api/v1/workflows/{workflow_id}/steps"
        )
        events_response = await self._authorized(
            session, "GET", f"/api/v1/workflows/{workflow_id}/events"
        )
        observe = await self.observe.get(f"/observe/api/v1/workflows/{workflow_id}")
        return {
            "workflow": sanitize_mapping(self._data(workflow_response)),
            "etag": workflow_response.headers.get("etag"),
            "steps": [sanitize_mapping(item) for item in self._list_data(steps_response)],
            "events": [sanitize_mapping(item) for item in self._list_data(events_response)],
            "observe": _sanitize_observe_workflow(observe),
        }

    async def approve_workflow(
        self,
        session: WebSession,
        workflow_id: str,
        *,
        etag: str,
        idempotency_key: str,
        reason: str | None,
    ) -> dict[str, Any]:
        _require_id(workflow_id, "workflow_")
        response = await self._authorized(
            session,
            "POST",
            f"/api/v1/workflows/{workflow_id}/approvals",
            json={"reason": reason},
            headers={"Idempotency-Key": idempotency_key, "If-Match": etag},
        )
        return sanitize_mapping(self._data(response))

    async def item_preview(
        self, session: WebSession, item_id: str, item_revision_id: str
    ) -> ItemPreview:
        _require_id(item_id, "item_")
        _require_id(item_revision_id, "itemrev_")
        item_response = await self._authorized(session, "GET", f"/api/v1/items/{item_id}")
        revision_response = await self._authorized(
            session, "GET", f"/api/v1/item-revisions/{item_revision_id}"
        )
        await self._authorized(
            session, "GET", f"/api/v1/item-revisions/{item_revision_id}/components"
        )
        item = self._data(item_response)
        revision = self._data(revision_response)
        if (
            revision.get("item_id") != item_id
            or item.get("current_revision_id") != item_revision_id
        ):
            raise GatewayError(status=409, code="ITEM_REVISION_POINTER_MISMATCH")
        return ItemPreview(
            preview_state="METADATA_ONLY",
            workflow_id=str(revision.get("workflow_id") or "unknown"),
            item_id=item_id,
            item_revision_id=item_revision_id,
            revision_state=str(revision.get("revision_state") or "UNKNOWN"),
            content_pack_release_id=str(revision.get("content_pack_release_id") or "unknown"),
        )

    async def explorer(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult:
        if query.entity == ExplorerEntity.ITEM_REVISIONS:
            return await self._item_revision_explorer(session, query)
        if query.entity in {ExplorerEntity.WORKFLOW_EVENTS, ExplorerEntity.WORKFLOW_COMMANDS}:
            return await self._event_explorer(session, query)
        if query.entity in OBSERVE_EXACT_ENTITIES:
            return await self._observe_explorer(query)
        if query.entity == ExplorerEntity.HWPX_BUILDS:
            return ExplorerResult(
                entity=query.entity,
                columns=(),
                rows=(),
                capability="PREPARED_NOT_DEPLOYED",
            )
        spec = EXPLORER_SPECS.get(query.entity)
        if spec is None:
            raise GatewayError(status=422, code="EXPLORER_ENTITY_UNSUPPORTED")
        path, columns, detail_template = spec
        if query.exact_id and detail_template:
            _require_generic_id(query.exact_id)
            response = await self._authorized(
                session, "GET", detail_template.format(identifier=query.exact_id)
            )
            values = [self._data(response)]
            page: dict[str, Any] = {}
        else:
            params: dict[str, str | int | float | bool | None] = {"limit": query.limit}
            if query.cursor:
                params["cursor"] = query.cursor
            if query.status and query.entity in {ExplorerEntity.WORKFLOWS, ExplorerEntity.ITEMS}:
                params["state"] = query.status
            response = await self._authorized(session, "GET", path, params=params)
            values = self._list_data(response)
            page = response.json().get("page", {})
        rows = _filtered_rows(values, columns, query)
        return ExplorerResult(
            entity=query.entity,
            columns=columns,
            rows=tuple(rows),
            next_cursor=page.get("next_cursor") if isinstance(page, dict) else None,
            has_more=bool(page.get("has_more")) if isinstance(page, dict) else False,
        )

    async def _observe_explorer(self, query: ExplorerQuery) -> ExplorerResult:
        if not query.exact_id:
            return ExplorerResult(
                entity=query.entity,
                columns=OBSERVE_EXACT_ENTITIES[query.entity][1],
                rows=(),
                capability="EXACT_ID_REQUIRED",
            )
        _require_generic_id(query.exact_id)
        route, columns = OBSERVE_EXACT_ENTITIES[query.entity]
        value = await self.observe.get(route.format(identifier=query.exact_id))
        if value is None:
            raise GatewayError(status=404, code="EXPLORER_RECORD_NOT_FOUND")
        rows_source: list[dict[str, Any]]
        if query.entity == ExplorerEntity.ARTIFACT_REVISIONS:
            raw = value.get("revisions", [])
            rows_source = [item for item in raw if isinstance(item, dict)]
        elif query.entity == ExplorerEntity.STEP_RUNS:
            raw = value.get("step_runs", [])
            rows_source = [item for item in raw if isinstance(item, dict)]
        else:
            rows_source = [value]
        rows = _filtered_rows(rows_source, columns, query)
        return ExplorerResult(entity=query.entity, columns=columns, rows=tuple(rows))

    async def _event_explorer(self, session: WebSession, query: ExplorerQuery) -> ExplorerResult:
        columns = EXPLORER_SPECS[query.entity][1]
        params: dict[str, str | int | float | bool | None] = {"limit": query.limit}
        if query.cursor:
            params["after_cursor"] = query.cursor
        if query.exact_id:
            _require_generic_id(query.exact_id)
            params["aggregate_id"] = query.exact_id
        if query.date_from:
            params["from_time"] = query.date_from.isoformat()
        if query.date_to:
            params["to_time"] = query.date_to.isoformat()
        response = await self._authorized(session, "GET", "/api/v1/events", params=params)
        values = self._list_data(response)
        page = response.json().get("page", {})
        rows = _filtered_rows(values, columns, query)
        return ExplorerResult(
            entity=query.entity,
            columns=columns,
            rows=tuple(rows),
            next_cursor=page.get("next_cursor") if isinstance(page, dict) else None,
            has_more=bool(page.get("has_more")) if isinstance(page, dict) else False,
        )

    async def _item_revision_explorer(
        self, session: WebSession, query: ExplorerQuery
    ) -> ExplorerResult:
        columns = EXPLORER_SPECS[ExplorerEntity.ITEM_REVISIONS][1]
        if not query.exact_id:
            return ExplorerResult(
                entity=query.entity,
                columns=columns,
                rows=(),
                capability="EXACT_ID_REQUIRED",
            )
        _require_generic_id(query.exact_id)
        if query.exact_id.startswith("itemrev_"):
            response = await self._authorized(
                session, "GET", f"/api/v1/item-revisions/{query.exact_id}"
            )
            values = [self._data(response)]
        elif query.exact_id.startswith("item_"):
            response = await self._authorized(
                session, "GET", f"/api/v1/items/{query.exact_id}/revisions"
            )
            values = self._list_data(response)
        else:
            raise GatewayError(status=422, code="RESOURCE_ID_INVALID")
        rows = _filtered_rows(values, columns, query)
        return ExplorerResult(entity=query.entity, columns=columns, rows=tuple(rows))

    async def _authorized(
        self,
        session: WebSession,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str | int | float | bool | None] | None = None,
    ) -> httpx.Response:
        used_access_token = session.tokens.access_token
        response = await self._client.request(
            method,
            path,
            json=json,
            params=params,
            headers={
                "Authorization": f"Bearer {used_access_token}",
                "Accept": "application/json",
                **(headers or {}),
            },
        )
        if response.status_code != 401:
            if response.status_code >= 400:
                raise _gateway_error(response)
            return response
        async with session.refresh_lock:
            if session.tokens.access_token == used_access_token:
                refresh = await self._request(
                    "POST",
                    "/api/v1/auth/refresh",
                    json={"refresh_token": session.tokens.refresh_token},
                )
                session.tokens = _tokens(self._data(refresh))
        response = await self._client.request(
            method,
            path,
            json=json,
            params=params,
            headers={
                "Authorization": f"Bearer {session.tokens.access_token}",
                "Accept": "application/json",
                **(headers or {}),
            },
        )
        if response.status_code >= 400:
            raise _gateway_error(response)
        return response

    async def _request(self, method: str, path: str, *, json: dict[str, object]) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                path,
                json=json,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise GatewayError(status=503, code="APPLICATION_API_UNAVAILABLE") from exc
        if response.status_code >= 400:
            raise _gateway_error(response)
        return response

    @staticmethod
    def _data(response: httpx.Response) -> dict[str, Any]:
        value = response.json()
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(data, dict):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        return data

    @staticmethod
    def _list_data(response: httpx.Response) -> list[dict[str, Any]]:
        value = response.json()
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise GatewayError(status=502, code="APPLICATION_API_RESPONSE_INVALID")
        return data

    async def close(self) -> None:
        await self._client.aclose()
        await self.observe.close()


EXPLORER_SPECS: dict[ExplorerEntity, tuple[str, tuple[str, ...], str | None]] = {
    ExplorerEntity.WORKFLOWS: (
        "/api/v1/workflows",
        ("workflow_id", "state", "stage", "current_step_key", "created_at", "updated_at"),
        "/api/v1/workflows/{identifier}",
    ),
    ExplorerEntity.ITEMS: (
        "/api/v1/items",
        ("item_id", "lifecycle_state", "current_revision_id", "created_at"),
        "/api/v1/items/{identifier}",
    ),
    ExplorerEntity.ITEM_REVISIONS: (
        "/api/v1/items",
        (
            "item_revision_id",
            "item_id",
            "revision_number",
            "revision_state",
            "workflow_id",
            "created_at",
        ),
        "/api/v1/item-revisions/{identifier}",
    ),
    ExplorerEntity.CONTENT_PACK_RELEASES: (
        "/api/v1/content-pack-releases",
        ("content_pack_release_id", "pack_key", "release_version", "release_state", "created_at"),
        "/api/v1/content-pack-releases/{identifier}",
    ),
    ExplorerEntity.USAGE_PLANS: (
        "/api/v1/usage-plans",
        ("usage_plan_id", "item_id", "usage_type", "status", "created_at"),
        "/api/v1/usage-plans/{identifier}",
    ),
    ExplorerEntity.USAGE_RECORDS: (
        "/api/v1/usage-records",
        ("usage_record_id", "usage_plan_id", "item_id", "status", "created_at"),
        "/api/v1/usage-records/{identifier}",
    ),
    ExplorerEntity.WORKFLOW_EVENTS: (
        "/api/v1/events",
        ("event_id", "aggregate_type", "aggregate_id", "event_type", "new_state", "created_at"),
        None,
    ),
    ExplorerEntity.WORKFLOW_COMMANDS: (
        "/api/v1/events",
        ("event_id", "aggregate_id", "event_type", "actor_id", "created_at"),
        None,
    ),
}

OBSERVE_EXACT_ENTITIES: dict[ExplorerEntity, tuple[str, tuple[str, ...]]] = {
    ExplorerEntity.STEP_RUNS: (
        "/observe/api/v1/workflows/{identifier}",
        (
            "step_run_id",
            "step_key",
            "attempt",
            "state",
            "platform_job_id",
            "started_at",
            "finished_at",
        ),
    ),
    ExplorerEntity.JOBS: (
        "/observe/api/v1/jobs/{identifier}",
        (
            "job_id",
            "status",
            "task_type",
            "worker_slot_id",
            "created_at",
            "updated_at",
            "completed_at",
        ),
    ),
    ExplorerEntity.ARTIFACTS: (
        "/observe/api/v1/artifacts/{identifier}",
        ("artifact_id", "artifact_type", "approved", "job_id", "created_at"),
    ),
    ExplorerEntity.ARTIFACT_REVISIONS: (
        "/observe/api/v1/artifacts/{identifier}",
        ("revision_id", "content_hash", "manifest_hash", "content_bytes", "approved", "created_at"),
    ),
}


def _tokens(data: dict[str, Any]) -> ApiTokens:
    try:
        access = str(data["access_token"])
        refresh = str(data["refresh_token"])
        access_expiry = _datetime(data["access_expires_at"])
        refresh_expiry = _datetime(data["refresh_expires_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GatewayError(status=502, code="APPLICATION_API_AUTH_RESPONSE_INVALID") from exc
    if not access.startswith("eom_at_") or not refresh.startswith("eom_rt_"):
        raise GatewayError(status=502, code="APPLICATION_API_AUTH_RESPONSE_INVALID")
    return ApiTokens(access, refresh, access_expiry, refresh_expiry)


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(UTC)


def _gateway_error(response: httpx.Response) -> GatewayError:
    code = "APPLICATION_API_REQUEST_FAILED"
    try:
        value = response.json()
        if isinstance(value, dict) and isinstance(value.get("error_code"), str):
            candidate = value["error_code"]
            if candidate.replace("_", "").isalnum() and candidate.upper() == candidate:
                code = candidate[:64]
    except ValueError:
        pass
    return GatewayError(status=response.status_code, code=code)


def _operator_view(value: dict[str, Any]) -> dict[str, Any]:
    roles = value.get("roles", [])
    permissions = value.get("effective_permissions", [])
    if not isinstance(roles, list) or not all(isinstance(item, str) for item in roles):
        raise GatewayError(status=502, code="APPLICATION_API_OPERATOR_INVALID")
    if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
        raise GatewayError(status=502, code="APPLICATION_API_OPERATOR_INVALID")
    result: dict[str, Any] = {}
    for key in ("operator_id", "username", "display_name", "password_change_required"):
        item = value.get(key)
        if isinstance(item, (str, bool)):
            result[key] = item
    result["roles"] = roles
    result["effective_permissions"] = permissions
    return result


def _require_id(value: str, prefix: str) -> None:
    if not value.startswith(prefix) or ID_PATTERN.fullmatch(value) is None:
        raise GatewayError(status=422, code="RESOURCE_ID_INVALID")


def _require_generic_id(value: str) -> None:
    if ID_PATTERN.fullmatch(value) is None:
        raise GatewayError(status=422, code="RESOURCE_ID_INVALID")


def _sanitize_observe_workflow(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result: dict[str, Any] = dict(sanitize_mapping(value))
    for key in ("step_runs", "approvals", "events"):
        values = value.get(key, [])
        if isinstance(values, list):
            result[key] = [sanitize_mapping(item) for item in values if isinstance(item, dict)]
    return result


def _filtered_rows(
    values: list[dict[str, Any]], columns: tuple[str, ...], query: ExplorerQuery
) -> list[dict[str, Any]]:
    rows = [
        {key: sanitize_mapping({key: value.get(key)}).get(key) for key in columns}
        for value in values
    ]
    if query.status:
        rows = [
            row
            for row in rows
            if query.status
            in {
                str(row.get(key) or "")
                for key in ("state", "status", "revision_state", "release_state")
            }
        ]
    timestamp_key = "updated_at" if query.sort.startswith("updated") else "created_at"
    if query.date_from:
        rows = [row for row in rows if _row_time(row.get(timestamp_key)) >= query.date_from]
    if query.date_to:
        rows = [row for row in rows if _row_time(row.get(timestamp_key)) <= query.date_to]
    rows.sort(
        key=lambda row: (str(row.get(timestamp_key) or ""), str(next(iter(row.values()), ""))),
        reverse=query.sort.endswith("desc"),
    )
    return rows[: query.limit]


def _row_time(value: object) -> datetime:
    if isinstance(value, str):
        try:
            return _datetime(value)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)
