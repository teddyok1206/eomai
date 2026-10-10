"""Fake-principal API metadata checks, not actual login or live corpus acceptance."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.services.inference_transfer_metadata import (
    InferenceTransferMetadataApplicationService,
    InferenceTransferMetadataReadError,
)
from eom_catalog_contracts.inference_transfer_metadata import MAX_METADATA_FRAME_BYTES
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_customer_support_endpoints import _authentication
from tests.api.test_hwpx_endpoints import FakeAudit
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_metadata_fixtures import metadata_request, metadata_result

PATH = "/api/v1/knowledge/inference-transfer/metadata"
PERMISSIONS = frozenset(
    {
        PermissionKey.ITEM_READ,
        PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        PermissionKey.KNOWLEDGE_ANALYSIS_READ,
        PermissionKey.CONTENT_INTAKE_READ,
    }
)


def authentication():
    return replace(_authentication(), permissions=PERMISSIONS)


def test_authenticated_read_only_route_uses_actual_principal_and_has_no_idempotency():
    reader = Mock()
    reader.resolve.return_value = metadata_result()
    services = disconnected_services()
    services.audit = FakeAudit()
    services.inference_transfer_metadata = InferenceTransferMetadataApplicationService(reader)
    app = create_app(services)

    def authenticated(request: Request):
        value = authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            first = client.post(PATH, json=metadata_request().model_dump(mode="json"))
            second = client.post(PATH, json=metadata_request().model_dump(mode="json"))
            assert first.status_code == second.status_code == 200
            assert first.json()["data"] == metadata_result().model_dump(mode="json")
            assert reader.resolve.call_count == 2
            reader.resolve.assert_called_with(
                authentication().operator.operator_id, metadata_request()
            )
            operation = app.openapi()["paths"][PATH]["post"]
            assert operation["x-eom-read-only"] is True
            assert operation["x-eom-permission"] == PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE.value
            assert not any(
                param["name"] == "Idempotency-Key" for param in operation.get("parameters", ())
            )
    finally:
        services.engine.dispose()


def test_missing_bearer_fails_before_catalog():
    services = disconnected_services()
    reader = Mock()
    services.inference_transfer_metadata = InferenceTransferMetadataApplicationService(reader)
    try:
        with TestClient(create_app(services), base_url="http://localhost") as client:
            assert (
                client.post(PATH, json=metadata_request().model_dump(mode="json")).status_code
                == 401
            )
            reader.resolve.assert_not_called()
    finally:
        services.engine.dispose()


def test_raw_http_body_budget_cannot_be_bypassed_by_json_whitespace():
    services = disconnected_services()
    services.audit = FakeAudit()
    reader = Mock()
    services.inference_transfer_metadata = InferenceTransferMetadataApplicationService(reader)
    app = create_app(services)

    def authenticated(request: Request):
        value = authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    raw = canonical_json_bytes(metadata_request().model_dump(mode="json"))
    raw += b" " * (MAX_METADATA_FRAME_BYTES + 1 - len(raw))
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(PATH, content=raw, headers={"Content-Type": "application/json"})
            assert response.status_code == 422
            assert response.json()["error_code"] == "INFERENCE_TRANSFER_METADATA_BUDGET_EXCEEDED"
            reader.resolve.assert_not_called()
    finally:
        services.engine.dispose()


@pytest.mark.parametrize("field", ["actor_id", "permissions", "role", "preset_id"])
def test_client_supplied_authority_rejected_by_route(field):
    services = disconnected_services()
    services.audit = FakeAudit()
    reader = Mock()
    services.inference_transfer_metadata = InferenceTransferMetadataApplicationService(reader)
    app = create_app(services)

    def authenticated(request: Request):
        value = authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            assert (
                client.post(
                    PATH, json=metadata_request().model_dump(mode="json") | {field: "ADMIN"}
                ).status_code
                == 422
            )
            reader.resolve.assert_not_called()
    finally:
        services.engine.dispose()


@pytest.mark.parametrize("permission", tuple(PERMISSIONS))
def test_source_permission_missing_rejected_before_dispatch(permission):
    reader = Mock()
    with pytest.raises(ApiError) as error:
        InferenceTransferMetadataApplicationService(reader).resolve(
            replace(authentication(), permissions=PERMISSIONS - {permission}), metadata_request()
        )
    assert error.value.status == 403
    reader.resolve.assert_not_called()


@pytest.mark.parametrize("change", ["disabled", "operator_password", "session_password"])
def test_current_operator_and_session_eligibility(change):
    auth = authentication()
    if change == "disabled":
        auth = replace(auth, operator=auth.operator.model_copy(update={"status": "DISABLED"}))
    elif change == "operator_password":
        auth = replace(
            auth, operator=auth.operator.model_copy(update={"must_change_password": True})
        )
    else:
        auth = replace(auth, password_change_required=True)
    reader = Mock()
    with pytest.raises(ApiError) as error:
        InferenceTransferMetadataApplicationService(reader).resolve(auth, metadata_request())
    assert error.value.status == 403
    reader.resolve.assert_not_called()


@pytest.mark.parametrize(
    "code,status",
    [
        ("INFERENCE_TRANSFER_FORBIDDEN", 403),
        ("INFERENCE_TRANSFER_METADATA_NOT_FOUND", 404),
        ("INFERENCE_TRANSFER_METADATA_PIN_MISMATCH", 409),
        ("INFERENCE_TRANSFER_METADATA_POLICY_INVALID", 409),
        ("INFERENCE_TRANSFER_METADATA_REQUEST_INVALID", 422),
        ("INFERENCE_TRANSFER_METADATA_BUDGET_EXCEEDED", 422),
        ("INTERNAL_SECRET_CODE", 503),
    ],
)
def test_port_errors_have_safe_stable_http_meaning(code, status):
    reader = Mock()
    reader.resolve.side_effect = InferenceTransferMetadataReadError(code)
    with pytest.raises(ApiError) as error:
        InferenceTransferMetadataApplicationService(reader).resolve(
            authentication(), metadata_request()
        )
    assert error.value.status == status
    assert error.value.error_code == (
        code if code != "INTERNAL_SECRET_CODE" else "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"
    )


def test_foreign_hash_valid_reply_is_rejected_not_rebound():
    reader = Mock()
    reader.resolve.return_value = metadata_result(snapshot_sha256=sha("1"))
    with pytest.raises(ApiError) as error:
        InferenceTransferMetadataApplicationService(reader).resolve(
            authentication(), metadata_request()
        )
    assert (
        error.value.status == 503
        and error.value.error_code == "INFERENCE_TRANSFER_METADATA_REPLY_INVALID"
    )


def test_stale_model_copy_is_revalidated_before_dispatch():
    reader = Mock()
    with pytest.raises(ApiError) as error:
        InferenceTransferMetadataApplicationService(reader).resolve(
            authentication(),
            metadata_request().model_copy(update={"expected_snapshot_sha256": sha("1")}),
        )
    assert error.value.status == 422
    reader.resolve.assert_not_called()
