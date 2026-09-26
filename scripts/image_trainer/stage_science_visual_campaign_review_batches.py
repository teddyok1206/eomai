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
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceVisualCampaignReviewBatchCommand,
    ScienceVisualCampaignPilotResult,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_science_visual_pilot_result,
)
from pydantic import ValidationError

WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
STATE_ROOT = Path("/var/lib/eom-workflow-runner")
MAX_JSON_BYTES = 16 * 1024 * 1024
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_REVIEWER = re.compile(r"^[A-Za-z0-9._:@-]+$")


class ReviewBatchStagingError(RuntimeError):
    """Stable failure that preserves the source campaign for investigation."""


@dataclass(frozen=True)
class ResolvedScienceVisualCampaign:
    campaign_id: str
    pilots: tuple[ScienceVisualCampaignPilotResult, ...]
    candidate_ids: tuple[str, ...]
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...]
    plan_pointers: tuple[ImageEvaluationArtifactMember, ...]
    results: tuple[LocalImageScienceCorpusVisualPilotResult, ...]
    result_pointers: tuple[ImageEvaluationArtifactMember, ...]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--batch-size", type=int, default=24)
    return parser


def _safe_read(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_MEMBER_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_JSON_BYTES
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_MEMBER_INVALID")
        chunks = bytearray()
        while len(chunks) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(chunks)))
            if not chunk:
                raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_MEMBER_TRUNCATED")
            chunks.extend(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_MEMBER_CHANGED")
    finally:
        os.close(descriptor)
    return bytes(chunks)


def _object(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_JSON_INVALID")
    return value


def _stage_receipt(attempt_id: str) -> Path:
    return STATE_ROOT / f"science-visual-pilot-stage-{attempt_id}.json"


def _result_receipt(attempt_id: str) -> Path:
    return STATE_ROOT / f"science-visual-pilot-publication-{attempt_id}.json"


def _load_campaign(
    attempt_ids: tuple[str, ...],
) -> ResolvedScienceVisualCampaign:
    pilots: list[ScienceVisualCampaignPilotResult] = []
    candidate_ids: list[str] = []
    source_documents: set[str] = set()
    campaign_id: str | None = None
    plans: list[LocalImageScienceCorpusVisualPilotPlanV3] = []
    plan_pointers: list[ImageEvaluationArtifactMember] = []
    results: list[LocalImageScienceCorpusVisualPilotResult] = []
    result_pointers: list[ImageEvaluationArtifactMember] = []
    for attempt_id in attempt_ids:
        workspace = WORKSPACE_PARENT / attempt_id
        try:
            stage = _object(_safe_read(_stage_receipt(attempt_id)))
            receipt = _object(_safe_read(_result_receipt(attempt_id)))
            plan_payload = _safe_read(workspace / "input/visual-pilot-plan.json")
            result_payload = _safe_read(workspace / "manifests/visual-pilot-result.json")
            plan_value = _object(plan_payload)
            result_value = _object(result_payload)
            validate_contract("science-corpus-visual-pilot-plan-v3", plan_value)
            validate_contract("science-corpus-visual-pilot-result", result_value)
            plan = LocalImageScienceCorpusVisualPilotPlanV3.model_validate(plan_value)
            result = LocalImageScienceCorpusVisualPilotResult.model_validate(result_value)
            plan_pointer = ImageEvaluationArtifactMember.model_validate(stage["plan"])
            result_pointer = ImageEvaluationArtifactMember.model_validate(
                receipt["result_artifact"]
            )
            if (
                stage.get("schema_version") != "science-visual-pilot-stage-receipt/1.0"
                or receipt.get("schema_version") != "science-visual-pilot-publication-receipt/1.0"
                or receipt.get("attempt_id") != attempt_id
                or plan_pointer.sha256
                != sha256_bytes(content_json_bytes(plan.model_dump(mode="json")))
                or receipt.get("result_file_sha256") != sha256_bytes(result_payload)
                or result.status != "SUCCEEDED"
                or result.plan_sha256 != plan.plan_sha256
            ):
                raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_BINDING_INVALID")
            validate_science_visual_pilot_result(plan, result)
            if campaign_id is None:
                campaign_id = plan.campaign_id
            elif plan.campaign_id != campaign_id:
                raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_CAMPAIGN_MISMATCH")
            for source in plan.selected_sources:
                if source.document_id in source_documents:
                    raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_SOURCE_OVERLAP")
                source_documents.add(source.document_id)
            pilots.append(
                ScienceVisualCampaignPilotResult(
                    attempt_id=attempt_id,
                    campaign_shard_index=plan.campaign_shard_index,
                    campaign_shard_count=plan.campaign_shard_count,
                    pilot_plan=plan_pointer,
                    pilot_plan_file_sha256=plan_pointer.sha256,
                    pilot_plan_semantic_sha256=plan.plan_sha256,
                    pilot_result=result_pointer,
                    pilot_result_file_sha256=result_pointer.sha256,
                    pilot_result_semantic_sha256=result.result_sha256,
                )
            )
            plans.append(plan)
            plan_pointers.append(plan_pointer)
            results.append(result)
            result_pointers.append(result_pointer)
            candidate_ids.extend(candidate.candidate_id for candidate in result.visual_candidates)
        except ReviewBatchStagingError:
            raise
        except (KeyError, TypeError, ValidationError, ValueError) as exc:
            raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_INPUT_INVALID") from exc
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_CANDIDATE_OVERLAP")
    if campaign_id is None:
        raise ReviewBatchStagingError("SCIENCE_VISUAL_REVIEW_BATCH_INPUT_INVALID")
    ordered = sorted(
        zip(pilots, plans, plan_pointers, results, result_pointers, strict=True),
        key=lambda value: value[0].campaign_shard_index,
    )
    return ResolvedScienceVisualCampaign(
        campaign_id=campaign_id,
        pilots=tuple(value[0] for value in ordered),
        candidate_ids=tuple(sorted(candidate_ids)),
        plans=tuple(value[1] for value in ordered),
        plan_pointers=tuple(value[2] for value in ordered),
        results=tuple(value[3] for value in ordered),
        result_pointers=tuple(value[4] for value in ordered),
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
