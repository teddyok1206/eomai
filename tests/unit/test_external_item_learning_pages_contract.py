"""The worker's page PNGs must trace back to one pinned preview PDF."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_learning_pages import (
    EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA,
    ExternalItemLearningPageSet,
    validate_external_item_learning_page_set_for_source,
)
from eom_catalog_contracts.external_item_learning_source import ExternalItemLearningSource
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.test_external_item_learning_source_contract import _source

ROOT = Path(__file__).resolve().parents[2]


def _pages() -> dict[str, object]:
    source = _source()
    preview = source["preview_manifest"]
    assert isinstance(preview, dict)
    result: dict[str, object] = {
        "schema_version": "external-item-learning-page-set/1.0",
        "source_input_sha256": source["input_sha256"],
        "preview_artifact_id": source["preview_artifact_id"],
        "preview_artifact_revision_id": source["preview_artifact_revision_id"],
        "preview_pdf_sha256": preview["pdf_sha256"],
        "renderer": {
            "profile": "PDFTOPPM_PNG_SCALE_2400_V1",
            "pdfinfo_sha256": "sha256:" + "a" * 64,
            "pdftoppm_sha256": "sha256:" + "b" * 64,
        },
        "pages": [
            {
                "physical_page": index,
                "member_path": f"pages/page-{index:04d}.png",
                "sha256": "sha256:" + str(index) * 64,
                "content_length": 4096,
                "width_px": 800,
                "height_px": 1200,
            }
            for index in (1, 2)
        ],
    }
    result["manifest_sha256"] = content_sha256(result)
    return result


def _rehash(value: dict[str, object]) -> None:
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )


def test_page_set_schema_and_model_close_over_exact_preview() -> None:
    value = _pages()
    validate_contract(EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA, value)
    pages = ExternalItemLearningPageSet.model_validate(value)
    source = ExternalItemLearningSource.model_validate(_source())
    validate_external_item_learning_page_set_for_source(pages, source)
    assert pages.pages[1].member_path == "pages/page-0002.png"
    assert "pdf_member_path" not in value


def test_page_set_schema_mirror_is_exact() -> None:
    canonical = ROOT / "schemas/external-item/external-item-learning-page-set-v1.schema.json"
    resource = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/external-item"
        / "external-item-learning-page-set-v1.schema.json"
    )
    assert canonical.read_bytes() == resource.read_bytes()


def test_page_set_rejects_page_gap_or_swapped_member() -> None:
    value = _pages()
    pages = value["pages"]
    assert isinstance(pages, list) and isinstance(pages[1], dict)
    pages[1]["physical_page"] = 3
    pages[1]["member_path"] = "pages/page-0003.png"
    _rehash(value)
    validate_contract(EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA, value)
    with pytest.raises(ValidationError, match="ordered, contiguous"):
        ExternalItemLearningPageSet.model_validate(value)

    value = _pages()
    pages = value["pages"]
    assert isinstance(pages, list) and isinstance(pages[0], dict)
    pages[0]["member_path"] = "pages/page-0002.png"
    _rehash(value)
    with pytest.raises(ValidationError, match="differs from its physical page"):
        ExternalItemLearningPageSet.model_validate(value)


def test_page_set_rejects_stale_source_and_manifest_hash() -> None:
    value = _pages()
    value["preview_pdf_sha256"] = "sha256:" + "e" * 64
    _rehash(value)
    pages = ExternalItemLearningPageSet.model_validate(value)
    source = ExternalItemLearningSource.model_validate(_source())
    with pytest.raises(ValueError, match="pinned source PDF"):
        validate_external_item_learning_page_set_for_source(pages, source)

    value = _pages()
    value["preview_pdf_sha256"] = "sha256:" + "e" * 64
    with pytest.raises(ValidationError, match="manifest hash differs"):
        ExternalItemLearningPageSet.model_validate(value)


def test_page_set_schema_rejects_oversized_or_unsafe_pages() -> None:
    value = deepcopy(_pages())
    pages = value["pages"]
    assert isinstance(pages, list) and isinstance(pages[0], dict)
    pages[0]["member_path"] = "../../escape.png"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(EXTERNAL_ITEM_LEARNING_PAGE_SET_SCHEMA, value)
