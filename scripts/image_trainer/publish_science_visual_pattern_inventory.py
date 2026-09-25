#!/usr/bin/env python3
"""Validate and publish one reviewed science-visual pattern inventory."""

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
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceVisualPatternInventoryV2,
    content_json_bytes,
    validate_contract,
    validate_science_visual_pattern_inventory_v2,
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


class ScienceVisualPatternPublicationError(RuntimeError):
    """Stable operator-facing inventory publication failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _safe_read(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_MEMBER_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_MEMBER_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise ScienceVisualPatternPublicationError(
                    "SCIENCE_VISUAL_PATTERN_MEMBER_TRUNCATED"
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
            raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_MEMBER_CHANGED")
    finally:
        os.close(descriptor)
    return bytes(payload)


def _json_object(payload: bytes) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_JSON_INVALID")
    return value


def _load_inputs(
    *,
    attempt_id: str,
    result_path: Path,
    result_publication_receipt_path: Path,
    inventory_path: Path,
) -> tuple[
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceVisualPatternInventoryV2,
    ImageEvaluationArtifactMember,
]:
    result_payload = _safe_read(result_path, maximum_bytes=MAX_JSON_BYTES)
    result_value = _json_object(result_payload)
    receipt_value = _json_object(
        _safe_read(result_publication_receipt_path, maximum_bytes=MAX_JSON_BYTES)
    )
    inventory_payload = _safe_read(inventory_path, maximum_bytes=MAX_JSON_BYTES)
    inventory_value = _json_object(inventory_payload)
    try:
        validate_contract("science-corpus-visual-pilot-result", result_value)
        validate_contract("science-visual-pattern-inventory-v2", inventory_value)
        result = LocalImageScienceCorpusVisualPilotResult.model_validate(result_value)
        inventory = LocalImageScienceVisualPatternInventoryV2.model_validate(inventory_value)
        pointer = ImageEvaluationArtifactMember.model_validate(receipt_value["result_artifact"])
        validate_science_visual_pattern_inventory_v2(result, inventory)
    except (KeyError, PydanticValidationError, TypeError, ValueError) as exc:
        raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_INPUT_INVALID") from exc

    expected_result_payload = content_json_bytes(result.model_dump(mode="json"))
    if (
        result.status != "SUCCEEDED"
        or receipt_value.get("schema_version") != "science-visual-pilot-publication-receipt/1.0"
        or receipt_value.get("attempt_id") != attempt_id
        or receipt_value.get("result_sha256") != result.result_sha256
        or receipt_value.get("result_file_sha256") != sha256_bytes(result_payload)
        or pointer != inventory.pilot_result
        or pointer.sha256 != sha256_bytes(expected_result_payload)
        or content_json_bytes(inventory.model_dump(mode="json")) != inventory_payload
    ):
        raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_BINDING_INVALID")
    return result, inventory, pointer


def _write_receipt(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if _safe_read(path, maximum_bytes=MAX_JSON_BYTES) != payload:
            raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_RECEIPT_CONFLICT")
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
        raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_ROOT_REQUIRED")
    if (
        _ATTEMPT.fullmatch(args.attempt_id) is None
        or _COMMIT.fullmatch(args.source_commit) is None
        or not args.inventory.is_absolute()
    ):
        raise ScienceVisualPatternPublicationError("SCIENCE_VISUAL_PATTERN_ARGUMENT_INVALID")
    workspace = WORKSPACE_PARENT / args.attempt_id
    publication_receipt_path = (
        STATE_ROOT / f"science-visual-pilot-publication-{args.attempt_id}.json"
    )
    result, inventory, result_pointer = _load_inputs(
        attempt_id=args.attempt_id,
        result_path=workspace / "manifests/visual-pilot-result.json",
        result_publication_receipt_path=publication_receipt_path,
        inventory_path=args.inventory,
    )
    summary = {
        "attempt_id": args.attempt_id,
        "candidate_count": len(result.visual_candidates),
        "deterministic_renderer_count": inventory.deterministic_renderer_count,
        "excluded_count": inventory.excluded_count,
        "inventory_id": inventory.inventory_id,
        "inventory_sha256": inventory.inventory_sha256,
        "lora_eligible_count": inventory.lora_eligible_count,
        "pilot_result_artifact_revision_id": result_pointer.artifact_revision_id,
        "primitive_recommendation_count": len(inventory.primitive_recommendations),
    }
    if args.preflight_only:
        print(json.dumps({**summary, "preflight": "PASS"}, sort_keys=True))
        return 0

    engine = build_engine()
    adapter = LocalImageTrainingControlArtifactPublisher(
        ControlArtifactPublisher(engine, Settings.from_environment()),
        source_commit=args.source_commit,
    )
    pointer = adapter.commit_science_visual_pattern_inventory_v2(inventory)
    STATE_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    receipt_path = STATE_ROOT / (
        f"science-visual-pattern-inventory-publication-{inventory.inventory_id}.json"
    )
    receipt_value = {
        "schema_version": "science-visual-pattern-inventory-publication-receipt/1.0",
        **summary,
        "inventory_artifact": pointer.model_dump(mode="json"),
        "source_commit": args.source_commit,
    }
    _write_receipt(receipt_path, content_json_bytes(receipt_value))
    print(
        json.dumps(
            {
                "artifact_id": pointer.artifact_id,
                "artifact_revision_id": pointer.artifact_revision_id,
                "inventory_id": inventory.inventory_id,
                "receipt": str(receipt_path),
                "result_file_sha256": pointer.sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
