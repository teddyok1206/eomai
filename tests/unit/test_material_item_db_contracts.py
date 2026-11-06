"""External source category is explicit; no fabricated archive number or AI label."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_api_contracts.item_db_registration import MaterialItemDbEntryView
from eom_catalog_contracts.material_item_lineage import MaterialImportedItemMetadata
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.content_pack_files import compile_pack


def metadata():
    return dict(
        item_type_key="uploaded-material-item",
        source_kind="EXTERNAL",
        material_id="material_" + "1" * 32,
        material_revision_id="materialrev_" + "2" * 32,
        unit_key="chapter-one-question-one",
        title="자료 문항",
        source_filename="문제.hwpx",
        printed_label="1",
        section_path=["1장"],
        physical_pages=[2, 3],
        lineage_sha256="sha256:" + "3" * 64,
        approval_basis="SOURCE_IMPORT_AUTOMATION_NOT_SCIENTIFIC_VERIFICATION",
    )


def entry():
    return dict(
        schema_version="material-item-db-entry/1.0",
        metadata=metadata(),
        material_title="자료",
        registration=dict(
            item_id="item_" + "4" * 32,
            item_revision_id="itemrev_" + "5" * 32,
            item_manifest_sha256="sha256:" + "6" * 64,
            approval_state="APPROVED",
            difficulty_band=None,
            item_type_key="uploaded-material-item",
        ),
    )


def test_pack_metadata_and_api_wire_agree_on_external_source():
    value = MaterialImportedItemMetadata.model_validate(metadata())
    validate_contract("material-learning-item-metadata-v1", value.model_dump(mode="json"))
    parsed = MaterialItemDbEntryView.model_validate(entry())
    assert parsed.metadata.source_kind == "EXTERNAL"
    assert "external_number" not in parsed.metadata.model_dump()
    pack = compile_pack(
        Path(__file__).resolve().parents[2] / "content/packs/uploaded-material-item/1.0.0"
    )
    assert pack is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_kind", "CREATIVE"),
        ("source_kind", "AI"),
        ("physical_pages", [1, 1]),
        ("physical_pages", [0]),
        ("external_number", "12345"),
    ],
)
def test_uploaded_metadata_cannot_claim_another_source_category(field, value):
    document = deepcopy(metadata())
    document[field] = value
    with pytest.raises(ValueError):
        MaterialImportedItemMetadata.model_validate(document)
