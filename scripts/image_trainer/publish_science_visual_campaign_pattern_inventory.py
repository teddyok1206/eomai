#!/usr/bin/env python3
"""Validate and publish one complete, bounded science-visual campaign inventory."""

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
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceVisualCampaignPatternInventory,
    content_json_bytes,
    validate_contract,
    validate_science_visual_campaign_pattern_inventory,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from pydantic import ValidationError as PydanticValidationError

WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
STATE_ROOT = Path("/var/lib/eom-workflow-runner")
MAX_JSON_BYTES = 16 * 1024 * 1024
_ATTEMPT = re.compile(r"^imgscivisattempt_[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ScienceVisualCampaignPatternPublicationError(RuntimeError):
    """Stable operator-facing campaign inventory publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", action="append", required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _safe_read(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ScienceVisualCampaignPatternPublicationError(
            "SCIENCE_VISUAL_CAMPAIGN_MEMBER_MISSING"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ScienceVisualCampaignPatternPublicationError(
                "SCIENCE_VISUAL_CAMPAIGN_MEMBER_INVALID"
            )
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceVisualCampaignPatternPublicationError(
                    "SCIENCE_VISUAL_CAMPAIGN_MEMBER_TRUNCATED"
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
            raise ScienceVisualCampaignPatternPublicationError(
                "SCIENCE_VISUAL_CAMPAIGN_MEMBER_CHANGED"
            )
    finally:
        os.close(descriptor)
    return bytes(payload)


def _json_object(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScienceVisualCampaignPatternPublicationError(
            "SCIENCE_VISUAL_CAMPAIGN_JSON_INVALID"
        ) from exc
    if not isinstance(value, dict):
        raise ScienceVisualCampaignPatternPublicationError("SCIENCE_VISUAL_CAMPAIGN_JSON_INVALID")
    return value


def _stage_receipt_path(attempt_id: str) -> Path:
    return STATE_ROOT / f"science-visual-pilot-stage-{attempt_id}.json"


def _result_receipt_path(attempt_id: str) -> Path:
    return STATE_ROOT / f"science-visual-pilot-publication-{attempt_id}.json"


def _load_inputs(
    *,
    attempt_ids: tuple[str, ...],
    inventory_path: Path,
) -> tuple[
    LocalImageScienceVisualCampaignPatternInventory,
    tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...],
    tuple[ImageEvaluationArtifactMember, ...],
    tuple[LocalImageScienceCorpusVisualPilotResult, ...],
    tuple[ImageEvaluationArtifactMember, ...],
]:
    inventory_payload = _safe_read(inventory_path, maximum_bytes=MAX_JSON_BYTES)
    inventory_value = _json_object(inventory_payload)
    plans: list[LocalImageScienceCorpusVisualPilotPlanV3] = []
    plan_pointers: list[ImageEvaluationArtifactMember] = []
    results: list[LocalImageScienceCorpusVisualPilotResult] = []
    result_pointers: list[ImageEvaluationArtifactMember] = []
    try:
        validate_contract("science-visual-campaign-pattern-inventory", inventory_value)
        inventory = LocalImageScienceVisualCampaignPatternInventory.model_validate(inventory_value)
        for attempt_id in attempt_ids:
            workspace = WORKSPACE_PARENT / attempt_id
            stage_receipt = _json_object(
                _safe_read(_stage_receipt_path(attempt_id), maximum_bytes=MAX_JSON_BYTES)
            )
            result_receipt = _json_object(
                _safe_read(_result_receipt_path(attempt_id), maximum_bytes=MAX_JSON_BYTES)
            )
            plan_payload = _safe_read(
                workspace / "input/visual-pilot-plan.json", maximum_bytes=MAX_JSON_BYTES
            )
            result_payload = _safe_read(
                workspace / "manifests/visual-pilot-result.json", maximum_bytes=MAX_JSON_BYTES
            )
            plan_value = _json_object(plan_payload)
            result_value = _json_object(result_payload)
            validate_contract("science-corpus-visual-pilot-plan-v3", plan_value)
            validate_contract("science-corpus-visual-pilot-result", result_value)
            plan = LocalImageScienceCorpusVisualPilotPlanV3.model_validate(plan_value)
            result = LocalImageScienceCorpusVisualPilotResult.model_validate(result_value)
            plan_pointer = ImageEvaluationArtifactMember.model_validate(stage_receipt["plan"])
            result_pointer = ImageEvaluationArtifactMember.model_validate(
                result_receipt["result_artifact"]
            )
            if (
                stage_receipt.get("schema_version") != "science-visual-pilot-stage-receipt/1.0"
                or stage_receipt.get("attempt_id") != attempt_id
                or stage_receipt.get("workspace") != str(workspace)
                or result_receipt.get("schema_version")
                != "science-visual-pilot-publication-receipt/1.0"
                or result_receipt.get("attempt_id") != attempt_id
                or result_receipt.get("result_sha256") != result.result_sha256
                or result_receipt.get("result_file_sha256") != sha256_bytes(result_payload)
                or plan_pointer.sha256
                != sha256_bytes(content_json_bytes(plan.model_dump(mode="json")))
                or result.status != "SUCCEEDED"
                or result.plan_sha256 != plan.plan_sha256
            ):
                raise ScienceVisualCampaignPatternPublicationError(
                    "SCIENCE_VISUAL_CAMPAIGN_BINDING_INVALID"
                )
            plans.append(plan)
            plan_pointers.append(plan_pointer)
            results.append(result)
            result_pointers.append(result_pointer)
        if content_json_bytes(inventory.model_dump(mode="json")) != inventory_payload:
            raise ScienceVisualCampaignPatternPublicationError(
                "SCIENCE_VISUAL_CAMPAIGN_BINDING_INVALID"
            )
        validate_science_visual_campaign_pattern_inventory(
            plans=tuple(plans),
            plan_pointers=tuple(plan_pointers),
            results=tuple(results),
            result_pointers=tuple(result_pointers),
            inventory=inventory,
        )
    except ScienceVisualCampaignPatternPublicationError:
        raise
    except (KeyError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualCampaignPatternPublicationError(
            "SCIENCE_VISUAL_CAMPAIGN_INPUT_INVALID"
        ) from exc
    return inventory, tuple(plans), tuple(plan_pointers), tuple(results), tuple(result_pointers)


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if _safe_read(path, maximum_bytes=MAX_JSON_BYTES) != payload:
            raise ScienceVisualCampaignPatternPublicationError(
                "SCIENCE_VISUAL_CAMPAIGN_RECEIPT_CONFLICT"
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
    if (
        os.geteuid() != 0
        or not 2 <= len(attempt_ids) <= 4
        or attempt_ids != tuple(sorted(set(attempt_ids)))
        or any(_ATTEMPT.fullmatch(value) is None for value in attempt_ids)
        or _COMMIT.fullmatch(args.source_commit) is None
        or not args.inventory.is_absolute()
    ):
        raise ScienceVisualCampaignPatternPublicationError(
            "SCIENCE_VISUAL_CAMPAIGN_ARGUMENT_INVALID"
        )
    inventory, plans, _, results, _ = _load_inputs(
        attempt_ids=attempt_ids,
        inventory_path=args.inventory,
    )
    summary = {
        "campaign_id": inventory.campaign_id,
        "candidate_count": sum(len(value.visual_candidates) for value in results),
        "deterministic_renderer_count": inventory.deterministic_renderer_count,
        "excluded_count": inventory.excluded_count,
        "inventory_id": inventory.inventory_id,
        "inventory_sha256": inventory.inventory_sha256,
        "lora_eligible_count": inventory.lora_eligible_count,
        "shard_count": len(plans),
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0
    engine = build_engine()
    try:
        adapter = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        )
        pointer = adapter.commit_science_visual_campaign_pattern_inventory(inventory)
    finally:
        engine.dispose()
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / (
        f"science-visual-campaign-pattern-inventory-publication-{inventory.inventory_id}.json"
    )
    _write_receipt(
        receipt_path,
        content_json_bytes(
            {
                "schema_version": (
                    "science-visual-campaign-pattern-inventory-publication-receipt/1.0"
                ),
                **summary,
                "inventory_artifact": pointer.model_dump(mode="json"),
                "source_commit": args.source_commit,
            }
        ),
    )
    print(
        json.dumps(
            {
                "artifact_id": pointer.artifact_id,
                "artifact_revision_id": pointer.artifact_revision_id,
                "inventory_id": inventory.inventory_id,
                "receipt": str(receipt_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
