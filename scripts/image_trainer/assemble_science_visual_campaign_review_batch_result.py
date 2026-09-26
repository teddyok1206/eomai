#!/usr/bin/env python3
"""Assemble one reviewed campaign batch into its exact protocol result."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualCampaignReviewBatchCommand,
    LocalImageScienceVisualCampaignReviewBatchResult,
    ScienceVisualPatternReview,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_science_visual_campaign_review_batch,
)
from eom_orchestrator.science_visual_campaign_resolution import (
    ResolvedScienceVisualCampaign,
    ScienceVisualCampaignResolutionError,
    parse_science_visual_campaign_object,
    resolve_science_visual_campaign,
    safe_read_science_visual_campaign_member,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

STATE_ROOT = Path("/var/lib/eom-workflow-runner")
WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_COMMAND_RECEIPT_SCHEMA = "science-visual-campaign-review-command-publication-receipt/1.0"


class ReviewBatchAssemblyError(RuntimeError):
    """Stable operator-facing assembly failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", action="append", required=True)
    parser.add_argument("--command", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--completed-at", required=True)
    parser.add_argument("--completed-by", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _command_receipt(batch_id: str) -> Path:
    return STATE_ROOT / f"science-visual-campaign-review-command-{batch_id}.json"


def _read_object(path: Path) -> tuple[bytes, dict[str, object]]:
    payload = safe_read_science_visual_campaign_member(path)
    return payload, parse_science_visual_campaign_object(payload)


def _read_reviews(path: Path) -> tuple[ScienceVisualPatternReview, ...]:
    payload = safe_read_science_visual_campaign_member(path)
    try:
        value = json.loads(payload)
        if not isinstance(value, list):
            raise TypeError("reviews must be a JSON array")
        return tuple(ScienceVisualPatternReview.model_validate(entry) for entry in value)
    except (UnicodeError, json.JSONDecodeError, PydanticValidationError, TypeError) as exc:
        raise ReviewBatchAssemblyError("SCIENCE_VISUAL_REVIEW_BATCH_REVIEWS_INVALID") from exc


def _load_campaign(attempt_ids: tuple[str, ...]) -> ResolvedScienceVisualCampaign:
    return resolve_science_visual_campaign(
        attempt_ids,
        workspace_parent=WORKSPACE_PARENT,
        state_root=STATE_ROOT,
    )


def _assemble_result(
    *,
    command: LocalImageScienceVisualCampaignReviewBatchCommand,
    command_pointer: ImageEvaluationArtifactMember,
    reviews: tuple[ScienceVisualPatternReview, ...],
    completed_at: str,
    completed_by: str,
    campaign: ResolvedScienceVisualCampaign,
) -> LocalImageScienceVisualCampaignReviewBatchResult:
    body: dict[str, object] = {
        "schema_version": "local-image-science-visual-campaign-review-batch-result/1.0",
        "batch_id": command.batch_id,
        "review_batch": command_pointer.model_dump(mode="json"),
        "command_sha256": command.command_sha256,
        "reviews": [review.model_dump(mode="json") for review in reviews],
        "completed_at": completed_at,
        "completed_by": completed_by,
    }
    value = {**body, "result_sha256": content_sha256(body)}
    validate_contract("science-visual-campaign-review-batch-result", value)
    result = LocalImageScienceVisualCampaignReviewBatchResult.model_validate(value)
    validate_science_visual_campaign_review_batch(
        command=command,
        command_pointer=command_pointer,
        plans=campaign.plans,
        plan_pointers=campaign.plan_pointers,
        results=campaign.results,
        result_pointers=campaign.result_pointers,
        review_result=result,
    )
    return result


def _write_new(path: Path, payload: bytes) -> None:
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
        or not args.command.is_absolute()
        or not args.reviews.is_absolute()
        or not args.output.is_absolute()
        or args.output.exists()
        or args.output.is_symlink()
    ):
        raise ReviewBatchAssemblyError("SCIENCE_VISUAL_REVIEW_BATCH_ARGUMENT_INVALID")
    try:
        command_payload, command_value = _read_object(args.command)
        validate_contract("science-visual-campaign-review-batch-command", command_value)
        command = LocalImageScienceVisualCampaignReviewBatchCommand.model_validate(command_value)
        if content_json_bytes(command.model_dump(mode="json")) != command_payload:
            raise ReviewBatchAssemblyError("SCIENCE_VISUAL_REVIEW_BATCH_NOT_CANONICAL")
        receipt_payload, receipt = _read_object(_command_receipt(command.batch_id))
        del receipt_payload
        command_pointer = ImageEvaluationArtifactMember.model_validate(receipt["command_artifact"])
        if (
            receipt.get("schema_version") != _COMMAND_RECEIPT_SCHEMA
            or receipt.get("batch_id") != command.batch_id
            or receipt.get("command_sha256") != command.command_sha256
            or command_pointer.sha256 != sha256_bytes(command_payload)
        ):
            raise ReviewBatchAssemblyError("SCIENCE_VISUAL_REVIEW_BATCH_RECEIPT_INVALID")
        campaign = _load_campaign(attempt_ids)
        reviews = _read_reviews(args.reviews)
        result = _assemble_result(
            command=command,
            command_pointer=command_pointer,
            reviews=reviews,
            completed_at=args.completed_at,
            completed_by=args.completed_by,
            campaign=campaign,
        )
    except ReviewBatchAssemblyError:
        raise
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        ScienceVisualCampaignResolutionError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ReviewBatchAssemblyError("SCIENCE_VISUAL_REVIEW_BATCH_ASSEMBLY_INVALID") from exc
    payload = content_json_bytes(result.model_dump(mode="json"))
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "batch_id": result.batch_id,
                    "preflight": "PASS",
                    "result_sha256": result.result_sha256,
                    "review_count": len(result.reviews),
                },
                sort_keys=True,
            )
        )
        return 0
    _write_new(args.output, payload)
    print(
        json.dumps(
            {
                "batch_id": result.batch_id,
                "output": str(args.output),
                "result_sha256": result.result_sha256,
                "review_count": len(result.reviews),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
