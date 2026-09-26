#!/usr/bin/env python3
"""Validate and publish one immutable campaign literal-crop refinement plan."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from eom_image_contracts import (
    LocalImageScienceVisualCampaignPatternInventory,
    LocalImageScienceVisualCampaignRasterRefinementPlan,
    LocalImageScienceVisualCampaignRasterSuitabilityReview,
    content_json_bytes,
    validate_contract,
    validate_science_visual_campaign_raster_refinement_plan,
)
from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.science_visual_campaign_resolution import (
    ScienceVisualCampaignResolutionError,
    parse_science_visual_campaign_object,
    resolve_science_visual_campaign,
    safe_read_science_visual_campaign_member,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
STATE_ROOT = Path("/var/lib/eom-workflow-runner")
MAX_JSON_BYTES = 16 * 1024 * 1024
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ScienceCampaignRefinementPublicationError(RuntimeError):
    """Stable operator-facing refinement-plan publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", action="append", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _load_plan_and_sources(
    *,
    engine: Engine,
    attempt_ids: tuple[str, ...],
    plan_path: Path,
) -> tuple[
    LocalImageScienceVisualCampaignRasterRefinementPlan,
    LocalImageScienceVisualCampaignPatternInventory,
    LocalImageScienceVisualCampaignRasterSuitabilityReview,
]:
    campaign = resolve_science_visual_campaign(
        attempt_ids,
        workspace_parent=WORKSPACE_PARENT,
        state_root=STATE_ROOT,
    )
    plan_payload = safe_read_science_visual_campaign_member(plan_path)
    try:
        plan_value = parse_science_visual_campaign_object(plan_payload)
        validate_contract("science-campaign-raster-refinement-plan", plan_value)
        plan = LocalImageScienceVisualCampaignRasterRefinementPlan.model_validate(plan_value)
        inventory_payload = resolve_control_artifact_member(
            engine,
            plan.pattern_inventory,
            maximum_bytes=MAX_JSON_BYTES,
        )
        review_payload = resolve_control_artifact_member(
            engine,
            plan.raster_suitability_review,
            maximum_bytes=MAX_JSON_BYTES,
        )
        inventory_value = parse_science_visual_campaign_object(inventory_payload)
        review_value = parse_science_visual_campaign_object(review_payload)
        validate_contract("science-visual-campaign-pattern-inventory", inventory_value)
        validate_contract("science-campaign-raster-suitability-review", review_value)
        inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(inventory_value)
        review = LocalImageScienceVisualCampaignRasterSuitabilityReview.model_validate(review_value)
        validate_science_visual_campaign_raster_refinement_plan(
            plans=campaign.plans,
            plan_pointers=campaign.plan_pointers,
            results=campaign.results,
            result_pointers=campaign.result_pointers,
            inventory=inventory,
            raster_suitability_review=review,
            plan=plan,
        )
    except ScienceVisualCampaignResolutionError:
        raise
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceCampaignRefinementPublicationError(
            "SCIENCE_CAMPAIGN_REFINEMENT_INPUT_INVALID"
        ) from exc
    if (
        campaign.campaign_id != plan.campaign_id
        or content_json_bytes(plan.model_dump(mode="json")) != plan_payload
        or content_json_bytes(inventory.model_dump(mode="json")) != inventory_payload
        or content_json_bytes(review.model_dump(mode="json")) != review_payload
    ):
        raise ScienceCampaignRefinementPublicationError(
            "SCIENCE_CAMPAIGN_REFINEMENT_BINDING_INVALID"
        )
    return plan, inventory, review


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if safe_read_science_visual_campaign_member(path) != payload:
            raise ScienceCampaignRefinementPublicationError(
                "SCIENCE_CAMPAIGN_REFINEMENT_RECEIPT_CONFLICT"
            )
        return
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def main() -> int:
    args = _parser().parse_args()
    attempt_ids = tuple(args.attempt_id)
    if (
        os.geteuid() != 0
        or not 2 <= len(attempt_ids) <= 4
        or attempt_ids != tuple(sorted(set(attempt_ids)))
        or any(_ATTEMPT.fullmatch(value) is None for value in attempt_ids)
        or _COMMIT.fullmatch(args.source_commit) is None
        or not args.plan.is_absolute()
    ):
        raise ScienceCampaignRefinementPublicationError(
            "SCIENCE_CAMPAIGN_REFINEMENT_ARGUMENT_INVALID"
        )
    engine = build_engine()
    try:
        plan, inventory, review = _load_plan_and_sources(
            engine=engine,
            attempt_ids=attempt_ids,
            plan_path=args.plan,
        )
        summary = {
            "campaign_id": plan.campaign_id,
            "inventory_id": inventory.inventory_id,
            "inventory_sha256": inventory.inventory_sha256,
            "proposal_count": len(plan.proposals),
            "refinement_plan_id": plan.refinement_plan_id,
            "refinement_plan_sha256": plan.plan_sha256,
            "raster_suitability_review_id": review.review_id,
            "raster_suitability_review_sha256": review.review_sha256,
        }
        if args.preflight_only:
            print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
            return 0
        pointer = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        ).commit_science_campaign_raster_refinement_plan(plan)
    finally:
        engine.dispose()
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / (
        f"science-campaign-raster-refinement-plan-publication-{plan.refinement_plan_id}.json"
    )
    _write_receipt(
        receipt_path,
        content_json_bytes(
            {
                "schema_version": (
                    "science-campaign-raster-refinement-plan-publication-receipt/1.0"
                ),
                **summary,
                "refinement_plan_artifact": pointer.model_dump(mode="json"),
                "source_commit": args.source_commit,
            }
        ),
    )
    print(
        json.dumps(
            {
                "artifact_id": pointer.artifact_id,
                "artifact_revision_id": pointer.artifact_revision_id,
                "receipt": str(receipt_path),
                "refinement_plan_id": plan.refinement_plan_id,
                "refinement_plan_sha256": plan.plan_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
