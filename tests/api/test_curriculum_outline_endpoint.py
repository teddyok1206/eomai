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
from eom_api.routers.item_bank import item_bank_entries, production_item_candidates
from eom_api.services.query_adapter import _production_content_profile
from eom_api_contracts import (
    AssessmentItemOccurrenceViewV2,
    CurriculumGraphCapabilityView,
    ItemBankCurriculumUnitView,
    ItemBankEntryView,
)
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
ITEM_BANK_PATH = "/api/v1/item-bank/entries"
PRODUCTION_CANDIDATES_PATH = "/api/v1/item-bank/production-candidates"
MOCK_EXAM_PLAN_PATH = "/api/v1/assessment-assemblies/plan"
MOCK_EXAM_PLANNED_CREATE_PATH = "/api/v1/assessment-assemblies/planned"
MOCK_EXAM_GET_PATH = "/api/v1/assessment-assemblies/{assembly_revision_id}"


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
        item_bank_operation = app.openapi()["paths"][ITEM_BANK_PATH]["get"]
        assert item_bank_operation["operationId"] == "item_bank_entry_list"
        assert item_bank_operation["x-eom-permission"] == "item:read"
        production_operation = app.openapi()["paths"][PRODUCTION_CANDIDATES_PATH]["get"]
        assert production_operation["operationId"] == "production_item_candidate_list"
        assert production_operation["x-eom-permission"] == "item:read"
        content_profile_parameter = next(
            row for row in production_operation["parameters"] if row["name"] == "content_profile"
        )
        assert set(content_profile_parameter["schema"]["anyOf"][0]["enum"]) == {
            "LEGACY_ITEM_CONTENT_V1",
            "CONTENT_TEAM_ITEM_CONTENT_V2",
            "CONTENT_TEAM_ITEM_CONTENT_V3",
            "UNSUPPORTED",
        }
        candidate_response_ref = production_operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        candidate_response = app.openapi()["components"]["schemas"][
            candidate_response_ref.rsplit("/", 1)[-1]
        ]
        candidate_items = candidate_response["properties"]["data"]["items"]
        assert candidate_items["discriminator"]["mapping"] == {
            "production-item-candidate-view/1.0": (
                "#/components/schemas/ProductionItemCandidateView"
            ),
            "production-item-candidate-view/2.0": (
                "#/components/schemas/ProductionItemCandidateViewV2"
            ),
        }
        plan_operation = app.openapi()["paths"][MOCK_EXAM_PLAN_PATH]["get"]
        assert plan_operation["operationId"] == "mock_exam_assembly_plan_preview"
        assert plan_operation["x-eom-permission"] == "deliverable:read"
        openapi = app.openapi()
        components = openapi["components"]["schemas"]
        assert set(components["MockExamAssemblyPlanView"]["discriminator"]["mapping"]) == {
            "mock-exam-assembly-plan/1.0",
            "mock-exam-assembly-plan/2.0",
        }
        assembly_operation = openapi["paths"][MOCK_EXAM_GET_PATH]["get"]
        assert assembly_operation["operationId"] == "mock_exam_assembly_get"
        assert set(components["MockExamAssemblyViewContract"]["discriminator"]["mapping"]) == {
            "mock-exam-assembly-manifest/1.0",
            "mock-exam-assembly-manifest/2.0",
            "mock-exam-assembly-manifest/3.0",
        }
        create_operation = app.openapi()["paths"][MOCK_EXAM_PLANNED_CREATE_PATH]["post"]
        assert create_operation["operationId"] == "planned_mock_exam_assembly_create"
        assert create_operation["x-eom-permission"] == "deliverable:create"
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


def _past_exam_item() -> AssessmentItemOccurrenceViewV2:
    return AssessmentItemOccurrenceViewV2(
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        placement_node_id="knode_" + "2" * 32,
        occurrence_node_id="knode_" + "3" * 32,
        item_node_id="knode_" + "4" * 32,
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
        assessment_occurrence_revision_id="occurrev_" + "7" * 32,
        item_number=12,
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
        "assessment_occurrence_revision_id": "occurrev_" + "7" * 32,
        "item_number": 12,
        "limit": 50,
        "cursor": None,
    }
    assert queries.unit_kwargs == {
        "curriculum_unit_id": unit_id,
        "limit": 50,
        "cursor": None,
    }


def test_item_bank_route_forwards_optional_graph_and_exam_filters() -> None:
    entry = ItemBankEntryView(
        graph_snapshot_revision_id="graphrev_" + "1" * 32,
        snapshot_sha256="sha256:" + "2" * 64,
        analysis_run_id="analysisrun_" + "3" * 32,
        graph_placement_node_id="knode_" + "d" * 32,
        assessment_occurrence_id="occurrence_" + "4" * 32,
        assessment_occurrence_revision_id="occurrev_" + "5" * 32,
        assessment_occurrence_revision_sha256="sha256:" + "6" * 64,
        occurrence_display_label="2025년 고1 6월 통합과학",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        subject_key="integrated-science",
        item_number=12,
        item_id="item_" + "7" * 32,
        item_revision_id="itemrev_" + "8" * 32,
        item_revision_state="APPROVED",
        item_type_key="multiple-choice",
        difficulty_band=None,
        item_manifest_sha256="sha256:" + "9" * 64,
        curriculum_units=(
            ItemBankCurriculumUnitView(
                curriculum_unit_id="currunit_" + "a" * 32,
                unit_key="eom.is.middle.3-3",
                unit_code="3-(3)",
                label="중력장 내의 운동",
                unit_level="MINOR",
                parent_unit_id="currunit_" + "b" * 32,
            ),
        ),
        placement_sha256="sha256:" + "c" * 64,
    )

    class Queries:
        kwargs: dict[str, object] | None = None

        def item_bank_entries(self, **kwargs: object) -> SimpleNamespace:
            self.kwargs = kwargs
            return SimpleNamespace(data=(entry,), next_cursor="next", has_more=True)

    queries = Queries()
    request = cast(
        Request,
        SimpleNamespace(
            state=SimpleNamespace(request_context=SimpleNamespace(request_id="req_item_bank")),
            app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(queries=queries))),
        ),
    )
    response = item_bank_entries(
        request,
        curriculum_unit_key="eom.is.middle.3-3",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        assessment_occurrence_revision_id="occurrev_" + "5" * 32,
        item_number=12,
        item_type_key=None,
        difficulty_band=None,
        limit=50,
        cursor=None,
    )
    assert response.data == (entry,)
    assert response.page.has_more is True
    assert queries.kwargs == {
        "curriculum_unit_key": "eom.is.middle.3-3",
        "administration_year": 2025,
        "administration_month": 6,
        "target_school_level": "HIGH_SCHOOL",
        "target_grade": 1,
        "assessment_occurrence_revision_id": "occurrev_" + "5" * 32,
        "item_number": 12,
        "item_type_key": None,
        "difficulty_band": None,
        "limit": 50,
        "cursor": None,
    }


def test_production_candidate_route_forwards_server_owned_capability_filters() -> None:
    class Queries:
        kwargs: dict[str, object] | None = None

        def production_item_candidates(self, **kwargs: object) -> SimpleNamespace:
            self.kwargs = kwargs
            return SimpleNamespace(data=(), next_cursor=None, has_more=False)

    queries = Queries()
    request = cast(
        Request,
        SimpleNamespace(
            state=SimpleNamespace(request_context=SimpleNamespace(request_id="req_candidates")),
            app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(queries=queries))),
        ),
    )
    response = production_item_candidates(
        request,
        curriculum_unit_key="eom.is.middle.3-3",
        source_class="APPROVED_ITEM",
        content_profile="CONTENT_TEAM_ITEM_CONTENT_V3",
        eligible=True,
        item_type_key="multiple-choice",
        difficulty_band="MEDIUM",
        limit=25,
        cursor=None,
    )
    assert response.data == ()
    assert queries.kwargs == {
        "curriculum_unit_key": "eom.is.middle.3-3",
        "source_class": "APPROVED_ITEM",
        "content_profile": "CONTENT_TEAM_ITEM_CONTENT_V3",
        "eligible": True,
        "item_type_key": "multiple-choice",
        "difficulty_band": "MEDIUM",
        "limit": 25,
        "cursor": None,
    }


def test_production_candidate_query_classifies_v3_only_by_the_exact_pointer_family() -> None:
    assert (
        _production_content_profile("application/json", "eom.assessment.item-content/3.0")
        == "CONTENT_TEAM_ITEM_CONTENT_V3"
    )
    assert (
        _production_content_profile(
            "application/json", "eom://schemas/item-registry/assessment-item-content-v3"
        )
        == "CONTENT_TEAM_ITEM_CONTENT_V3"
    )
    assert (
        _production_content_profile("application/json", "eom.assessment.item-content/2.0")
        == "CONTENT_TEAM_ITEM_CONTENT_V2"
    )
    assert _production_content_profile("text/plain", "eom.assessment.item-content/3.0") == (
        "UNSUPPORTED"
    )
