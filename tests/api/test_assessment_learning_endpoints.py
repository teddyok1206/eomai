from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.query_adapter import PageResult
from eom_api_contracts.assessment_learning import (
    AssessmentLearningBatchView,
    AssessmentLearningExamView,
    AssessmentLearningItemCounts,
    AssessmentLearningWorkUnitCounts,
)
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import OperatorProjection, PermissionKey, RoleKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services

NOW = datetime.now(UTC)
BATCH_ID = "legacybatch_" + "1" * 32


def _authentication(*, admin: bool) -> AccessAuthentication:
    permissions = (
        frozenset(PermissionKey) if admin else frozenset({PermissionKey.KNOWLEDGE_ANALYSIS_READ})
    )
    operator = OperatorProjection(
        operator_id="operator_" + "2" * 32,
        username="learning-admin" if admin else "learning-viewer",
        display_name="Learning Test Operator",
        status="ACTIVE",
        must_change_password=False,
        roles=(RoleKey.ADMIN,) if admin else (RoleKey.VIEWER,),
        effective_permissions=tuple(sorted(permissions, key=str)),
        resource_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return AccessAuthentication(
        operator=operator,
        session_id="apisession_" + "3" * 32,
        authenticated_at=NOW - timedelta(hours=1),
        access_expires_at=NOW + timedelta(hours=1),
        permissions=permissions,
        password_change_required=False,
    )


def _work_units() -> AssessmentLearningWorkUnitCounts:
    return AssessmentLearningWorkUnitCounts(
        pending=107,
        claimed=0,
        submitted=0,
        awaiting_review=0,
        accepted=1,
        failed=0,
        cancelled=0,
    )


def _items() -> AssessmentLearningItemCounts:
    return AssessmentLearningItemCounts(
        expected=520,
        accepted=5,
        promoted=2,
        analysis_active=1,
        analysis_accepted=1,
        analysis_failed=0,
        graph_published=0,
    )


def _batch() -> AssessmentLearningBatchView:
    return AssessmentLearningBatchView(
        extraction_batch_id=BATCH_ID,
        inventory_id="legacyinventory_" + "4" * 32,
        inventory_sha256="sha256:" + "5" * 64,
        state="RUNNING",
        exam_count=25,
        total_work_unit_count=108,
        image_required_work_unit_count=108,
        work_units=_work_units(),
        items=_items(),
        current_graph_snapshot_revision_id="graphrev_" + "6" * 32,
        resource_version=2,
        created_at=NOW,
        started_at=NOW,
        completed_at=None,
        updated_at=NOW,
    )


def _exam() -> AssessmentLearningExamView:
    return AssessmentLearningExamView(
        extraction_batch_id=BATCH_ID,
        assessment_occurrence_id="occurrence_" + "7" * 32,
        assessment_occurrence_revision_id="occurrev_" + "8" * 32,
        assessment_occurrence_revision_sha256="sha256:" + "9" * 64,
        assessment_source_bundle_revision_id="assessbundlerev_" + "a" * 32,
        display_label="2025년 고1 6월 통합과학",
        administration_year=2025,
        administration_month=6,
        target_school_level="HIGH_SCHOOL",
        target_grade=1,
        subject_key="integrated-science",
        total_work_unit_count=4,
        image_required_work_unit_count=4,
        work_units=AssessmentLearningWorkUnitCounts(
            pending=3,
            claimed=0,
            submitted=0,
            awaiting_review=0,
            accepted=1,
            failed=0,
            cancelled=0,
        ),
        items=AssessmentLearningItemCounts(
            expected=20,
            accepted=5,
            promoted=2,
            analysis_active=1,
            analysis_accepted=1,
            analysis_failed=0,
            graph_published=0,
        ),
    )


class FakeQueries:
    list_values: dict[str, object] | None = None
    exam_values: tuple[str, dict[str, object]] | None = None

    def list_assessment_learning_batches(
        self, **values: Any
    ) -> PageResult[AssessmentLearningBatchView]:
        self.list_values = values
        return PageResult((_batch(),), None, False)

    def assessment_learning_exams(
        self, batch_id: str, **values: Any
    ) -> PageResult[AssessmentLearningExamView]:
        self.exam_values = (batch_id, values)
        return PageResult((_exam(),), None, False)


def _client(*, admin: bool) -> tuple[TestClient, Any, FakeQueries]:
    services = disconnected_services()
    queries = FakeQueries()
    services.queries = queries  # type: ignore[assignment]
    app = create_app(services)

    def authenticated(request: Request) -> AccessAuthentication:
        value = _authentication(admin=admin)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services, queries


def test_admin_reads_durable_batch_and_exam_progress_without_fresh_auth() -> None:
    client, services, queries = _client(admin=True)
    try:
        with client:
            batches = client.get(
                "/api/v1/assessment-learning-batches",
                params={"limit": 10, "state": "RUNNING"},
            )
            exams = client.get(f"/api/v1/assessment-learning-batches/{BATCH_ID}/exams")
        assert batches.status_code == exams.status_code == 200
        assert batches.json()["data"][0]["image_observation_mode"] == "REQUIRED"
        assert batches.json()["data"][0]["text_evidence_mode"] == ("AUXILIARY_WHEN_AVAILABLE")
        assert exams.json()["data"][0]["display_label"] == "2025년 고1 6월 통합과학"
        assert queries.list_values == {"limit": 10, "cursor": None, "state": "RUNNING"}
        assert queries.exam_values == (BATCH_ID, {"limit": 100, "cursor": None})
    finally:
        services.engine.dispose()


def test_non_admin_cannot_read_assessment_learning_progress() -> None:
    client, services, _queries = _client(admin=False)
    try:
        with client:
            response = client.get("/api/v1/assessment-learning-batches")
        assert response.status_code == 403
        assert response.json()["error_code"] == "PERMISSION_DENIED"
    finally:
        services.engine.dispose()
