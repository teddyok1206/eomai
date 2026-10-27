"""Creative worker inputs pin one source and one immutable page Artifact."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.external_item_learning_work import (
    EXTERNAL_ITEM_LEARNING_WORK_INPUT_SCHEMA,
    ExternalItemLearningWorkInput,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.unit.test_external_item_learning_pages_contract import _pages
from tests.unit.test_external_item_learning_source_contract import _source

ROOT = Path(__file__).resolve().parents[2]


def _work() -> dict[str, object]:
    pages = _pages()
    value: dict[str, object] = {
        "schema_version": "external-item-learning-work-input/1.0",
        "request_id": "extlearnreq_" + "f" * 32,
        "source": _source(),
        "page_set": pages,
        "page_artifact": {
            "artifact_type": "control_external_item_learning_pages",
            "artifact_id": "artifact_" + "e" * 32,
            "artifact_revision_id": "rev_" + "d" * 32,
            "member_path": "page-set-manifest.json",
            "schema_ref": "eom://schemas/external-item/learning-page-set/1.0",
            "media_type": "application/json",
            "sha256": sha256_bytes(canonical_json_bytes(pages)),
            "file_set_manifest_sha256": "sha256:" + "c" * 64,
        },
    }
    value["request_sha256"] = content_sha256(value)
    return value


def _rehash(value: dict[str, object]) -> None:
    value["request_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "request_sha256"}
    )


def test_work_input_schema_and_model_pin_page_package_without_payloads() -> None:
    value = _work()
    validate_contract(EXTERNAL_ITEM_LEARNING_WORK_INPUT_SCHEMA, value)
    parsed = ExternalItemLearningWorkInput.model_validate(value)
    assert parsed.page_artifact.sha256 == sha256_bytes(
        canonical_json_bytes(parsed.page_set.model_dump(mode="json"))
    )
    assert parsed.source.external_number == "12345"
    assert not any(key in value for key in ("pdf_bytes", "page_bytes", "workspace_path"))


def test_work_input_schema_resource_matches_canonical_bytes() -> None:
    canonical = ROOT / "schemas/external-item/external-item-learning-work-input-v1.schema.json"
    resource = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/external-item"
        / "external-item-learning-work-input-v1.schema.json"
    )
    assert canonical.read_bytes() == resource.read_bytes()


def test_work_input_rejects_different_page_artifact_even_with_new_outer_hash() -> None:
    value = _work()
    pointer = value["page_artifact"]
    assert isinstance(pointer, dict)
    pointer["sha256"] = "sha256:" + "0" * 64
    _rehash(value)
    validate_contract(EXTERNAL_ITEM_LEARNING_WORK_INPUT_SCHEMA, value)
    with pytest.raises(ValidationError, match="differs from its manifest"):
        ExternalItemLearningWorkInput.model_validate(value)


def test_work_input_rejects_mismatched_source_and_page_set() -> None:
    value = _work()
    source = value["source"]
    assert isinstance(source, dict)
    source["external_number"] = "54321"
    source["input_sha256"] = content_sha256(
        {key: item for key, item in source.items() if key != "input_sha256"}
    )
    _rehash(value)
    with pytest.raises(ValidationError, match="pinned source PDF"):
        ExternalItemLearningWorkInput.model_validate(value)


def test_work_input_rejects_stale_outer_hash_and_untrusted_member_path() -> None:
    value = _work()
    value["request_id"] = "extlearnreq_" + "1" * 32
    with pytest.raises(ValidationError, match="work input hash differs"):
        ExternalItemLearningWorkInput.model_validate(value)

    value = deepcopy(_work())
    pointer = value["page_artifact"]
    assert isinstance(pointer, dict)
    pointer["member_path"] = "../../page-set-manifest.json"
    _rehash(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(EXTERNAL_ITEM_LEARNING_WORK_INPUT_SCHEMA, value)
