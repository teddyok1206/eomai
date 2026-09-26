from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_image_contracts import content_json_bytes, content_sha256

from scripts.image_trainer.publish_science_campaign_raster_suitability_review import (
    ScienceCampaignRasterSuitabilityPublicationError,
    _load_inputs,
)
from tests.unit.test_science_corpus_visual_contracts import _campaign_raster_review_value


def _write(path: Path, value: dict[str, object]) -> bytes:
    payload = content_json_bytes(value)
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    inventory, review = _campaign_raster_review_value()
    inventory_path = tmp_path / "inventory.json"
    inventory_payload = _write(inventory_path, inventory)
    pointer = copy.deepcopy(review["pattern_inventory"])
    assert isinstance(pointer, dict)
    pointer["sha256"] = sha256_bytes(inventory_payload)
    review["pattern_inventory"] = pointer
    review["pattern_inventory_file_sha256"] = pointer["sha256"]
    body = {
        key: value for key, value in review.items() if key not in {"review_id", "review_sha256"}
    }
    review["review_id"] = (
        "imgsciviscampaignrasterreview_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    review["review_sha256"] = content_sha256(
        {key: value for key, value in review.items() if key != "review_sha256"}
    )
    receipt_path = tmp_path / "inventory-receipt.json"
    _write(
        receipt_path,
        {
            "schema_version": ("science-visual-campaign-pattern-inventory-publication-receipt/1.1"),
            "inventory_id": inventory["inventory_id"],
            "inventory_sha256": inventory["inventory_sha256"],
            "inventory_artifact": pointer,
        },
    )
    review_path = tmp_path / "review.json"
    _write(review_path, review)
    return inventory_path, receipt_path, review_path


def test_load_inputs_binds_campaign_inventory_and_complete_review(tmp_path: Path) -> None:
    inventory_path, receipt_path, review_path = _fixture(tmp_path)

    inventory, review, pointer = _load_inputs(
        inventory_path=inventory_path,
        inventory_receipt_path=receipt_path,
        review_path=review_path,
    )

    assert pointer.sha256 == sha256_bytes(inventory_path.read_bytes())
    assert review.pattern_inventory_semantic_sha256 == inventory.inventory_sha256
    assert review.gpu_raster_eligible_count == len(review.entries)


def test_load_inputs_rejects_noncanonical_or_unpinned_campaign_review(
    tmp_path: Path,
) -> None:
    inventory_path, receipt_path, review_path = _fixture(tmp_path)
    review = json.loads(review_path.read_text())
    review["pattern_inventory_semantic_sha256"] = "sha256:" + "0" * 64
    review_path.write_text(json.dumps(review), encoding="utf-8")
    review_path.chmod(0o600)

    with pytest.raises(
        ScienceCampaignRasterSuitabilityPublicationError,
        match="INPUT_INVALID",
    ):
        _load_inputs(
            inventory_path=inventory_path,
            inventory_receipt_path=receipt_path,
            review_path=review_path,
        )
