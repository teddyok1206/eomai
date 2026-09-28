from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from eom_identifiers import sha256_bytes as real_sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceObjectLineArtSuitabilityReview,
    LocalImageScienceVisualCampaignPatternInventory,
    ScienceVisualCampaignPilotResult,
)
from eom_orchestrator.science_visual_campaign_resolution import (
    ResolvedScienceVisualCampaign,
)

import scripts.image_trainer.publish_science_object_line_art_crop_set as publisher
from scripts.image_trainer.publish_science_object_line_art_crop_set import (
    _build_crop_set,
    _CandidateSource,
    _PerceptualIndex,
    _process_png,
    _ProcessedPng,
)
from tests.unit.test_science_corpus_visual_contracts import _object_line_art_values


def test_process_png_uses_literal_pixel_coordinates(monkeypatch) -> None:
    output = b"c" * 128
    metadata = {
        "height": 64,
        "perceptual_hash": "fedcba9876543210",
        "perceptual_value": 0xFEDCBA9876543210,
        "source_height": 100,
        "source_width": 120,
        "width": 80,
    }
    monkeypatch.setattr(
        publisher.subprocess,
        "run",
        lambda *_args, **_kwargs: type(
            "Completed",
            (),
            {"stdout": output, "stderr": json.dumps(metadata).encode()},
        )(),
    )

    inspected = _process_png(
        b"p" * 128,
        ImageEvaluationBoundingBox(left=10, top=20, right=90, bottom=84),
    )

    assert inspected.payload == output
    assert (inspected.width, inspected.height) == (80, 64)


def test_build_crop_set_materializes_exact_reviewed_24(monkeypatch, tmp_path: Path) -> None:
    (
        plan_values,
        result_values,
        plan_pointer_values,
        result_pointer_values,
        inventory_value,
        review_value,
        _,
    ) = _object_line_art_values()
    plans = tuple(LocalImageScienceCorpusVisualPilotPlanV3.model_validate(v) for v in plan_values)
    results = tuple(
        LocalImageScienceCorpusVisualPilotResult.model_validate(v) for v in result_values
    )
    plan_pointers = tuple(
        ImageEvaluationArtifactMember.model_validate(v) for v in plan_pointer_values
    )
    result_pointers = tuple(
        ImageEvaluationArtifactMember.model_validate(v) for v in result_pointer_values
    )
    inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(inventory_value)
    review = LocalImageScienceObjectLineArtSuitabilityReview.model_validate(review_value)
    pilots = tuple(
        ScienceVisualCampaignPilotResult.model_validate(v) for v in inventory.pilot_results
    )
    campaign = ResolvedScienceVisualCampaign(
        campaign_id=inventory.campaign_id,
        pilots=pilots,
        candidate_ids=tuple(
            sorted(v.candidate_id for result in results for v in result.visual_candidates)
        ),
        plans=plans,
        plan_pointers=plan_pointers,
        results=results,
        result_pointers=result_pointers,
    )
    sources: dict[str, _CandidateSource] = {}
    source_payloads: dict[bytes, str] = {}
    payload_by_path: dict[Path, bytes] = {}
    for pilot, plan, result in zip(pilots, plans, results, strict=True):
        by_document = {source.document_id: source for source in plan.selected_sources}
        for candidate in result.visual_candidates:
            payload = candidate.candidate_id.encode().ljust(candidate.size_bytes, b"x")
            source_payloads[payload] = candidate.sha256
            sources[candidate.candidate_id] = _CandidateSource(
                candidate=candidate,
                source=by_document[candidate.document_id],
                path=Path(pilot.attempt_id) / f"{candidate.candidate_id}.png",
            )
            payload_by_path[sources[candidate.candidate_id].path] = payload
    monkeypatch.setattr(publisher, "_candidate_sources", lambda _campaign: sources)
    monkeypatch.setattr(publisher, "_safe_read_png", lambda path: payload_by_path[path])
    monkeypatch.setattr(
        publisher._PerceptualIndex,
        "contains_near_duplicate",
        lambda _self, _value: False,
    )
    monkeypatch.setattr(
        publisher,
        "sha256_bytes",
        lambda payload: source_payloads.get(payload, real_sha256_bytes(payload)),
    )
    counter = 0

    def process_png(payload: bytes, box: ImageEvaluationBoundingBox) -> _ProcessedPng:
        nonlocal counter
        counter += 1
        output = (b"crop:" + hashlib.sha256(payload).digest()).ljust(96, bytes([counter]))
        perceptual_value = int(hashlib.sha256(b"phash:" + payload).hexdigest()[:16], 16)
        perceptual_hash = f"{perceptual_value:016x}"
        return _ProcessedPng(
            payload=output,
            width=box.right - box.left,
            height=box.bottom - box.top,
            perceptual_hash=perceptual_hash,
            perceptual_value=perceptual_value,
        )

    review_pointer = ImageEvaluationArtifactMember.model_validate(
        {
            "artifact_id": "artifact_" + "f" * 32,
            "artifact_revision_id": "rev_" + "e" * 32,
            "member_path": "manifests/science-object-line-art-suitability-review.json",
            "schema_ref": (
                "eom://schemas/image-provider/"
                "local-image-science-object-line-art-suitability-review/1.0"
            ),
            "media_type": "application/json",
            "sha256": real_sha256_bytes(
                publisher.content_json_bytes(review.model_dump(mode="json"))
            ),
        }
    )
    crop_set, materialized = _build_crop_set(
        campaign=campaign,
        inventory=inventory,
        review=review,
        review_pointer=review_pointer,
        temporary=tmp_path,
        created_at=datetime(2026, 9, 28, 14, 0, tzinfo=UTC),
        created_by="orchestrator_line_art_crop_set",
        process_png=process_png,
    )

    assert len(materialized) == 24
    assert len(crop_set.members) == 24
    assert {value.member.partition for value in materialized} == {
        "TRAIN",
        "VALIDATION",
        "HOLDOUT",
    }
    assert all((tmp_path / f"{value.member.sample_id}.png").is_file() for value in materialized)


def test_perceptual_index_rejects_only_bounded_near_duplicates() -> None:
    index = _PerceptualIndex()
    index.add(0)
    assert index.contains_near_duplicate(1)
    assert index.contains_near_duplicate(3)
    assert not index.contains_near_duplicate(7)
