from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from eom_api.app import create_app
from eom_api.routers.curriculum import (
    assessment_occurrence_items,
    curriculum_unit_past_exam_items,
    integrated_science_editorial_outline,
    integrated_science_graph_capability,
)
from eom_api_contracts import AssessmentItemOccurrenceView, CurriculumGraphCapabilityView
from eom_catalog_contracts import (
    INTEGRATED_SCIENCE_EDITORIAL_OUTLINE_SHA256,
    IntegratedScienceEditorialOutline,
)
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services

PATH = "/api/v1/curriculum/integrated-science-editorial-outline"
CAPABILITY_PATH = "/api/v1/curriculum/integrated-science-graph-capability"
EXAM_ITEMS_PATH = "/api/v1/curriculum/assessment-occurrences/items"
UNIT_ITEMS_PATH = "/api/v1/curriculum/integrated-science-units/{curriculum_unit_id}/past-exam-items"


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
        exam_items_operation = app.openapi()["paths"][EXAM_ITEMS_PATH]["get"]
        assert exam_items_operation["operationId"] == "assessment_occurrence_item_list"
        assert exam_items_operation["x-eom-permission"] == "workflow:start"
        unit_items_operation = app.openapi()["paths"][UNIT_ITEMS_PATH]["get"]
        assert unit_items_operation["operationId"] == "curriculum_unit_past_exam_item_list"
        assert unit_items_operation["x-eom-permission"] == "workflow:start"
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


def _past_exam_item() -> AssessmentItemOccurrenceView:
    return AssessmentItemOccurrenceView(
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        placement_node_id="knode_" + "2" * 64,
        occurrence_node_id="knode_" + "3" * 64,
        item_node_id="knode_" + "4" * 64,
        analysis_run_id="analysisrun_" + "5" * 32,
        assessment_occurrence_id="occurrence_" + "6" * 32,
        assessment_occurrence_revision_id="occurrev_" + "7" * 32,
        assessment_occurrence_revision_sha256="sha256:" + "8" * 64,
        occurrence_display_label="2025년 고1 6월 통합과학",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        subject_key="integrated-science",
        item_number=12,
        item_id="item_" + "9" * 32,
        item_revision_id="itemrev_" + "a" * 32,
        curriculum_unit_ids=("currunit_" + "b" * 32,),
        placement_sha256="sha256:" + "c" * 64,
    )


def test_curriculum_item_routes_forward_exact_exam_and_unit_keys() -> None:
    item = _past_exam_item()

    class Queries:
        exam_kwargs: dict[str, object] | None = None
        unit_kwargs: dict[str, object] | None = None

        def assessment_items_by_exam(self, **kwargs: object) -> SimpleNamespace:
            self.exam_kwargs = kwargs
            return SimpleNamespace(data=(item,), next_cursor=None, has_more=False)

        def assessment_items_by_curriculum_unit(self, **kwargs: object) -> SimpleNamespace:
            self.unit_kwargs = kwargs
            return SimpleNamespace(data=(item,), next_cursor=None, has_more=False)

    queries = Queries()
    request = cast(
        Request,
        SimpleNamespace(
            state=SimpleNamespace(request_context=SimpleNamespace(request_id="req_items")),
            app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(queries=queries))),
        ),
    )
    exam = assessment_occurrence_items(
        request,
        administration_year=2025,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        administration_month=6,
        subject_key="integrated-science",
        limit=50,
        cursor=None,
    )
    unit_id = "currunit_" + "b" * 32
    unit = curriculum_unit_past_exam_items(request, unit_id, limit=50, cursor=None)
    assert exam.data == unit.data == (item,)
    assert queries.exam_kwargs == {
        "administration_year": 2025,
        "target_school_level": "HIGH_SCHOOL",
        "target_grade": 1,
        "administration_month": 6,
        "subject_key": "integrated-science",
        "limit": 50,
        "cursor": None,
    }
    assert queries.unit_kwargs == {
        "curriculum_unit_id": unit_id,
        "limit": 50,
        "cursor": None,
    }
