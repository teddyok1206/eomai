#!/usr/bin/env python3
"""Build one bounded benchmark plan from published subject and adapter pointers."""

from __future__ import annotations

import argparse
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_service.science_visual_subject_benchmark import (
    build_science_visual_subject_benchmark_plan,
)
from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCampaignLoraMicroAdapterManifestV2,
    content_json_bytes,
    validate_contract,
)
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    resolve_control_artifact_member,
)
from eom_orchestrator.database import build_engine
from pydantic import ValidationError as PydanticValidationError

from scripts.image_trainer.publish_science_visual_subject_inventory import (
    load_subject_inventory,
    safe_read_subject_inventory,
)

MAX_JSON_BYTES = 16 * 1024 * 1024


class ScienceVisualSubjectBenchmarkPlanBuildError(RuntimeError):
    """Stable operator error for benchmark-plan construction."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-artifact-id", required=True)
    parser.add_argument("--inventory-artifact-revision-id", required=True)
    parser.add_argument("--inventory-artifact-sha256", required=True)
    parser.add_argument("--adapter-artifact-id", required=True)
    parser.add_argument("--adapter-artifact-revision-id", required=True)
    parser.add_argument("--adapter-artifact-sha256", required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _pointer(
    *,
    artifact_id: str,
    artifact_revision_id: str,
    member_path: str,
    schema_ref: str,
    sha256: str,
) -> ImageEvaluationArtifactMember:
    try:
        return ImageEvaluationArtifactMember(
            artifact_id=artifact_id,
            artifact_revision_id=artifact_revision_id,
            member_path=member_path,
            schema_ref=schema_ref,
            media_type="application/json",
            sha256=sha256,
        )
    except PydanticValidationError as exc:
        raise ScienceVisualSubjectBenchmarkPlanBuildError(
            "SCIENCE_VISUAL_SUBJECT_BENCHMARK_POINTER_INVALID"
        ) from exc


def _adapter_manifest(payload: bytes) -> LocalImageScienceCampaignLoraMicroAdapterManifestV2:
    try:
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise TypeError("adapter manifest is not an object")
        validate_contract("science-campaign-lora-micro-adapter-manifest-v2", value)
        manifest = LocalImageScienceCampaignLoraMicroAdapterManifestV2.model_validate(value)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ScienceVisualSubjectBenchmarkPlanBuildError(
            "SCIENCE_VISUAL_SUBJECT_BENCHMARK_ADAPTER_INVALID"
        ) from exc
    canonical = content_json_bytes(manifest.model_dump(mode="json"))
    if payload not in {canonical, canonical + b"\n"}:
        raise ScienceVisualSubjectBenchmarkPlanBuildError(
            "SCIENCE_VISUAL_SUBJECT_BENCHMARK_ADAPTER_NOT_CANONICAL"
        )
    return manifest


def _write_exclusive(path: Path, payload: bytes) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink() or path.parent.is_symlink():
        raise ScienceVisualSubjectBenchmarkPlanBuildError(
            "SCIENCE_VISUAL_SUBJECT_BENCHMARK_OUTPUT_INVALID"
        )
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ScienceVisualSubjectBenchmarkPlanBuildError(
                "SCIENCE_VISUAL_SUBJECT_BENCHMARK_OUTPUT_INVALID"
            )
    finally:
        os.close(descriptor)


def main() -> int:
    args = _parser().parse_args()
    if args.created_at.tzinfo is None or args.created_at.utcoffset() != UTC.utcoffset(
        args.created_at
    ):
        raise ScienceVisualSubjectBenchmarkPlanBuildError(
            "SCIENCE_VISUAL_SUBJECT_BENCHMARK_CREATED_AT_NOT_UTC"
        )
    inventory_payload = safe_read_subject_inventory(args.inventory)
    inventory = load_subject_inventory(inventory_payload)
    inventory_pointer = _pointer(
        artifact_id=args.inventory_artifact_id,
        artifact_revision_id=args.inventory_artifact_revision_id,
        member_path="manifests/science-visual-subject-inventory.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-visual-subject-inventory/1.0"
        ),
        sha256=args.inventory_artifact_sha256,
    )
    if inventory_pointer.sha256 != sha256_bytes(inventory_payload):
        raise ScienceVisualSubjectBenchmarkPlanBuildError(
            "SCIENCE_VISUAL_SUBJECT_BENCHMARK_INVENTORY_HASH_MISMATCH"
        )
    adapter_pointer = _pointer(
        artifact_id=args.adapter_artifact_id,
        artifact_revision_id=args.adapter_artifact_revision_id,
        member_path="manifests/adapter-manifest.json",
        schema_ref=(
            "eom://schemas/image-provider/"
            "local-image-science-campaign-lora-micro-adapter-manifest/1.1"
        ),
        sha256=args.adapter_artifact_sha256,
    )
    engine = build_engine()
    try:
        if (
            resolve_control_artifact_member(
                engine,
                inventory_pointer,
                maximum_bytes=MAX_JSON_BYTES,
            )
            != inventory_payload
        ):
            raise ScienceVisualSubjectBenchmarkPlanBuildError(
                "SCIENCE_VISUAL_SUBJECT_BENCHMARK_INVENTORY_POINTER_MISMATCH"
            )
        adapter = _adapter_manifest(
            resolve_control_artifact_member(
                engine,
                adapter_pointer,
                maximum_bytes=MAX_JSON_BYTES,
            )
        )
    except ScienceVisualSubjectBenchmarkPlanBuildError:
        raise
    except ControlArtifactResolutionError as exc:
        raise ScienceVisualSubjectBenchmarkPlanBuildError(
            "SCIENCE_VISUAL_SUBJECT_BENCHMARK_POINTER_RESOLUTION_FAILED"
        ) from exc
    finally:
        engine.dispose()
    plan = build_science_visual_subject_benchmark_plan(
        inventory=inventory,
        inventory_pointer=inventory_pointer,
        adapter_manifest=adapter,
        adapter_manifest_pointer=adapter_pointer,
        created_at=args.created_at,
        created_by=args.created_by,
    )
    value = plan.model_dump(mode="json")
    validate_contract("science-visual-subject-benchmark-plan", value)
    summary = {
        "case_count": len(plan.cases),
        "gpu_policy_negative_count": sum(
            case.case_kind == "GPU_POLICY_NEGATIVE" for case in plan.cases
        ),
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "quality_case_count": sum(case.case_kind == "QUALITY" for case in plan.cases),
        "route_case_count": sum(case.case_kind == "ROUTE" for case in plan.cases),
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0
    _write_exclusive(args.output, content_json_bytes(value))
    print(json.dumps({**summary, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
