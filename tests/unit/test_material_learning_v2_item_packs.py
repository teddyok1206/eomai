"""New Material ROLE2 Pack releases preserve both historical metadata families."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from eom_catalog_contracts.material_item_lineage import MaterialImportedItemMetadata
from eom_catalog_contracts.material_native_files import MaterialImportedNativeItemMetadata
from eom_catalog_service.content_pack_files import build_pack, compile_pack, inspect_bundle
from eom_catalog_service.models import ContentPackReleaseRecord
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_content_pack import ContentPackError
from eom_identifiers import sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as SchemaError

from tests.unit.test_material_native_files import metadata_data

ROOT = Path(__file__).resolve().parents[2]
PACKS = ROOT / "content/packs/uploaded-material-item"
PAIRS = (("1.0.0", "1.2.0"), ("1.1.0", "1.3.0"))
OLD_SHA256 = {
    "1.0.0/pack.yaml": "8ebd9262ca98db1e0e748eff17edb3ab893d06046f7d1ebed8cfbc914c7e85e3",
    "1.0.0/item-types/uploaded-material-item.yaml": (
        "7c3a05f0a528aa2f25982a596d257a1ec77a22415695a1ddc6e9b10042723a26"
    ),
    "1.0.0/metadata-schemas/item-metadata.schema.json": (
        "b48e64a6c9fe43c551989d38c9765f2a44214e4cfcb0d5e425ee3c5ecf438eac"
    ),
    "1.1.0/pack.yaml": "b16f856ed948b5227c4bd383f17b98ef8dbbae51a5e5c18a62cb48fdc66ff9a5",
    "1.1.0/item-types/uploaded-material-item.yaml": (
        "ddcec4b38f77a0ce28df7754c5cbb29af3ea417298273f14bffa1ec1155d87f3"
    ),
    "1.1.0/metadata-schemas/item-metadata.schema.json": (
        "d9e07783f544aa983606e4c6822ac0557884c639ec124b74316b3b95599b81c5"
    ),
}


def _schema(version: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((PACKS / version / "metadata-schemas/item-metadata.schema.json").read_text()),
    )


def _metadata(native: bool) -> dict[str, object]:
    value = metadata_data()  # type: ignore[no-untyped-call]
    if native:
        return MaterialImportedNativeItemMetadata.model_validate(value).model_dump(mode="json")
    fields = MaterialImportedItemMetadata.model_fields
    return MaterialImportedItemMetadata.model_validate(
        {key: item for key, item in value.items() if key in fields}
    ).model_dump(mode="json")


@pytest.mark.parametrize(("old", "successor"), PAIRS)
def test_successors_compile_with_only_release_and_compatibility_changes(
    old: str, successor: str
) -> None:
    before = compile_pack(PACKS / old)
    after = compile_pack(PACKS / successor)
    expected = before.manifest.model_dump(mode="json")
    expected["pack"]["version"] = successor
    expected["compatibility"]["protocol"] = {
        "minimum": "1.39.0",
        "maximum_exclusive": "1.40.0",
    }
    expected["compatibility"]["workflow_definitions"] = [
        {"key": "material-learning", "versions": ["2.0.0"]}
    ]
    assert after.manifest.model_dump(mode="json") == expected
    assert after.manifest.pack.key == before.manifest.pack.key == "uploaded-material-item"
    assert not after.profiles and after.manifest.profiles == {}
    assert {value.relative_path for value in after.files} == {
        "pack.yaml",
        "item-types/uploaded-material-item.yaml",
        "metadata-schemas/item-metadata.schema.json",
    }


@pytest.mark.parametrize(("old", "successor"), PAIRS)
@pytest.mark.parametrize(
    "relative",
    ["item-types/uploaded-material-item.yaml", "metadata-schemas/item-metadata.schema.json"],
)
def test_item_type_and_metadata_schema_bytes_are_historical_exact_copies(
    old: str, successor: str, relative: str
) -> None:
    assert (PACKS / successor / relative).read_bytes() == (PACKS / old / relative).read_bytes()


@pytest.mark.parametrize(
    ("version", "native", "identifier"),
    [
        ("1.2.0", False, "eom://metadata/uploaded-material-item@1.0"),
        ("1.3.0", True, "eom://metadata/uploaded-material-item@2.0"),
    ],
)
def test_successor_metadata_ids_sources_and_closed_schema_are_unchanged(
    version: str, native: bool, identifier: str
) -> None:
    schema = _schema(version)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert schema["$id"] == identifier
    validator.validate(_metadata(native))
    with pytest.raises(SchemaError):
        validator.validate(_metadata(not native))
    wrong_source = _metadata(native) | {"source_kind": "CREATIVE"}
    with pytest.raises(SchemaError):
        validator.validate(wrong_source)
    with pytest.raises(SchemaError):
        validator.validate(_metadata(native) | {"visual_coverage": {}})


@pytest.mark.parametrize(("old", "successor"), PAIRS)
def test_existing_pack_compatibility_owner_rejects_mixed_definition_families(
    old: str, successor: str
) -> None:
    historical = ContentPackReleaseRecord(
        compatibility_json=compile_pack(PACKS / old).manifest.compatibility.model_dump(mode="json")
    )
    current = ContentPackReleaseRecord(
        compatibility_json=compile_pack(PACKS / successor).manifest.compatibility.model_dump(
            mode="json"
        )
    )
    WorkflowCatalogService._require_compatibility(historical, "material-learning", "1.0.0")
    WorkflowCatalogService._require_compatibility(current, "material-learning", "2.0.0")
    with pytest.raises(ContentPackError, match="does not allow"):
        WorkflowCatalogService._require_compatibility(historical, "material-learning", "2.0.0")
    with pytest.raises(ContentPackError, match="does not allow"):
        WorkflowCatalogService._require_compatibility(current, "material-learning", "1.0.0")
    with pytest.raises(ContentPackError, match="does not allow"):
        WorkflowCatalogService._require_compatibility(current, "generic-item-development", "2.0.0")
    assert current.compatibility_json["protocol"] == {
        "minimum": "1.39.0",
        "maximum_exclusive": "1.40.0",
    }
    assert historical.compatibility_json["protocol"] == {
        "minimum": "1.37.0",
        "maximum_exclusive": "1.38.0",
    }


@pytest.mark.parametrize("version", ["1.2.0", "1.3.0"])
def test_successor_bundles_are_deterministic_and_complete(version: str, tmp_path: Path) -> None:
    first = build_pack(PACKS / version, tmp_path / "first")
    second = build_pack(PACKS / version, tmp_path / "second")
    assert first.bundle_sha256 == second.bundle_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.compiled.source_tree_sha256 == second.compiled.source_tree_sha256
    assert inspect_bundle(first.bundle_path) == first.compiled.canonical_manifest
    assert len(first.compiled.files) == 3


def test_every_original_pack_byte_remains_frozen() -> None:
    before = deepcopy(OLD_SHA256)
    for relative, expected in before.items():
        assert sha256_bytes((PACKS / relative).read_bytes()) == "sha256:" + expected
