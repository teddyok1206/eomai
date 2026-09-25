#!/usr/bin/env python3
"""Validate and publish one isolated crop-locator result through the Orchestrator."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from eom_image_contracts import (
    LocalImageCropLocatorCommand,
    LocalImageCropLocatorResult,
    build_training_crop_review_draft,
    validate_contract,
    validate_crop_locator_result,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.database import build_engine
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.settings import Settings
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

REPOSITORY_ROOT = Path("/home/eom/EOM")
WORKSPACE_PARENT = Path("/srv/eom/image-training-workspaces")
MAX_JSON_BYTES = 16 * 1024 * 1024


class CropLocatorPublicationError(RuntimeError):
    """Stable operator-facing publication failure."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise CropLocatorPublicationError("IMAGE_TRAINING_RESULT_INVALID")
        value[key] = item
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locator-run-id", required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def _require_release(source_commit: str) -> None:
    if os.geteuid() != 0:
        raise CropLocatorPublicationError("IMAGE_TRAINING_PUBLICATION_ROOT_REQUIRED")
    try:
        head = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"],
            check=True,
            text=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CropLocatorPublicationError("IMAGE_TRAINING_SOURCE_RELEASE_INVALID") from exc
    if head != source_commit or dirty:
        raise CropLocatorPublicationError("IMAGE_TRAINING_SOURCE_RELEASE_INVALID")


def _safe_json(path: Path) -> dict[str, object]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise CropLocatorPublicationError("IMAGE_TRAINING_RESULT_MISSING") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_JSON_BYTES
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise CropLocatorPublicationError("IMAGE_TRAINING_RESULT_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise CropLocatorPublicationError("IMAGE_TRAINING_RESULT_TRUNCATED")
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
            raise CropLocatorPublicationError("IMAGE_TRAINING_RESULT_CHANGED")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                CropLocatorPublicationError("IMAGE_TRAINING_RESULT_INVALID")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CropLocatorPublicationError("IMAGE_TRAINING_RESULT_INVALID") from exc
    if not isinstance(value, dict):
        raise CropLocatorPublicationError("IMAGE_TRAINING_RESULT_INVALID")
    return value


def _require_workspace(locator_run_id: str) -> Path:
    if not locator_run_id.startswith("imgcroplocator_") or len(locator_run_id) != 47:
        raise CropLocatorPublicationError("IMAGE_TRAINING_LOCATOR_RUN_ID_INVALID")
    workspace = WORKSPACE_PARENT / locator_run_id
    if workspace.parent != WORKSPACE_PARENT or workspace.is_symlink():
        raise CropLocatorPublicationError("IMAGE_TRAINING_WORKSPACE_INVALID")
    metadata = workspace.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise CropLocatorPublicationError("IMAGE_TRAINING_WORKSPACE_INVALID")
    return workspace


def _review_materialization_sha256(workspace: Path, proposal_set_sha256: str) -> str:
    review_root = workspace / "review"
    if review_root.is_symlink() or not stat.S_ISDIR(review_root.lstat().st_mode):
        raise CropLocatorPublicationError("IMAGE_TRAINING_REVIEW_OUTPUT_INVALID")
    index = _safe_json(review_root / "review-index.json")
    if index.get("proposal_set_sha256") != proposal_set_sha256:
        raise CropLocatorPublicationError("IMAGE_TRAINING_REVIEW_OUTPUT_INVALID")
    names = sorted(path.name for path in review_root.glob("contact-sheet-*.png"))
    if not names:
        raise CropLocatorPublicationError("IMAGE_TRAINING_REVIEW_OUTPUT_INVALID")
    digest = hashlib.sha256()
    for name in names:
        path = review_root / name
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or not 0 < metadata.st_size <= 64 * 1024 * 1024
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                raise CropLocatorPublicationError("IMAGE_TRAINING_REVIEW_OUTPUT_INVALID")
            digest.update(name.encode("utf-8"))
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            after = os.fstat(descriptor)
            if (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise CropLocatorPublicationError("IMAGE_TRAINING_REVIEW_OUTPUT_CHANGED")
        finally:
            os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def main() -> None:
    args = _parser().parse_args()
    _require_release(args.source_commit)
    workspace = _require_workspace(args.locator_run_id)
    try:
        command_value = _safe_json(workspace / "command.json")
        validate_contract("crop-locator-command", command_value)
        command = LocalImageCropLocatorCommand.model_validate(command_value)
        result_value = _safe_json(workspace / command.output_member)
        validate_contract("crop-locator-result", result_value)
        result = LocalImageCropLocatorResult.model_validate(result_value)
        validate_crop_locator_result(command, result)
    except (JsonSchemaValidationError, PydanticValidationError, TypeError, ValueError) as exc:
        raise CropLocatorPublicationError("IMAGE_TRAINING_CROP_LOCATOR_RESULT_INVALID") from exc
    if command.locator_run_id != args.locator_run_id:
        raise CropLocatorPublicationError("IMAGE_TRAINING_WORKSPACE_ID_MISMATCH")
    if result.status != "SUCCEEDED" or result.proposal_set is None:
        raise CropLocatorPublicationError(result.error_code or "IMAGE_TRAINING_CROP_LOCATOR_FAILED")
    review_materialization_sha256 = _review_materialization_sha256(
        workspace,
        result.proposal_set.proposal_set_sha256,
    )
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "status": "PREFLIGHT_PASS",
                    "locator_run_id": command.locator_run_id,
                    "proposal_count": len(result.proposal_set.proposals),
                    "source_anchor_count": len(
                        {value.source_anchor_id for value in result.proposal_set.proposals}
                    ),
                    "omission_count": len(result.proposal_set.omissions),
                    "review_materialization_sha256": review_materialization_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    engine = build_engine()
    try:
        publisher = LocalImageTrainingControlArtifactPublisher(
            ControlArtifactPublisher(engine, Settings.from_environment()),
            source_commit=args.source_commit,
        )
        proposal_pointer = publisher.commit_crop_proposal_set(result.proposal_set)
        review = build_training_crop_review_draft(
            proposal_set=result.proposal_set,
            proposal_set_pointer=proposal_pointer,
            reviewed_at=result.completed_at,
            reviewed_by=args.reviewed_by,
        )
        review_pointer = publisher.commit_crop_review(review)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "status": "DRAFT_REVIEW_REQUIRED",
                "locator_run_id": command.locator_run_id,
                "proposal_count": len(result.proposal_set.proposals),
                "source_anchor_count": len(
                    {value.source_anchor_id for value in result.proposal_set.proposals}
                ),
                "omission_count": len(result.proposal_set.omissions),
                "proposal_pointer": proposal_pointer.model_dump(mode="json"),
                "draft_review_id": review.crop_review_id,
                "draft_review_pointer": review_pointer.model_dump(mode="json"),
                "review_materialization_sha256": review_materialization_sha256,
                "review_workspace": str(workspace / "review"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
