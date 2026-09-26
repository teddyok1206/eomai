from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    content_json_bytes,
)

import scripts.image_trainer.publish_science_visual_campaign_crop_set as publisher
from scripts.image_trainer.publish_science_visual_campaign_crop_set import (
    _load_inputs,
    _PerceptualIndex,
    _process_png,
)
from tests.unit.test_science_corpus_visual_contracts import _campaign_crop_successor_values


def _input_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    values = _campaign_crop_successor_values()
    plan_values, result_values, plan_pointer_values, result_pointer_values = values[:4]
    inventory, review, refinement_plan = values[4:7]
    plan_payload = content_json_bytes(refinement_plan)
    plan_pointer = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="manifests/science-campaign-raster-refinement-plan.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-campaign-raster-refinement-plan/1.0"
        ),
        media_type="application/json",
        sha256=sha256_bytes(plan_payload),
    )
    receipt_path = tmp_path / "refinement-receipt.json"
    receipt_path.write_bytes(
        content_json_bytes(
            {
                "schema_version": (
                    "science-campaign-raster-refinement-plan-publication-receipt/1.0"
                ),
                "refinement_plan_id": refinement_plan["refinement_plan_id"],
                "refinement_plan_sha256": refinement_plan["plan_sha256"],
                "refinement_plan_artifact": plan_pointer.model_dump(mode="json"),
            }
        )
    )
    receipt_path.chmod(0o600)
    monkeypatch.setattr(
        publisher,
        "resolve_science_visual_campaign",
        lambda *_args, **_kwargs: SimpleNamespace(
            campaign_id=refinement_plan["campaign_id"],
            plans=tuple(
                LocalImageScienceCorpusVisualPilotPlanV3.model_validate(value)
                for value in plan_values
            ),
            plan_pointers=tuple(
                ImageEvaluationArtifactMember.model_validate(value) for value in plan_pointer_values
            ),
            results=tuple(
                LocalImageScienceCorpusVisualPilotResult.model_validate(value)
                for value in result_values
            ),
            result_pointers=tuple(
                ImageEvaluationArtifactMember.model_validate(value)
                for value in result_pointer_values
            ),
        ),
    )

    def resolve(_engine, pointer, *, maximum_bytes: int) -> bytes:
        assert maximum_bytes == publisher.MAX_JSON_BYTES
        if pointer == plan_pointer:
            return plan_payload
        if pointer.schema_ref.endswith("campaign-pattern-inventory/1.0"):
            return content_json_bytes(inventory)
        return content_json_bytes(review)

    monkeypatch.setattr(publisher, "resolve_control_artifact_member", resolve)
    return receipt_path


def test_load_inputs_resolves_approved_campaign_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path = _input_fixture(tmp_path, monkeypatch)

    campaign, inventory, review, plan, pointer = _load_inputs(
        engine=object(),  # type: ignore[arg-type]
        attempt_ids=("imgscivisattempt_" + "1" * 32, "imgscivisattempt_" + "2" * 32),
        receipt_path=receipt_path,
    )

    assert campaign.campaign_id == inventory.campaign_id == plan.campaign_id
    assert review.review_sha256 == plan.raster_suitability_review_sha256
    assert pointer.sha256 == sha256_bytes(content_json_bytes(plan.model_dump(mode="json")))


def test_process_png_requires_direct_bytes_to_remain_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"p" * 128
    metadata = {
        "height": 80,
        "perceptual_hash": "0123456789abcdef",
        "perceptual_value": 0x0123456789ABCDEF,
        "source_height": 80,
        "source_width": 100,
        "width": 100,
    }
    monkeypatch.setattr(
        publisher.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=payload,
            stderr=json.dumps(metadata).encode(),
        ),
    )

    inspected = _process_png(payload, None)

    assert inspected.payload == payload
    assert inspected.width == 100
    assert inspected.height == 80


def test_process_png_checks_literal_crop_pixel_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = b"c" * 128
    metadata = {
        "height": 64,
        "perceptual_hash": "fedcba9876543210",
        "perceptual_value": 0xFEDCBA9876543210,
        "source_height": 80,
        "source_width": 100,
        "width": 80,
    }
    monkeypatch.setattr(
        publisher.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=output,
            stderr=json.dumps(metadata).encode(),
        ),
    )

    inspected = _process_png(
        b"p" * 128,
        ImageEvaluationBoundingBox(left=1000, top=1000, right=9000, bottom=9000),
    )

    assert inspected.payload == output
    assert (inspected.width, inspected.height) == (80, 64)


def test_perceptual_index_detects_only_bounded_near_duplicates() -> None:
    index = _PerceptualIndex()
    index.add(0)
    assert index.contains_near_duplicate(1)
    assert index.contains_near_duplicate(3)
    assert not index.contains_near_duplicate(7)
