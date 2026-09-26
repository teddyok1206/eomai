#!/usr/bin/env python3
"""Assemble and publish a campaign inventory from exact published review batches."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

from eom_identifiers import sha256_bytes
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualCampaignReviewBatchCommand,
    LocalImageScienceVisualCampaignReviewBatchResult,
    assemble_science_visual_campaign_pattern_inventory,
    content_json_bytes,
    validate_contract,
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
from eom_orchestrator.science_visual_campaign_resolution import (
    ResolvedScienceVisualCampaign,
    ScienceVisualCampaignResolutionError,
    parse_science_visual_campaign_object,
    resolve_science_visual_campaign,
    safe_read_science_visual_campaign_member,
)
from eom_orchestrator.settings import Settings
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Engine

STATE_ROOT = Path("/var/lib/eom-workflow-runner")
WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
MAX_JSON_BYTES = 16 * 1024 * 1024
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_BATCH = re.compile(r"^imgscivisreviewbatch_[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_COMMAND_RECEIPT_SCHEMA = "science-visual-campaign-review-command-publication-receipt/1.0"
_RESULT_RECEIPT_SCHEMA = "science-visual-campaign-review-result-publication-receipt/1.0"


class CampaignInventoryAssemblyError(RuntimeError):
    """Stable operator-facing campaign inventory assembly failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", action="append", required=True)
    parser.add_argument("--batch-id", action="append", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--created-by", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _command_receipt_path(batch_id: str) -> Path:
    return STATE_ROOT / f"science-visual-campaign-review-command-{batch_id}.json"


def _result_receipt_path(batch_id: str) -> Path:
    return STATE_ROOT / f"science-visual-campaign-review-result-{batch_id}.json"


def _read_object(path: Path) -> dict[str, object]:
    return parse_science_visual_campaign_object(safe_read_science_visual_campaign_member(path))


def _load_published_reviews(
    *,
    engine: Engine,
    campaign: ResolvedScienceVisualCampaign,
    batch_ids: tuple[str, ...],
) -> tuple[
    tuple[LocalImageScienceVisualCampaignReviewBatchCommand, ...],
    tuple[ImageEvaluationArtifactMember, ...],
    tuple[LocalImageScienceVisualCampaignReviewBatchResult, ...],
    tuple[ImageEvaluationArtifactMember, ...],
    tuple[dict[str, object], ...],
]:
    commands: list[LocalImageScienceVisualCampaignReviewBatchCommand] = []
    command_pointers: list[ImageEvaluationArtifactMember] = []
    review_results: list[LocalImageScienceVisualCampaignReviewBatchResult] = []
    result_pointers: list[ImageEvaluationArtifactMember] = []
    provenance: list[dict[str, object]] = []
    for batch_id in batch_ids:
        command_receipt = _read_object(_command_receipt_path(batch_id))
        result_receipt = _read_object(_result_receipt_path(batch_id))
        command_pointer = ImageEvaluationArtifactMember.model_validate(
            command_receipt["command_artifact"]
        )
        result_pointer = ImageEvaluationArtifactMember.model_validate(
            result_receipt["result_artifact"]
        )
        command_payload = resolve_control_artifact_member(
            engine, command_pointer, maximum_bytes=MAX_JSON_BYTES
        )
        result_payload = resolve_control_artifact_member(
            engine, result_pointer, maximum_bytes=MAX_JSON_BYTES
        )
        command_value = parse_science_visual_campaign_object(command_payload)
        result_value = parse_science_visual_campaign_object(result_payload)
        validate_contract("science-visual-campaign-review-batch-command", command_value)
        validate_contract("science-visual-campaign-review-batch-result", result_value)
        command = LocalImageScienceVisualCampaignReviewBatchCommand.model_validate(command_value)
        review_result = LocalImageScienceVisualCampaignReviewBatchResult.model_validate(
            result_value
        )
        if (
            command_receipt.get("schema_version") != _COMMAND_RECEIPT_SCHEMA
            or command_receipt.get("batch_id") != batch_id
            or command_receipt.get("command_sha256") != command.command_sha256
            or _COMMIT.fullmatch(str(command_receipt.get("source_commit"))) is None
            or result_receipt.get("schema_version") != _RESULT_RECEIPT_SCHEMA
            or result_receipt.get("batch_id") != batch_id
            or result_receipt.get("result_sha256") != review_result.result_sha256
            or _COMMIT.fullmatch(str(result_receipt.get("source_commit"))) is None
            or command.batch_id != batch_id
            or review_result.batch_id != batch_id
            or command.campaign_id != campaign.campaign_id
            or command.pilot_results != campaign.pilots
            or command_pointer.sha256 != sha256_bytes(command_payload)
            or result_pointer.sha256 != sha256_bytes(result_payload)
            or content_json_bytes(command.model_dump(mode="json")) != command_payload
            or content_json_bytes(review_result.model_dump(mode="json")) != result_payload
        ):
            raise CampaignInventoryAssemblyError("SCIENCE_VISUAL_CAMPAIGN_REVIEW_RECEIPT_INVALID")
        commands.append(command)
        command_pointers.append(command_pointer)
        review_results.append(review_result)
        result_pointers.append(result_pointer)
        provenance.append(
            {
                "batch_id": batch_id,
                "command_artifact": command_pointer.model_dump(mode="json"),
                "command_sha256": command.command_sha256,
                "result_artifact": result_pointer.model_dump(mode="json"),
                "result_sha256": review_result.result_sha256,
            }
        )
    return (
        tuple(commands),
        tuple(command_pointers),
        tuple(review_results),
        tuple(result_pointers),
        tuple(provenance),
    )


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if safe_read_science_visual_campaign_member(path) != payload:
            raise CampaignInventoryAssemblyError(
                "SCIENCE_VISUAL_CAMPAIGN_INVENTORY_RECEIPT_CONFLICT"
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
    batch_ids = tuple(args.batch_id)
    if (
        os.geteuid() != 0
        or not 2 <= len(attempt_ids) <= 4
        or attempt_ids != tuple(sorted(set(attempt_ids)))
        or any(_ATTEMPT.fullmatch(value) is None for value in attempt_ids)
        or not 1 <= len(batch_ids) <= 128
        or batch_ids != tuple(sorted(set(batch_ids)))
        or any(_BATCH.fullmatch(value) is None for value in batch_ids)
        or _COMMIT.fullmatch(args.source_commit) is None
    ):
        raise CampaignInventoryAssemblyError("SCIENCE_VISUAL_CAMPAIGN_ARGUMENT_INVALID")
    try:
        created_at = datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
        campaign = resolve_science_visual_campaign(
            attempt_ids,
            workspace_parent=WORKSPACE_PARENT,
            state_root=STATE_ROOT,
        )
        engine = build_engine()
        try:
            commands, command_pointers, review_results, result_pointers, provenance = (
                _load_published_reviews(
                    engine=engine,
                    campaign=campaign,
                    batch_ids=batch_ids,
                )
            )
            inventory = assemble_science_visual_campaign_pattern_inventory(
                plans=campaign.plans,
                plan_pointers=campaign.plan_pointers,
                results=campaign.results,
                result_pointers=campaign.result_pointers,
                commands=commands,
                command_pointers=command_pointers,
                review_results=review_results,
                review_result_pointers=result_pointers,
                created_at=created_at,
                created_by=args.created_by,
            )
            if args.preflight_only:
                print(
                    json.dumps(
                        {
                            "batch_count": len(batch_ids),
                            "candidate_count": len(inventory.reviews),
                            "campaign_id": inventory.campaign_id,
                            "inventory_id": inventory.inventory_id,
                            "inventory_sha256": inventory.inventory_sha256,
                            "lora_eligible_count": inventory.lora_eligible_count,
                            "preflight": "PASS",
                        },
                        sort_keys=True,
                    )
                )
                return 0
            adapter = LocalImageTrainingControlArtifactPublisher(
                ControlArtifactPublisher(engine, Settings.from_environment()),
                source_commit=args.source_commit,
            )
            inventory_pointer = adapter.commit_science_visual_campaign_pattern_inventory(inventory)
        finally:
            engine.dispose()
    except CampaignInventoryAssemblyError:
        raise
    except (
        ControlArtifactResolutionError,
        JsonSchemaValidationError,
        PydanticValidationError,
        ScienceVisualCampaignResolutionError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise CampaignInventoryAssemblyError("SCIENCE_VISUAL_CAMPAIGN_INPUT_INVALID") from exc

    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / (
        f"science-visual-campaign-pattern-inventory-publication-{inventory.inventory_id}.json"
    )
    _write_receipt(
        receipt_path,
        content_json_bytes(
            {
                "schema_version": (
                    "science-visual-campaign-pattern-inventory-publication-receipt/1.1"
                ),
                "campaign_id": inventory.campaign_id,
                "inventory_id": inventory.inventory_id,
                "inventory_sha256": inventory.inventory_sha256,
                "inventory_artifact": inventory_pointer.model_dump(mode="json"),
                "review_batches": list(provenance),
                "source_commit": args.source_commit,
            }
        ),
    )
    print(
        json.dumps(
            {
                "artifact_id": inventory_pointer.artifact_id,
                "artifact_revision_id": inventory_pointer.artifact_revision_id,
                "inventory_id": inventory.inventory_id,
                "receipt": str(receipt_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
