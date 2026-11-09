"""Content scope preparation crosses API/Catalog without inventing a build or print."""

import json
from dataclasses import replace
from unittest.mock import Mock

from eom_api.services.catalog_application_client import CatalogApplicationClient
from eom_catalog_contracts.content_delivery import ContentDeliveryPrepared, PrepareContentDelivery
from eom_catalog_service.content_planning_dispatch import dispatch_content_planning
from eom_operator_identity import PermissionKey

from tests.api.test_content_planning_routes import planning_client as planning_client
from tests.api.test_hwpx_endpoints import OPERATOR_ID
from tests.unit.content_planning_fixtures import SHA, TIME, composition, identifier
from tests.unit.test_curated_document_assembly_resolution import _actor


def delivery_example():
    value = composition()
    request = PrepareContentDelivery(
        edition_id=value["edition_id"],
        revision_id=value["deliverable_revision_id"],
        composition_sha256=value["composition_sha256"],
        section_ids=(identifier("section"),),
    )
    result = ContentDeliveryPrepared(
        edition_id=request.edition_id,
        revision_id=request.revision_id,
        composition_sha256=request.composition_sha256,
        scope_sha256=SHA,
        assembly_id=identifier("assembly"),
        assembly_revision_id=identifier("assemblyrev"),
        manifest_sha256=SHA,
        placement_count=1200,
        created_at=TIME,
        replayed=False,
    )
    return request, result


def test_prepare_route_is_not_build_or_print(planning_client):
    client, catalog, state = planning_client
    request, prepared = delivery_example()
    catalog.prepare_content_delivery = Mock(return_value=prepared)
    response = client.post(
        "/api/v1/content-planning/deliveries",
        json=request.model_dump(mode="json"),
        headers={"Idempotency-Key": "content-output-12345678"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == prepared.model_dump(mode="json")
    assert catalog.prepare_content_delivery.call_args.kwargs["actor"].operator_id == OPERATOR_ID
    catalog.record_content_print.assert_not_called()
    state.authentication = replace(
        state.authentication,
        permissions=state.authentication.permissions - {PermissionKey.HWPX_BUILD_CREATE},
    )
    response = client.post(
        "/api/v1/content-planning/deliveries",
        json=request.model_dump(mode="json"),
        headers={"Idempotency-Key": "content-output-12345679"},
    )
    assert response.status_code == 403 and catalog.prepare_content_delivery.call_count == 1


def test_prepare_socket_roundtrip_reuses_actual_actor_and_key(monkeypatch):
    request, prepared = delivery_example()
    service = Mock()
    service.deliveries.prepare.return_value = prepared
    client = CatalogApplicationClient()
    monkeypatch.setattr(
        client,
        "_raw_request",
        lambda value, **_: json.loads(dispatch_content_planning(service, value)),
    )
    result = client.prepare_content_delivery(
        request, actor=_actor(), idempotency_key="content-output-12345678"
    )
    assert result == prepared
    assert not service.deliveries.prepare.call_args.kwargs["actor"].permissions
    assert (
        service.deliveries.prepare.call_args.kwargs["idempotency_key"] == "content-output-12345678"
    )
