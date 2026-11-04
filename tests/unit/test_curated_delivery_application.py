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
