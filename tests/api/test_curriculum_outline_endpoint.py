from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from eom_api.app import create_app
from eom_api.routers.curriculum import (
    integrated_science_editorial_outline,
    integrated_science_graph_capability,
)
from eom_api_contracts import CurriculumGraphCapabilityView
from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
    IntegratedScienceEditorialOutline,
)
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services

PATH = "/api/v1/curriculum/integrated-science-editorial-outline"
CAPABILITY_PATH = "/api/v1/curriculum/integrated-science-graph-capability"


def test_curriculum_outline_endpoint_is_authenticated_and_author_permissioned() -> None:
    services = cast(Any, disconnected_services())
    try:
        app = create_app(services)
        operation = app.openapi()["paths"][PATH]["get"]
        assert operation["operationId"] == "integrated_science_editorial_outline_get"
        assert operation["x-eom-permission"] == "workflow:start"
        capability_operation = app.openapi()["paths"][CAPABILITY_PATH]["get"]
        assert capability_operation["operationId"] == "integrated_science_graph_capability_get"
        assert capability_operation["x-eom-permission"] == "workflow:start"
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


def test_curriculum_graph_capability_endpoint_returns_query_projection() -> None:
    value = CurriculumGraphCapabilityView(
        outline_sha256=INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
        capability_state="READY",
        graph_grounding_available=True,
        reason="READY",
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        snapshot_sha256="sha256:" + "2" * 64,
        framework_revision_id="curriculumrev_" + "3" * 32,
        unit_count=43,
        closure_count=119,
    )
    request = cast(
        Request,
        SimpleNamespace(
            state=SimpleNamespace(
                request_context=SimpleNamespace(request_id="req_curriculum_capability")
            ),
            app=SimpleNamespace(
                state=SimpleNamespace(
                    services=SimpleNamespace(
                        queries=SimpleNamespace(integrated_science_graph_capability=lambda: value)
                    )
                )
            ),
        ),
    )
    response = integrated_science_graph_capability(request)
    assert response.data == value
