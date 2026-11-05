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
    read = Mock(return_value=CuratedDocumentAssemblyManifestV1.model_validate(_manifest()))
    list_recent = Mock(return_value=((), None))
    services.catalog_application = SimpleNamespace(
        create_curated_document_assembly=create,
        read_curated_document_assembly=read,
        list_curated_document_assemblies=list_recent,
    )
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
            reopened = client.get("/api/v1/item-db/assemblies/assembly_" + "1" * 32)
            listed = client.get("/api/v1/item-db/assemblies")
        assert missing.status_code == 400
        assert missing.json()["error_code"] == "API_IDEMPOTENCY_REQUIRED"
        assert created.status_code == 201
        assert created.json()["data"]["assembly_revision_id"] == "assemblyrev_" + "2" * 32
        assert reopened.status_code == 200
        assert reopened.json()["data"]["assembly_revision_id"] == "assemblyrev_" + "2" * 32
        assert listed.status_code == 200
        assert listed.json()["data"] == []
        create.assert_called_once()
        read.assert_called_once()
        list_recent.assert_called_once()
        route = app.openapi()["paths"]["/api/v1/item-db/assemblies"]["post"]
        assert route["x-eom-permission"] == PermissionKey.DELIVERABLE_CREATE.value
        read_route = app.openapi()["paths"]["/api/v1/item-db/assemblies/{assembly_id}"]["get"]
        assert read_route["x-eom-permission"] == PermissionKey.ITEM_READ.value
        assert (
            app.openapi()["paths"]["/api/v1/item-db/assemblies"]["get"]["x-eom-permission"]
            == PermissionKey.ITEM_READ.value
        )
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


def test_titled_save_library_and_remove_preserve_exact_revision_and_retry_key():
    from eom_catalog_contracts.curated_document_assembly_library import (
        CuratedDocumentAssemblyDraftV2,
        CuratedDocumentAssemblyListEntryV2,
        CuratedDocumentAssemblyRemovalReceipt,
    )

    from tests.unit.test_curated_assembly_library import titled

    services = disconnected_services()
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_manifest())
    entry = CuratedDocumentAssemblyListEntryV2(
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        created_at=manifest.created_at,
        placement_count=len(manifest.placements),
        title="통합과학 1회",
    )
    receipt = CuratedDocumentAssemblyRemovalReceipt(
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        removed_at=manifest.created_at,
    )
    create, listed, remove = (
        Mock(return_value=manifest),
        Mock(return_value=((entry,), None)),
        Mock(return_value=receipt),
    )
    services.catalog_application = SimpleNamespace(
        create_curated_document_assembly=create,
        list_titled_curated_document_assemblies=listed,
        remove_curated_document_assembly=remove,
    )
    services.audit = SimpleNamespace(append=Mock())
    app = create_app(services)

    def authenticated(request: Request):
        value = _authentication(admin=True)
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    body = receipt.model_dump(mode="json", exclude={"assembly_id", "removed_at"})
    try:
        with TestClient(app, base_url="http://localhost") as client:
            saved = client.post(
                "/api/v1/item-db/assemblies",
                json=titled().model_dump(mode="json"),
                headers={"Idempotency-Key": "titled-save-http-key-1"},
            )
            library = client.get("/api/v1/item-db/assemblies/library")
            path = "/api/v1/item-db/assemblies/" + manifest.assembly_id + "/remove"
            missing = client.post(path, json=body)
            removed = client.post(
                path, json=body, headers={"Idempotency-Key": "remove-replay-http-key-1"}
            )
        assert saved.status_code == 201 and isinstance(
            create.call_args.args[0], CuratedDocumentAssemblyDraftV2
        )
        assert library.status_code == 200 and library.json()["data"][0]["title"] == "통합과학 1회"
        assert missing.status_code == 400
        assert removed.status_code == 200 and removed.json()["data"] == receipt.model_dump(
            mode="json"
        )
        assert remove.call_args.args[0] == manifest.assembly_id
        assert remove.call_args.args[1].assembly_revision_id == manifest.assembly_revision_id
        assert remove.call_args.kwargs["idempotency_key"] == "remove-replay-http-key-1"
        assert remove.call_args.kwargs["actor"].actor_id == "operator_" + "6" * 32
        assert (
            services.audit.append.call_args.kwargs["event_type"]
            == "CURATED_DOCUMENT_ASSEMBLY_REMOVED_FROM_LIST"
        )
    finally:
        services.engine.dispose()


def test_library_removal_requires_item_read_as_well_as_delivery_permission():
    services = disconnected_services()
    remove = Mock()
    services.catalog_application = SimpleNamespace(remove_curated_document_assembly=remove)
    app = create_app(services)

    def authenticated(request: Request):
        original = _authentication(admin=True)
        value = replace(original, permissions=original.permissions - {PermissionKey.ITEM_READ})
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    manifest = _manifest()
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post(
                "/api/v1/item-db/assemblies/" + manifest["assembly_id"] + "/remove",
                json={key: manifest[key] for key in ("assembly_revision_id", "manifest_sha256")},
                headers={"Idempotency-Key": "remove-denied-http-key-1"},
            )
        assert response.status_code == 403
        remove.assert_not_called()
    finally:
        services.engine.dispose()
