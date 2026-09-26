#!/usr/bin/env python3
"""Publish one validated science-visual campaign review command or result."""

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
    content_json_bytes,
    validate_contract,
    validate_science_visual_campaign_review_batch,
    validate_science_visual_campaign_review_batch_command,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from scripts.image_trainer.stage_science_visual_campaign_review_batches import (
    ReviewBatchStagingError,
    _load_campaign,
    _object,
    _safe_read,
)

STATE_ROOT = Path("/var/lib/eom-workflow-runner")
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_COMMAND_RECEIPT_SCHEMA = "science-visual-campaign-review-command-publication-receipt/1.0"
_RESULT_RECEIPT_SCHEMA = "science-visual-campaign-review-result-publication-receipt/1.0"


class ReviewBatchPublicationError(RuntimeError):
    """Stable operator-facing publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", action="append", required=True)
    parser.add_argument("--command", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _command_receipt(batch_id: str) -> Path:
    return STATE_ROOT / f"science-visual-campaign-review-command-{batch_id}.json"


def _result_receipt(batch_id: str) -> Path:
    return STATE_ROOT / f"science-visual-campaign-review-result-{batch_id}.json"


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if _safe_read(path) != payload:
            raise ReviewBatchPublicationError("SCIENCE_VISUAL_REVIEW_BATCH_RECEIPT_CONFLICT")
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
    if (
        os.geteuid() != 0
        or not 2 <= len(attempt_ids) <= 4
        or attempt_ids != tuple(sorted(set(attempt_ids)))
        or any(_ATTEMPT.fullmatch(value) is None for value in attempt_ids)
        or _COMMIT.fullmatch(args.source_commit) is None
        or not args.command.is_absolute()
        or (args.result is not None and not args.result.is_absolute())
    ):
        raise ReviewBatchPublicationError("SCIENCE_VISUAL_REVIEW_BATCH_ARGUMENT_INVALID")
    try:
        command_payload = _safe_read(args.command)
        command_value = _object(command_payload)
        validate_contract("science-visual-campaign-review-batch-command", command_value)
        command = LocalImageScienceVisualCampaignReviewBatchCommand.model_validate(command_value)
        if content_json_bytes(command.model_dump(mode="json")) != command_payload:
            raise ReviewBatchPublicationError("SCIENCE_VISUAL_REVIEW_BATCH_NOT_CANONICAL")
        campaign = _load_campaign(attempt_ids)
        if command.pilot_results != campaign.pilots or command.campaign_id != campaign.campaign_id:
            raise ReviewBatchPublicationError("SCIENCE_VISUAL_REVIEW_BATCH_BINDING_INVALID")
        validate_science_visual_campaign_review_batch_command(
            command=command,
            plans=campaign.plans,
            plan_pointers=campaign.plan_pointers,
            results=campaign.results,
            result_pointers=campaign.result_pointers,
        )
    except ReviewBatchPublicationError:
        raise
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        ReviewBatchStagingError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ReviewBatchPublicationError("SCIENCE_VISUAL_REVIEW_BATCH_INPUT_INVALID") from exc

    command_receipt_path = _command_receipt(command.batch_id)
    if args.result is None:
        if args.preflight_only:
            print(
                json.dumps(
                    {
                        "batch_id": command.batch_id,
                        "candidate_count": len(command.candidate_ids),
                        "preflight": "PASS",
                    },
                    sort_keys=True,
                )
            )
            return 0
        engine = build_engine()
        try:
            adapter = LocalImageTrainingControlArtifactPublisher(
                ControlArtifactPublisher(engine, Settings.from_environment()),
                source_commit=args.source_commit,
            )
            pointer = adapter.commit_science_visual_campaign_review_batch_command(command)
        finally:
            engine.dispose()
        STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
        _write_receipt(
            command_receipt_path,
            content_json_bytes(
                {
                    "schema_version": _COMMAND_RECEIPT_SCHEMA,
                    "batch_id": command.batch_id,
                    "command_sha256": command.command_sha256,
                    "command_artifact": pointer.model_dump(mode="json"),
                    "source_commit": args.source_commit,
                }
            ),
        )
        print(
            json.dumps(
                {
                    "artifact_id": pointer.artifact_id,
                    "artifact_revision_id": pointer.artifact_revision_id,
                    "batch_id": command.batch_id,
                },
                sort_keys=True,
            )
        )
        return 0

    try:
        receipt = _object(_safe_read(command_receipt_path))
        pointer = ImageEvaluationArtifactMember.model_validate(receipt["command_artifact"])
        if (
            receipt.get("schema_version") != _COMMAND_RECEIPT_SCHEMA
            or receipt.get("batch_id") != command.batch_id
            or receipt.get("command_sha256") != command.command_sha256
            or pointer.sha256 != sha256_bytes(command_payload)
        ):
            raise ReviewBatchPublicationError("SCIENCE_VISUAL_REVIEW_BATCH_RECEIPT_INVALID")
        result_payload = _safe_read(args.result)
        result_value = _object(result_payload)
        validate_contract("science-visual-campaign-review-batch-result", result_value)
        result = LocalImageScienceVisualCampaignReviewBatchResult.model_validate(result_value)
        if content_json_bytes(result.model_dump(mode="json")) != result_payload:
            raise ReviewBatchPublicationError("SCIENCE_VISUAL_REVIEW_BATCH_NOT_CANONICAL")
        validate_science_visual_campaign_review_batch(
            command=command,
            command_pointer=pointer,
            plans=campaign.plans,
            plan_pointers=campaign.plan_pointers,
            results=campaign.results,
            result_pointers=campaign.result_pointers,
            review_result=result,
        )
    except ReviewBatchPublicationError:
        raise
    except (
        JsonSchemaValidationError,
        PydanticValidationError,
        ReviewBatchStagingError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ReviewBatchPublicationError("SCIENCE_VISUAL_REVIEW_BATCH_RESULT_INVALID") from exc
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "batch_id": result.batch_id,
                    "review_count": len(result.reviews),
                    "preflight": "PASS",
                },
                sort_keys=True,
            )
        )
        return 0
    engine = build_engine()
    try:
        adapter = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        )
        result_pointer = adapter.commit_science_visual_campaign_review_batch_result(result)
    finally:
        engine.dispose()
    _write_receipt(
        _result_receipt(result.batch_id),
        content_json_bytes(
            {
                "schema_version": _RESULT_RECEIPT_SCHEMA,
                "batch_id": result.batch_id,
                "result_sha256": result.result_sha256,
                "result_artifact": result_pointer.model_dump(mode="json"),
                "source_commit": args.source_commit,
            }
        ),
    )
    print(
        json.dumps(
            {
                "artifact_id": result_pointer.artifact_id,
                "artifact_revision_id": result_pointer.artifact_revision_id,
                "batch_id": result.batch_id,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
