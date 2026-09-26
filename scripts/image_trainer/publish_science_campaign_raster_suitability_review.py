#!/usr/bin/env python3
"""Validate and publish one immutable campaign raster-suitability review."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualCampaignPatternInventory,
    LocalImageScienceVisualCampaignRasterSuitabilityReview,
    content_json_bytes,
    validate_contract,
    validate_science_visual_campaign_raster_suitability_review,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError

STATE_ROOT = Path("/var/lib/eom-workflow-runner")
MAX_JSON_BYTES = 16 * 1024 * 1024
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ScienceCampaignRasterSuitabilityPublicationError(RuntimeError):
    """Stable operator-facing campaign raster-review publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--inventory-receipt", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _safe_read(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise ScienceCampaignRasterSuitabilityPublicationError(
            "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_MEMBER_MISSING"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ScienceCampaignRasterSuitabilityPublicationError(
                "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_MEMBER_INVALID"
            )
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceCampaignRasterSuitabilityPublicationError(
                    "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_MEMBER_TRUNCATED"
                )
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
            raise ScienceCampaignRasterSuitabilityPublicationError(
                "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_MEMBER_CHANGED"
            )
    finally:
        os.close(descriptor)
    return bytes(payload)


def _json_object(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScienceCampaignRasterSuitabilityPublicationError(
            "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_JSON_INVALID"
        ) from exc
    if not isinstance(value, dict):
        raise ScienceCampaignRasterSuitabilityPublicationError(
            "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_JSON_INVALID"
        )
    return value


def _load_inputs(
    *,
    inventory_path: Path,
    inventory_receipt_path: Path,
    review_path: Path,
) -> tuple[
    LocalImageScienceVisualCampaignPatternInventory,
    LocalImageScienceVisualCampaignRasterSuitabilityReview,
    ImageEvaluationArtifactMember,
]:
    inventory_payload = _safe_read(inventory_path, maximum_bytes=MAX_JSON_BYTES)
    receipt_value = _json_object(_safe_read(inventory_receipt_path, maximum_bytes=MAX_JSON_BYTES))
    review_payload = _safe_read(review_path, maximum_bytes=MAX_JSON_BYTES)
    inventory_value = _json_object(inventory_payload)
    review_value = _json_object(review_payload)
    try:
        validate_contract("science-visual-campaign-pattern-inventory", inventory_value)
        validate_contract("science-campaign-raster-suitability-review", review_value)
        inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(inventory_value)
        review = LocalImageScienceVisualCampaignRasterSuitabilityReview.model_validate(review_value)
        inventory_pointer = ImageEvaluationArtifactMember.model_validate(
            receipt_value["inventory_artifact"]
        )
        validate_science_visual_campaign_raster_suitability_review(inventory, review)
    except (KeyError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceCampaignRasterSuitabilityPublicationError(
            "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_INPUT_INVALID"
        ) from exc
    if (
        receipt_value.get("schema_version")
        != "science-visual-campaign-pattern-inventory-publication-receipt/1.1"
        or receipt_value.get("inventory_id") != inventory.inventory_id
        or receipt_value.get("inventory_sha256") != inventory.inventory_sha256
        or inventory_pointer != review.pattern_inventory
        or inventory_pointer.sha256 != sha256_bytes(inventory_payload)
        or content_json_bytes(inventory.model_dump(mode="json")) != inventory_payload
        or content_json_bytes(review.model_dump(mode="json")) != review_payload
    ):
        raise ScienceCampaignRasterSuitabilityPublicationError(
            "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_BINDING_INVALID"
        )
    return inventory, review, inventory_pointer


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if _safe_read(path, maximum_bytes=MAX_JSON_BYTES) != payload:
            raise ScienceCampaignRasterSuitabilityPublicationError(
                "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_RECEIPT_CONFLICT"
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
    if (
        os.geteuid() != 0
        or _COMMIT.fullmatch(args.source_commit) is None
        or not args.inventory.is_absolute()
        or not args.inventory_receipt.is_absolute()
        or not args.review.is_absolute()
    ):
        raise ScienceCampaignRasterSuitabilityPublicationError(
            "SCIENCE_CAMPAIGN_RASTER_SUITABILITY_ARGUMENT_INVALID"
        )
    inventory, review, inventory_pointer = _load_inputs(
        inventory_path=args.inventory,
        inventory_receipt_path=args.inventory_receipt,
        review_path=args.review,
    )
    summary = {
        "campaign_id": inventory.campaign_id,
        "excluded_count": review.excluded_count,
        "gpu_raster_eligible_count": review.gpu_raster_eligible_count,
        "inventory_artifact_revision_id": inventory_pointer.artifact_revision_id,
        "inventory_id": inventory.inventory_id,
        "inventory_sha256": inventory.inventory_sha256,
        "python_svg_required_count": review.python_svg_required_count,
        "review_id": review.review_id,
        "review_sha256": review.review_sha256,
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0
    adapter = LocalImageTrainingControlArtifactPublisher(
        ControlArtifactPublisher(build_engine(), Settings.from_environment()),
        source_commit=args.source_commit,
    )
    pointer = adapter.commit_science_campaign_raster_suitability_review(review)
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / (
        f"science-campaign-raster-suitability-review-publication-{review.review_id}.json"
    )
    _write_receipt(
        receipt_path,
        content_json_bytes(
            {
                "schema_version": (
                    "science-campaign-raster-suitability-review-publication-receipt/1.0"
                ),
                **summary,
                "raster_suitability_review_artifact": pointer.model_dump(mode="json"),
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
                "review_id": review.review_id,
                "review_sha256": review.review_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
