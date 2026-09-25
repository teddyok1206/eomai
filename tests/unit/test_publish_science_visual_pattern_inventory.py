from __future__ import annotations

import json
from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_image_contracts import content_json_bytes, content_sha256

from scripts.image_trainer.publish_science_visual_pattern_inventory import (
    ScienceVisualPatternPublicationError,
    _load_inputs,
)


def _write(path: Path, value: dict[str, object]) -> bytes:
    payload = content_json_bytes(value)
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def _result_value() -> dict[str, object]:
    document_id = "sciencedoc_" + "1" * 32
    page_sha256 = "sha256:" + "2" * 64
    candidate_body: dict[str, object] = {
        "document_id": document_id,
        "physical_page": 1,
        "page_image_sha256": page_sha256,
        "bounding_box": {"left": 1000, "top": 1000, "right": 8000, "bottom": 7000},
        "representation_kind": "UNKNOWN",
        "rendering_mode": "MIXED",
        "visual_features": [],
        "authority_class": "UNKNOWN_REVIEW_REQUIRED",
        "review_state": "PENDING",
        "locator_score_milli": 300,
    }
    candidate_id = (
        "imgsciviscandidate_" + content_sha256(candidate_body).removeprefix("sha256:")[:32]
    )
    body: dict[str, object] = {
        "schema_version": "local-image-science-corpus-visual-pilot-result/1.0",
        "pilot_id": "imgscivispilot_" + "3" * 32,
        "plan_sha256": "sha256:" + "4" * 64,
        "status": "SUCCEEDED",
        "page_images": [
            {
                "document_id": document_id,
                "physical_page": 1,
                "member_path": f"pages/{document_id}/page-1.png",
                "sha256": page_sha256,
                "size_bytes": 1024,
                "width_px": 1000,
                "height_px": 1400,
            }
        ],
        "visual_candidates": [
            {
                "candidate_id": candidate_id,
                **candidate_body,
                "member_path": f"crops/{candidate_id}.png",
                "sha256": "sha256:" + "5" * 64,
                "size_bytes": 512,
            }
        ],
        "omissions": [],
        "runtime": {
            "python_version": "3.11",
            "pillow_version": "11.3",
            "opencv_version": "4.11",
            "tesseract_version": "5.3",
            "pdftoppm_version": "24.02",
        },
        "error_code": None,
        "started_at": "2026-09-25T18:00:00Z",
        "completed_at": "2026-09-25T18:01:00Z",
    }
    return {**body, "result_sha256": content_sha256(body)}


def _inventory_value(*, result: dict[str, object], pointer: dict[str, object]) -> dict[str, object]:
    candidate_id = result["visual_candidates"][0]["candidate_id"]
    body: dict[str, object] = {
        "schema_version": "local-image-science-visual-pattern-inventory/1.1",
        "pilot_result": pointer,
        "pilot_result_file_sha256": pointer["sha256"],
        "pilot_result_semantic_sha256": result["result_sha256"],
        "reviews": [
            {
                "candidate_id": candidate_id,
                "decision": "EXCLUDED",
                "pattern_family": "OTHER",
                "visual_features": [],
                "caption_en": None,
                "caption_sha256": None,
                "reviewed_by": "reviewer_user",
                "reviewed_at": "2026-09-25T18:02:00Z",
            }
        ],
        "primitive_recommendations": [],
        "lora_eligible_count": 0,
        "deterministic_renderer_count": 0,
        "excluded_count": 1,
        "created_at": "2026-09-25T18:03:00Z",
        "created_by": "reviewer_user",
    }
    identity = content_sha256(body).removeprefix("sha256:")
    body["inventory_id"] = "imgscivisinventory_" + identity[:32]
    return {**body, "inventory_sha256": content_sha256(body)}


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    attempt_id = "imgscivisattempt_" + "6" * 32
    result = _result_value()
    result_path = tmp_path / "result.json"
    result_payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    result_path.write_bytes(result_payload)
    result_path.chmod(0o600)
    canonical_result_payload = content_json_bytes(result)
    pointer: dict[str, object] = {
        "artifact_id": "artifact_" + "7" * 32,
        "artifact_revision_id": "rev_" + "8" * 32,
        "member_path": "manifests/visual-pilot-result.json",
        "schema_ref": (
            "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-result/1.0"
        ),
        "media_type": "application/json",
        "sha256": sha256_bytes(canonical_result_payload),
    }
    receipt_path = tmp_path / "receipt.json"
    _write(
        receipt_path,
        {
            "schema_version": "science-visual-pilot-publication-receipt/1.0",
            "attempt_id": attempt_id,
            "result_sha256": result["result_sha256"],
            "result_file_sha256": sha256_bytes(result_payload),
            "result_artifact": pointer,
        },
    )
    inventory_path = tmp_path / "inventory.json"
    _write(inventory_path, _inventory_value(result=result, pointer=pointer))
    return result_path, receipt_path, inventory_path, attempt_id


def test_load_inputs_binds_exact_result_file_semantics_and_inventory(tmp_path: Path) -> None:
    result_path, receipt_path, inventory_path, attempt_id = _fixture(tmp_path)
    result, inventory, pointer = _load_inputs(
        attempt_id=attempt_id,
        result_path=result_path,
        result_publication_receipt_path=receipt_path,
        inventory_path=inventory_path,
    )
    assert inventory.pilot_result_file_sha256 == pointer.sha256
    assert inventory.pilot_result_semantic_sha256 == result.result_sha256
    assert pointer.sha256 != sha256_bytes(result_path.read_bytes())


def test_load_inputs_rejects_pointer_and_semantic_drift(tmp_path: Path) -> None:
    result_path, receipt_path, inventory_path, attempt_id = _fixture(tmp_path)
    inventory = json.loads(inventory_path.read_bytes())
    inventory["pilot_result_semantic_sha256"] = "sha256:" + "9" * 64
    body = {
        key: value
        for key, value in inventory.items()
        if key not in {"inventory_id", "inventory_sha256"}
    }
    inventory["inventory_id"] = (
        "imgscivisinventory_" + content_sha256(body).removeprefix("sha256:")[:32]
    )
    inventory["inventory_sha256"] = content_sha256(
        {key: value for key, value in inventory.items() if key != "inventory_sha256"}
    )
    inventory_path.unlink()
    _write(inventory_path, inventory)
    with pytest.raises(ScienceVisualPatternPublicationError, match="INPUT_INVALID"):
        _load_inputs(
            attempt_id=attempt_id,
            result_path=result_path,
            result_publication_receipt_path=receipt_path,
            inventory_path=inventory_path,
        )

    _, receipt_path, inventory_path, attempt_id = _fixture(tmp_path / "second")
    receipt = json.loads(receipt_path.read_bytes())
    receipt["result_artifact"]["artifact_revision_id"] = "rev_" + "a" * 32
    receipt_path.unlink()
    _write(receipt_path, receipt)
    with pytest.raises(ScienceVisualPatternPublicationError, match="BINDING_INVALID"):
        _load_inputs(
            attempt_id=attempt_id,
            result_path=tmp_path / "second/result.json",
            result_publication_receipt_path=receipt_path,
            inventory_path=inventory_path,
        )
