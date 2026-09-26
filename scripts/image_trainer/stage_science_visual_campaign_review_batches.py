#!/usr/bin/env python3
"""Stage deterministic, bounded reviewer command drafts from a V1.2 campaign.

This root-owned adapter writes local draft inputs only.  It neither publishes an
artifact nor grants a reviewer NAS/DB access; publication remains the Orchestrator's
control-artifact boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from eom_image_contracts import (
    LocalImageScienceVisualCampaignReviewBatchCommand,
    content_json_bytes,
    content_sha256,
    validate_contract,
)
from eom_orchestrator.science_visual_campaign_resolution import (
    ResolvedScienceVisualCampaign,
    ScienceVisualCampaignResolutionError,
    parse_science_visual_campaign_object,
    resolve_science_visual_campaign,
    safe_read_science_visual_campaign_member,
)

WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
STATE_ROOT = Path("/var/lib/eom-workflow-runner")
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_REVIEWER = re.compile(r"^[A-Za-z0-9._:@-]+$")

ReviewBatchStagingError = ScienceVisualCampaignResolutionError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--batch-size", type=int, default=24)
    return parser


def _safe_read(path: Path) -> bytes:
    return safe_read_science_visual_campaign_member(path)


def _object(payload: bytes) -> dict[str, object]:
    return parse_science_visual_campaign_object(payload)


def _load_campaign(
    attempt_ids: tuple[str, ...],
) -> ResolvedScienceVisualCampaign:
    return resolve_science_visual_campaign(
        attempt_ids,
        workspace_parent=WORKSPACE_PARENT,
        state_root=STATE_ROOT,
    )


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    args = _parser().parse_args()
    attempt_ids = tuple(args.attempt_id)
    try:
        created_at = datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_ARGUMENT_INVALID") from exc
    if (
        os.geteuid() != 0
        or not 2 <= len(attempt_ids) <= 4
        or attempt_ids != tuple(sorted(set(attempt_ids)))
        or any(_ATTEMPT.fullmatch(value) is None for value in attempt_ids)
        or not 12 <= args.batch_size <= 48
        or args.output_dir.exists()
        or not args.output_dir.is_absolute()
        or _REVIEWER.fullmatch(args.created_by) is None
        or created_at.tzinfo is None
        or created_at.utcoffset() != UTC.utcoffset(created_at)
    ):
        raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_ARGUMENT_INVALID")

    campaign = _load_campaign(attempt_ids)
    campaign_id = campaign.campaign_id
    pilots = campaign.pilots
    candidate_ids = campaign.candidate_ids
    if len(candidate_ids) % args.batch_size:
        raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_CARDINALITY_INVALID")
    args.output_dir.mkdir(mode=0o700)
    commands: list[dict[str, object]] = []
    for offset in range(0, len(candidate_ids), args.batch_size):
        body: dict[str, object] = {
            "schema_version": "local-image-science-visual-campaign-review-batch-command/1.0",
            "campaign_id": campaign_id,
            "pilot_results": [value.model_dump(mode="json") for value in pilots],
            "candidate_ids": list(candidate_ids[offset : offset + args.batch_size]),
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "created_by": args.created_by,
        }
        body["batch_id"] = (
            "imgscivisreviewbatch_" + content_sha256(body).removeprefix("sha256:")[:32]
        )
        value = {**body, "command_sha256": content_sha256(body)}
        validate_contract("science-visual-campaign-review-batch-command", value)
        command = LocalImageScienceVisualCampaignReviewBatchCommand.model_validate(value)
        filename = f"batch-{offset // args.batch_size + 1:02d}-{command.batch_id}.json"
        _write_new(args.output_dir / filename, content_json_bytes(command.model_dump(mode="json")))
        commands.append(
            {
                "batch_id": command.batch_id,
                "candidate_count": len(command.candidate_ids),
                "command_sha256": command.command_sha256,
                "file": filename,
            }
        )
    manifest = {
        "schema_version": "science-visual-campaign-review-batch-drafts/1.0",
        "campaign_id": campaign_id,
        "candidate_count": len(candidate_ids),
        "batch_size": args.batch_size,
        "commands": commands,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": args.created_by,
    }
    _write_new(args.output_dir / "manifest.json", content_json_bytes(manifest))
    print(
        json.dumps(
            {"batch_count": len(commands), "campaign_id": campaign_id, "result": "READY"},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
