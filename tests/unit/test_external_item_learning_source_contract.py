"""Creative learning input is a pinned source pointer, not an Item admission."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_learning_source import (
    EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA,
    ExternalItemLearningSource,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _source() -> dict[str, object]:
    preview: dict[str, object] = {
        "schema_version": "external-item-preview-manifest/1.0",
        "source_id": "extitem_" + "1" * 32,
        "source_revision_id": "extitemrev_" + "2" * 32,
        "edition": 3,
        "source_file_id": "sourcefile_" + "3" * 32,
        "source_artifact_id": "artifact_" + "4" * 32,
        "source_artifact_revision_id": "rev_" + "5" * 32,
        "source_member_path": "source/original-12345.hwp",
        "source_schema_ref": "eom://schemas/content-intake/source-file/1.0",
        "source_sha256": "sha256:" + "6" * 64,
        "source_media_type": "application/vnd.hancom.hwp",
        "source_bytes": 4096,
        "source_format": "HWP",
        "pdf_member_path": "preview/original.pdf",
        "pdf_sha256": "sha256:" + "7" * 64,
        "pdf_bytes": 8192,
        "conversion": {
            "conversion_kind": "LIBREOFFICE_H2ORESTART_PDF",
            "review_pdf_sha256": "sha256:" + "7" * 64,
            "libreoffice_version": "LibreOffice 24.2",
            "libreoffice_sha256": "sha256:" + "8" * 64,
            "h2orestart_sha256": "sha256:" + "9" * 64,
        },
    }
    preview["manifest_sha256"] = content_sha256(preview)
    source: dict[str, object] = {
        "schema_version": "external-item-learning-source/1.0",
        "import_id": "extimport_" + "a" * 32,
        "source_namespace": "notion.nje",
        "source_id": preview["source_id"],
        "source_revision_id": preview["source_revision_id"],
        "external_number": "12345",
        "origin_kind": "PAST_EXAM_VARIATION",
        "observation_sha256": "sha256:" + "b" * 64,
        "selected_edition": 3,
        "preview_artifact_id": "artifact_" + "c" * 32,
        "preview_artifact_revision_id": "rev_" + "d" * 32,
        "preview_manifest": preview,
    }
    source["input_sha256"] = content_sha256(source)
    return source


def test_learning_source_schema_and_model_pin_original_and_derivative() -> None:
    value = _source()
    validate_contract(EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA, value)
    parsed = ExternalItemLearningSource.model_validate(value)
    assert parsed.preview_manifest.source_file_id == "sourcefile_" + "3" * 32
    assert parsed.preview_manifest.pdf_sha256 == "sha256:" + "7" * 64
    assert parsed.external_number == "12345"
    assert not any(key in value for key in ("source_payload", "pdf_payload", "workspace_path"))


def test_learning_source_schema_mirror_is_exact() -> None:
    canonical = ROOT / "schemas/external-item/external-item-learning-source-v1.schema.json"
    resource = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/external-item"
        / "external-item-learning-source-v1.schema.json"
    )
    assert canonical.read_bytes() == resource.read_bytes()


def test_learning_source_rejects_different_preview_revision_even_with_new_outer_hash() -> None:
    value = _source()
    value["source_revision_id"] = "extitemrev_" + "e" * 32
    value["input_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "input_sha256"}
    )
    validate_contract(EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA, value)
    with pytest.raises(ValidationError, match="differs from its preview"):
        ExternalItemLearningSource.model_validate(value)


def test_learning_source_rejects_stale_outer_or_inner_hash() -> None:
    value = _source()
    value["external_number"] = "54321"
    with pytest.raises(ValidationError, match="input hash differs"):
        ExternalItemLearningSource.model_validate(value)

    value = _source()
    preview = deepcopy(value["preview_manifest"])
    assert isinstance(preview, dict)
    preview["source_sha256"] = "sha256:" + "e" * 64
    value["preview_manifest"] = preview
    value["input_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "input_sha256"}
    )
    with pytest.raises(ValidationError, match="manifest hash differs"):
        ExternalItemLearningSource.model_validate(value)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("origin_kind", "PAST_EXAM"),
        ("selected_edition", 1),
        ("external_number", "1234"),
        ("preview_artifact_id", "../../preview"),
    ],
)
def test_learning_source_schema_rejects_false_authority(field: str, replacement: object) -> None:
    value = _source()
    value[field] = replacement
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(EXTERNAL_ITEM_LEARNING_SOURCE_SCHEMA, value)
