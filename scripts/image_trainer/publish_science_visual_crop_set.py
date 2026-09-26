#!/usr/bin/env python3
"""Publish one reviewed, group-deduplicated science visual crop set."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from eom_identifiers import content_sha256, sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotCommandV2,
    LocalImageScienceCorpusVisualPilotPlanV2,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceVisualCropSet,
    LocalImageScienceVisualCropSetV2,
    LocalImageScienceVisualPatternInventoryV2,
    LocalImageScienceVisualRasterSuitabilityReview,
    ScienceVisualReviewedCropMember,
    content_json_bytes,
    validate_contract,
    validate_science_visual_crop_set,
    validate_science_visual_crop_set_v2,
    validate_science_visual_pilot_command,
    validate_science_visual_raster_suitability_review,
)
from eom_image_contracts.science_corpus_visual import ScienceVisualRasterPatternFamily
from eom_orchestrator.database import build_engine
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

from scripts.image_trainer.stage_crop_locator import _load_artifact_member

WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
STATE_ROOT = Path("/var/lib/eom-workflow-runner")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_CROP_BYTES = 64 * 1024 * 1024
NEAR_DUPLICATE_HAMMING_DISTANCE = 2
TRAINER_PYTHON = Path("/srv/eom/conda/envs/eom-image-trainer/bin/python")
CROP_SCHEMA_REF = "eom://schemas/image-provider/local-image-science-visual-crop/1.0"
CROP_SET_SCHEMA_REF = "eom://schemas/image-provider/local-image-science-visual-crop-set/1.0"
CROP_SET_V2_SCHEMA_REF = "eom://schemas/image-provider/local-image-science-visual-crop-set/1.1"
RASTER_SUITABILITY_REVIEW_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-raster-suitability-review/1.0"
)
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_INVENTORY = re.compile(r"^imgscivisinventory_[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_RASTER_PATTERN_FAMILIES = frozenset(
    {
        "ASTRONOMICAL_SCENE",
        "FOSSIL",
        "GEOLOGIC_TEXTURE",
        "MICROSCOPIC_TEXTURE",
        "NATURAL_TEXTURE",
        "ORGANISM",
    }
)


class ScienceVisualCropSetPublicationError(RuntimeError):
    """Stable operator-facing crop-set publication failure."""


@dataclass(frozen=True, slots=True)
class _InspectedCandidate:
    member: ScienceVisualReviewedCropMember
    source: Path
    perceptual_value: int


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--inventory-id", required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--raster-suitability-review-artifact-id")
    parser.add_argument("--raster-suitability-review-artifact-revision-id")
    parser.add_argument("--raster-suitability-review-artifact-sha256")
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_TIMESTAMP_INVALID")
    return value


def _safe_read(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_MEMBER_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_MEMBER_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_MEMBER_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_MEMBER_CHANGED")
    finally:
        os.close(descriptor)
    return bytes(payload)


def _json_object(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_JSON_INVALID")
    return value


def _inspect_png(payload: bytes) -> tuple[int, int, str, int]:
    # Pillow remains isolated to the image-trainer environment; DB and Artifact publication
    # remain in the API/orchestrator environment. Only one bounded, untrusted PNG crosses stdin.
    script = """
import json,sys
from eom_image_trainer.crop_processing import average_hash,decode_png
image=decode_png(sys.stdin.buffer.read())
perceptual_hash,perceptual_value=average_hash(image)
print(json.dumps({'width':image.width,'height':image.height,
                  'perceptual_hash':perceptual_hash,
                  'perceptual_value':perceptual_value},sort_keys=True,separators=(',',':')))
"""
    try:
        completed = subprocess.run(
            [str(TRAINER_PYTHON), "-I", "-c", script],
            input=payload,
            capture_output=True,
            check=True,
            timeout=30,
        )
        value = json.loads(completed.stdout)
        if (
            not isinstance(value, dict)
            or set(value) != {"height", "perceptual_hash", "perceptual_value", "width"}
            or not isinstance(value["width"], int)
            or not isinstance(value["height"], int)
            or not isinstance(value["perceptual_hash"], str)
            or re.fullmatch(r"[0-9a-f]{16}", value["perceptual_hash"]) is None
            or not isinstance(value["perceptual_value"], int)
            or value["perceptual_value"] < 0
            or value["perceptual_value"] >= 2**64
        ):
            raise ValueError
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_PNG_INVALID") from exc
    return (
        value["width"],
        value["height"],
        value["perceptual_hash"],
        value["perceptual_value"],
    )


def _hamming_near_duplicate(value: int, selected: tuple[int, ...]) -> bool:
    return any(
        (value ^ existing).bit_count() <= NEAR_DUPLICATE_HAMMING_DISTANCE for existing in selected
    )


def _select_group_representatives(
    candidates: tuple[_InspectedCandidate, ...],
) -> tuple[_InspectedCandidate, ...]:
    """Select one deterministic non-near-duplicate member per exact exam group."""

    grouped: dict[str, list[_InspectedCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.member.exam_group_sha256].append(candidate)
    selected: list[_InspectedCandidate] = []
    perceptual_values: tuple[int, ...] = ()
    partition_order = {"TRAIN": 0, "VALIDATION": 1, "HOLDOUT": 2}
    group_order = sorted(
        grouped,
        key=lambda group: (
            partition_order[grouped[group][0].member.partition],
            group,
        ),
    )
    for group in group_order:
        options = sorted(grouped[group], key=lambda value: value.member.candidate_id)
        partitions = {value.member.partition for value in options}
        if len(partitions) != 1:
            raise ScienceVisualCropSetPublicationError(
                "SCIENCE_VISUAL_CROP_GROUP_PARTITION_INVALID"
            )
        chosen = next(
            (
                value
                for value in options
                if not _hamming_near_duplicate(value.perceptual_value, perceptual_values)
            ),
            None,
        )
        if chosen is None:
            raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_NEAR_DUPLICATE")
        selected.append(chosen)
        perceptual_values = (*perceptual_values, chosen.perceptual_value)
    return tuple(sorted(selected, key=lambda value: value.member.candidate_id))


def _load_artifact_json(
    engine: Engine,
    pointer: ImageEvaluationArtifactMember,
) -> dict[str, object]:
    return _json_object(_load_artifact_member(engine, pointer, maximum_bytes=MAX_JSON_BYTES))


def _load_inputs(
    *,
    engine: Engine,
    attempt_id: str,
    inventory_id: str,
    workspace: Path,
    result_receipt_path: Path,
    inventory_receipt_path: Path,
) -> tuple[
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotPlanV2,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceVisualPatternInventoryV2,
    ImageEvaluationArtifactMember,
    ImageEvaluationArtifactMember,
]:
    command_payload = _safe_read(workspace / "command.json", maximum_bytes=MAX_JSON_BYTES)
    plan_payload = _safe_read(
        workspace / "input/visual-pilot-plan.json", maximum_bytes=MAX_JSON_BYTES
    )
    result_payload = _safe_read(
        workspace / "manifests/visual-pilot-result.json", maximum_bytes=MAX_JSON_BYTES
    )
    result_receipt = _json_object(_safe_read(result_receipt_path, maximum_bytes=MAX_JSON_BYTES))
    inventory_receipt = _json_object(
        _safe_read(inventory_receipt_path, maximum_bytes=MAX_JSON_BYTES)
    )
    try:
        command_value = _json_object(command_payload)
        plan_value = _json_object(plan_payload)
        result_value = _json_object(result_payload)
        validate_contract("science-corpus-visual-pilot-command-v2", command_value)
        validate_contract("science-corpus-visual-pilot-plan-v2", plan_value)
        validate_contract("science-corpus-visual-pilot-result", result_value)
        command = LocalImageScienceCorpusVisualPilotCommandV2.model_validate(command_value)
        plan = LocalImageScienceCorpusVisualPilotPlanV2.model_validate(plan_value)
        result = LocalImageScienceCorpusVisualPilotResult.model_validate(result_value)
        result_pointer = ImageEvaluationArtifactMember.model_validate(
            result_receipt["result_artifact"]
        )
        inventory_pointer = ImageEvaluationArtifactMember.model_validate(
            inventory_receipt["inventory_artifact"]
        )
        inventory_value = _load_artifact_json(engine, inventory_pointer)
        authorization_value = _load_artifact_json(engine, plan.training_authorization)
        published_plan_value = _load_artifact_json(engine, command.plan)
        validate_contract("science-visual-pattern-inventory-v2", inventory_value)
        validate_contract("science-corpus-training-authorization", authorization_value)
        inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(inventory_value)
        authorization = LocalImageScienceCorpusTrainingAuthorization.model_validate(
            authorization_value
        )
        validate_science_visual_pilot_command(plan, command)
    except (KeyError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_INPUT_INVALID") from exc
    if (
        command.attempt_id != attempt_id
        or command.plan_sha256 != plan.plan_sha256
        or content_json_bytes(plan.model_dump(mode="json")) != plan_payload
        or published_plan_value != plan.model_dump(mode="json")
        or command.plan.sha256 != sha256_bytes(content_json_bytes(published_plan_value))
        or result.pilot_id != plan.pilot_id
        or result.plan_sha256 != plan.plan_sha256
        or result.status != "SUCCEEDED"
        or result_receipt.get("schema_version") != "science-visual-pilot-publication-receipt/1.0"
        or result_receipt.get("attempt_id") != attempt_id
        or result_receipt.get("result_sha256") != result.result_sha256
        or result_receipt.get("result_file_sha256") != sha256_bytes(result_payload)
        or inventory_receipt.get("schema_version")
        != "science-visual-pattern-inventory-publication-receipt/1.0"
        or inventory_receipt.get("attempt_id") != attempt_id
        or inventory_receipt.get("inventory_id") != inventory_id
        or inventory_receipt.get("inventory_sha256") != inventory.inventory_sha256
    ):
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_BINDING_INVALID")
    if (
        inventory.inventory_id != inventory_id
        or inventory.pilot_result != result_pointer
        or inventory_pointer.schema_ref
        != "eom://schemas/image-provider/local-image-science-visual-pattern-inventory/1.1"
        or inventory_pointer.member_path != "manifests/science-visual-pattern-inventory.json"
        or inventory_pointer.media_type != "application/json"
        or inventory_pointer.sha256
        != sha256_bytes(content_json_bytes(inventory.model_dump(mode="json")))
        or content_sha256(authorization.model_dump(mode="json"))
        != plan.training_authorization.sha256
    ):
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_BINDING_INVALID")
    return authorization, plan, result, inventory, inventory_pointer, command.plan


def _load_raster_suitability_review(
    *,
    engine: Engine,
    inventory: LocalImageScienceVisualPatternInventoryV2,
    inventory_pointer: ImageEvaluationArtifactMember,
    artifact_id: str | None,
    artifact_revision_id: str | None,
    artifact_sha256: str | None,
) -> tuple[LocalImageScienceVisualRasterSuitabilityReview, ImageEvaluationArtifactMember] | None:
    """Resolve the optional successor-only audit through its immutable pointer."""

    values = (artifact_id, artifact_revision_id, artifact_sha256)
    if not any(values):
        return None
    if not all(values):
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_RASTER_ARGUMENT_INVALID")
    assert artifact_id is not None
    assert artifact_revision_id is not None
    assert artifact_sha256 is not None
    try:
        pointer = ImageEvaluationArtifactMember(
            artifact_id=artifact_id,
            artifact_revision_id=artifact_revision_id,
            member_path="manifests/science-raster-suitability-review.json",
            schema_ref=RASTER_SUITABILITY_REVIEW_SCHEMA_REF,
            media_type="application/json",
            sha256=artifact_sha256,
        )
        value = _load_artifact_json(engine, pointer)
        validate_contract("science-raster-suitability-review", value)
        review = LocalImageScienceVisualRasterSuitabilityReview.model_validate(value)
        validate_science_visual_raster_suitability_review(inventory, review)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_RASTER_INVALID") from exc
    if review.pattern_inventory != inventory_pointer:
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_RASTER_INVALID")
    return review, pointer


def _build_crop_set(
    *,
    authorization: LocalImageScienceCorpusTrainingAuthorization,
    plan: LocalImageScienceCorpusVisualPilotPlanV2,
    result: LocalImageScienceCorpusVisualPilotResult,
    inventory: LocalImageScienceVisualPatternInventoryV2,
    inventory_pointer: ImageEvaluationArtifactMember,
    plan_pointer: ImageEvaluationArtifactMember,
    raster_suitability_review: LocalImageScienceVisualRasterSuitabilityReview | None,
    raster_suitability_review_pointer: ImageEvaluationArtifactMember | None,
    workspace: Path,
    created_at: datetime,
    created_by: str,
    inspect_png: Callable[[bytes], tuple[int, int, str, int]] = _inspect_png,
) -> tuple[
    LocalImageScienceVisualCropSet | LocalImageScienceVisualCropSetV2,
    tuple[_InspectedCandidate, ...],
]:
    sources = {value.document_id: value for value in plan.selected_sources}
    candidates = {value.candidate_id: value for value in result.visual_candidates}
    raster_reviews = (
        {value.candidate_id: value for value in raster_suitability_review.entries}
        if raster_suitability_review is not None
        else None
    )
    if (raster_suitability_review is None) != (raster_suitability_review_pointer is None):
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_RASTER_INVALID")
    inspected: list[_InspectedCandidate] = []
    for review in inventory.reviews:
        if review.decision != "LORA_ELIGIBLE":
            continue
        raster_review = (
            raster_reviews.get(review.candidate_id) if raster_reviews is not None else None
        )
        if raster_reviews is not None and (
            raster_review is None
            or raster_review.decision != "GPU_RASTER_ELIGIBLE"
            or raster_review.semantic_alignment != "VERIFIED"
            or raster_review.caption_en != review.caption_en
            or raster_review.caption_sha256 != review.caption_sha256
        ):
            continue
        candidate = candidates.get(review.candidate_id)
        source = sources.get(candidate.document_id) if candidate is not None else None
        if (
            candidate is None
            or source is None
            or review.caption_en is None
            or review.caption_sha256 is None
            or review.pattern_family not in _RASTER_PATTERN_FAMILIES
        ):
            raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_BINDING_INVALID")
        crop_path = workspace / candidate.member_path
        payload = _safe_read(crop_path, maximum_bytes=MAX_CROP_BYTES)
        if sha256_bytes(payload) != candidate.sha256 or len(payload) != candidate.size_bytes:
            raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_HASH_MISMATCH")
        width, height, perceptual_hash, perceptual_value = inspect_png(payload)
        inspected.append(
            _InspectedCandidate(
                member=ScienceVisualReviewedCropMember(
                    candidate_id=candidate.candidate_id,
                    document_id=candidate.document_id,
                    physical_page=candidate.physical_page,
                    exam_group_sha256=source.exam_group_sha256,
                    partition=source.partition,
                    pattern_family=cast(ScienceVisualRasterPatternFamily, review.pattern_family),
                    member_path=candidate.member_path,
                    media_type="image/png",
                    width_px=width,
                    height_px=height,
                    size_bytes=candidate.size_bytes,
                    sha256=candidate.sha256,
                    caption_en=review.caption_en,
                    caption_sha256=review.caption_sha256,
                    perceptual_hash=perceptual_hash,
                ),
                source=crop_path,
                perceptual_value=perceptual_value,
            )
        )
    selected = _select_group_representatives(tuple(inspected))
    body: dict[str, object] = {
        "schema_version": (
            "local-image-science-visual-crop-set/1.1"
            if raster_suitability_review is not None
            else "local-image-science-visual-crop-set/1.0"
        ),
        "pattern_inventory": inventory_pointer.model_dump(mode="json"),
        "pattern_inventory_semantic_sha256": inventory.inventory_sha256,
        "pilot_plan": plan_pointer.model_dump(mode="json"),
        "pilot_plan_sha256": plan.plan_sha256,
        "pilot_result": inventory.pilot_result.model_dump(mode="json"),
        "pilot_result_semantic_sha256": result.result_sha256,
        "training_authorization": plan.training_authorization.model_dump(mode="json"),
        "members": [value.member.model_dump(mode="json") for value in selected],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    if raster_suitability_review is not None and raster_suitability_review_pointer is not None:
        body["raster_suitability_review"] = raster_suitability_review_pointer.model_dump(
            mode="json"
        )
        body["raster_suitability_review_sha256"] = raster_suitability_review.review_sha256
    identity = content_sha256(body).removeprefix("sha256:")
    body["crop_set_id"] = "imgsciviscropset_" + identity[:32]
    body["crop_set_sha256"] = content_sha256(body)
    try:
        value: LocalImageScienceVisualCropSet | LocalImageScienceVisualCropSetV2
        if raster_suitability_review is None:
            value = LocalImageScienceVisualCropSet.model_validate(body)
            validate_contract("science-visual-crop-set", value.model_dump(mode="json"))
            validate_science_visual_crop_set(
                authorization=authorization,
                plan=plan,
                result=result,
                inventory=inventory,
                crop_set=value,
            )
        else:
            value = LocalImageScienceVisualCropSetV2.model_validate(body)
            validate_contract("science-visual-crop-set-v2", value.model_dump(mode="json"))
            validate_science_visual_crop_set_v2(
                authorization=authorization,
                plan=plan,
                result=result,
                inventory=inventory,
                raster_suitability_review=raster_suitability_review,
                crop_set=value,
            )
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_SET_INVALID") from exc
    return value, selected


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if _safe_read(path, maximum_bytes=MAX_JSON_BYTES) != payload:
            raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_RECEIPT_CONFLICT")
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
    if os.geteuid() != 0:
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_ROOT_REQUIRED")
    if (
        _ATTEMPT.fullmatch(args.attempt_id) is None
        or _INVENTORY.fullmatch(args.inventory_id) is None
        or _COMMIT.fullmatch(args.source_commit) is None
    ):
        raise ScienceVisualCropSetPublicationError("SCIENCE_VISUAL_CROP_ARGUMENT_INVALID")
    created_at = _utc(args.created_at)
    workspace = WORKSPACE_PARENT / args.attempt_id
    result_receipt_path = STATE_ROOT / f"science-visual-pilot-publication-{args.attempt_id}.json"
    inventory_receipt_path = (
        STATE_ROOT / f"science-visual-pattern-inventory-publication-{args.inventory_id}.json"
    )
    engine = build_engine()
    authorization, plan, result, inventory, inventory_pointer, plan_pointer = _load_inputs(
        engine=engine,
        attempt_id=args.attempt_id,
        inventory_id=args.inventory_id,
        workspace=workspace,
        result_receipt_path=result_receipt_path,
        inventory_receipt_path=inventory_receipt_path,
    )
    raster_review = _load_raster_suitability_review(
        engine=engine,
        inventory=inventory,
        inventory_pointer=inventory_pointer,
        artifact_id=args.raster_suitability_review_artifact_id,
        artifact_revision_id=args.raster_suitability_review_artifact_revision_id,
        artifact_sha256=args.raster_suitability_review_artifact_sha256,
    )
    raster_suitability_review, raster_suitability_review_pointer = (
        raster_review if raster_review is not None else (None, None)
    )
    crop_set, selected = _build_crop_set(
        authorization=authorization,
        plan=plan,
        result=result,
        inventory=inventory,
        inventory_pointer=inventory_pointer,
        plan_pointer=plan_pointer,
        raster_suitability_review=raster_suitability_review,
        raster_suitability_review_pointer=raster_suitability_review_pointer,
        workspace=workspace,
        created_at=created_at,
        created_by=args.created_by,
    )
    partition_counts = {
        partition: sum(value.member.partition == partition for value in selected)
        for partition in ("TRAIN", "VALIDATION", "HOLDOUT")
    }
    summary = {
        "attempt_id": args.attempt_id,
        "crop_set_id": crop_set.crop_set_id,
        "crop_set_sha256": crop_set.crop_set_sha256,
        "eligible_candidates": inventory.lora_eligible_count,
        "raster_suitability_review": (
            raster_suitability_review_pointer.model_dump(mode="json")
            if raster_suitability_review_pointer is not None
            else None
        ),
        "selected_groups": len(selected),
        "partition_counts": partition_counts,
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0

    with tempfile.TemporaryDirectory(prefix="eom-science-crop-set-") as temporary:
        manifest_path = Path(temporary) / "science-visual-crop-set.json"
        manifest_path.write_bytes(content_json_bytes(crop_set.model_dump(mode="json")))
        manifest_path.chmod(0o600)
        manifest_member = ControlFileSetMember(
            file_name="manifests/science-visual-crop-set.json",
            source=manifest_path,
            sha256=sha256_bytes(manifest_path.read_bytes()),
            bytes=manifest_path.stat().st_size,
            schema_ref=(
                CROP_SET_V2_SCHEMA_REF
                if isinstance(crop_set, LocalImageScienceVisualCropSetV2)
                else CROP_SET_SCHEMA_REF
            ),
            media_type="application/json",
        )
        crop_members = tuple(
            ControlFileSetMember(
                file_name=value.member.member_path,
                source=value.source,
                sha256=value.member.sha256,
                bytes=value.member.size_bytes,
                schema_ref=CROP_SCHEMA_REF,
                media_type="image/png",
            )
            for value in selected
        )
        members = tuple(sorted((*crop_members, manifest_member), key=lambda value: value.file_name))
        published = ControlFileSetPublisher(engine, Settings.from_environment()).publish(
            members=members,
            primary_file=manifest_member.file_name,
            artifact_type=(
                "control_local_image_science_visual_raster_reviewed_crop_set"
                if isinstance(crop_set, LocalImageScienceVisualCropSetV2)
                else "control_local_image_science_visual_crop_set"
            ),
            manifest_version=(
                "local-image-science-visual-crop-set-files/1.1"
                if isinstance(crop_set, LocalImageScienceVisualCropSetV2)
                else "local-image-science-visual-crop-set-files/1.0"
            ),
            idempotency_key=(
                f"science-visual-raster-reviewed-crop-set:{crop_set.crop_set_id}"
                if isinstance(crop_set, LocalImageScienceVisualCropSetV2)
                else f"science-visual-crop-set:{crop_set.crop_set_id}"
            ),
            source_commit=args.source_commit,
            created_at=created_at,
        )
    pointer = ImageEvaluationArtifactMember(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path=published.primary_file,
        schema_ref=(
            CROP_SET_V2_SCHEMA_REF
            if isinstance(crop_set, LocalImageScienceVisualCropSetV2)
            else CROP_SET_SCHEMA_REF
        ),
        media_type="application/json",
        sha256=published.primary_sha256,
    )
    receipt = {
        "schema_version": (
            "science-visual-raster-reviewed-crop-set-publication-receipt/1.0"
            if isinstance(crop_set, LocalImageScienceVisualCropSetV2)
            else "science-visual-crop-set-publication-receipt/1.0"
        ),
        **summary,
        "crop_set_artifact": pointer.model_dump(mode="json"),
        "file_set_manifest_sha256": published.manifest_sha256,
        "source_commit": args.source_commit,
    }
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / (f"science-visual-crop-set-publication-{crop_set.crop_set_id}.json")
    _write_receipt(receipt_path, content_json_bytes(receipt))
    print(json.dumps({**summary, "receipt": str(receipt_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
