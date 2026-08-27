"""FastAPI application factory for EOM Application API V1."""

from __future__ import annotations

from typing import Any

from eom_api_contracts import ProblemDetails
from fastapi import FastAPI

from eom_api.lifespan import AppServices, build_services, lifespan_for
from eom_api.middleware import RequestBoundaryMiddleware
from eom_api.openapi import build_openapi, install_route_metadata
from eom_api.problem_details import install_exception_handlers
from eom_api.routers import (
    auth,
    content_intakes,
    content_packs,
    control_plane,
    curriculum,
    deliverables,
    events,
    health,
    hwpx,
    items,
    knowledge_analysis,
    knowledge_analysis_batches,
    knowledge_retrieval,
    operators,
    system,
    usage,
    workflows,
)

API_PREFIX = "/api/v1"
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ProblemDetails, "description": description}
    for status, description in {
        400: "Malformed request",
        401: "Authentication failure",
        403: "Permission or freshness failure",
        404: "Resource not found",
        409: "Domain or idempotency conflict",
        412: "Resource version mismatch",
        415: "Unsupported media type",
        422: "Schema validation failure",
        428: "Missing precondition",
        429: "Rate limit exceeded",
        500: "Unexpected internal error",
        503: "Dependency unavailable",
    }.items()
}


def create_app(services: AppServices | None = None) -> FastAPI:
    actual = services or build_services()
    docs = actual.settings.server.docs_enabled
    app = FastAPI(
        title="EOM Application API",
        version="0.1.0",
        openapi_version="3.1.0",
        docs_url="/api/v1/docs" if docs else None,
        redoc_url="/api/v1/redoc" if docs else None,
        openapi_url="/api/v1/openapi.json" if docs else None,
        lifespan=lifespan_for(actual),
        responses=PROBLEM_RESPONSES,
        strict_content_type=True,
    )
    app.state.services = actual
    for module in (
        health,
        hwpx,
        auth,
        operators,
        content_intakes,
        content_packs,
        control_plane,
        curriculum,
        workflows,
        items,
        knowledge_analysis,
        knowledge_analysis_batches,
        knowledge_retrieval,
        deliverables,
        usage,
        events,
        system,
    ):
        app.include_router(module.router, prefix=API_PREFIX)
    install_route_metadata(app)
    install_exception_handlers(app)
    app.add_middleware(
        RequestBoundaryMiddleware,
        body_limit=actual.settings.server.request_body_limit_bytes,
        fingerprint_key=actual.fingerprint_key,
        allowed_hosts=actual.settings.security.allowed_hosts,
    )
    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]
    return app
