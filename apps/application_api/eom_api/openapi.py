"""Deterministic OpenAPI 3.1 export and route security metadata."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from eom_api.dependencies import PermissionDependency

PUBLIC_OPERATIONS = frozenset({"health_live", "health_ready", "auth_login", "auth_refresh"})
AUTH_CONTROL_OPERATIONS = frozenset(
    {"auth_logout", "auth_logout_all", "auth_me", "auth_change_password"}
)


def install_route_metadata(app: FastAPI) -> None:
    seen: set[str] = set()
    candidates: list[object] = []
    for included in app.routes:
        original_router = getattr(included, "original_router", None)
        if original_router is not None:
            candidates.extend(original_router.routes)
        else:
            candidates.append(included)
    for route in candidates:
        if not isinstance(route, APIRoute):
            continue
        operation_id = route.operation_id
        if not operation_id or operation_id in seen:
            raise RuntimeError("API routes require unique explicit operation IDs")
        seen.add(operation_id)
        permissions = [
            dependency.dependency
            for dependency in route.dependencies
            if isinstance(dependency.dependency, PermissionDependency)
        ]
        route.openapi_extra = dict(route.openapi_extra or {})
        if operation_id in PUBLIC_OPERATIONS:
            if permissions:
                raise RuntimeError("public endpoint cannot declare a permission")
            route.openapi_extra["x-eom-public"] = True
        elif operation_id in AUTH_CONTROL_OPERATIONS:
            route.openapi_extra["x-eom-auth-control"] = True
        else:
            if len(permissions) != 1:
                raise RuntimeError(
                    f"protected operation {operation_id} requires one permission declaration"
                )
            permission = permissions[0]
            route.openapi_extra["x-eom-permission"] = permission.permission_key.value
            route.openapi_extra["x-eom-fresh-auth"] = permission.fresh_required
            route.openapi_extra["x-eom-admin-only"] = permission.admin_only


def build_openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version="3.1.0",
        description="Versioned metadata, command, identity, and RBAC API for EOM clients.",
        routes=app.routes,
    )
    schema["servers"] = [{"url": "http://127.0.0.1:8765"}]
    schema["x-eom-api-version"] = "1"
    security = schema.get("components", {}).get("securitySchemes", {}).get("OpaqueBearer")
    if security is not None:
        security["description"] = "Opaque DB-backed bearer access token."
        security["bearerFormat"] = "opaque"
    problem_schema = {"$ref": "#/components/schemas/ProblemDetails"}
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for status, response in operation.get("responses", {}).items():
                if str(status).isdigit() and int(status) >= 400:
                    response["content"] = {"application/problem+json": {"schema": problem_schema}}
    app.openapi_schema = schema
    return schema


def export_openapi(app: FastAPI, output: Path) -> str:
    payload = (
        json.dumps(
            build_openapi(app),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    digest_path = (
        output.with_name(output.name.removesuffix(".openapi.json") + ".sha256")
        if output.name.endswith(".openapi.json")
        else output.with_suffix(".sha256")
    )
    digest_path.write_text(f"{digest}  {output.name}\n", encoding="ascii")
    return digest
