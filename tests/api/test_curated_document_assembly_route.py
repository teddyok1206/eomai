"""The public save route passes only the selected pins to the Catalog owner."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.routers.curated_document_assemblies import create_curated_assembly
from eom_api.services.catalog_application_client import CatalogApplicationClientError
from eom_catalog_contracts import CuratedDocumentAssemblyManifestV1
from eom_operator_identity import PermissionKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import _authentication
from tests.unit.test_curated_document_assembly_manifest import _manifest
from tests.unit.test_curated_document_assembly_resolution import _actor, _draft


def _request() -> tuple[SimpleNamespace, list[tuple[object, ...]], list[dict[str, object]]]:
    calls: list[tuple[object, ...]] = []
    audit: list[dict[str, object]] = []
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())

    def create(draft: object, *, actor: object, idempotency_key: str) -> object:
        calls.append((draft, actor, idempotency_key))
        return manifest

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                services=SimpleNamespace(
                    catalog_application=SimpleNamespace(create_curated_document_assembly=create),
                    audit=SimpleNamespace(append=lambda _context, **kwargs: audit.append(kwargs)),
                )
            )
        ),
        state=SimpleNamespace(
            request_context=SimpleNamespace(request_id="curated-route-1", actor=lambda: _actor())
        ),
    )
    return request, calls, audit


def test_save_passes_exact_ordered_selection_and_operator_to_catalog() -> None:
    request, calls, audit = _request()
    draft = _draft()
    answer = create_curated_assembly(
        request,
        draft,
        SimpleNamespace(
            permissions=frozenset({PermissionKey.CONTENT_INTAKE_READ, PermissionKey.ITEM_READ})
        ),
        "curated-route-key-1",
    )
    assert answer.data.assembly_revision_id == "assemblyrev_" + "2" * 32
    assert calls == [(draft, _actor(), "curated-route-key-1")]
    assert audit[0]["target_id"] == answer.data.assembly_revision_id
    assert "delivery_artifact" not in answer.model_dump()


def test_external_selection_rejects_missing_source_permission_before_catalog() -> None:
    request, calls, audit = _request()
    with pytest.raises(ApiError) as captured:
        create_curated_assembly(
            request,
            _draft(),
            SimpleNamespace(permissions=frozenset()),
            "curated-route-key-1",
        )
    assert captured.value.status == 403
    assert calls == [] and audit == []


def test_authenticated_http_route_requires_one_retry_key_and_declares_permissions() -> None:
    services = disconnected_services()
    create = Mock(return_value=CuratedDocumentAssemblyManifestV1.model_validate(_manifest()))
    services.catalog_application = SimpleNamespace(create_curated_document_assembly=create)
    services.audit = SimpleNamespace(append=Mock())
    app = create_app(services)

    def authenticated(request: Request):
        value = _authentication(admin=True)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            payload = _draft().model_dump(mode="json")
            missing = client.post("/api/v1/item-db/assemblies", json=payload)
            created = client.post(
                "/api/v1/item-db/assemblies",
                json=payload,
                headers={"Idempotency-Key": "curated-http-key-1"},
            )
        assert missing.status_code == 400
        assert missing.json()["error_code"] == "API_IDEMPOTENCY_REQUIRED"
        assert created.status_code == 201
        assert created.json()["data"]["assembly_revision_id"] == "assemblyrev_" + "2" * 32
        create.assert_called_once()
        route = app.openapi()["paths"]["/api/v1/item-db/assemblies"]["post"]
        assert route["x-eom-permission"] == PermissionKey.DELIVERABLE_CREATE.value
    finally:
        services.engine.dispose()


def test_http_route_rejects_external_source_without_intake_permission() -> None:
    services = disconnected_services()
    create = Mock()
    services.catalog_application = SimpleNamespace(create_curated_document_assembly=create)
    app = create_app(services)

    def authenticated(request: Request):
        value = _authentication(admin=True)
        value = replace(value, permissions=value.permissions - {PermissionKey.CONTENT_INTAKE_READ})
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/item-db/assemblies",
                json=_draft().model_dump(mode="json"),
                headers={"Idempotency-Key": "curated-http-key-1"},
            )
        assert response.status_code == 403
        assert response.json()["error_code"] == "PERMISSION_DENIED"
        create.assert_not_called()
    finally:
        services.engine.dispose()


def test_catalog_reauthorization_denial_maps_to_forbidden() -> None:
    services = disconnected_services()
    services.catalog_application = SimpleNamespace(
        create_curated_document_assembly=Mock(
            side_effect=CatalogApplicationClientError(
                "CURATED_SOURCE_PERMISSION_DENIED", "The role changed before commit"
            )
        )
    )
    app = create_app(services)

    def authenticated(request: Request):
        value = _authentication(admin=True)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/item-db/assemblies",
                json=_draft().model_dump(mode="json"),
                headers={"Idempotency-Key": "curated-http-key-1"},
            )
        assert response.status_code == 403
        assert response.json()["error_code"] == "CURATED_SOURCE_PERMISSION_DENIED"
    finally:
        services.engine.dispose()
