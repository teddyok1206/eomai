"""Actual authenticated HTTP routing with synthetic source/IAM ports, not live acceptance."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.services.exam_similarity_client import (
    CatalogExamSimilarityClient,
    ExamSimilarityClientError,
)
from eom_api.services.exam_similarity_read import ExamSimilarityReadApplicationService
from eom_catalog_contracts.exam_similarity_read import MAX_EXAM_READ_SELECTOR_BYTES
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_customer_support_endpoints import _authentication
from tests.api.test_hwpx_endpoints import FakeAudit
from tests.unit.exam_similarity_read_fixtures import read_case

PATH = "/api/v1/assessment-assemblies/similarity-observation"
PERMISSIONS = frozenset(
    {
        PermissionKey.DELIVERABLE_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        PermissionKey.CONTENT_INTAKE_READ,
    }
)


def authentication():
    return replace(_authentication(), permissions=PERMISSIONS)


@pytest.fixture
def setup():
    selected, expected, _ = read_case()
    services = disconnected_services()
    services.audit = FakeAudit()
    reader = Mock(read=Mock(return_value=expected.result))
    services.exam_similarity_reads = ExamSimilarityReadApplicationService(reader, enabled=True)
    app = create_app(services)

    def authenticated(request: Request):
        value = authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        yield app, services, reader, selected.selection, expected.result
    finally:
        services.engine.dispose()


def test_service_is_fixed_client_default_off_independent_of_reference_query():
    services = disconnected_services()
    try:
        assert type(services.exam_similarity_reads.reader) is CatalogExamSimilarityClient
        assert services.exam_similarity_reads.enabled is False
    finally:
        services.engine.dispose()


def test_actual_http_read_replays_without_job_idempotency_or_commands(setup):
    app, services, reader, selection, result = setup
    services.idempotency = Mock(side_effect=AssertionError("read cannot claim"))
    services.commands = Mock(side_effect=AssertionError("read cannot submit"))
    with TestClient(app, base_url="http://localhost") as client:
        for _ in range(2):
            response = client.post(PATH, json=selection.model_dump(mode="json"))
            assert response.status_code == 200, response.text
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json()["data"] == result.model_dump(mode="json")
        reader.read.assert_called_with(authentication().operator.operator_id, selection)
        assert reader.read.call_count == 2
        operation = app.openapi()["paths"][PATH]["post"]
        assert operation["x-eom-read-only"] is True
        assert operation["x-eom-permission"] == PermissionKey.DELIVERABLE_READ.value
        assert not any(p["name"] == "Idempotency-Key" for p in operation.get("parameters", ()))
    assert not services.idempotency.mock_calls and not services.commands.mock_calls


@pytest.mark.parametrize(
    "field", ("actor_id", "role", "permissions", "vectors", "runtime_bundle", "token")
)
def test_public_input_never_injects_actor_or_execution_payload(setup, field):
    app, _services, reader, selection, _result = setup
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, json=selection.model_dump(mode="json") | {field: "ADMIN"})
        assert response.status_code == 422
    reader.read.assert_not_called()


@pytest.mark.parametrize("permission", tuple(PERMISSIONS))
def test_current_required_permissions_are_checked_before_catalog_dispatch(setup, permission):
    _app, services, reader, selection, _result = setup
    actor = replace(authentication(), permissions=PERMISSIONS - {permission})
    with pytest.raises(ApiError) as error:
        services.exam_similarity_reads.read(actor, selection)
    assert error.value.status == 403
    reader.read.assert_not_called()


def test_formatted_body_cannot_bypass_selector_byte_budget(setup):
    app, _services, reader, selection, _result = setup
    raw = canonical_json_bytes(selection)
    raw += b" " * (MAX_EXAM_READ_SELECTOR_BYTES + 1 - len(raw))
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, content=raw, headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        assert response.json()["error_code"] == "EXAM_OBSERVATION_BUDGET_EXCEEDED"
    reader.read.assert_not_called()


@pytest.mark.parametrize("fault", ("disabled", "operator_password", "session_password"))
def test_current_account_state_is_not_inferred_from_old_manifest(setup, fault):
    _app, services, reader, selection, _result = setup
    actor = authentication()
    if fault == "disabled":
        actor = replace(actor, operator=actor.operator.model_copy(update={"status": "DISABLED"}))
    elif fault == "operator_password":
        actor = replace(
            actor, operator=actor.operator.model_copy(update={"must_change_password": True})
        )
    else:
        actor = replace(actor, password_change_required=True)
    with pytest.raises(ApiError) as error:
        services.exam_similarity_reads.read(actor, selection)
    assert error.value.status == 403
    reader.read.assert_not_called()


@pytest.mark.parametrize(
    "code,status",
    (
        ("SOURCE_ACCESS_DENIED", 403),
        ("SOURCE_REVOKED", 409),
        ("ASSEMBLY_REVISION_NOT_FOUND", 404),
        ("EXAM_OBSERVATION_UNAVAILABLE", 503),
    ),
)
def test_catalog_denial_missing_and_unavailable_are_not_silently_empty(setup, code, status):
    app, _services, reader, selection, _result = setup
    reader.read.side_effect = ExamSimilarityClientError(code)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, json=selection.model_dump(mode="json"))
        assert response.status_code == status
        assert response.json()["error_code"] == code
        assert "data" not in response.json()


def test_disabled_feature_does_not_open_socket_or_change_old_assembly_reads(setup):
    app, services, reader, selection, _result = setup
    services.exam_similarity_reads.enabled = False
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, json=selection.model_dump(mode="json"))
        assert response.status_code == 503
    reader.read.assert_not_called()
