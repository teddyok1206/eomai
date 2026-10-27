"""Mixed-source assembly selection pins exact raw files without pretending they are Items."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts import CuratedDocumentAssemblyManifestV1, validate_contract
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _manifest() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "curated-document-assembly-manifest/1.0",
        "assembly_id": "assembly_" + "1" * 32,
        "assembly_revision_id": "assemblyrev_" + "2" * 32,
        "selection_sha256": "sha256:" + "3" * 64,
        "placements": [
            {
                "placement_kind": "EXTERNAL_SOURCE_DOCUMENT",
                "position": 1,
                "source_id": "extitem_" + "4" * 32,
                "source_revision_id": "extitemrev_" + "5" * 32,
                "external_number": "10310",
                "observation_sha256": "sha256:" + "6" * 64,
                "edition": 3,
                "source_format": "HWP",
                "source_file_id": "sourcefile_" + "7" * 32,
                "document_artifact": {
                    "artifact_id": "artifact_" + "8" * 32,
                    "artifact_revision_id": "rev_" + "9" * 32,
                    "member_path": "source/10310.hwp",
                    "schema_ref": "eom://schemas/content-intake/source-file/1.0",
                    "media_type": "application/vnd.hancom.hwp",
                    "sha256": "sha256:" + "a" * 64,
                },
                "document_size_bytes": 123456,
            },
            {
                "placement_kind": "PAST_EXAM_ITEM_REVISION",
                "position": 2,
                "item_id": "item_" + "b" * 32,
                "item_revision_id": "itemrev_" + "c" * 32,
                "item_manifest_sha256": "sha256:" + "d" * 64,
                "graph_snapshot_revision_id": "graphrev_" + "e" * 32,
                "graph_snapshot_sha256": "sha256:" + "f" * 64,
            },
            {
                "placement_kind": "REGISTERED_ITEM_REVISION",
                "position": 3,
                "item_id": "item_" + "0" * 32,
                "item_revision_id": "itemrev_" + "1" * 32,
                "item_manifest_sha256": "sha256:" + "2" * 64,
                "graph_snapshot_revision_id": "graphrev_" + "3" * 32,
                "graph_snapshot_sha256": "sha256:" + "4" * 64,
            },
        ],
        "created_by": "guiadmin",
        "created_at": "2026-10-27T11:20:00Z",
    }
    value["manifest_sha256"] = content_sha256(value)
    return value


def _rehash(value: dict[str, object]) -> dict[str, object]:
    value["manifest_sha256"] = content_sha256(
        {key: field for key, field in value.items() if key != "manifest_sha256"}
    )
    return value


def test_resolved_manifest_schema_mirror_and_mixed_pointers() -> None:
    canonical = (
        ROOT / "schemas/assessment-assembly/curated-document-assembly-manifest-v1.schema.json"
    )
    resource = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly"
        / "curated-document-assembly-manifest-v1.schema.json"
    )
    assert canonical.read_bytes() == resource.read_bytes()
    value = _manifest()
    validate_contract("curated-document-assembly-manifest-v1", value)
    parsed = CuratedDocumentAssemblyManifestV1.model_validate(value)
    assert parsed.placements[0].placement_kind == "EXTERNAL_SOURCE_DOCUMENT"
    assert parsed.placements[1].placement_kind == "PAST_EXAM_ITEM_REVISION"
    assert parsed.placements[2].placement_kind == "REGISTERED_ITEM_REVISION"


def test_resolved_manifest_rejects_drift_duplicate_and_unsafe_member() -> None:
    changed = deepcopy(_manifest())
    placements = changed["placements"]
    assert isinstance(placements, list)
    external = placements[0]
    assert isinstance(external, dict)
    artifact = external["document_artifact"]
    assert isinstance(artifact, dict)

    artifact["media_type"] = "application/vnd.hancom.hwpx"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("curated-document-assembly-manifest-v1", _rehash(changed))
    with pytest.raises(ValidationError, match="source format differs"):
        CuratedDocumentAssemblyManifestV1.model_validate(changed)

    changed = deepcopy(_manifest())
    placements = changed["placements"]
    assert isinstance(placements, list)
    placements[1]["position"] = 3
    with pytest.raises(ValidationError, match="contiguous"):
        CuratedDocumentAssemblyManifestV1.model_validate(_rehash(changed))

    changed = deepcopy(_manifest())
    placements = changed["placements"]
    assert isinstance(placements, list)
    placements[2]["item_revision_id"] = placements[1]["item_revision_id"]
    with pytest.raises(ValidationError, match="repeat"):
        CuratedDocumentAssemblyManifestV1.model_validate(_rehash(changed))

    changed = deepcopy(_manifest())
    placements = changed["placements"]
    assert isinstance(placements, list)
    placements[0]["document_artifact"]["member_path"] = "../outside.hwp"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("curated-document-assembly-manifest-v1", _rehash(changed))
    with pytest.raises(ValidationError, match="safe relative"):
        CuratedDocumentAssemblyManifestV1.model_validate(changed)

    changed = deepcopy(_manifest())
    changed["created_by"] = "different-actor"
    with pytest.raises(ValidationError, match="manifest hash differs"):
        CuratedDocumentAssemblyManifestV1.model_validate(changed)
