"""Additive native material views keep source metadata and existing read permissions."""

from unittest.mock import Mock

from eom_api.services.pagination import PageResult
from eom_api_contracts.item_db_registration import MaterialNativeItemDbEntryView
from eom_catalog_contracts.material_native_files import MaterialImportedNativeItemMetadata

from tests.api.test_external_item_db_routes import _client
from tests.unit.test_material_item_db_contracts import entry
from tests.unit.test_material_native_files import metadata_data


def native_entry():
    value = entry()
    value.update(schema_version="material-item-db-entry/2.0", metadata=metadata_data())
    return MaterialNativeItemDbEntryView.model_validate(value)


def test_material_list_serves_native_metadata_without_a_fake_legacy_number_or_source_id():
    client, services, _ = _client()
    services.queries.material_item_db_entries = Mock(
        return_value=PageResult((native_entry(),), None, False)
    )
    try:
        with client:
            response = client.get("/api/v1/item-db/materials?approval_state=APPROVED")
        assert response.status_code == 200, response.text
        value = response.json()["data"][0]
        assert value["schema_version"] == "material-item-db-entry/2.0"
        assert value["metadata"]["external_number"] is None
        assert value["metadata"]["original_unit"] == " 단원 원문 "
        assert value["metadata"]["source_kind"] == "EXTERNAL"
        assert "source_id" not in value and "cells" not in value
    finally:
        services.engine.dispose()


def test_original_source_read_can_return_native_metadata_without_graph_unit_substitution():
    client, services, reads = _client()
    value = native_entry()
    reads.registration_source = Mock(return_value=value.metadata)
    try:
        with client:
            response = client.get(
                f"/api/v1/item-db/registrations/{value.registration.item_revision_id}/source",
                params={"manifest_sha256": value.registration.item_manifest_sha256},
            )
        assert response.status_code == 200, response.text
        source = MaterialImportedNativeItemMetadata.model_validate(response.json()["data"])
        assert source == value.metadata
        assert "curriculum_units" not in response.json()["data"]
    finally:
        services.engine.dispose()


def test_native_original_metadata_is_not_disclosed_without_existing_intake_permission():
    client, services, reads = _client(allow_intake=False)
    reads.registration_source = Mock(return_value=native_entry().metadata)
    try:
        with client:
            response = client.get(
                f"/api/v1/item-db/registrations/{native_entry().registration.item_revision_id}/source",
                params={"manifest_sha256": native_entry().registration.item_manifest_sha256},
            )
        assert response.status_code == 403
        reads.registration_source.assert_not_called()
    finally:
        services.engine.dispose()
