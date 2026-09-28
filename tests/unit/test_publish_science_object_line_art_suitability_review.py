from __future__ import annotations

import copy
from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_image_contracts import content_json_bytes

from scripts.image_trainer.publish_science_object_line_art_suitability_review import (
    ScienceObjectLineArtReviewPublicationError,
    _load_inputs,
)
from tests.unit.test_science_corpus_visual_contracts import _object_line_art_values


def _write(path: Path, value: dict[str, object]) -> bytes:
    payload = content_json_bytes(value)
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    *_, inventory, review, _crop_set = _object_line_art_values()
    inventory_path = tmp_path / "inventory.json"
    inventory_payload = _write(inventory_path, inventory)
    pointer = copy.deepcopy(review["pattern_inventory"])
    assert isinstance(pointer, dict)
    pointer["sha256"] = sha256_bytes(inventory_payload)
    review["pattern_inventory"] = pointer
    review_path = tmp_path / "review.json"
    _write(review_path, review)
    receipt_path = tmp_path / "inventory-receipt.json"
    _write(
        receipt_path,
        {
            "schema_version": "science-visual-campaign-pattern-inventory-publication-receipt/1.1",
            "inventory_id": inventory["inventory_id"],
            "inventory_sha256": inventory["inventory_sha256"],
            "inventory_artifact": pointer,
        },
    )
    return inventory_path, receipt_path, review_path


def test_load_inputs_binds_complete_object_line_art_review(tmp_path: Path) -> None:
    inventory_path, receipt_path, review_path = _fixture(tmp_path)

    inventory, review, pointer = _load_inputs(
        inventory_path=inventory_path,
        inventory_receipt_path=receipt_path,
        review_path=review_path,
    )

    assert pointer.sha256 == sha256_bytes(inventory_path.read_bytes())
    assert review.pattern_inventory_semantic_sha256 == inventory.inventory_sha256
    assert review.decision_counts.OBJECT_LINE_ART_ELIGIBLE == 24


def test_load_inputs_rejects_noncanonical_object_line_art_review(tmp_path: Path) -> None:
    inventory_path, receipt_path, review_path = _fixture(tmp_path)
    review_path.write_bytes(review_path.read_bytes() + b"\n")
    review_path.chmod(0o600)

    with pytest.raises(
        ScienceObjectLineArtReviewPublicationError,
        match="BINDING_INVALID",
    ):
        _load_inputs(
            inventory_path=inventory_path,
            inventory_receipt_path=receipt_path,
            review_path=review_path,
        )
