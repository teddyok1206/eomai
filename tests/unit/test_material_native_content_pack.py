"""Native metadata is the same rule in runtime and an offline released Pack."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.material_native_files import MaterialImportedNativeItemMetadata
from eom_catalog_service.content_pack_files import compile_pack
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError

from scripts.contracts.generate_material_native_pack import render_schema
from tests.unit.test_material_native_files import metadata_data

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "content/packs/uploaded-material-item/1.1.0"


def test_native_pack_is_standalone_and_matches_the_canonical_contract():
    raw = (PACK / "metadata-schemas/item-metadata.schema.json").read_text()
    assert raw == render_schema()
    schema = json.loads(raw)
    assert schema["$id"] == "eom://metadata/uploaded-material-item@2.0"
    Draft202012Validator.check_schema(schema)
    value = metadata_data()
    MaterialImportedNativeItemMetadata.model_validate(value)
    Draft202012Validator(schema).validate(value)
    changed = deepcopy(value)
    changed["external_number"] = "not-a-number"
    with pytest.raises(SchemaError):
        Draft202012Validator(schema).validate(changed)


def test_native_pack_compiles_without_reinterpreting_the_original_pack():
    pack = compile_pack(PACK)
    original = compile_pack(ROOT / "content/packs/uploaded-material-item/1.0.0")
    assert pack.manifest.pack.key == original.manifest.pack.key == "uploaded-material-item"
    assert pack.manifest.pack.version == "1.1.0"
    assert original.manifest.pack.version == "1.0.0"
