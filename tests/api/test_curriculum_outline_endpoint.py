from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from eom_api.app import create_app
from eom_api.routers.curriculum import integrated_science_editorial_outline
from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
    IntegratedScienceEditorialOutline,
)
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services

PATH = "/api/v1/curriculum/integrated-science-editorial-outline"


def test_curriculum_outline_endpoint_is_authenticated_and_author_permissioned() -> None:
    services = cast(Any, disconnected_services())
    try:
        app = create_app(services)
        operation = app.openapi()["paths"][PATH]["get"]
        assert operation["operationId"] == "integrated_science_editorial_outline_get"
        assert operation["x-eom-permission"] == "workflow:start"
        with TestClient(app, base_url="http://localhost") as client:
            response = client.get(PATH)
        assert response.status_code == 401
        assert response.json()["error_code"] == "AUTH_TOKEN_INVALID"
    finally:
        services.engine.dispose()


def test_curriculum_outline_endpoint_returns_the_typed_pinned_catalog() -> None:
    request = cast(
        Request,
        SimpleNamespace(
            state=SimpleNamespace(
                request_context=SimpleNamespace(request_id="req_curriculum_outline")
            )
        ),
    )
    response = integrated_science_editorial_outline(request)
    data: IntegratedScienceEditorialOutline = response.data
    assert data.outline_key == "eom-integrated-science-editorial-outline"
    assert len(data.units) == 41
    assert tuple(data.supported_product_levels) == ("LARGE", "MIDDLE")
    assert INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256 == (
        "sha256:f11389c8ab26c2bd5b93acf66fe92d30fea9c1d0bc7e6b91a6b6751fdccb5108"
    )
