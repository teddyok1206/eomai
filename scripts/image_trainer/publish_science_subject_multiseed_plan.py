#!/usr/bin/env python3
"""Build and publish one pinned science-subject multi-seed plan."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_service.science_visual_subject_multiseed import (
    build_science_visual_subject_multiseed_plan,
)
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectBenchmarkResult,
    LocalImageScienceVisualSubjectBenchmarkReview,
    LocalImageScienceVisualSubjectInventory,
    content_json_bytes,
    validate_contract,
    validate_science_visual_subject_benchmark_plan,
    validate_science_visual_subject_benchmark_review,
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

from scripts.image_trainer.stage_crop_locator import (
    MAX_JSON_BYTES,
    _parse_json,
    _require_release,
    _write_exclusive,
)

STATE_ROOT = Path("/var/lib/eom-workflow-runner")


class ScienceSubjectMultiseedPlanPublicationError(RuntimeError):
    """Stable operator error for multi-seed plan publication."""


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


def _pointer(args: argparse.Namespace) -> ImageEvaluationArtifactMember:
    try:
        return ImageEvaluationArtifactMember(
            artifact_id=args.review_artifact_id,
            artifact_revision_id=args.review_artifact_revision_id,
            member_path="manifests/science-visual-subject-benchmark-review.json",
            schema_ref=(
                "eom://schemas/image-provider/"
                "local-image-science-visual-subject-benchmark-review/1.0"
            ),
            media_type="application/json",
            sha256=args.review_artifact_sha256,
        )
    except ValueError as exc:
        raise ScienceSubjectMultiseedPlanPublicationError(
            "SCIENCE_SUBJECT_MULTISEED_REVIEW_POINTER_INVALID"
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
        raise ScienceSubjectMultiseedPlanPublicationError(
            "SCIENCE_SUBJECT_MULTISEED_SOURCE_INVALID"
        ) from exc
    canonical = content_json_bytes(parsed.model_dump(mode="json"))
    if payload not in {canonical, canonical + b"\n"}:
        raise ScienceSubjectMultiseedPlanPublicationError(
            "SCIENCE_SUBJECT_MULTISEED_SOURCE_INVALID"
        )
    return parsed


def _write_receipt(path: Path, payload: bytes) -> None:
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.read_bytes() != payload:
            raise ScienceSubjectMultiseedPlanPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_PLAN_RECEIPT_CONFLICT"
            )
        return
    _write_exclusive(path, payload, mode=0o600)


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    if args.created_at.tzinfo is None or args.created_at.utcoffset() != UTC.utcoffset(
        args.created_at
    ):
        raise ScienceSubjectMultiseedPlanPublicationError(
            "SCIENCE_SUBJECT_MULTISEED_CREATED_AT_INVALID"
        )
    review_pointer = _pointer(args)
    engine = build_engine()
    try:
        review = _resolve_typed(
            engine,
            review_pointer,
            contract="science-visual-subject-benchmark-review",
            model=LocalImageScienceVisualSubjectBenchmarkReview,
        )
        inventory = _resolve_typed(
            engine,
            review.subject_inventory,
            contract="science-visual-subject-inventory",
            model=LocalImageScienceVisualSubjectInventory,
        )
        initial_plan = _resolve_typed(
            engine,
            review.benchmark_plan,
            contract="science-visual-subject-benchmark-plan",
            model=LocalImageScienceVisualSubjectBenchmarkPlan,
        )
        initial_result = _resolve_typed(
            engine,
            review.benchmark_result,
            contract="science-visual-subject-benchmark-result",
            model=LocalImageScienceVisualSubjectBenchmarkResult,
        )
        validate_science_visual_subject_benchmark_plan(inventory, initial_plan)
        if initial_result.plan_id != initial_plan.plan_id:
            raise ScienceSubjectMultiseedPlanPublicationError(
                "SCIENCE_SUBJECT_MULTISEED_SOURCE_INVALID"
            )
        validate_science_visual_subject_benchmark_review(
            inventory,
            initial_plan,
            initial_result,
            review,
        )
        plan = build_science_visual_subject_multiseed_plan(
            inventory=inventory,
            initial_plan=initial_plan,
            initial_plan_pointer=review.benchmark_plan,
            initial_review=review,
            initial_review_pointer=review_pointer,
            created_at=args.created_at,
            created_by=args.created_by,
        )
        summary = {
            "case_count": len(plan.cases),
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "subject_count": len({value.subject_id for value in plan.cases}),
        }
        if args.preflight_only:
            print(json.dumps({**summary, "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        pointer = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        ).commit_science_visual_subject_multiseed_plan(plan)
    finally:
        engine.dispose()
    receipt = {
        "schema_version": "science-subject-multiseed-plan-publication-receipt/1.0",
        **summary,
        "plan_artifact": pointer.model_dump(mode="json"),
        "source_commit": args.source_commit,
    }
    receipt_path = STATE_ROOT / f"science-subject-multiseed-plan-{plan.plan_id}.json"
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
