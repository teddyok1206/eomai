#!/usr/bin/env python3
"""Publish one validated science-subject benchmark plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eom_image_contracts import (
    LocalImageScienceVisualSubjectBenchmarkPlan,
    LocalImageScienceVisualSubjectInventory,
    content_json_bytes,
    validate_contract,
    validate_science_visual_subject_benchmark_plan,
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
from pydantic import ValidationError as PydanticValidationError

from scripts.image_trainer.publication_io import (
    PublicationFileReadError,
    read_regular_file,
)
from scripts.image_trainer.stage_crop_locator import MAX_JSON_BYTES, _parse_json, _require_release


class ScienceSubjectBenchmarkPlanPublicationError(RuntimeError):
    """Stable operator-facing plan publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _load_plan(path: Path) -> tuple[bytes, LocalImageScienceVisualSubjectBenchmarkPlan]:
    try:
        payload = read_regular_file(path, maximum_bytes=MAX_JSON_BYTES)
        value = _parse_json(payload)
        validate_contract("science-visual-subject-benchmark-plan", value)
        plan = LocalImageScienceVisualSubjectBenchmarkPlan.model_validate(value)
    except (
        PublicationFileReadError,
        PydanticValidationError,
        TypeError,
        ValueError,
    ) as exc:
        raise ScienceSubjectBenchmarkPlanPublicationError(
            "SCIENCE_SUBJECT_BENCHMARK_PLAN_INVALID"
        ) from exc
    if payload != content_json_bytes(plan.model_dump(mode="json")):
        raise ScienceSubjectBenchmarkPlanPublicationError("SCIENCE_SUBJECT_BENCHMARK_PLAN_INVALID")
    return payload, plan


def main() -> int:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    _payload, plan = _load_plan(args.plan)
    engine = build_engine()
    try:
        try:
            inventory_payload = resolve_control_artifact_member(
                engine, plan.subject_inventory, maximum_bytes=MAX_JSON_BYTES
            )
            inventory_value = _parse_json(inventory_payload)
            validate_contract("science-visual-subject-inventory", inventory_value)
            inventory = LocalImageScienceVisualSubjectInventory.model_validate(inventory_value)
            validate_science_visual_subject_benchmark_plan(inventory, plan)
        except (
            ControlArtifactResolutionError,
            PydanticValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise ScienceSubjectBenchmarkPlanPublicationError(
                "SCIENCE_SUBJECT_BENCHMARK_PLAN_SOURCE_INVALID"
            ) from exc
        summary = {
            "case_count": len(plan.cases),
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
        }
        if args.preflight_only:
            print(json.dumps({**summary, "status": "PREFLIGHT_PASS"}, sort_keys=True))
            return 0
        publisher = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        )
        pointer = publisher.commit_science_visual_subject_benchmark_plan(plan)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {**summary, "plan_artifact": pointer.model_dump(mode="json"), "status": "PUBLISHED"},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
