"""External Item preview must pin its original without copying original bytes."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts.external_item_media import (
    ExternalItemPreviewMediaQuery,
    ExternalItemPreviewMediaResponse,
    ExternalItemPreviewPrepareCommand,
    ExternalItemPreviewPrepareResponse,
)
from eom_catalog_contracts.external_item_preview import (
    EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA,
    ExternalItemPreviewManifest,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError


def _manifest() -> dict[str, object]:
    value: dict[str, object] = {
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
    value["manifest_sha256"] = content_sha256(value)
    return value


def test_preview_manifest_pins_exact_source_and_pdf() -> None:
    value = _manifest()
    validate_contract(EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA, value)
    manifest = ExternalItemPreviewManifest.model_validate(value)
    assert manifest.source_file_id == value["source_file_id"]
    assert "source_bytes" in value
    assert not any(key in value for key in ("source_payload", "source_path", "original_bytes"))


def test_preview_socket_request_and_result_are_closed_variants() -> None:
    query = ExternalItemPreviewMediaQuery(
        source_id="extitem_" + "1" * 32,
        source_revision_id="extitemrev_" + "2" * 32,
        edition=3,
    )
    validate_contract("catalog-external-item-preview-media-request", query.model_dump(mode="json"))
    response = ExternalItemPreviewMediaResponse(
        status="OK",
        media_type="application/pdf",
        content_length=8192,
        sha256="sha256:" + "7" * 64,
    )
    validate_contract(
        "catalog-external-item-preview-media-response",
        response.model_dump(mode="json", exclude_none=True),
    )
    with pytest.raises(ValidationError):
        ExternalItemPreviewMediaResponse(
            status="OK",
            media_type="application/pdf",
            content_length=8192,
            sha256="sha256:" + "7" * 64,
            error_code="PREVIEW_NOT_READY",
        )


def test_preview_prepare_is_explicit_mutation_with_closed_response() -> None:
    command = ExternalItemPreviewPrepareCommand(
        source_id="extitem_" + "1" * 32,
        source_revision_id="extitemrev_" + "2" * 32,
        edition=3,
    )
    validate_contract(
        "catalog-external-item-preview-prepare-request", command.model_dump(mode="json")
    )
    response = ExternalItemPreviewPrepareResponse(status="OK", sha256="sha256:" + "7" * 64)
    validate_contract(
        "catalog-external-item-preview-prepare-response",
        response.model_dump(mode="json", exclude_none=True),
    )
    with pytest.raises(ValidationError):
        ExternalItemPreviewPrepareResponse(
            status="OK", error_code="EXTERNAL_ITEM_PREVIEW_NOT_READY"
        )


def test_preview_manifest_accepts_detected_hwpx_with_hwp_source_filename() -> None:
    value = _manifest()
    value["source_member_path"] = "source/문항_12345.hwp"
    value["source_format"] = "HWPX"
    value["source_media_type"] = "application/vnd.hancom.hwpx"
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    validate_contract(EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA, value)
    assert ExternalItemPreviewManifest.model_validate(value).source_format == "HWPX"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_media_type", "application/pdf"),
        ("pdf_member_path", "source/original.hwp"),
        ("source_schema_ref", "eom://schemas/document-review/hwp-source/2.0"),
    ],
)
def test_preview_schema_rejects_wrong_pointer_shape(field: str, replacement: str) -> None:
    value = _manifest()
    value[field] = replacement
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA, value)


def test_preview_model_rejects_changed_source_and_converter_hash() -> None:
    value = _manifest()
    value["source_sha256"] = "sha256:" + "a" * 64
    with pytest.raises(ValidationError, match="manifest hash differs"):
        ExternalItemPreviewManifest.model_validate(value)

    value = _manifest()
    conversion = deepcopy(value["conversion"])
    assert isinstance(conversion, dict)
    conversion["review_pdf_sha256"] = "sha256:" + "a" * 64
    value["conversion"] = conversion
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="converter receipt"):
        ExternalItemPreviewManifest.model_validate(value)


@pytest.mark.parametrize("member_path", ["source/../outside", "source//original.hwp", "source/./a"])
def test_preview_model_rejects_unsafe_source_member(member_path: str) -> None:
    value = _manifest()
    value["source_member_path"] = member_path
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="source member path is unsafe"):
        ExternalItemPreviewManifest.model_validate(value)
