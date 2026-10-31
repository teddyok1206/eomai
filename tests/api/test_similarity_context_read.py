"""Actual API routing with synthetic login/Catalog source; not live operator acceptance."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.services.similarity_context_client import SimilarityContextClientError
from eom_api.services.similarity_context_read import (
    MAX_PUBLIC_SIMILARITY_SELECTOR_BYTES,
    SimilarityContextReadApplicationService,
)
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_customer_support_endpoints import _authentication
from tests.api.test_hwpx_endpoints import FakeAudit
from tests.unit.test_similarity_read_contract import pair

PATH = "/api/v1/knowledge/inference-transfer/similarity-context"
PERMISSIONS = frozenset(
    {
        PermissionKey.WORKFLOW_READ,
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
    request, reply = pair()
    services = disconnected_services()
    services.audit = FakeAudit()
    reader = Mock()
    reader.read.return_value = reply.result
    services.similarity_context_reads = SimilarityContextReadApplicationService(reader)
    app = create_app(services)

    def authenticated(request: Request):
        value = authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        yield app, services, reader, request.selection, reply.result
    finally:
        services.engine.dispose()


def test_composed_service_uses_only_fixed_catalog_client():
    from eom_api.services.similarity_context_client import CatalogSimilarityContextClient

    services = disconnected_services()
    try:
        assert type(services.similarity_context_reads) is SimilarityContextReadApplicationService
        assert type(services.similarity_context_reads.reader) is CatalogSimilarityContextClient
    finally:
        services.engine.dispose()


def test_authenticated_read_uses_actual_actor_and_reauthorizes_repeat_without_commands(setup):
    app, services, reader, selector, expected = setup
    services.idempotency = Mock(side_effect=AssertionError("readonly must not claim"))
    services.commands = Mock(side_effect=AssertionError("must not submit workflow"))
    with TestClient(app, base_url="http://localhost") as client:
        for _ in range(2):
            response = client.post(PATH, json=selector.model_dump(mode="json"))
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json()["data"] == expected.model_dump(mode="json")
        reader.read.assert_called_with(authentication().operator.operator_id, selector)
        assert reader.read.call_count == 2
        operation = app.openapi()["paths"][PATH]["post"]
        assert operation["x-eom-read-only"] is True
        assert operation["x-eom-permission"] == PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value
        assert set(operation["x-eom-additional-permissions"]) == {
            permission.value
            for permission in PERMISSIONS
            if permission != PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE
        }
        assert not any(
            param["name"] == "Idempotency-Key" for param in operation.get("parameters", ())
        )
        assert not services.idempotency.mock_calls and not services.commands.mock_calls


def test_missing_login_denies_before_any_catalog_read(setup):
    app, _services, reader, selector, _expected = setup
    app.dependency_overrides.clear()
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post(PATH, json=selector.model_dump(mode="json")).status_code == 401
    reader.read.assert_not_called()


@pytest.mark.parametrize("registered", [False, True])
def test_public_context_http_uses_exact_selection_and_current_actor_without_new_work(
    setup, registered
):
    from tests.unit.test_public_solution_similarity_read_boundary import pair as public_pair
    from tests.unit.test_registered_public_similarity_read_boundary import pair as registered_pair

    app, _services, reader, _selector, _expected = setup
    request, reply = registered_pair() if registered else public_pair()
    reader.read_public.return_value = reply.result
    body = request.selection.model_dump(mode="json") | {
        "schema_version": "system-rag-similarity-read-selection/3.0",
    }
    with TestClient(app, base_url="http://localhost") as client:
        for _ in range(2):
            response = client.post(PATH, json=body)
            assert response.status_code == 200
            assert response.json()["data"] == reply.result.model_dump(mode="json")
            assert response.headers["Cache-Control"] == "no-store"
    assert reader.read_public.call_count == 2
    reader.read_public.assert_called_with(authentication().operator.operator_id, request.selection)
    reader.read.assert_not_called()
    reader.read_v2.assert_not_called()


@pytest.mark.parametrize("field", ("actor_id", "path", "vectors", "source_ids"))
def test_public_context_http_rejects_untrusted_authority_and_values(setup, field):
    from tests.unit.test_public_solution_similarity_read_boundary import pair as public_pair

    app, _services, reader, _selector, _expected = setup
    request, _reply = public_pair()
    body = request.selection.model_dump(mode="json") | {
        "schema_version": "system-rag-similarity-read-selection/3.0",
        field: "untrusted",
    }
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, json=body)
        assert response.status_code == 422
    reader.read_public.assert_not_called()


@pytest.mark.parametrize(
    "field",
    ("actor_id", "role", "permissions", "token", "runtime_bundle", "workflow_request", "vectors"),
)
def test_public_request_cannot_supply_authority_or_large_execution_values(setup, field):
    app, _services, reader, selector, _expected = setup
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, json=selector.model_dump(mode="json") | {field: "ADMIN"})
        assert response.status_code == 422
    reader.read.assert_not_called()


def test_whitespace_cannot_bypass_the_small_public_selector_body_budget(setup):
    app, _services, reader, selector, _expected = setup
    raw = canonical_json_bytes(selector)
    raw += b" " * (MAX_PUBLIC_SIMILARITY_SELECTOR_BYTES + 1 - len(raw))
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, content=raw, headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        assert response.json()["error_code"] == "SIMILARITY_CONTEXT_BUDGET_EXCEEDED"
    reader.read.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    (
        ("workflow_id", "latest"),
        ("workflow_id", 123),
        ("workflow_request_sha256", "not-a-hash"),
        ("context_request_sha256", True),
    ),
)
def test_malformed_canonical_selector_becomes_safe_http_input_error(setup, field, value):
    app, _services, reader, selector, _expected = setup
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, json=selector.model_dump(mode="json") | {field: value})
        assert response.status_code == 422
        assert response.json()["error_code"] == "API_REQUEST_INVALID"
        issues = response.json()["errors"]
        assert issues and all(
            issue["detail"] == "The supplied value does not satisfy the request schema."
            for issue in issues
        )
    reader.read.assert_not_called()


@pytest.mark.parametrize("permission", tuple(PERMISSIONS))
def test_every_required_read_permission_is_checked_before_dispatch(setup, permission):
    _app, services, reader, selector, _expected = setup
    with pytest.raises(ApiError) as caught:
        services.similarity_context_reads.read(
            replace(authentication(), permissions=PERMISSIONS - {permission}), selector
        )
    assert caught.value.status == 403
    reader.read.assert_not_called()


@pytest.mark.parametrize("fault", ("disabled", "operator_password", "session_password"))
def test_current_account_and_forced_password_state_are_not_inferred_from_old_query(setup, fault):
    _app, services, reader, selector, _expected = setup
    auth = authentication()
    if fault == "disabled":
        auth = replace(auth, operator=auth.operator.model_copy(update={"status": "DISABLED"}))
    elif fault == "operator_password":
        auth = replace(
            auth, operator=auth.operator.model_copy(update={"must_change_password": True})
        )
    else:
        auth = replace(auth, password_change_required=True)
    with pytest.raises(ApiError) as caught:
        services.similarity_context_reads.read(auth, selector)
    assert caught.value.status == 403
    reader.read.assert_not_called()


@pytest.mark.parametrize(
    "code,status",
    (
        ("SOURCE_ACCESS_DENIED", 403),
        ("SOURCE_REVOKED", 409),
        ("SOURCE_HASH_MISMATCH", 409),
        ("INDEX_POINTER_INVALID", 409),
        ("QUERY_RESULT_INVALID", 409),
        ("AUTHORITY_UNAVAILABLE", 503),
        ("SIMILARITY_CONTEXT_REQUEST_INVALID", 422),
        ("SIMILARITY_CONTEXT_BUDGET_EXCEEDED", 422),
        ("SIMILARITY_CONTEXT_UNAVAILABLE", 503),
        ("PRIVATE_ERROR_TEXT", 503),
    ),
)
def test_owner_errors_have_closed_http_meaning_without_partial_result(setup, code, status):
    app, _services, reader, selector, _expected = setup
    reader.read.side_effect = SimilarityContextClientError(code)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, json=selector.model_dump(mode="json"))
        assert response.status_code == status
        assert response.json()["error_code"] == (
            "SIMILARITY_CONTEXT_UNAVAILABLE" if code == "PRIVATE_ERROR_TEXT" else code
        )
        assert "data" not in response.json()
        assert "PRIVATE_ERROR_TEXT" not in response.text


@pytest.mark.parametrize("fault", ("context_pin", "extra_result", "partial_failure"))
def test_changed_or_invalid_result_cannot_become_success(setup, fault):
    app, _services, reader, selector, expected = setup
    if fault == "context_pin":
        selector = selector.model_copy(update={"context_request_sha256": "sha256:" + "f" * 64})
    elif fault == "extra_result":
        reader.read.return_value = expected.model_copy(update={"actor_id": "ADMIN"})
    else:
        body = expected.model_dump(mode="json") | {
            "status": "FAILED",
            "population": None,
            "query_execution": None,
            "graph_evidence": None,
            "candidates": [],
            "error_code": "SOURCE_REVOKED",
            "limitations": ["REFERENCE_ANCHOR_NOT_PRIVATE_INTENT"],
        }
        body["context_sha256"] = content_sha256(
            {key: value for key, value in body.items() if key != "context_sha256"}
        )
        reader.read.return_value = parse_similarity_context(body)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(PATH, json=selector.model_dump(mode="json"))
        assert response.status_code == (409 if fault == "partial_failure" else 503)
        assert "data" not in response.json()
