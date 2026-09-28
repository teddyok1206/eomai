#!/usr/bin/env python3
"""Materialize and publish one immutable object-line-art crop-set Artifact."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    LocalImageScienceObjectLineArtCropSet,
    LocalImageScienceObjectLineArtSuitabilityReview,
    LocalImageScienceVisualCampaignPatternInventory,
    ScienceObjectLineArtCropMember,
    ScienceObjectLineArtSuitabilityEntry,
    ScienceVisualCandidate,
    ScienceVisualPilotSource,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_science_object_line_art_crop_set,
    validate_science_object_line_art_suitability_review,
    validate_science_visual_campaign_pattern_inventory,
)
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    resolve_control_artifact_member,
)
from eom_orchestrator.database import build_engine
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.science_visual_campaign_resolution import (
    ResolvedScienceVisualCampaign,
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
MAX_PNG_BYTES = 64 * 1024 * 1024
TRAINER_PYTHON = Path("/srv/eom/conda/envs/eom-image-trainer/bin/python")
CROP_SCHEMA_REF = "eom://schemas/image-provider/local-image-science-visual-crop/1.0"
CROP_SET_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-object-line-art-crop-set/1.0"
)
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_CREATOR = re.compile(r"^[A-Za-z0-9._:@-]+$")


class ScienceObjectLineArtCropSetPublicationError(RuntimeError):
    """Stable operator-facing line-art crop publication failure."""


@dataclass(frozen=True, slots=True)
class _ProcessedPng:
    payload: bytes
    width: int
    height: int
    perceptual_hash: str
    perceptual_value: int


@dataclass(frozen=True, slots=True)
class _CandidateSource:
    candidate: ScienceVisualCandidate
    source: ScienceVisualPilotSource
    path: Path


@dataclass(frozen=True, slots=True)
class _MaterializedMember:
    member: ScienceObjectLineArtCropMember
    source: Path
    perceptual_value: int


class _PerceptualIndex:
    """Four-band index for constant-radius Hamming membership checks."""

    def __init__(self) -> None:
        self._values: list[int] = []
        self._bands: dict[tuple[int, int], set[int]] = defaultdict(set)

    def contains_near_duplicate(self, value: int) -> bool:
        candidates: set[int] = set()
        for band in range(4):
            candidates.update(self._bands[(band, (value >> (band * 16)) & 0xFFFF)])
        return any((value ^ self._values[index]).bit_count() <= 2 for index in candidates)

    def add(self, value: int) -> None:
        index = len(self._values)
        self._values.append(value)
        for band in range(4):
            self._bands[(band, (value >> (band * 16)) & 0xFFFF)].add(index)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", action="append", required=True)
    parser.add_argument("--review-receipt", type=Path, required=True)
    parser.add_argument("--created-at", type=datetime.fromisoformat, required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _safe_read_png(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ScienceObjectLineArtCropSetPublicationError(
            "SCIENCE_OBJECT_LINE_ART_CROP_SOURCE_MISSING"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 64 <= before.st_size <= MAX_PNG_BYTES
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ScienceObjectLineArtCropSetPublicationError(
                "SCIENCE_OBJECT_LINE_ART_CROP_SOURCE_INVALID"
            )
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceObjectLineArtCropSetPublicationError(
                    "SCIENCE_OBJECT_LINE_ART_CROP_SOURCE_TRUNCATED"
                )
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ScienceObjectLineArtCropSetPublicationError(
                "SCIENCE_OBJECT_LINE_ART_CROP_SOURCE_CHANGED"
            )
        return bytes(payload)
    finally:
        os.close(descriptor)


def _process_png(payload: bytes, crop_box: ImageEvaluationBoundingBox) -> _ProcessedPng:
    script = """
import json,sys
from eom_image_contracts import ImageEvaluationBoundingBox
from eom_image_trainer.crop_processing import average_hash,decode_png,png_bytes
source=decode_png(sys.stdin.buffer.read())
box=ImageEvaluationBoundingBox.model_validate(json.loads(sys.argv[1]))
if box.right > source.width or box.bottom > source.height:
    raise ValueError('crop exceeds source bounds')
output=source.crop((box.left,box.top,box.right,box.bottom))
payload=png_bytes(output)
perceptual_hash,perceptual_value=average_hash(output)
sys.stderr.write(json.dumps({
    'source_width':source.width,'source_height':source.height,
    'width':output.width,'height':output.height,
    'perceptual_hash':perceptual_hash,'perceptual_value':perceptual_value,
},sort_keys=True,separators=(',',':')))
sys.stdout.buffer.write(payload)
"""
    try:
        completed = subprocess.run(
            [
                str(TRAINER_PYTHON),
                "-I",
                "-c",
                script,
                json.dumps(crop_box.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            ],
            input=payload,
            capture_output=True,
            check=True,
            timeout=30,
        )
        metadata = json.loads(completed.stderr)
        if (
            not isinstance(metadata, dict)
            or set(metadata)
            != {
                "height",
                "perceptual_hash",
                "perceptual_value",
                "source_height",
                "source_width",
                "width",
            }
            or metadata["width"] != crop_box.right - crop_box.left
            or metadata["height"] != crop_box.bottom - crop_box.top
            or not isinstance(metadata["perceptual_hash"], str)
            or re.fullmatch(r"[0-9a-f]{16}", metadata["perceptual_hash"]) is None
            or not isinstance(metadata["perceptual_value"], int)
            or metadata["perceptual_value"] not in range(2**64)
            or not 64 <= len(completed.stdout) <= MAX_PNG_BYTES
        ):
            raise ValueError
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
        raise ScienceObjectLineArtCropSetPublicationError(
            "SCIENCE_OBJECT_LINE_ART_CROP_PNG_INVALID"
        ) from exc
    return _ProcessedPng(
        payload=completed.stdout,
        width=metadata["width"],
        height=metadata["height"],
        perceptual_hash=metadata["perceptual_hash"],
        perceptual_value=metadata["perceptual_value"],
    )


def _load_inputs(
    *,
    engine: Engine,
    attempt_ids: tuple[str, ...],
    receipt_path: Path,
) -> tuple[
    ResolvedScienceVisualCampaign,
    LocalImageScienceVisualCampaignPatternInventory,
    LocalImageScienceObjectLineArtSuitabilityReview,
    ImageEvaluationArtifactMember,
]:
    campaign = resolve_science_visual_campaign(
        attempt_ids,
        workspace_parent=WORKSPACE_PARENT,
        state_root=STATE_ROOT,
    )
    try:
        receipt = parse_science_visual_campaign_object(
            safe_read_science_visual_campaign_member(receipt_path)
        )
        review_pointer = ImageEvaluationArtifactMember.model_validate(
            receipt["line_art_suitability_review_artifact"]
        )
        review_payload = resolve_control_artifact_member(
            engine,
            review_pointer,
            maximum_bytes=MAX_JSON_BYTES,
        )
        review_value = parse_science_visual_campaign_object(review_payload)
        validate_contract("science-object-line-art-suitability-review", review_value)
        review = LocalImageScienceObjectLineArtSuitabilityReview.model_validate(review_value)
        inventory_payload = resolve_control_artifact_member(
            engine,
            review.pattern_inventory,
            maximum_bytes=MAX_JSON_BYTES,
        )
        inventory_value = parse_science_visual_campaign_object(inventory_payload)
        validate_contract("science-visual-campaign-pattern-inventory", inventory_value)
        inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(inventory_value)
        validate_science_visual_campaign_pattern_inventory(
            plans=campaign.plans,
            plan_pointers=campaign.plan_pointers,
            results=campaign.results,
            result_pointers=campaign.result_pointers,
            inventory=inventory,
        )
        validate_science_object_line_art_suitability_review(inventory, review)
    except (ControlArtifactResolutionError, ScienceVisualCampaignResolutionError):
        raise
    except (KeyError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceObjectLineArtCropSetPublicationError(
            "SCIENCE_OBJECT_LINE_ART_CROP_INPUT_INVALID"
        ) from exc
    if (
        receipt.get("schema_version") != "science-object-line-art-review-publication-receipt/1.0"
        or receipt.get("review_id") != review.review_id
        or receipt.get("review_sha256") != review.review_sha256
        or review_pointer.sha256 != sha256_bytes(review_payload)
        or content_json_bytes(review.model_dump(mode="json")) != review_payload
        or content_json_bytes(inventory.model_dump(mode="json")) != inventory_payload
    ):
        raise ScienceObjectLineArtCropSetPublicationError(
            "SCIENCE_OBJECT_LINE_ART_CROP_BINDING_INVALID"
        )
    return campaign, inventory, review, review_pointer


def _candidate_sources(campaign: ResolvedScienceVisualCampaign) -> dict[str, _CandidateSource]:
    resolved: dict[str, _CandidateSource] = {}
    for pilot, plan, result in zip(
        campaign.pilots,
        campaign.plans,
        campaign.results,
        strict=True,
    ):
        sources = {value.document_id: value for value in plan.selected_sources}
        workspace = WORKSPACE_PARENT / pilot.attempt_id
        for candidate in result.visual_candidates:
            source = sources.get(candidate.document_id)
            if source is None or candidate.candidate_id in resolved:
                raise ScienceObjectLineArtCropSetPublicationError(
                    "SCIENCE_OBJECT_LINE_ART_CROP_SOURCE_INVALID"
                )
            resolved[candidate.candidate_id] = _CandidateSource(
                candidate=candidate,
                source=source,
                path=workspace / candidate.member_path,
            )
    return resolved


def _member(
    *,
    entry: ScienceObjectLineArtSuitabilityEntry,
    resolved: _CandidateSource,
    output: _ProcessedPng,
) -> ScienceObjectLineArtCropMember:
    if (
        entry.crop_bounding_box is None
        or entry.object_family is None
        or entry.caption_en is None
        or entry.caption_sha256 is None
    ):
        raise ScienceObjectLineArtCropSetPublicationError(
            "SCIENCE_OBJECT_LINE_ART_CROP_REVIEW_INVALID"
        )
    body: dict[str, object] = {
        "parent_candidate_id": resolved.candidate.candidate_id,
        "parent_candidate_sha256": resolved.candidate.sha256,
        "crop_bounding_box": entry.crop_bounding_box.model_dump(mode="json"),
        "document_id": resolved.candidate.document_id,
        "physical_page": resolved.candidate.physical_page,
        "exam_group_sha256": resolved.source.exam_group_sha256,
        "partition": resolved.source.partition,
        "object_family": entry.object_family,
        "media_type": "image/png",
        "width_px": output.width,
        "height_px": output.height,
        "size_bytes": len(output.payload),
        "sha256": sha256_bytes(output.payload),
        "caption_en": entry.caption_en,
        "caption_sha256": entry.caption_sha256,
        "perceptual_hash": output.perceptual_hash,
    }
    sample_id = "imgscivislineartcrop_" + content_sha256(body).removeprefix("sha256:")[:32]
    return ScienceObjectLineArtCropMember.model_validate(
        {**body, "sample_id": sample_id, "member_path": f"crops/{sample_id}.png"}
    )


def _build_crop_set(
    *,
    campaign: ResolvedScienceVisualCampaign,
    inventory: LocalImageScienceVisualCampaignPatternInventory,
    review: LocalImageScienceObjectLineArtSuitabilityReview,
    review_pointer: ImageEvaluationArtifactMember,
    temporary: Path,
    created_at: datetime,
    created_by: str,
    process_png: Callable[[bytes, ImageEvaluationBoundingBox], _ProcessedPng] = _process_png,
) -> tuple[LocalImageScienceObjectLineArtCropSet, tuple[_MaterializedMember, ...]]:
    sources = _candidate_sources(campaign)
    selected: list[_MaterializedMember] = []
    document_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    group_partitions: dict[str, str] = {}
    hashes: set[str] = set()
    perceptual = _PerceptualIndex()

    for entry in review.entries:
        if entry.decision != "OBJECT_LINE_ART_ELIGIBLE":
            continue
        resolved = sources.get(entry.candidate_id)
        if resolved is None or entry.crop_bounding_box is None:
            raise ScienceObjectLineArtCropSetPublicationError(
                "SCIENCE_OBJECT_LINE_ART_CROP_SOURCE_INVALID"
            )
        parent = _safe_read_png(resolved.path)
        if (
            sha256_bytes(parent) != resolved.candidate.sha256
            or len(parent) != resolved.candidate.size_bytes
        ):
            raise ScienceObjectLineArtCropSetPublicationError(
                "SCIENCE_OBJECT_LINE_ART_CROP_SOURCE_HASH_MISMATCH"
            )
        output = process_png(parent, entry.crop_bounding_box)
        member = _member(entry=entry, resolved=resolved, output=output)
        existing_partition = group_partitions.get(member.exam_group_sha256)
        if (
            document_counts[member.document_id] >= 3
            or group_counts[member.exam_group_sha256] >= 4
            or member.sha256 in hashes
            or perceptual.contains_near_duplicate(output.perceptual_value)
            or (existing_partition is not None and existing_partition != member.partition)
        ):
            raise ScienceObjectLineArtCropSetPublicationError(
                "SCIENCE_OBJECT_LINE_ART_CROP_DUPLICATE"
            )
        path = temporary / f"{member.sample_id}.png"
        path.write_bytes(output.payload)
        path.chmod(0o600)
        selected.append(_MaterializedMember(member, path, output.perceptual_value))
        document_counts[member.document_id] += 1
        group_counts[member.exam_group_sha256] += 1
        group_partitions[member.exam_group_sha256] = member.partition
        hashes.add(member.sha256)
        perceptual.add(output.perceptual_value)

    authorizations = {value.training_authorization for value in campaign.plans}
    if len(authorizations) != 1:
        raise ScienceObjectLineArtCropSetPublicationError(
            "SCIENCE_OBJECT_LINE_ART_CROP_AUTHORIZATION_INVALID"
        )
    ordered = tuple(sorted(selected, key=lambda value: value.member.sample_id))
    body: dict[str, object] = {
        "schema_version": "local-image-science-object-line-art-crop-set/1.0",
        "campaign_id": inventory.campaign_id,
        "pattern_inventory": review.pattern_inventory.model_dump(mode="json"),
        "pattern_inventory_semantic_sha256": inventory.inventory_sha256,
        "line_art_suitability_review": review_pointer.model_dump(mode="json"),
        "line_art_suitability_review_sha256": review.review_sha256,
        "training_authorization": next(iter(authorizations)).model_dump(mode="json"),
        "member_policy": {
            "partition_policy": "PINNED_SOURCE_GROUP_V1",
            "max_members_per_document": 3,
            "max_members_per_exam_group": 4,
        },
        "members": [value.member.model_dump(mode="json") for value in ordered],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    crop_set_id = "imgscivislineartcropset_" + content_sha256(body).removeprefix("sha256:")[:32]
    with_identity = {**body, "crop_set_id": crop_set_id}
    crop_set = LocalImageScienceObjectLineArtCropSet.model_validate(
        {**with_identity, "crop_set_sha256": content_sha256(with_identity)}
    )
    validate_contract("science-object-line-art-crop-set", crop_set.model_dump(mode="json"))
    validate_science_object_line_art_crop_set(
        plans=campaign.plans,
        plan_pointers=campaign.plan_pointers,
        results=campaign.results,
        result_pointers=campaign.result_pointers,
        inventory=inventory,
        review=review,
        crop_set=crop_set,
    )
    return crop_set, ordered


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if safe_read_science_visual_campaign_member(path) != payload:
            raise ScienceObjectLineArtCropSetPublicationError(
                "SCIENCE_OBJECT_LINE_ART_CROP_RECEIPT_CONFLICT"
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
    created_at = args.created_at
    if (
        os.geteuid() != 0
        or not 2 <= len(attempt_ids) <= 4
        or attempt_ids != tuple(sorted(set(attempt_ids)))
        or any(_ATTEMPT.fullmatch(value) is None for value in attempt_ids)
        or _COMMIT.fullmatch(args.source_commit) is None
        or _CREATOR.fullmatch(args.created_by) is None
        or not args.review_receipt.is_absolute()
        or created_at.tzinfo is None
        or created_at.utcoffset() != UTC.utcoffset(created_at)
    ):
        raise ScienceObjectLineArtCropSetPublicationError(
            "SCIENCE_OBJECT_LINE_ART_CROP_ARGUMENT_INVALID"
        )
    engine = build_engine()
    try:
        campaign, inventory, review, review_pointer = _load_inputs(
            engine=engine,
            attempt_ids=attempt_ids,
            receipt_path=args.review_receipt,
        )
        with tempfile.TemporaryDirectory(prefix="eom-science-object-line-art-crop-set-") as root:
            temporary = Path(root)
            crop_set, materialized = _build_crop_set(
                campaign=campaign,
                inventory=inventory,
                review=review,
                review_pointer=review_pointer,
                temporary=temporary,
                created_at=created_at,
                created_by=args.created_by,
            )
            counts = Counter(value.member.partition for value in materialized)
            summary = {
                "campaign_id": crop_set.campaign_id,
                "crop_set_id": crop_set.crop_set_id,
                "crop_set_sha256": crop_set.crop_set_sha256,
                "holdout_count": counts["HOLDOUT"],
                "member_count": len(materialized),
                "train_count": counts["TRAIN"],
                "validation_count": counts["VALIDATION"],
            }
            if args.preflight_only:
                print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
                return 0
            manifest_path = temporary / "science-object-line-art-crop-set.json"
            manifest_path.write_bytes(content_json_bytes(crop_set.model_dump(mode="json")))
            manifest_path.chmod(0o600)
            manifest_member = ControlFileSetMember(
                file_name="manifests/science-object-line-art-crop-set.json",
                source=manifest_path,
                sha256=sha256_bytes(manifest_path.read_bytes()),
                bytes=manifest_path.stat().st_size,
                schema_ref=CROP_SET_SCHEMA_REF,
                media_type="application/json",
            )
            png_members = tuple(
                ControlFileSetMember(
                    file_name=value.member.member_path,
                    source=value.source,
                    sha256=value.member.sha256,
                    bytes=value.member.size_bytes,
                    schema_ref=CROP_SCHEMA_REF,
                    media_type="image/png",
                )
                for value in materialized
            )
            published = ControlFileSetPublisher(engine, Settings.from_environment()).publish(
                members=tuple(
                    sorted((*png_members, manifest_member), key=lambda value: value.file_name)
                ),
                primary_file=manifest_member.file_name,
                artifact_type="control_local_image_science_object_line_art_crop_set",
                manifest_version="local-image-science-object-line-art-crop-set-files/1.0",
                idempotency_key=f"science-object-line-art-crop-set:{crop_set.crop_set_id}",
                source_commit=args.source_commit,
                created_at=created_at,
            )
    finally:
        engine.dispose()
    pointer = ImageEvaluationArtifactMember(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        member_path=published.primary_file,
        schema_ref=CROP_SET_SCHEMA_REF,
        media_type="application/json",
        sha256=published.primary_sha256,
    )
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / f"science-object-line-art-crop-set-{crop_set.crop_set_id}.json"
    _write_receipt(
        receipt_path,
        content_json_bytes(
            {
                "schema_version": "science-object-line-art-crop-set-publication-receipt/1.0",
                **summary,
                "crop_set_artifact": pointer.model_dump(mode="json"),
                "file_set_manifest_sha256": published.manifest_sha256,
                "source_commit": args.source_commit,
            }
        ),
    )
    print(
        json.dumps(
            {
                "artifact_id": pointer.artifact_id,
                "artifact_revision_id": pointer.artifact_revision_id,
                "crop_set_id": crop_set.crop_set_id,
                "crop_set_sha256": crop_set.crop_set_sha256,
                "receipt": str(receipt_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
