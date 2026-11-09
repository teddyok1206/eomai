"""Catalog delivery frames preserve exact revisions and actual actor authority."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import validate_contract
from eom_catalog_contracts.curated_document_delivery_application import (
    CuratedDocumentDeliveryQueryV1,
    CuratedDocumentDeliveryResponseV1,
)
from eom_catalog_service.application_server import (
    CatalogApplicationServer,
    _CatalogApplicationHandler,
)
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_curated_document_assembly_resolution import _actor
from tests.unit.test_curated_hwpx_build import build_inputs, build_manifest


def query(purpose):
    actor = _actor()
    manifest = build_manifest()
    inputs = build_inputs(manifest)
    return CuratedDocumentDeliveryQueryV1(
        purpose=purpose,
        actor_id=actor.actor_id,
        session_id=actor.session_id,
        request_id=actor.request_id,
        authentication_time=actor.authentication_time,
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        handoff=inputs.handoff if purpose == "PIN_INPUTS" else None,
        converter=inputs.converter if purpose == "PIN_INPUTS" else None,
    )


@pytest.mark.parametrize("purpose", ["PIN_INPUTS", "AUTHORIZE_BUILD", "AUTHORIZE_READ"])
def test_catalog_uses_current_actor_and_does_not_repin_during_status_read(purpose):
    value = query(purpose)
    payload = value.model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-curated-document-delivery-request-v1", payload)
    with pytest.raises(SchemaError):
        validate_contract(
            "catalog-curated-document-delivery-request-v1", {**payload, "permissions": ["ADMIN"]}
        )
    service = Mock()
    service.authorize_delivery_build.return_value = service.read_for_delivery.return_value = (
        build_manifest()
    )
    service.pin_delivery_inputs.return_value = build_inputs(build_manifest())
    handler = object.__new__(_CatalogApplicationHandler)
    handler.server = SimpleNamespace(
        curated_document_assemblies=service,
        write_curated_document_delivery_response=CatalogApplicationServer.write_curated_document_delivery_response,
    )
    handler.wfile = BytesIO()
    handler._resolve_curated_document_delivery(value)
    result = CuratedDocumentDeliveryResponseV1.model_validate_json(handler.wfile.getvalue())
    assert result.status == "OK"
    authorize = (
        service.read_for_delivery
        if purpose == "AUTHORIZE_READ"
        else service.authorize_delivery_build
    )
    assert authorize.call_args.kwargs["actor"].permissions == frozenset()
    assert authorize.call_args.kwargs["actor"].actor_id == value.actor_id
    assert (result.inputs is not None) == (purpose == "PIN_INPUTS")
    assert service.pin_delivery_inputs.call_count == int(purpose == "PIN_INPUTS")


def test_admission_pins_are_not_accepted_as_followup_authority():
    with pytest.raises(ValidationError):
        CuratedDocumentDeliveryQueryV1.model_validate(
            {**query("PIN_INPUTS").model_dump(mode="json"), "purpose": "AUTHORIZE_READ"}
        )
    with pytest.raises(ValidationError):
        CuratedDocumentDeliveryQueryV1.model_validate(
            {**query("AUTHORIZE_READ").model_dump(mode="json"), "purpose": "PIN_INPUTS"}
        )


def test_new_catalog_schema_is_exactly_mirrored():
    root = Path(__file__).resolve().parents[2]
    for branch in ("request", "response"):
        name = f"catalog-curated-document-delivery-{branch}-v1.schema.json"
        assert (root / "schemas/catalog-application" / name).read_bytes() == (
            root
            / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application"
            / name
        ).read_bytes()


@pytest.mark.parametrize("purpose", ["PIN_INPUTS", "AUTHORIZE_BUILD", "AUTHORIZE_READ"])
def test_occurrence_transport_preserves_pins_and_refuses_cross_family(purpose):
    import json

    from eom_api.services.catalog_application_client import CatalogApplicationClient
    from eom_catalog_contracts.curated_document_delivery_application import (
        CuratedDocumentDeliveryQueryV2,
        CuratedDocumentDeliveryResponseV2,
    )
    from eom_catalog_contracts.curated_document_slots import CuratedDocumentAssemblyManifestV2
    from eom_hwpx_contracts.curated_occurrences import CuratedHwpxBuildInputV2
    from eom_identifiers import content_sha256

    from tests.unit.content_planning_fixtures import identifier, slot

    legacy = build_manifest()
    # The registered example below reuses the exact pointer family, not its text.
    selected = next(
        row for row in legacy.placements if row.placement_kind == "REGISTERED_ITEM_REVISION"
    )
    target = selected.model_dump(mode="json")
    target.pop("position")
    slots = [slot(i, target=target) for i in range(1, 301)]
    value = {
        **legacy.model_dump(mode="json"),
        "schema_version": "curated-document-assembly-manifest/2.0",
        "previous_revision_id": None,
        "revision_number": 1,
        "placements": slots,
    }
    value.pop("manifest_sha256")
    manifest = CuratedDocumentAssemblyManifestV2.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    old_input = build_inputs(legacy)
    selected_input = next(row for row in old_input.placements if row.kind == "REGISTERED_ITEM")
    inputs = CuratedHwpxBuildInputV2(
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        assembly_manifest_sha256=manifest.manifest_sha256,
        handoff=old_input.handoff,
        converter=None,
        placements=tuple(
            {
                **selected_input.model_dump(mode="json"),
                "position": i,
                "placement_id": identifier("placement", i),
            }
            for i in range(1, 301)
        ),
    )
    request = CuratedDocumentDeliveryQueryV2.model_validate(
        {
            **query(purpose).model_dump(mode="json"),
            "operation": "RESOLVE_CURATED_DOCUMENT_DELIVERY_V2",
            "manifest_sha256": manifest.manifest_sha256,
        }
    )
    validate_contract(
        "catalog-curated-document-delivery-request-v2", request.model_dump(mode="json")
    )
    service = Mock()
    service.authorize_delivery_build.return_value = service.read_for_delivery.return_value = (
        manifest
    )
    service.pin_delivery_inputs.return_value = inputs
    handler = object.__new__(_CatalogApplicationHandler)
    handler.server = SimpleNamespace(
        curated_document_assemblies=service,
        write_curated_document_delivery_response=CatalogApplicationServer.write_curated_document_delivery_response,
    )
    handler.wfile = BytesIO()
    handler._resolve_curated_document_delivery(request)
    reply = CuratedDocumentDeliveryResponseV2.model_validate_json(handler.wfile.getvalue())
    assert reply.status == "OK" and reply.manifest == manifest
    client = CatalogApplicationClient()
    client._raw_request = Mock(return_value=json.loads(handler.wfile.getvalue()))
    assert client.resolve_curated_document_delivery(request) == reply
    with pytest.raises(SchemaError):
        validate_contract(
            "catalog-curated-document-delivery-response-v1", reply.model_dump(mode="json")
        )
    if purpose == "PIN_INPUTS":
        assert reply.inputs == inputs
        with pytest.raises(ValidationError, match="family"):
            CuratedDocumentDeliveryResponseV2(
                status="OK",
                manifest=legacy,
                inputs=inputs.model_copy(
                    update={"assembly_manifest_sha256": legacy.manifest_sha256}
                ),
            )
