from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.query_adapter import PageResult
from eom_api_contracts.knowledge_analysis import (
    KnowledgeAnalysisBatchRangeView,
    KnowledgeAnalysisBatchView,
)
from eom_catalog_contracts import KnowledgeAnalysisBatchApplicationResult
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import OperatorProjection, PermissionKey, RoleKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import FakeAudit, MemoryIdempotency

OPERATOR_ID = "operator_" + "1" * 32
BATCH_ID = "analysisbatch_" + "2" * 32
RANGE_ID = "analysisrange_" + "3" * 32
DOCUMENT_ID = "edudoc_" + "4" * 32
DOCUMENT_REVISION_ID = "edudocrev_" + "5" * 32
NOW = datetime.now(UTC)


def _authentication(*, admin: bool, age: timedelta = timedelta()) -> AccessAuthentication:
    roles = (RoleKey.ADMIN,) if admin else (RoleKey.VIEWER,)
    permissions = (
        frozenset(PermissionKey) if admin else frozenset({PermissionKey.KNOWLEDGE_ANALYSIS_READ})
    )
    authenticated_at = datetime.now(UTC) - age
    operator = OperatorProjection(
        operator_id=OPERATOR_ID,
        username="batch-admin" if admin else "batch-viewer",
        display_name="Batch Test Operator",
        status="ACTIVE",
        must_change_password=False,
        roles=roles,
        effective_permissions=tuple(sorted(permissions, key=str)),
        resource_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return AccessAuthentication(
        operator=operator,
        session_id="apisession_" + "6" * 32,
        authenticated_at=authenticated_at,
        access_expires_at=datetime.now(UTC) + timedelta(hours=1),
        permissions=permissions,
        password_change_required=False,
    )


def _batch_view() -> KnowledgeAnalysisBatchView:
    return KnowledgeAnalysisBatchView(
        batch_id=BATCH_ID,
        request_sha256="sha256:" + "7" * 64,
        preset_id="execpreset_" + "8" * 32,
        preset_revision_id="execpresetrev_" + "9" * 32,
        preset_sha256="sha256:" + "a" * 64,
        risk_policy_revision_id="analysisriskrev_" + "b" * 32,
        risk_policy_sha256="sha256:" + "c" * 64,
        general_knowledge_mode="AUXILIARY_UNATTRIBUTED",
        review_policy="PREAUTHORIZED_APPROVE_VALIDATED",
        authorized_by_operator_id=OPERATOR_ID,
        authorized_at=NOW,
        state="QUEUED",
        total_range_count=1,
        accepted_range_count=0,
        failed_range_count=0,
        failure_code=None,
        resource_version=1,
        created_at=NOW,
        started_at=None,
        completed_at=None,
        updated_at=NOW,
    )


def _range_view() -> KnowledgeAnalysisBatchRangeView:
    return KnowledgeAnalysisBatchRangeView(
        range_id=RANGE_ID,
        batch_id=BATCH_ID,
        ordinal=0,
        document_id=DOCUMENT_ID,
        document_revision_id=DOCUMENT_REVISION_ID,
        first_physical_page=1,
        last_physical_page=4,
        curriculum_unit_keys=("1-(1)",),
        source_artifact_id="artifact_" + "d" * 32,
        source_artifact_revision_id="rev_" + "e" * 32,
        source_sha256="sha256:" + "f" * 64,
        source_media_type="application/pdf",
        source_schema_ref="eom://schemas/educational-document/pdf-source/1.0",
        analysis_artifact_id="artifact_" + "0" * 32,
        analysis_artifact_revision_id="rev_" + "1" * 32,
        analysis_manifest_sha256="sha256:" + "2" * 64,
        analysis_media_type="application/json",
        analysis_schema_ref=(
            "eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0"
        ),
        rights_artifact_id="artifact_" + "3" * 32,
        rights_artifact_revision_id="rev_" + "4" * 32,
        rights_attestation_sha256="sha256:" + "5" * 64,
        rights_media_type="application/json",
        rights_schema_ref="eom://schemas/educational-document/rights-attestation/1.0",
        execution_mode="EXECUTE",
        predecessor_analysis_run_id=None,
        reuse_accepted_analysis_run_id=None,
        analysis_run_id=None,
        state="PENDING",
        submission_attempts=0,
        error_code=None,
        resource_version=1,
        created_at=NOW,
        submitted_at=None,
        completed_at=None,
        updated_at=NOW,
    )


class FakeCatalogApplication:
    def __init__(self) -> None:
        self.commands: list[object] = []

    def create_knowledge_analysis_batch(
        self, command: object
    ) -> KnowledgeAnalysisBatchApplicationResult:
        self.commands.append(command)
        return KnowledgeAnalysisBatchApplicationResult(
            batch_id=BATCH_ID,
            state="QUEUED",
            resource_version=1,
            total_range_count=1,
            accepted_range_count=0,
            failed_range_count=0,
        )


class FakeQueries:
    @staticmethod
    def list_knowledge_analysis_batches(**_values: Any) -> PageResult[KnowledgeAnalysisBatchView]:
        return PageResult((_batch_view(),), None, False)

    @staticmethod
    def knowledge_analysis_batch(batch_id: str) -> KnowledgeAnalysisBatchView:
        assert batch_id == BATCH_ID
        return _batch_view()

    @staticmethod
    def knowledge_analysis_batch_ranges(
        batch_id: str,
        **_values: Any,
    ) -> PageResult[KnowledgeAnalysisBatchRangeView]:
        assert batch_id == BATCH_ID
        return PageResult((_range_view(),), None, False)


def _client(
    *,
    admin: bool,
    age: timedelta = timedelta(),
) -> tuple[TestClient, Any]:
    services = disconnected_services()
    services.catalog_application = FakeCatalogApplication()  # type: ignore[assignment]
    services.queries = FakeQueries()  # type: ignore[assignment]
    services.idempotency = MemoryIdempotency()  # type: ignore[assignment]
    services.audit = FakeAudit()  # type: ignore[assignment]
    app = create_app(services)

    def authenticated(request: Request) -> AccessAuthentication:
        value = _authentication(admin=admin, age=age)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services


def _request_body() -> dict[str, object]:
    return {
        "preset_key": "knowledge-analysis",
        "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
        "risk_policy_revision_id": "analysisriskrev_" + "b" * 32,
        "review_policy": "PREAUTHORIZED_APPROVE_VALIDATED",
        "ranges": [
            {
                "ordinal": 0,
                "source": {
                    "source_kind": "DOCUMENT_REVISION",
                    "source_class": "TEXTBOOK",
                    "document_revision_id": DOCUMENT_REVISION_ID,
                    "first_physical_page": 1,
                    "last_physical_page": 4,
                    "curriculum_unit_keys": ["1-(1)"],
                },
                "execution": {
                    "mode": "EXECUTE",
                    "predecessor_analysis_run_id": None,
                },
            }
        ],
    }


def test_fresh_admin_authorizes_one_pointer_only_batch_and_replay_is_idempotent() -> None:
    client, services = _client(admin=True)
    try:
        with client:
            first = client.post(
                "/api/v1/knowledge-analysis-batches",
                headers={"Idempotency-Key": "knowledge-analysis-batch-api-0001"},
                json=_request_body(),
            )
            replay = client.post(
                "/api/v1/knowledge-analysis-batches",
                headers={"Idempotency-Key": "knowledge-analysis-batch-api-0001"},
                json=_request_body(),
            )
        assert first.status_code == replay.status_code == 202
        assert first.json()["data"] == replay.json()["data"]
        assert first.json()["data"]["resource_id"] == BATCH_ID
        assert len(services.catalog_application.commands) == 1
        command = services.catalog_application.commands[0]
        serialized = command.model_dump(mode="json")
        assert serialized["request"]["ranges"][0]["source"]["document_revision_id"] == (
            DOCUMENT_REVISION_ID
        )
        assert not ({"session_id", "token", "password"} & set(serialized))
    finally:
        services.engine.dispose()


def test_batch_creation_requires_fresh_admin_but_reads_do_not_require_fresh_auth() -> None:
    stale_admin, stale_services = _client(admin=True, age=timedelta(minutes=20))
    try:
        with stale_admin:
            denied = stale_admin.post(
                "/api/v1/knowledge-analysis-batches",
                headers={"Idempotency-Key": "knowledge-analysis-batch-api-0002"},
                json=_request_body(),
            )
            batch = stale_admin.get(f"/api/v1/knowledge-analysis-batches/{BATCH_ID}")
            ranges = stale_admin.get(f"/api/v1/knowledge-analysis-batches/{BATCH_ID}/ranges")
        assert denied.status_code == 403
        assert denied.json()["error_code"] == "AUTH_REAUTHENTICATION_REQUIRED"
        assert batch.status_code == ranges.status_code == 200
        assert ranges.json()["data"][0]["range_id"] == RANGE_ID
    finally:
        stale_services.engine.dispose()

    viewer, viewer_services = _client(admin=False)
    try:
        with viewer:
            denied = viewer.get(f"/api/v1/knowledge-analysis-batches/{BATCH_ID}")
        assert denied.status_code == 403
        assert denied.json()["error_code"] == "PERMISSION_DENIED"
    finally:
        viewer_services.engine.dispose()


def test_batch_creation_rejects_a_non_textbook_document_source() -> None:
    client, services = _client(admin=True)
    body = _request_body()
    ranges = body["ranges"]
    assert isinstance(ranges, list)
    source = ranges[0]["source"]
    assert isinstance(source, dict)
    source["source_class"] = "CURRICULUM"
    try:
        with client:
            denied = client.post(
                "/api/v1/knowledge-analysis-batches",
                headers={"Idempotency-Key": "knowledge-analysis-batch-api-0003"},
                json=body,
            )
        assert denied.status_code == 422
        assert len(services.catalog_application.commands) == 0
    finally:
        services.engine.dispose()


def test_batch_creation_rejects_a_page_outside_the_catalog_contract() -> None:
    client, services = _client(admin=True)
    body = _request_body()
    ranges = body["ranges"]
    assert isinstance(ranges, list)
    source = ranges[0]["source"]
    assert isinstance(source, dict)
    source["last_physical_page"] = 10001
    try:
        with client:
            denied = client.post(
                "/api/v1/knowledge-analysis-batches",
                headers={"Idempotency-Key": "knowledge-analysis-batch-api-0004"},
                json=body,
            )
        assert denied.status_code == 422
        assert len(services.catalog_application.commands) == 0
    finally:
        services.engine.dispose()
