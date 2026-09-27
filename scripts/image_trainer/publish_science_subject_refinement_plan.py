#!/usr/bin/env python3
"""Build and publish one evidence-bound science-subject refinement plan."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkResult,
    LocalImageScienceVisualSubjectBenchmarkReview,
    LocalImageScienceVisualSubjectInventory,
    LocalImageScienceVisualSubjectMultiseedPlan,
    LocalImageScienceVisualSubjectMultiseedResult,
    LocalImageScienceVisualSubjectMultiseedReview,
    build_science_visual_subject_refinement_plan,
    content_json_bytes,
    validate_contract,
    validate_science_visual_subject_benchmark_review,
    validate_science_visual_subject_multiseed_review,
)
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    resolve_control_artifact_member,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_trainer.publication_io import PublicationFileReadError, read_regular_file
from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    _parse_json,
    _require_release,
    _write_exclusive,
)

STATE_ROOT = Path("/var/lib/eom-workflow-runner")

# These are evaluation candidates, not production prompts. Each is content-bound in the plan and
# must pass a later route-specific benchmark before any successor inventory or provider binding.
CANDIDATE_PROMPTS = {
    "AIR_CUSHION_PACKAGING": (
        "monochrome Korean science assessment illustration of one rectangular inflated air-cushion "
        "landing pad with repeated sealed air cells, three-quarter view, white background, "
        "no people, no text, no labels, no border"
    ),
    "APPLE_TREE": (
        "monochrome Korean science assessment background showing one apple tree branch with leaves "
        "and three clearly separated apples, side view, white background, no people, no text, no "
        "labels, leave annotations to a vector overlay"
    ),
    "BIODIVERSITY": (
        "monochrome Korean science assessment background showing one flowering plant, one beetle, "
        "and one fish as three separated non-human biodiversity examples in a row, white "
        "background, no text, no labels, leave annotations to a vector overlay"
    ),
    "BURR_FRUIT": (
        "monochrome Korean science assessment close-up of one hooked burr fruit seed head "
        "with many distinct curved hooks and a short stem, centered on white, no text, "
        "no labels, no border"
    ),
    "CLOUD_WEATHER": (
        "monochrome Korean science assessment weather scene with three distinct cloud formations "
        "above a minimal horizon, restrained grayscale, white background, no people, no text, no "
        "labels, no decorative border"
    ),
    "CONSUMER_SCIENCE_PRODUCT": (
        "monochrome Korean science assessment line-art reference showing a safety helmet, a rubber "
        "tire, and an air cushion as three separate simple objects, white background, "
        "no people, no text, no labels, leave exact callouts to SVG"
    ),
    "FOSSIL": (
        "monochrome Korean science assessment illustration of one ammonite fossil embedded in an "
        "irregular rock slab with visible spiral ridges, centered on white, no text, no labels, no "
        "decorative border"
    ),
    "GEOLOGIC_ROCK": (
        "monochrome Korean science assessment illustration of three separate natural rock hand "
        "specimens with visibly different grain textures, centered on white, no text, "
        "no labels, no decorative border"
    ),
    "MICROSCOPIC_TISSUE": (
        "monochrome Korean science assessment microscope field showing repeated elongated plant "
        "tissue cells with natural irregular boundaries, restrained grayscale, no text, "
        "no labels, no decorative border"
    ),
    "NON_HUMAN_ANIMAL": (
        "monochrome Korean science assessment illustration of one small non-human animal in strict "
        "side profile with a clear silhouette and minimal texture, centered on white, no text, no "
        "labels, no decorative border"
    ),
    "OCEAN_WATER": (
        "monochrome non-authoritative Korean science assessment background showing a calm ocean "
        "surface and a simple underwater depth gradient, white margin, no people, no text, "
        "no labels, leave map boundaries and arrows to SVG"
    ),
    "SAFETY_EQUIPMENT": (
        "monochrome Korean science assessment line-art reference of one safety helmet in "
        "exact side view with a simple outer shell and inner padding, centered on white, "
        "no person, no text, no labels, leave callouts to SVG"
    ),
    "SPACECRAFT": (
        "monochrome Korean science assessment background showing one artificial satellite with a "
        "central body, two rectangular solar panels, and one dish antenna, isolated on white, no "
        "text, no labels, leave exact geometry to SVG"
    ),
    "STAR_FIELD": (
        "monochrome Korean science assessment astronomical field with sparse stars of three "
        "distinct point brightness levels on a clean light background, no nebula text, "
        "no labels, no border"
    ),
}


class ScienceSubjectRefinementPlanPublicationError(RuntimeError):
    """Stable operator-facing refinement-plan publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-artifact-id", required=True)
    parser.add_argument("--review-artifact-revision-id", required=True)
    parser.add_argument("--review-artifact-sha256", required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _review_pointer(args: argparse.Namespace) -> ImageEvaluationArtifactMember:
    try:
        return ImageEvaluationArtifactMember(
            artifact_id=args.review_artifact_id,
            artifact_revision_id=args.review_artifact_revision_id,
            member_path="manifests/science-visual-subject-multiseed-review.json",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-visual-subject-multiseed-review/1.0"
            ),
            media_type="application/json",
            sha256=args.review_artifact_sha256,
        )
    except ValueError as exc:
        raise ScienceSubjectRefinementPlanPublicationError(
            "SCIENCE_SUBJECT_REFINEMENT_REVIEW_POINTER_INVALID"
        ) from exc


def _resolve_typed[T: BaseModel](
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
    *,
    contract: str,
    model: type[T],
) -> T:
    try:
        payload = resolve_control_artifact_member(engine, pointer, maximum_bytes=MAX_JSON_BYTES)
        value = _parse_json(payload)
        validate_contract(contract, value)
        parsed = model.model_validate(value)
    except (
        ControlArtifactResolutionError,
        JsonSchemaValidationError,
        PydanticValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise ScienceSubjectRefinementPlanPublicationError(
            "SCIENCE_SUBJECT_REFINEMENT_SOURCE_INVALID"
        ) from exc
    canonical = content_json_bytes(parsed.model_dump(mode="json"))
    if payload not in {canonical, canonical + b"\n"}:
        raise ScienceSubjectRefinementPlanPublicationError(
            "SCIENCE_SUBJECT_REFINEMENT_SOURCE_INVALID"
        )
    return parsed


def _write_receipt(path: Path, payload: bytes) -> None:
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        try:
            existing = read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
        except PublicationFileReadError as exc:
            raise ScienceSubjectRefinementPlanPublicationError(
                "SCIENCE_SUBJECT_REFINEMENT_RECEIPT_INVALID"
            ) from exc
        if existing != payload:
            raise ScienceSubjectRefinementPlanPublicationError(
                "SCIENCE_SUBJECT_REFINEMENT_RECEIPT_CONFLICT"
            )
        return
    _write_exclusive(path, payload, mode=0o600)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    if args.created_at.tzinfo is None or args.created_at.utcoffset() != UTC.utcoffset(
        args.created_at
    ):
        raise ScienceSubjectRefinementPlanPublicationError(
            "SCIENCE_SUBJECT_REFINEMENT_CREATED_AT_INVALID"
        )
    review_pointer = _review_pointer(args)
    engine = build_engine()
    try:
        review = _resolve_typed(
            engine,
            review_pointer,
            contract="science-visual-subject-multiseed-review",
            model=LocalImageScienceVisualSubjectMultiseedReview,
        )
        multiseed_plan = _resolve_typed(
            engine,
            review.multiseed_plan,
            contract="science-visual-subject-multiseed-plan",
            model=LocalImageScienceVisualSubjectMultiseedPlan,
        )
        multiseed_result = _resolve_typed(
            engine,
            review.multiseed_result,
            contract="science-visual-subject-multiseed-result",
            model=LocalImageScienceVisualSubjectMultiseedResult,
        )
        initial_review = _resolve_typed(
            engine,
            review.initial_quality_review,
            contract="science-visual-subject-benchmark-review",
            model=LocalImageScienceVisualSubjectBenchmarkReview,
        )
        inventory = _resolve_typed(
            engine,
            initial_review.subject_inventory,
            contract="science-visual-subject-inventory",
            model=LocalImageScienceVisualSubjectInventory,
        )
        initial_plan = _resolve_typed(
            engine,
            initial_review.benchmark_plan,
            contract="science-visual-subject-benchmark-plan",
            model=LocalImageScienceVisualSubjectBenchmarkPlan,
        )
        initial_result = _resolve_typed(
            engine,
            initial_review.benchmark_result,
            contract="science-visual-subject-benchmark-result",
            model=LocalImageScienceVisualSubjectBenchmarkResult,
        )
        try:
            validate_science_visual_subject_benchmark_review(
                inventory,
                initial_plan,
                initial_result,
                initial_review,
            )
            validate_science_visual_subject_multiseed_review(
                initial_plan,
                initial_result,
                initial_review,
                multiseed_plan,
                multiseed_result,
                review,
                plan_pointer=review.multiseed_plan,
                result_pointer=review.multiseed_result,
                initial_review_pointer=review.initial_quality_review,
            )
            plan = build_science_visual_subject_refinement_plan(
                inventory=inventory,
                inventory_pointer=initial_review.subject_inventory,
                review=review,
                review_pointer=review_pointer,
                candidate_prompts=CANDIDATE_PROMPTS,
                created_at=args.created_at,
                created_by=args.created_by,
            )
        except ValueError as exc:
            raise ScienceSubjectRefinementPlanPublicationError(
                "SCIENCE_SUBJECT_REFINEMENT_PLAN_INVALID"
            ) from exc
        dispositions: dict[str, int] = {}
        for strategy in plan.strategies:
            dispositions[strategy.production_disposition] = (
                dispositions.get(strategy.production_disposition, 0) + 1
            )
        summary = {
            "dispositions": dispositions,
            "global_adapter_activation": plan.global_adapter_activation,
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "subject_count": len(plan.strategies),
        }
        if args.preflight_only:
            print(json.dumps({**summary, "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        pointer = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        ).commit_science_visual_subject_refinement_plan(plan)
    finally:
        engine.dispose()
    receipt = {
        "schema_version": "science-subject-refinement-plan-publication-receipt/1.0",
        **summary,
        "plan_artifact": pointer.model_dump(mode="json"),
        "source_commit": args.source_commit,
    }
    receipt_path = STATE_ROOT / f"science-subject-refinement-plan-{plan.plan_id}.json"
    _write_receipt(receipt_path, content_json_bytes(receipt))
    print(
        json.dumps(
            {**summary, "plan_artifact": pointer.model_dump(mode="json"), "status": "PUBLISHED"},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
