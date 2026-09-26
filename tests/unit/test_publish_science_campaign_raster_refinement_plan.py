from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    content_json_bytes,
)

import scripts.image_trainer.publish_science_campaign_raster_refinement_plan as publisher
from scripts.image_trainer.publish_science_campaign_raster_refinement_plan import (
    ScienceCampaignRefinementPublicationError,
    _load_plan_and_sources,
)
from tests.unit.test_science_corpus_visual_contracts import _campaign_crop_successor_values


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    values = _campaign_crop_successor_values()
    plan_values, result_values, plan_pointer_values, result_pointer_values = values[:4]
    inventory, review, refinement_plan = values[4:7]
    plan_path = tmp_path / "refinement-plan.json"
    plan_path.write_bytes(content_json_bytes(refinement_plan))
    plan_path.chmod(0o600)
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
        if (
            pointer
            == publisher.LocalImageScienceVisualCampaignRasterRefinementPlan.model_validate(
                refinement_plan
            ).pattern_inventory
        ):
            return content_json_bytes(inventory)
        return content_json_bytes(review)

    monkeypatch.setattr(publisher, "resolve_control_artifact_member", resolve)
    return plan_path


def test_load_plan_and_sources_validates_complete_campaign_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = _fixture(tmp_path, monkeypatch)

    plan, inventory, review = _load_plan_and_sources(
        engine=object(),  # type: ignore[arg-type]
        attempt_ids=("imgscivisattempt_" + "1" * 32, "imgscivisattempt_" + "2" * 32),
        plan_path=plan_path,
    )

    assert plan.campaign_id == inventory.campaign_id
    assert plan.raster_suitability_review_sha256 == review.review_sha256


def test_load_plan_and_sources_rejects_noncanonical_local_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = _fixture(tmp_path, monkeypatch)
    plan_path.write_bytes(plan_path.read_bytes() + b"\n")

    with pytest.raises(ScienceCampaignRefinementPublicationError, match="BINDING_INVALID"):
        _load_plan_and_sources(
            engine=object(),  # type: ignore[arg-type]
            attempt_ids=("imgscivisattempt_" + "1" * 32, "imgscivisattempt_" + "2" * 32),
            plan_path=plan_path,
        )
